# ui/ssl_tab.py
"""
SSL Certificate Expiry Checker.
Checks each configured service host:port via openssl s_client on the remote server.
Shows days to expiry, issuer, and color-coded warning/critical thresholds.
"""

import datetime
import tkinter as tk
from tkinter import ttk
import threading
import time
import re

from ui.refresh_control import RefreshControl


def _dq(value):
    """Escape a value for safe embedding inside a double-quoted bash -c "..."
    string: host/port fields here come from user-editable config, and are
    interpolated into an already-double-quoted command, so shlex.quote (which
    produces single-quoted output) would not protect against embedded double
    quotes, $, or backticks the way it does for a top-level shell argument."""
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


class SSLTab(tk.Frame):

    WARN_DAYS  = 30
    CRIT_DAYS  = 7

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._results   = []
        self._loaded_host = None
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="SSL CERTIFICATES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "ssl",
                                  default=1440, on_refresh=self.refresh)   # 24 h default
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Check All", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._check_btn = btn
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary row
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_ok   = self._stat_card(s_row, "Valid",    "—", t.status_running)
        self._card_warn = self._stat_card(s_row, "Expiring", "—", t.yellow)
        self._card_crit = self._stat_card(s_row, "Critical", "—", t.status_stopped)
        self._card_err  = self._stat_card(s_row, "Errors",   "—", t.text_muted)

        # Cert table
        tbl_frame = tk.Frame(self, bg=t.bg)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        style.configure("SSL.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=28, font=t.font_mono)
        style.configure("SSL.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("SSL.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("host", "port", "days", "expires", "issuer", "sans")
        self._tree = ttk.Treeview(tbl_frame, columns=cols,
                                   show="headings", style="SSL.Treeview")
        for col, w, lbl, anchor in [
            ("host",    200, "Host",       "w"),
            ("port",     60, "Port",       "e"),
            ("days",     70, "Days Left",  "e"),
            ("expires", 160, "Expires",    "w"),
            ("issuer",  200, "Issuer",     "w"),
            ("sans",    260, "Alt Names",  "w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anchor)
            self._tree.column(col, width=w, minwidth=50,
                              anchor=anchor, stretch=(col in ("host", "issuer", "sans")))

        self._tree.tag_configure("ok",   foreground=t.status_running)
        self._tree.tag_configure("warn", foreground=t.yellow)
        self._tree.tag_configure("crit", foreground=t.status_stopped)
        self._tree.tag_configure("err",  foreground=t.text_muted)

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Add-host row
        add_frame = tk.Frame(self, bg=t.bg)
        add_frame.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(add_frame, text="Add host:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._host_var = tk.StringVar()
        self._port_var = tk.StringVar(value="443")
        h_entry = tk.Entry(add_frame, textvariable=self._host_var, width=28)
        t.style_entry(h_entry)
        h_entry.pack(side="left", padx=(6, 4))
        tk.Label(add_frame, text=":", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        p_entry = tk.Entry(add_frame, textvariable=self._port_var, width=6)
        t.style_entry(p_entry)
        p_entry.pack(side="left", padx=(4, 6))
        add_btn = tk.Button(add_frame, text="Add & Check", command=self._add_host)
        t.style_button(add_btn)
        add_btn.pack(side="left")

        diag_btn = tk.Button(add_frame, text="🔍 Diagnose Server", command=self._diagnose)
        t.style_button(diag_btn)
        diag_btn.pack(side="left", padx=(12, 0))

        # Diagnostic output panel (hidden until Diagnose is clicked)
        self._diag_frame = tk.Frame(self, bg=t.surface_dark,
                                     highlightbackground=t.card_border, highlightthickness=1)
        self._diag_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._diag_frame.pack_forget()
        diag_hdr = tk.Frame(self._diag_frame, bg=t.surface_dark)
        diag_hdr.pack(fill="x")
        tk.Label(diag_hdr, text="Server certificate diagnostics", bg=t.surface_dark,
                 fg=t.text_muted, font=t.font_small).pack(side="left", padx=8, pady=2)
        tk.Button(diag_hdr, text="✕", command=lambda: self._diag_frame.pack_forget(),
                  bg=t.surface_dark, fg=t.text_muted, bd=0, relief="flat",
                  font=t.font_small).pack(side="right", padx=6)
        self._diag_text = tk.Text(self._diag_frame, bg=t.surface_dark, fg=t.text,
                                   font=t.font_mono, height=10, state="disabled",
                                   relief="flat", wrap="none", pady=4, padx=8)
        dsb = tk.Scrollbar(self._diag_frame, orient="vertical",
                           command=self._diag_text.yview)
        dsb.pack(side="right", fill="y")
        self._diag_text.configure(yscrollcommand=dsb.set)
        self._diag_text.pack(fill="x")

        # Status bar
        self._status = tk.Label(self, text="Press 'Check All' to scan certificates",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        # Pre-populate from config
        self._load_hosts_from_config()

    def _stat_card(self, parent, label, value, color):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    # =========================================================
    # HOSTS FROM CONFIG
    # =========================================================
    # Well-known HTTPS ports worth auto-checking
    _HTTPS_PORTS = {"443", "8443", "4443", "9443", "2053", "2083", "2087", "2096",
                    "8920"}  # 8920 = Emby built-in HTTPS

    def _load_hosts_from_config(self):
        """
        Pre-populate with likely-HTTPS endpoints only.
        Most internal service ports (8096, 8989, etc.) are plain HTTP —
        we only add them if they're a known HTTPS port.
        We always seed host:443 as the primary entry.
        """
        cfg  = self.controller.config_manager
        host = cfg.last_host or "localhost"
        self._loaded_host = host
        if not host or host == "localhost":
            return

        seen = set()

        def _add(h, p):
            key = (h, str(p))
            if key not in seen:
                seen.add(key)
                self._results.append({"host": h, "port": str(p), "status": "pending"})

        # Always try the main SSH host on standard HTTPS
        _add(host, "443")

        # Reverse proxy host (may differ from SSH host)
        rp_host = getattr(cfg, "reverse_proxy_host", "") or ""
        if rp_host and rp_host not in (host, "localhost"):
            _add(rp_host, "443")

        # Only add service/media ports that are known HTTPS ports
        for svc, data in cfg.get_services().items():
            p = str(data.get("port", ""))
            if p in self._HTTPS_PORTS:
                _add(host, p)

        for attr, default_port in [
            ("plex_host",     32400),
            ("emby_host",     8096),
            ("jellyfin_host", 8096),
        ]:
            h = getattr(cfg, attr, "") or host
            port_attr = attr.replace("_host", "_port")
            p = str(getattr(cfg, port_attr, default_port) or default_port)
            if p in self._HTTPS_PORTS and h and h not in ("localhost",):
                _add(h, p)

        # Emby HTTPS is on a separate port (default 8920) — always seed it
        emby_h = getattr(cfg, "emby_host", "") or host
        if emby_h and emby_h not in ("localhost",):
            _add(emby_h, "8920")

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._set_status("Not connected to SSH", "error")
            return
        if self.controller.config_manager.last_host != self._loaded_host:
            self._results = []
            self._load_hosts_from_config()
        if not self._results:
            self._set_status("No hosts configured — add a host below", "info")
            return
        self._check_btn.config(state="disabled", text="Checking…")
        self._set_status("Checking {} certificate{}…".format(
            len(self._results), "s" if len(self._results) != 1 else ""))
        self._fetching = True
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _add_host(self):
        h = self._host_var.get().strip()
        p = self._port_var.get().strip() or "443"
        if not h:
            return
        # Avoid duplicates
        if not any(r["host"] == h and r["port"] == p for r in self._results):
            self._results.append({"host": h, "port": p, "status": "pending"})
        self._host_var.set("")
        if self.controller.ssh.connected:
            self._check_single(h, p)

    # =========================================================
    # FETCH
    # =========================================================
    def _fetch_all(self):
        try:
            for r in self._results:
                self._check_cert(r)
            self.after(0, self._repopulate)
            self.after(0, lambda: self._check_btn.config(state="normal", text="⟳ Check All"))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False

    def _check_single(self, host, port):
        r = next((x for x in self._results if x["host"] == host and x["port"] == port), None)
        if r:
            threading.Thread(target=lambda: (self._check_cert(r), self.after(0, self._repopulate)),
                             daemon=True).start()

    def _check_cert(self, r):
        ssh   = self.controller.ssh
        host  = r["host"]
        port  = r["port"]

        # </dev/null sends EOF immediately so openssl completes the TLS
        # handshake and outputs the full cert before exiting — more reliable
        # than "echo |" which races against the handshake timing.
        # Try several connect targets: external IP may be unreachable from
        # within the server itself, so fall back to loopback variants.
        def _try(connect_host, servername):
            cmd = (
                "bash -c \"timeout 10 openssl s_client "
                "-connect {c}:{p} -servername {s} </dev/null 2>/dev/null "
                "| openssl x509 -noout -text 2>/dev/null\""
                .format(c=_dq(connect_host), p=_dq(port), s=_dq(servername))
            )
            o, _, _ = ssh.run(cmd)
            return o if (o and "Not After" in o) else None

        out = (
            _try(host,        host)        or  # external IP/hostname with SNI
            _try("localhost", host)        or  # loopback with original SNI
            _try("127.0.0.1", host)        or  # loopback numeric with SNI
            _try("localhost", "localhost") or  # loopback, no SNI
            None
        )

        if out is None:
            diag, diag_err, _ = ssh.run(
                "bash -c \"timeout 10 openssl s_client "
                "-connect {h}:{p} </dev/null 2>&1 | head -3\""
                .format(h=_dq(host), p=_dq(port))
            )
            detail = (diag or diag_err or "no output").strip().splitlines()[0][:80]
            r.update({"status": "error",
                      "error": "No cert — {}".format(detail)})
            return

        # ── Parse -text output ──────────────────────────────────────────
        expires = "--"
        days    = None
        issuer  = "--"
        sans    = "--"

        for line in out.splitlines():
            line = line.strip()

            # "Not After : Jan  2 12:00:00 2026 GMT"
            m = re.search(r'Not After\s*:\s*(.+)', line)
            if m:
                date_str = m.group(1).strip()
                expires  = date_str
                try:
                    dt = None
                    for fmt in ("%b %d %H:%M:%S %Y %Z",
                                "%b  %d %H:%M:%S %Y %Z"):
                        try:
                            dt = datetime.datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            pass
                    if dt:
                        days    = (dt - datetime.datetime.utcnow()).days
                        expires = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # "Issuer: C = US, O = Let's Encrypt, CN = R3"
            m = re.search(r'Issuer:.*?O\s*=\s*([^,\n]+)', line)
            if m:
                issuer = m.group(1).strip().strip('"')

            # "DNS:myserver.com, DNS:www.myserver.com"
            if "DNS:" in line:
                san_matches = re.findall(r"DNS:([^\s,]+)", line)
                if san_matches:
                    sans = ", ".join(san_matches[:4])
                    if len(san_matches) > 4:
                        sans += " +{}".format(len(san_matches) - 4)

        if days is None:
            r.update({"status": "error", "error": "Could not parse expiry date"})
        elif days <= self.CRIT_DAYS:
            r.update({"status": "crit", "days": days, "expires": expires,
                      "issuer": issuer, "sans": sans})
        elif days <= self.WARN_DAYS:
            r.update({"status": "warn", "days": days, "expires": expires,
                      "issuer": issuer, "sans": sans})
        else:
            r.update({"status": "ok",   "days": days, "expires": expires,
                      "issuer": issuer, "sans": sans})

        # This specific host:port is Emby's cert, renewed unattended on the
        # server via certbot + a deploy hook (see RESTORE.md-adjacent
        # rebuild-server.sh era changes) rather than the app itself — the
        # live cert can still look "ok" for weeks after that automation has
        # silently broken, so cross-check it here instead of waiting for
        # the cert to actually expire.
        emby_host = getattr(self.controller.config_manager, "emby_host", "") or ""
        if r["host"] == emby_host and r["port"] == "8920" and r["status"] != "error":
            self._check_certbot_automation(r)

    def _check_certbot_automation(self, r):
        ssh = self.controller.ssh
        out, _, _ = ssh.run(
            "systemctl is-active certbot.timer 2>/dev/null; "
            "test -x /etc/letsencrypt/renewal-hooks/deploy/emby-cert.sh "
            "&& echo HOOK_OK || echo HOOK_MISSING"
        )
        lines = (out or "").splitlines()
        timer_active = lines[0].strip() == "active" if lines else False
        hook_ok      = "HOOK_OK" in (lines[1] if len(lines) > 1 else "")

        if timer_active and hook_ok:
            return

        problems = []
        if not timer_active:
            problems.append("certbot.timer inactive")
        if not hook_ok:
            problems.append("deploy hook missing")
        r["sans"] = "{} ⚠ {}".format(r.get("sans", "--"), "; ".join(problems))
        if r["status"] == "ok":
            r["status"] = "warn"

    # =========================================================
    # POPULATE
    # =========================================================
    def _repopulate(self):
        ok   = sum(1 for r in self._results if r["status"] == "ok")
        warn = sum(1 for r in self._results if r["status"] == "warn")
        crit = sum(1 for r in self._results if r["status"] == "crit")
        err  = sum(1 for r in self._results if r["status"] == "error")

        self._card_ok.config(text=str(ok))
        self._card_warn.config(text=str(warn),
                               fg=self.theme.yellow if warn else self.theme.text_muted)
        self._card_crit.config(text=str(crit),
                               fg=self.theme.status_stopped if crit else self.theme.text_muted)
        self._card_err.config(text=str(err),
                              fg=self.theme.status_stopped if err else self.theme.text_muted)

        self._tree.delete(*self._tree.get_children())
        for r in sorted(self._results,
                        key=lambda x: ({"crit": 0, "warn": 1, "error": 2, "ok": 3}.get(x["status"], 4),
                                       x.get("days", 9999))):
            status = r["status"]
            # dict uses "error"; treeview tag is "err"
            tag    = "err" if status == "error" else (
                     status if status in ("ok", "warn", "crit") else "err")
            days_s = str(r.get("days", "--"))
            self._tree.insert("", "end", values=(
                r["host"], r["port"], days_s,
                r.get("expires", "--"),
                r.get("issuer", r.get("error", "--")),
                r.get("sans", "--"),
            ), tags=(tag,))

        if crit:
            self._set_status("{} certificate{} expiring within {} days!".format(
                crit, "s" if crit != 1 else "", self.CRIT_DAYS), "error")
        elif warn:
            self._set_status("{} certificate{} expiring within {} days".format(
                warn, "s" if warn != 1 else "", self.WARN_DAYS), "warn")
        elif err:
            self._set_status("{} host{} could not be checked".format(
                err, "s" if err != 1 else ""), "error")
        elif ok:
            self._set_status("All {} certificate{} OK".format(
                ok, "s" if ok != 1 else ""), "ok")
        else:
            self._set_status("No results", "info")

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "ok": t.status_running, "warn": t.yellow, "error": t.status_stopped}
        self._status.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))

    # =========================================================
    # DIAGNOSE
    # =========================================================
    def _diagnose(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._diag_frame.pack(fill="x", padx=16, pady=(0, 4),
                               before=self._status)
        self._diag_write("Running diagnostics…\n\n")
        threading.Thread(target=self._run_diagnostics, daemon=True).start()

    def _run_diagnostics(self):
        ssh  = self.controller.ssh
        host = self.controller.config_manager.last_host or "localhost"
        lines = []

        # 1. All TCP listeners (what ports are actually open)
        out, _, _ = ssh.run(
            "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null")
        lines.append("=== All TCP listeners ===")
        lines.append(out.strip() if out.strip() else "(could not list ports)")
        lines.append("")

        # 2. Docker containers + port mappings
        out, _, _ = ssh.run(
            "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null")
        lines.append("=== Docker containers & ports ===")
        lines.append(out.strip() if out.strip() else "(docker not available or no containers)")
        lines.append("")

        # 3. Let's Encrypt / Certbot certs
        out, _, _ = ssh.run(
            "if [ -d /etc/letsencrypt/live ]; then "
            "  echo \"Let's Encrypt domains:\"; ls /etc/letsencrypt/live/; "
            "  for d in /etc/letsencrypt/live/*/; do echo; echo \"  $d\"; "
            "    openssl x509 -noout -enddate -subject -in \"$d/cert.pem\" 2>/dev/null "
            "    || echo '    (unreadable)'; done; "
            "else echo 'No /etc/letsencrypt/live directory'; fi")
        lines.append("=== Let's Encrypt / Certbot ===")
        lines.append(out.strip() if out.strip() else "(not found)")
        lines.append("")

        # 4. Nginx Proxy Manager cert store (common Docker volume mount paths)
        out, _, _ = ssh.run(
            "for p in"
            " /opt/npm/data/letsencrypt/live"
            " /opt/nginx-proxy-manager/data/letsencrypt/live"
            " /data/letsencrypt/live"
            " /docker/nginx-proxy-manager/data/letsencrypt/live"
            " /home/*/nginx-proxy-manager/data/letsencrypt/live"
            " /root/nginx-proxy-manager/data/letsencrypt/live; do"
            " if [ -d \"$p\" ]; then"
            "   echo \"Found NPM certs at $p:\"; ls \"$p\";"
            "   for d in \"$p\"/*/; do echo; echo \"  $d\";"
            "     openssl x509 -noout -enddate -subject -in \"$d/cert.pem\" 2>/dev/null"
            "     || echo '    (unreadable)'; done; fi; done")
        lines.append("=== Nginx Proxy Manager (NPM) cert paths ===")
        lines.append(out.strip() if out.strip() else "(no NPM cert paths found)")
        lines.append("")

        # 5. Docker volume inspect — find any SSL/cert mounts
        out, _, _ = ssh.run(
            "docker inspect $(docker ps -q 2>/dev/null) 2>/dev/null"
            " | python3 -c \""
            "import sys,json; data=json.load(sys.stdin);"
            "[print(c['Name'],m['Source'],'->',m['Destination'])"
            " for c in data for m in c.get('Mounts',[])"
            " if any(k in (m.get('Source','')+m.get('Destination',''))"
            "        for k in ['letsencrypt','ssl','cert','tls','npm','acme'])"
            "]\" 2>/dev/null")
        lines.append("=== Docker SSL volume mounts ===")
        lines.append(out.strip() if out.strip() else "(none found)")
        lines.append("")

        # 6. Traefik acme.json
        out, _, _ = ssh.run(
            "find /opt /root /home /docker /var/lib -name 'acme.json' 2>/dev/null"
            " | head -5")
        lines.append("=== Traefik acme.json locations ===")
        lines.append(out.strip() if out.strip() else "(no acme.json found)")
        lines.append("")

        # 7. Direct openssl probes (443 on all targets)
        for target in ["localhost", "127.0.0.1", host]:
            out, _, _ = ssh.run(
                "bash -c \"timeout 5 openssl s_client"
                " -connect {t}:443 -servername {h} </dev/null 2>&1"
                " | grep -E 'CONNECTED|subject|issuer|Not After|errno|refused'\"".format(
                    t=_dq(target), h=_dq(host)))
            lines.append("=== openssl probe -> {}:443 ===".format(target))
            lines.append(out.strip() if out.strip() else "(connection refused)")
            lines.append("")

        # 8. Web server config cert references
        out, _, _ = ssh.run(
            "grep -rh 'ssl_certificate\\|SSLCertificateFile\\|cert_file\\|tls_certificate' "
            "/etc/nginx /etc/apache2 /etc/caddy ~/.config/caddy /etc/haproxy 2>/dev/null"
            " | grep -v '#' | sort -u | head -20")
        lines.append("=== Cert paths in web server configs ===")
        lines.append(out.strip() if out.strip() else "(none found)")

        self.after(0, lambda: self._diag_write("\n".join(lines)))

    def _diag_write(self, text):
        self._diag_text.configure(state="normal")
        self._diag_text.delete("1.0", "end")
        self._diag_text.insert("end", text)
        self._diag_text.configure(state="disabled")
