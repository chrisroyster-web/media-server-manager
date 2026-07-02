# ui/speedtest_tab.py
"""
Speedtest on demand.
Runs speedtest-cli (or the Ookla speedtest CLI) on the remote server via SSH.
Supports server selection via --list and multiple curl fallback endpoints.
"""

import tkinter as tk
from tkinter import ttk
import threading
import json
import re
import time


# Curl fallback endpoints: display_name -> (ping_url, download_url)
CURL_ENDPOINTS = {
    "Cloudflare":         ("https://speed.cloudflare.com/__down?bytes=1",
                           "https://speed.cloudflare.com/__down?bytes=25000000"),
    "Hetzner (Germany)":  ("http://speed.hetzner.de/1MB.bin",
                           "http://speed.hetzner.de/100MB.bin"),
    "Hetzner (Ashburn)":  ("http://ash-speed.hetzner.com/1MB.bin",
                           "http://ash-speed.hetzner.com/100MB.bin"),
    "Hetzner (Helsinki)": ("http://hel-speed.hetzner.com/1MB.bin",
                           "http://hel-speed.hetzner.com/100MB.bin"),
    "OVH (Canada)":       ("https://bhs.proof.ovh.net/files/1Mb.dat",
                           "https://bhs.proof.ovh.net/files/100Mb.dat"),
    "OVH (France)":       ("https://rbx.proof.ovh.net/files/1Mb.dat",
                           "https://rbx.proof.ovh.net/files/100Mb.dat"),
    "OVH (Germany)":      ("https://fra.proof.ovh.net/files/1Mb.dat",
                           "https://fra.proof.ovh.net/files/100Mb.dat"),
}


