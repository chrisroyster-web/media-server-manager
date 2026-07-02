# ui/reverse_proxy_tab.py
"""
Reverse Proxy viewer.
Reads Nginx, Caddy, or Traefik configs over SSH and shows active routes.
Auto-detects proxy type when set to "Auto-detect" in config.
"""

import tkinter as tk
from tkinter import ttk
import threading
import re
import shlex


# ── Detection helpers ─────────────────────────────────────────────────────────

_NGINX_CONF_PATHS = [
    "/etc/nginx/nginx.conf",
    "/etc/nginx/sites-enabled",
    "/etc/nginx/conf.d",
]
_CADDY_CONF_PATHS = [
    "/etc/caddy/Caddyfile",
    "/etc/caddy/caddy.conf",
    "~/.config/caddy/Caddyfile",
]
_TRAEFIK_CONF_PATHS = [
    "/etc/traefik/traefik.yml",
    "/etc/traefik/traefik.yaml",
    "/opt/traefik/traefik.yml",
]


def _detect_proxy(ssh):
    """Return 'Nginx', 'Caddy', 'Traefik', or None."""
    checks = [
        ("which nginx 2>/dev/null || systemctl is-active nginx 2>/dev/null",   "Nginx"),
        ("which caddy 2>/dev/null || systemctl is-active caddy 2>/dev/null",   "Caddy"),
        ("which traefik 2>/dev/null || systemctl is-active traefik 2>/dev/null", "Traefik"),
    ]
    for cmd, name in checks:
        out, _, _ = ssh.run(cmd)
        if out and out.strip() and "not found" not in out and "inactive" not in out:
            return name
    return None


# ── Route parsers ─────────────────────────────────────────────────────────────

def _parse_nginx(text):
    """Extract server_name + proxy_pass / location blocks from nginx config text."""
    routes = []
    server_name = ""
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"server_name\s+(.+?);", line)
        if m:
            server_name = m.group(1).strip()
        loc = re.match(r"location\s+(\S+)\s*\{?", line)
        if loc:
            path = loc.group(1)
            routes.append({"domain": server_name or "—", "path": path,
                           "backend": "—", "tls": ""})
        pp = re.match(r"proxy_pass\s+(.+?);", line)
        if pp and routes:
            routes[-1]["backend"] = pp.group(1).strip()
        if "ssl_certificate" in line or "listen 443" in line:
            if routes:
                routes[-1]["tls"] = "✓"
    return routes


