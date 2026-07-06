# ui/tailscale_tab.py
"""
Tailscale status tab.
Parses `tailscale status --json` over SSH into a peer table.
"""

import datetime
import tkinter as tk
from tkinter import ttk
import threading
import time
import json

from ui.refresh_control import RefreshControl


class TailscaleTab(tk.Frame):

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

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="TAILSCALE", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "tailscale",
                                  default=30, on_refresh=self.refresh)
        self._rc.pack(side="right")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_self    = self._stat_card(s_row, "My Node",  "--", t.cyan)
        self._card_online  = self._stat_card(s_row, "Online",   "--", t.status_running)
        self._card_offline = self._stat_card(s_row, "Offline",  "--", t.text_muted)
        self._card_exits   = self._stat_card(s_row, "Exits",    "--", t.purple)

        # Peer table
        tbl_frame = tk.Frame(self, bg=t.bg)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        style.configure("TS.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("TS.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("TS.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("name", "addr", "os", "relay", "rx", "tx", "last_seen", "exit")
        self._tree = ttk.Treeview(tbl_frame, columns=cols,
                                   show="headings", style="TS.Treeview")
        for col, w, lbl, anchor in [
            ("name",      160, "Hostname",   "w"),
            ("addr",      140, "Tailscale IP","w"),
            ("os",         80, "OS",         "w"),
            ("relay",      80, "Relay",      "w"),
            ("rx",         80, "RX",         "e"),
            ("tx",         80, "TX",         "e"),
            ("last_seen", 130, "Last Seen",  "w"),
            ("exit",       40, "Exit",       "c"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anchor)
            self._tree.column(col, width=w, minwidth=40,
                              anchor=anchor, stretch=(col in ("name", "addr")))

        self._tree.tag_configure("online",  foreground=t.status_running)
        self._tree.tag_configure("offline", foreground=t.text_muted)
        self._tree.tag_configure("exit",    foreground=t.purple)

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status / detail panel
        det_frame = tk.Frame(self, bg=t.surface_dark,
                             highlightbackground=t.card_border, highlightthickness=1)
        det_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._detail = tk.Label(det_frame, text="", bg=t.surface_dark,
                                fg=t.text_muted, font=t.font_mono,
                                anchor="w", justify="left")
        self._detail.pack(fill="x", padx=8, pady=4)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Status bar
        self._status = tk.Label(self, text="Press 'Refresh' to load Tailscale status",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        self._peers = []

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
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected", bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)
            return
        self._status.config(text="Loading Tailscale status…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        self._refresh_btn.config(state="disabled")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            out, err, code = ssh.run("tailscale status --json 2>/dev/null")
            if code != 0 or not out.strip():
                # Try without --json (older versions)
                out_txt, _, code2 = ssh.run("tailscale status 2>/dev/null")
                if code2 == 0:
                    self.after(0, lambda: self._populate_text(out_txt))
                else:
                    self.after(0, lambda: self._status.config(
                        text="tailscale not found or not running",
                        bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
                return
            try:
                data = json.loads(out)
            except Exception:
                self.after(0, lambda: self._status.config(
                    text="Could not parse tailscale JSON output",
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
                return
            self.after(0, lambda: self._populate(data))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False
            self.after(0, lambda: self._refresh_btn.config(state="normal"))

    def _populate(self, data):
        t = self.theme
        # Self node
        self_node = data.get("Self", {})
        self_name = self_node.get("HostName", "")
        self._card_self.config(text=self_name[:16] if self_name else "--")

        peers = data.get("Peer", {})
        self._peers = sorted(peers.values(),
                             key=lambda p: (0 if p.get("Online") else 1,
                                            p.get("HostName", "")))

        online  = sum(1 for p in self._peers if p.get("Online"))
        offline = len(self._peers) - online
        exits   = sum(1 for p in self._peers if p.get("ExitNodeOption"))

        self._card_online.config(text=str(online),
                                  fg=t.status_running if online else t.text_muted)
        self._card_offline.config(text=str(offline),
                                   fg=t.text_dim if not offline else t.text_muted)
        self._card_exits.config(text=str(exits),
                                 fg=t.purple if exits else t.text_muted)

        self._tree.delete(*self._tree.get_children())
        for peer in self._peers:
            is_online = peer.get("Online", False)
            is_exit   = peer.get("ExitNodeOption", False)
            tag = "exit" if is_exit else ("online" if is_online else "offline")
            addrs = peer.get("TailscaleIPs", [])
            addr  = addrs[0] if addrs else "--"
            relay = peer.get("Relay", "direct") or "direct"
            rx_b  = peer.get("RxBytes", 0)
            tx_b  = peer.get("TxBytes", 0)
            last  = peer.get("LastSeen", "") or ("now" if is_online else "—")
            if last and last not in ("now", "—") and "T" in last:
                try:
                    dt = datetime.datetime.fromisoformat(last.replace("Z", "+00:00"))
                    last = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            self._tree.insert("", "end", values=(
                peer.get("HostName", "--"),
                addr,
                peer.get("OS", "--"),
                relay,
                self._fmt_bytes(rx_b),
                self._fmt_bytes(tx_b),
                last,
                "✓" if is_exit else "",
            ), tags=(tag,))

        total = len(self._peers)
        self._status.config(
            text="{} peer{} total  |  {} online  |  {} offline".format(
                total, "s" if total != 1 else "", online, offline),
            bg=t.surface_dark, fg=t.text_muted)

    def _populate_text(self, text):
        """Fallback: display raw text output in the status area."""
        self._status.config(text=text[:200], bg=self.theme.surface_dark, fg=self.theme.text_muted)

    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        idx  = self._tree.index(sel[0])
        peer = self._peers[idx] if idx < len(self._peers) else {}
        addrs = ", ".join(peer.get("TailscaleIPs", []))
        tags  = ", ".join(peer.get("Tags", []) or [])
        lines = [
            "Hostname: {}    OS: {}    IPs: {}".format(
                peer.get("HostName", "--"),
                peer.get("OS", "--"),
                addrs or "--"),
            "Online: {}    Relay: {}    Exit node: {}    Active: {}".format(
                peer.get("Online", False),
                peer.get("Relay", "direct"),
                peer.get("ExitNodeOption", False),
                peer.get("Active", False)),
        ]
        if tags:
            lines.append("Tags: {}".format(tags))
        self._detail.config(text="  |  ".join(lines[:2]) + ("\n" + lines[2] if len(lines) > 2 else ""))

    @staticmethod
    def _fmt_bytes(b):
        if not b:
            return "--"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return "{:.1f} {}".format(b, unit)
            b /= 1024
        return "{:.1f} PB".format(b)
