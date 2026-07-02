# ui/vpn_tab.py
"""
VPN Status tab — ProtonVPN-aware.
Tries protonvpn-cli first, then falls back to wg show / tun interface detection.
"""

import tkinter as tk
import threading
import re

from ui.refresh_control import RefreshControl


class VPNTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller   = controller
        self.theme        = controller.theme
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # ── Header ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="VPN STATUS",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "vpn",
                                  default=30, on_refresh=self.refresh)
        self._rc.pack(side="right")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh",
                                       command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="",
                                   bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # ── Big status card ───────────────────────────────────
        self._status_card = tk.Frame(self, bg=t.card_bg,
                                      highlightbackground=t.card_border,
                                      highlightthickness=1)
        self._status_card.pack(fill="x", padx=16, pady=(0, 12))

        # Left: icon + big status text
        left = tk.Frame(self._status_card, bg=t.card_bg)
        left.pack(side="left", padx=24, pady=20)

        self._icon_lbl = tk.Label(left, text="🔒",
                                   bg=t.card_bg, fg=t.text_muted,
                                   font=("Segoe UI", 36))
        self._icon_lbl.pack()
        self._state_lbl = tk.Label(left, text="Unknown",
                                    bg=t.card_bg, fg=t.text_muted,
                                    font=("Segoe UI Semibold", 18))
        self._state_lbl.pack()

        # Right: detail grid
        right = tk.Frame(self._status_card, bg=t.card_bg)
        right.pack(side="left", padx=(0, 24), pady=20, fill="both", expand=True)

        self._detail_rows = {}
        for label in ("Server", "Protocol", "VPN IP", "Public IP",
                       "Data In", "Data Out", "Uptime"):
            row = tk.Frame(right, bg=t.card_bg)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label + ":",
                     bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small, width=10, anchor="w").pack(side="left")
            val = tk.Label(row, text="—",
                           bg=t.card_bg, fg=t.text,
                           font=t.font_regular, anchor="w")
            val.pack(side="left")
            self._detail_rows[label] = val

        # ── Raw output box ────────────────────────────────────
        raw_frame = tk.Frame(self, bg=t.bg)
        raw_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tk.Label(raw_frame, text="Raw Output",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(anchor="w")
        self._raw = tk.Text(raw_frame, height=12,
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
        self._rc.cancel()

        if not self.controller.ssh.connected:
            self._set_bar("Not connected to SSH", "error")
            return

        self._refresh_btn.config(state="disabled", text="Checking…")
        self._set_bar("Querying VPN status…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _schedule_next(self):
        self._rc.schedule()

    # =========================================================
    # FETCH  (background thread)
    # =========================================================
    def _fetch(self):
        try:
            ssh    = self.controller.ssh
            result = {"state": "Unknown", "raw": ""}

            # ── 1. Try protonvpn-cli ─────────────────────────────
            out, _, code = ssh.run(
                "protonvpn-cli status 2>/dev/null || protonvpn status 2>/dev/null")
            if out and out.strip() and "command not found" not in out:
                result["raw"] = out
                self._parse_protonvpn_cli(out, result)
            else:
                # ── 2. Try systemctl ──────────────────────────────
                svc_out, _, _ = ssh.run(
                    "systemctl is-active protonvpn 2>/dev/null; "
                    "systemctl is-active protonvpn-cli 2>/dev/null")
                if "active" in (svc_out or ""):
                    result["state"] = "Connected"

                # ── 3. Try wg show ────────────────────────────────
                wg_out, _, _ = ssh.run("sudo wg show 2>/dev/null")
                if wg_out and wg_out.strip():
                    result["raw"] += "\n--- wg show ---\n" + wg_out
                    self._parse_wg(wg_out, result)

                # ── 4. Detect tun/proton interface ────────────────
                ip_out, _, _ = ssh.run(
                    "ip addr show 2>/dev/null | grep -E '(proton|tun|wg)[0-9]'")
                if ip_out and ip_out.strip():
                    result.setdefault("iface", ip_out.strip().split()[1].rstrip(":"))
                    if result["state"] == "Unknown":
                        result["state"] = "Connected (interface up)"
                    result["raw"] += "\n--- ip addr ---\n" + ip_out

            # ── 5. Public IP check ───────────────────────────────
            pub_out, _, _ = ssh.run(
                "curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
            if pub_out and pub_out.strip():
                result["public_ip"] = pub_out.strip()

            if not result.get("raw"):
                result["raw"] = ("protonvpn-cli not found and no WireGuard/tun "
                                 "interface detected.\n\n"
                                 "Make sure protonvpn-cli is installed or that "
                                 "the VPN interface is visible to this user.")

            self.after(0, lambda r=result: self._populate(r))
        finally:
            self._fetching = False

    # =========================================================
    # PARSERS
    # =========================================================
    def _parse_protonvpn_cli(self, text, result):
        """Parse protonvpn-cli status output into result dict."""
        lines = text.splitlines()
        for line in lines:
            low = line.lower()
            if "status" in low and ":" in line:
                val = line.split(":", 1)[1].strip()
                result["state"] = val
            elif "server" in low and ":" in line:
                result["server"] = line.split(":", 1)[1].strip()
            elif "exit ip" in low and ":" in line:
                result["vpn_ip"] = line.split(":", 1)[1].strip()
            elif "ip" in low and ":" in line and "vpn_ip" not in result:
                val = line.split(":", 1)[1].strip()
                if re.match(r"\d+\.\d+\.\d+\.\d+", val):
                    result["vpn_ip"] = val
            elif "protocol" in low and ":" in line:
                result["protocol"] = line.split(":", 1)[1].strip()
            elif "time" in low and ":" in line:
                result["uptime"] = line.split(":", 1)[1].strip()
            elif "country" in low and ":" in line:
                result.setdefault("server",
                                  line.split(":", 1)[1].strip())

    def _parse_wg(self, text, result):
        """Parse wg show output into result dict."""
        if not text.strip():
            return
        result.setdefault("protocol", "WireGuard")
        if result["state"] == "Unknown":
            result["state"] = "Connected"

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("interface:"):
                result["iface"] = line.split(":", 1)[1].strip()
            elif line.startswith("endpoint:"):
                result.setdefault("server", line.split(":", 1)[1].strip())
            elif line.startswith("transfer:"):
                # "transfer: 123 MiB received, 45 MiB sent"
                m = re.search(
                    r"([\d.]+ \w+)\s+received,\s+([\d.]+ \w+)\s+sent",
                    line)
                if m:
                    result["data_in"]  = m.group(1)
                    result["data_out"] = m.group(2)
            elif line.startswith("latest handshake:"):
                result["uptime"] = "Last handshake: " + line.split(":", 1)[1].strip()

    # =========================================================
    # POPULATE  (main thread)
    # =========================================================
    def _populate(self, result):
        import time
        t      = self.theme
        state  = result.get("state", "Unknown")
        is_con = any(x in state.lower() for x in ("connected", "active"))

        # Icon + color
        icon  = "🔒" if is_con else "🔓"
        color = t.status_running if is_con else t.status_stopped
        if state.lower() in ("unknown", "disconnected", ""):
            icon  = "🔓"
            color = t.text_muted

        self._icon_lbl.config(text=icon, fg=color)
        self._state_lbl.config(text=state, fg=color)
        self._status_card.config(
            highlightbackground=color if is_con else t.card_border)

        # Detail rows
        fields = {
            "Server":    result.get("server",     "—"),
            "Protocol":  result.get("protocol",   "—"),
            "VPN IP":    result.get("vpn_ip",     "—"),
            "Public IP": result.get("public_ip",  "—"),
            "Data In":   result.get("data_in",    "—"),
            "Data Out":  result.get("data_out",   "—"),
            "Uptime":    result.get("uptime",     "—"),
        }
        for label, val in fields.items():
            self._detail_rows[label].config(text=val)

        # Raw output
        self._raw.config(state="normal")
        self._raw.delete("1.0", "end")
        self._raw.insert("end", result.get("raw", "").strip())
        self._raw.config(state="disabled")

        # Timestamps + button
        self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M:%S")))
        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._set_bar(
            "VPN is {}".format(state),
            "ok" if is_con else "info")

        self._schedule_next()

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