def _parse_caddy(text):
    """Extract host blocks and reverse_proxy directives from a Caddyfile."""
    routes = []
    current_host = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Host line: e.g.  example.com { or  https://example.com {
        host_m = re.match(r"^(https?://)?([a-zA-Z0-9.*:_-]+)\s*\{?$", line)
        if host_m and not line.startswith("reverse_proxy"):
            current_host = host_m.group(2)
        rp = re.match(r"reverse_proxy\s+(.+)", line)
        if rp:
            tls = "✓" if current_host.startswith("https") or "." in current_host else ""
            routes.append({"domain": current_host or "—", "path": "*",
                           "backend": rp.group(1).strip(), "tls": tls})
    return routes


def _parse_traefik(text):
    """Very lightweight YAML parse for Traefik http.routers / services."""
    routes = []
    rule = ""
    service = ""
    for line in text.splitlines():
        stripped = line.strip()
        r = re.match(r"rule:\s+['\"]?(.+?)['\"]?$", stripped)
        if r:
            rule = r.group(1)
        s = re.match(r"service:\s+(\S+)", stripped)
        if s:
            service = s.group(1)
        if rule and service:
            tls = "✓" if "tls" in text.lower() else ""
            routes.append({"domain": rule, "path": "—",
                           "backend": service, "tls": tls})
            rule = service = ""
    return routes


# ── Tab ───────────────────────────────────────────────────────────────────────

class ReverseProxyTab(tk.Frame):

    COLUMNS = ("Domain / Rule", "Path", "Backend", "TLS")
    COL_W   = (260, 120, 240, 50)

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # ── Header ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="REVERSE PROXY",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh",
                                      command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")
        self._proxy_lbl = tk.Label(hdr, text="",
                                   bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._proxy_lbl.pack(side="right", padx=12)

        # ── Summary card ─────────────────────────────────────
        card = tk.Frame(self, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=(0, 10))
        inner = tk.Frame(card, bg=t.card_bg)
        inner.pack(fill="x", padx=16, pady=10)

        self._summary_vars = {}
        for label in ("Proxy", "Status", "Routes"):
            col = tk.Frame(inner, bg=t.card_bg)
            col.pack(side="left", padx=20)
            tk.Label(col, text=label, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small).pack()
            var = tk.StringVar(value="—")
            self._summary_vars[label] = var
            tk.Label(col, textvariable=var, bg=t.card_bg, fg=t.text,
                     font=("Segoe UI Semibold", 14)).pack()

        # ── Routes table ─────────────────────────────────────
        table_frame = tk.Frame(self, bg=t.bg)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Proxy.Treeview",
                        background=t.surface,
                        foreground=t.text,
                        fieldbackground=t.surface,
                        borderwidth=0,
                        rowheight=26)
        style.configure("Proxy.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        relief="flat")
        style.map("Proxy.Treeview", background=[("selected", t.sidebar_active_bg)])

        self._tree = ttk.Treeview(table_frame,
                                   columns=self.COLUMNS,
                                   show="headings",
                                   style="Proxy.Treeview")
        for col, w in zip(self.COLUMNS, self.COL_W):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, minwidth=40,
                              anchor="center" if col == "TLS" else "w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                             command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # ── Raw config box ────────────────────────────────────
        raw_frame = tk.Frame(self, bg=t.bg)
        raw_frame.pack(fill="both", expand=False, padx=16, pady=(0, 8))
        tk.Label(raw_frame, text="Raw Config",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(anchor="w")
        self._raw = tk.Text(raw_frame, height=8,
                            bg=t.surface_dark, fg=t.text_secondary,
                            font=t.font_mono, state="disabled",
                            relief="flat", padx=8, pady=6)
        self._raw.pack(fill="both", expand=True)

        # ── Status bar ───────────────────────────────────────
        self._status_bar = tk.Label(self, text="Not connected to SSH",
                                    bg=t.surface_dark, fg=t.text_muted,
                                    font=t.font_small, anchor="w")
        self._status_bar.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        if not self.controller.ssh.connected:
            self._set_bar("Not connected to SSH", "error")
            return
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._set_bar("Reading proxy config…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    # =========================================================
    # FETCH  (background thread)
    # =========================================================
    def _fetch(self):
        try:
            ssh    = self.controller.ssh
            cfg    = self.controller.config_manager
            ptype  = cfg.proxy_type  # "Auto-detect", "Nginx", "Caddy", "Traefik"
            result = {"proxy": ptype, "routes": [], "raw": "", "status": "Unknown"}

            if ptype == "Auto-detect":
                detected = _detect_proxy(ssh)
                if detected:
                    ptype = detected
                    result["proxy"] = detected
                else:
                    result["status"] = "Not detected"
                    result["raw"] = ("Could not detect a running reverse proxy.\n"
                                     "Make sure nginx/caddy/traefik is installed and active.")
                    self.after(0, lambda r=result: self._populate(r))
                    return

            # ── Nginx ─────────────────────────────────────────────
            if ptype == "Nginx":
                conf_text = ""
                for path in _NGINX_CONF_PATHS:
                    qp = shlex.quote(path)
                    out, _, _ = ssh.run(
                        "cat {p} 2>/dev/null || "
                        "find {p} -name '*.conf' -exec cat {{}} \\; 2>/dev/null".format(p=qp))
                    if out and out.strip():
                        conf_text += out + "\n"
                if conf_text:
                    result["routes"] = _parse_nginx(conf_text)
                    result["raw"]    = conf_text[:4000]
                    # Check if nginx is active
                    svc, _, _ = ssh.run("systemctl is-active nginx 2>/dev/null")
                    result["status"] = svc.strip() if svc else "unknown"
                else:
                    result["status"] = "Config not found"
                    result["raw"]    = "Could not read nginx config files."

            # ── Caddy ─────────────────────────────────────────────
            elif ptype == "Caddy":
                conf_text = ""
                for path in _CADDY_CONF_PATHS:
                    out, _, _ = ssh.run("cat {p} 2>/dev/null".format(p=shlex.quote(path)))
                    if out and out.strip():
                        conf_text = out
                        break
                if not conf_text:
                    # Try caddy adapt
                    out, _, _ = ssh.run("caddy adapt 2>/dev/null | head -200")
                    conf_text = out or ""
                if conf_text:
                    result["routes"] = _parse_caddy(conf_text)
                    result["raw"]    = conf_text[:4000]
                    svc, _, _ = ssh.run("systemctl is-active caddy 2>/dev/null")
                    result["status"] = svc.strip() if svc else "unknown"
                else:
                    result["status"] = "Config not found"
                    result["raw"]    = "Could not read Caddy config files."

            # ── Traefik ───────────────────────────────────────────
            elif ptype == "Traefik":
                conf_text = ""
                for path in _TRAEFIK_CONF_PATHS:
                    out, _, _ = ssh.run("cat {p} 2>/dev/null".format(p=shlex.quote(path)))
                    if out and out.strip():
                        conf_text = out
                        break
                if not conf_text:
                    # Try docker labels inspection
                    out, _, _ = ssh.run(
                        "docker inspect $(docker ps -q) 2>/dev/null | "
                        "grep -o '\"traefik[^\"]*\":[^,}]*' | head -40")
                    conf_text = out or ""
                if conf_text:
                    result["routes"] = _parse_traefik(conf_text)
                    result["raw"]    = conf_text[:4000]
                    svc, _, _ = ssh.run("systemctl is-active traefik 2>/dev/null")
                    result["status"] = svc.strip() if svc else "unknown"
                else:
                    result["status"] = "Config not found"
                    result["raw"]    = "Could not read Traefik config files."

            self.after(0, lambda r=result: self._populate(r))
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE  (main thread)
    # =========================================================
    def _populate(self, result):
        routes  = result.get("routes", [])
        proxy   = result.get("proxy", "—")
        status  = result.get("status", "—")
        is_up   = status.lower() in ("active", "running")

        self._summary_vars["Proxy"].set(proxy)
        self._summary_vars["Status"].set(status)
        self._summary_vars["Routes"].set(str(len(routes)))
        self._proxy_lbl.config(text=proxy)

        # Table
        self._tree.delete(*self._tree.get_children())
        for r in routes:
            self._tree.insert("", "end", values=(
                r.get("domain", "—"),
                r.get("path",   "—"),
                r.get("backend","—"),
                r.get("tls",    ""),
            ))

        # Raw
        self._raw.config(state="normal")
        self._raw.delete("1.0", "end")
        self._raw.insert("end", result.get("raw", "").strip())
        self._raw.config(state="disabled")

        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._set_bar(
            "{} — {} route{} found".format(
                proxy, len(routes), "" if len(routes) == 1 else "s"),
            "ok" if is_up else "info")

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_bar(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status_bar.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "ok": t.status_running, "error": t.status_stopped}
        self._status_bar.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