class SpeedtestTab(tk.Frame):

    MAX_HISTORY = 20

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller  = controller
        self.theme       = controller.theme
        self._history    = []
        self._running    = False
        self._server_map = {}   # display label -> server ID for speedtest-cli
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="SPEEDTEST",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._install_btn = tk.Button(hdr, text="Download speedtest-cli",
                                      command=self._install_speedtest)
        t.style_button(self._install_btn)
        self._install_btn.pack(side="right", padx=(0, 8))
        self._install_btn.pack_forget()
        self._run_btn = tk.Button(hdr, text="Run Test", command=self._start_test)
        t.style_button(self._run_btn)
        self._run_btn.pack(side="right")
        self._ts_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                font=t.font_small)
        self._ts_lbl.pack(side="right", padx=12)

        # Server picker row (CLI mode)
        picker = tk.Frame(self, bg=t.bg)
        picker.pack(fill="x", padx=16, pady=(0, 8))

        self._cli_picker = tk.Frame(picker, bg=t.bg)
        self._cli_picker.pack(side="left", fill="x")
        tk.Label(self._cli_picker, text="Server:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._server_var = tk.StringVar(value="Auto (best)")
        self._server_menu = tk.OptionMenu(self._cli_picker, self._server_var,
                                          "Auto (best)")
        self._server_menu.configure(
            bg=t.surface, fg=t.text, activebackground=t.surface_light,
            relief="flat", bd=0, font=t.font_small,
            highlightthickness=1, highlightbackground=t.card_border,
            padx=8, pady=3)
        self._server_menu["menu"].configure(bg=t.surface, fg=t.text,
                                            font=t.font_small)
        self._server_menu.pack(side="left", padx=(4, 0))
        self._list_btn = tk.Button(self._cli_picker, text="List Servers",
                                   command=self._list_servers)
        t.style_button(self._list_btn)
        self._list_btn.pack(side="left", padx=(6, 0))
        self._list_lbl = tk.Label(self._cli_picker, text="", bg=t.bg,
                                  fg=t.text_muted, font=t.font_small)
        self._list_lbl.pack(side="left", padx=(8, 0))

        # Endpoint picker row (curl mode) - hidden until needed
        self._curl_picker = tk.Frame(picker, bg=t.bg)
        tk.Label(self._curl_picker, text="Endpoint:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._curl_ep_var = tk.StringVar(value="Cloudflare")
        curl_menu = tk.OptionMenu(self._curl_picker, self._curl_ep_var,
                                  *list(CURL_ENDPOINTS.keys()))
        curl_menu.configure(
            bg=t.surface, fg=t.text, activebackground=t.surface_light,
            relief="flat", bd=0, font=t.font_small,
            highlightthickness=1, highlightbackground=t.card_border,
            padx=8, pady=3)
        curl_menu["menu"].configure(bg=t.surface, fg=t.text, font=t.font_small)
        curl_menu.pack(side="left", padx=(4, 0))

        # Big metric cards
        cards_frame = tk.Frame(self, bg=t.bg)
        cards_frame.pack(fill="x", padx=16, pady=(0, 12))
        self._metric_vals  = {}
        self._metric_units = {}
        for label, color in [("Download", t.status_running),
                              ("Upload",   t.blue),
                              ("Ping",     t.yellow)]:
            card = tk.Frame(cards_frame, bg=t.card_bg,
                            highlightbackground=t.card_border,
                            highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small).pack(pady=(12, 0))
            val_var  = tk.StringVar(value="--")
            unit_var = tk.StringVar(value="")
            self._metric_vals[label]  = val_var
            self._metric_units[label] = unit_var
            tk.Label(card, textvariable=val_var, bg=t.card_bg, fg=color,
                     font=("Segoe UI Semibold", 26)).pack()
            tk.Label(card, textvariable=unit_var, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small).pack(pady=(0, 12))

        # Info card
        info_card = tk.Frame(self, bg=t.card_bg,
                             highlightbackground=t.card_border,
                             highlightthickness=1)
        info_card.pack(fill="x", padx=16, pady=(0, 12))
        inner = tk.Frame(info_card, bg=t.card_bg)
        inner.pack(fill="x", padx=16, pady=10)
        self._info_vars = {}
        for label in ("ISP", "Server", "Location", "Distance"):
            col = tk.Frame(inner, bg=t.card_bg)
            col.pack(side="left", padx=16)
            tk.Label(col, text=label, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small).pack()
            var = tk.StringVar(value="--")
            self._info_vars[label] = var
            tk.Label(col, textvariable=var, bg=t.card_bg, fg=t.text,
                     font=t.font_regular).pack()

        # Progress
        prog_frame = tk.Frame(self, bg=t.bg)
        prog_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._prog_lbl = tk.Label(prog_frame, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small, anchor="w")
        self._prog_lbl.pack(fill="x")
        self._pbar = ttk.Progressbar(prog_frame, mode="indeterminate", length=200)

        # History table
        tk.Label(self, text="Test History", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=16)
        hist_frame = tk.Frame(self, bg=t.bg)
        hist_frame.pack(fill="both", expand=True, padx=16, pady=(2, 8))
        cols   = ("Time", "Download", "Upload", "Ping", "Server")
        widths = (120, 100, 100, 80, 260)
        style  = ttk.Style()
        style.configure("Speed.Treeview", background=t.surface, foreground=t.text,
                        fieldbackground=t.surface, borderwidth=0, rowheight=24)
        style.configure("Speed.Treeview.Heading", background=t.surface_dark,
                        foreground=t.text_muted, relief="flat")
        style.map("Speed.Treeview",
                  background=[("selected", t.sidebar_active_bg)])
        self._tree = ttk.Treeview(hist_frame, columns=cols, show="headings",
                                   style="Speed.Treeview")
        for col, w in zip(cols, widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, minwidth=40,
                              anchor="center" if col in ("Download","Upload","Ping") else "w")
        vsb = ttk.Scrollbar(hist_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status bar
        self._status_bar = tk.Label(self, text="Press Run Test to start",
                                    bg=t.surface_dark, fg=t.text_muted,
                                    font=t.font_small, anchor="w")
        self._status_bar.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # LIST SERVERS
    # =========================================================
    def _list_servers(self):
        if not self.controller.ssh.connected:
            self._set_bar("Not connected to SSH", "error")
            return
        self._list_btn.config(state="disabled", text="Fetching...")
        self._list_lbl.config(text="")
        threading.Thread(target=self._do_list_servers, daemon=True).start()

    def _do_list_servers(self):
        ssh = self.controller.ssh
        out, _, _ = ssh.run(
            "python3 -m speedtest --list 2>/dev/null | head -25 || "
            "speedtest-cli --list 2>/dev/null | head -25")
        servers = []
        if out:
            pat = re.compile(
                r'^\s*(\d+)\)\s+(.+?)\s+\((.+?)\)\s+\[([\d.]+)\s+km\]', re.M)
            for m in pat.finditer(out):
                sid, name, location, dist = m.groups()
                label = "{}) {} ({}) [{} km]".format(sid, name, location, dist)
                servers.append((label, sid))
        self.after(0, lambda s=servers: self._apply_server_list(s))

    def _apply_server_list(self, servers):
        self._list_btn.config(state="normal", text="List Servers")
        if not servers:
            self._list_lbl.config(text="No servers found (need speedtest-cli)")
            return
        self._server_map = {lbl: sid for lbl, sid in servers}
        menu = self._server_menu["menu"]
        menu.delete(0, "end")
        menu.add_command(label="Auto (best)",
                         command=lambda: self._server_var.set("Auto (best)"))
        for lbl, _ in servers:
            menu.add_command(label=lbl,
                             command=lambda l=lbl: self._server_var.set(l))
        self._server_var.set("Auto (best)")
        self._list_lbl.config(text="{} servers found".format(len(servers)))

    # =========================================================
    # RUN TEST
    # =========================================================
    def _start_test(self):
        if self._running:
            return
        if not self.controller.ssh.connected:
            self._set_bar("Not connected to SSH", "error")
            return
        self._running = True
        self._run_btn.config(state="disabled", text="Running...")
        self._prog_lbl.config(text="Starting speedtest...")
        self._pbar.pack(fill="x", pady=4)
        self._pbar.start(12)
        self._set_bar("Running speedtest on server...")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _selected_server_id(self):
        sel = self._server_var.get()
        if sel == "Auto (best)":
            return None
        return self._server_map.get(sel)

    # =========================================================
    # FETCH  (background thread)
    # =========================================================
    @staticmethod
    def _has_data(r):
        return bool(r) and "error" not in r and r.get("download") is not None

    def _fetch(self):
        ssh       = self.controller.ssh
        result    = {}
        server_id = self._selected_server_id()
        sv_flag   = "--server {}".format(server_id) if server_id else ""

        # Pre-check available tools
        probe, _, _ = ssh.run(
            "echo START;"
            "command -v speedtest   2>/dev/null && echo HAS_OOKLA || true;"
            "command -v speedtest-cli 2>/dev/null && echo HAS_CLI  || true;"
            "python3 -c 'import speedtest; print(\"HAS_PY\")' 2>/dev/null || true;"
            "echo END")
        has_ookla = "HAS_OOKLA" in (probe or "")
        has_cli   = "HAS_CLI"   in (probe or "")
        has_py    = "HAS_PY"    in (probe or "")

        # 1. Ookla CLI
        if has_ookla:
            ookla_sv = "--server-id {}".format(server_id) if server_id else ""
            self.after(0, lambda: self._prog_lbl.config(
                text="Running Ookla speedtest (~30 s)..."))
            out, _, _ = ssh.run(
                "speedtest --format=json --accept-license --accept-gdpr "
                "{} 2>/dev/null".format(ookla_sv))
            if out and self._extract_json(out):
                result = self._parse_ookla(out)

        # 2. speedtest-cli binary
        if not self._has_data(result) and has_cli:
            self.after(0, lambda: self._prog_lbl.config(
                text="Running speedtest-cli (~30 s)..."))
            out, _, _ = ssh.run(
                "speedtest-cli --json {} 2>/dev/null".format(sv_flag))
            if out:
                parsed = self._extract_json(out)
                if parsed:
                    result = self._parse_json_dict(parsed)
            if not self._has_data(result):
                out, _, _ = ssh.run(
                    "speedtest-cli --simple {} 2>/dev/null".format(sv_flag))
                if out and out.strip():
                    result = self._parse_simple(out)

        # 3. python3 -m speedtest
        if not self._has_data(result) and has_py:
            self.after(0, lambda: self._prog_lbl.config(
                text="Running speedtest via python3 (~30 s)..."))
            out, _, _ = ssh.run(
                "python3 -m speedtest --json {} 2>/dev/null".format(sv_flag))
            if out:
                parsed = self._extract_json(out)
                if parsed:
                    result = self._parse_json_dict(parsed)
            if not self._has_data(result):
                out, _, _ = ssh.run(
                    "python3 -m speedtest --simple {} 2>/dev/null".format(sv_flag))
                if out and out.strip():
                    result = self._parse_simple(out)

        # 4. curl fallback
        if not self._has_data(result):
            ep = self._curl_ep_var.get()
            self.after(0, lambda e=ep: self._prog_lbl.config(
                text="No speedtest CLI -- measuring with curl ({})...".format(e)))
            result = self._curl_speedtest(ssh)

        result["timestamp"] = time.strftime("%Y-%m-%d %H:%M")
        self.after(0, lambda r=result: self._populate(r))

    def _curl_speedtest(self, ssh):
        ep_name = self._curl_ep_var.get()
        ping_url, dl_url = CURL_ENDPOINTS.get(
            ep_name, list(CURL_ENDPOINTS.values())[0])

        self.after(0, lambda: self._prog_lbl.config(
            text="Measuring latency ({})...".format(ep_name)))
        ping_out, _, _ = ssh.run(
            "curl -o /dev/null -s -w '%%{time_connect}' "
            "--max-time 10 '{}' 2>/dev/null".format(ping_url))
        try:
            ping_ms = round(float(ping_out.strip()) * 1000, 1)
        except Exception:
            ping_ms = None

        self.after(0, lambda: self._prog_lbl.config(
            text="Measuring download ({})...".format(ep_name)))
        dl_out, _, _ = ssh.run(
            "curl -o /dev/null -s -w '%%{speed_download}' "
            "--max-time 60 '{}' 2>/dev/null".format(dl_url))
        try:
            dl_mbps = round(float(dl_out.strip()) * 8 / 1_000_000, 2)
        except Exception:
            dl_mbps = None

        if dl_mbps is None and ping_ms is None:
            return {"needs_install": True,
                    "error": "curl test failed -- check internet access on the server."}

        return {
            "download":     dl_mbps or 0,
            "upload":       None,
            "ping":         ping_ms,
            "server":       "{} (curl)".format(ep_name),
            "location":     "--",
            "isp":          "--",
            "distance":     "--",
            "curl_fallback": True,
        }

    # =========================================================
    # PARSERS
    # =========================================================
    def _extract_json(self, text):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        try:
            return json.loads(text.strip())
        except Exception:
            return None

    def _parse_json_dict(self, d):
        try:
            dist = d.get("server", {}).get("d")
            dist_str = "{:.1f} km".format(dist) if dist else "--"
            srv  = d.get("server", {}) or {}
            loc  = "{}, {}".format(
                srv.get("name", ""), srv.get("country", "")).strip(", ")
            return {
                "download": round(d.get("download", 0) / 1_000_000, 2),
                "upload":   round(d.get("upload",   0) / 1_000_000, 2),
                "ping":     round(d.get("ping",     0), 1),
                "isp":      d.get("client", {}).get("isp", "--"),
                "server":   srv.get("sponsor", "--"),
                "location": loc,
                "distance": dist_str,
            }
        except Exception as e:
            return {"error": "Parse error: {}".format(e)}

    def _parse_ookla(self, text):
        try:
            d   = self._extract_json(text) or json.loads(text)
            srv = d.get("server", {}) or {}
            loc = "{}, {}".format(
                srv.get("location", ""), srv.get("country", "")).strip(", ")
            return {
                "download": round(d["download"]["bandwidth"] * 8 / 1_000_000, 2),
                "upload":   round(d["upload"]["bandwidth"]   * 8 / 1_000_000, 2),
                "ping":     round(d["ping"]["latency"], 1),
                "isp":      d.get("isp", "--"),
                "server":   srv.get("name", "--"),
                "location": loc,
                "distance": "--",
            }
        except Exception:
            return {"error": "Failed to parse Ookla JSON:\n" + text[:500]}

    def _parse_simple(self, text):
        result = {}
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"Ping:\s+([\d.]+)\s+ms", line, re.I)
            if m:
                result["ping"] = float(m.group(1))
            m = re.match(r"Download:\s+([\d.]+)\s+Mbit/s", line, re.I)
            if m:
                result["download"] = float(m.group(1))
            m = re.match(r"Upload:\s+([\d.]+)\s+Mbit/s", line, re.I)
            if m:
                result["upload"] = float(m.group(1))
        if not result:
            result["error"] = "No results parsed from:\n" + text
        return result

    # =========================================================
    # POPULATE  (main thread)
    # =========================================================
    def _populate(self, result):
        self._pbar.stop()
        self._pbar.pack_forget()
        self._prog_lbl.config(text="")
        self._run_btn.config(state="normal", text="Run Test")
        self._running = False

        if "error" in result:
            self._set_bar(result["error"].splitlines()[0], "error")
            for key in self._metric_vals:
                self._metric_vals[key].set("--")
                self._metric_units[key].set("")
            if result.get("needs_install"):
                self._install_btn.pack(side="right", padx=(0, 8),
                                       before=self._run_btn)
            return

        dl      = result.get("download")
        ul      = result.get("upload")
        ping    = result.get("ping")
        is_curl = result.get("curl_fallback", False)

        # Swap pickers depending on mode
        if is_curl:
            self._cli_picker.pack_forget()
            self._curl_picker.pack(side="left", fill="x")
            self._install_btn.pack(side="right", padx=(0, 8), before=self._run_btn)
        else:
            self._curl_picker.pack_forget()
            self._cli_picker.pack(side="left", fill="x")
            self._install_btn.pack_forget()

        self._metric_vals["Download"].set(str(dl)   if dl   is not None else "--")
        self._metric_vals["Upload"].set(str(ul)     if ul   is not None else "--")
        self._metric_vals["Ping"].set(str(ping)     if ping is not None else "--")
        self._metric_units["Download"].set("Mbps"   if dl   is not None else "")
        self._metric_units["Upload"].set(
            "Mbps" if ul is not None else
            "(curl can't measure upload)" if is_curl else "")
        self._metric_units["Ping"].set("ms"         if ping is not None else "")

        self._info_vars["ISP"].set(result.get("isp",      "--"))
        self._info_vars["Server"].set(result.get("server",   "--"))
        self._info_vars["Location"].set(result.get("location", "--"))
        self._info_vars["Distance"].set(result.get("distance", "--"))

        ts = result.get("timestamp", "")
        self._ts_lbl.config(text="Last run {}".format(ts))

        self._history.insert(0, result)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[:self.MAX_HISTORY]
        self._tree.delete(*self._tree.get_children())
        for r in self._history:
            self._tree.insert("", "end", values=(
                r.get("timestamp", "--"),
                "{} Mbps".format(r.get("download", "--")),
                "{} Mbps".format(r.get("upload",   "--")),
                "{} ms".format(r.get("ping",       "--")),
                r.get("server", "--"),
            ))

        parts = []
        if dl   is not None: parts.append("Download {} Mbps".format(dl))
        if ul   is not None: parts.append("Upload {} Mbps".format(ul))
        if ping is not None: parts.append("Ping {} ms".format(ping))
        if is_curl: parts.append("(curl -- install speedtest-cli for upload)")
        self._set_bar("  .  ".join(parts) if parts else "Test complete", "ok")

    # =========================================================
    # INSTALL
    # =========================================================
    def _install_speedtest(self):
        if not self.controller.ssh.connected:
            return
        self._install_btn.config(state="disabled", text="Installing...")
        self._set_bar("Installing speedtest-cli via pip...")
        def _do():
            ssh = self.controller.ssh
            out, err, code = ssh.run(
                "pip3 install speedtest-cli --break-system-packages 2>&1 || "
                "pip install speedtest-cli --break-system-packages 2>&1")
            combined = (out or "") + (err or "")
            ok = code == 0 or "Successfully installed" in combined
            def _done():
                self._install_btn.config(state="normal",
                                         text="Download speedtest-cli")
                if ok:
                    self._install_btn.pack_forget()
                    self._set_bar("speedtest-cli installed -- running test...", "ok")
                    self._start_test()
                else:
                    self._set_bar("Install failed: " + combined[:120], "error")
            self.after(0, _done)
        threading.Thread(target=_do, daemon=True).start()

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
