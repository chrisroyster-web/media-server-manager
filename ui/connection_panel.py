# ui/connection_panel.py

import tkinter as tk
from tkinter import messagebox
import threading
import re
import socket
import time


class ConnectionPanel(tk.Frame):
    """
    Connection log panel — shows SSH connect/disconnect events.
    Server management (add / edit / delete / connect) is handled
    by the sidebar "+" button and the Server Dialog modal.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)

        self.controller = controller
        self.theme      = controller.theme
        self.config_mgr = controller.config_manager

        self._build_ui()

    # ---------------------------------------------------------
    # BUILD UI
    # ---------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # ── Left panel: controls ──────────────────────────────
        left = tk.Frame(self, bg=t.surface, padx=16, pady=16)
        left.pack(side="left", fill="y")

        tk.Label(left, text="CONNECTION", bg=t.surface,
                 fg=t.text, font=t.font_title).pack(anchor="w", pady=(0, 6))

        tk.Label(left,
                 text="Use the server buttons in the sidebar\n"
                      "to connect and switch servers.\n\n"
                      "Click  +  in the SERVERS section to\n"
                      "add a new server profile.",
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small, justify="left").pack(anchor="w", pady=(0, 14))

        btn_frame = tk.Frame(left, bg=t.surface)
        btn_frame.pack(fill="x")

        self.disconnect_btn = tk.Button(btn_frame, text="Disconnect",
                                        command=self._disconnect)
        t.style_button(self.disconnect_btn)
        self.disconnect_btn.pack(fill="x", pady=4)

        self.shutdown_btn = tk.Button(btn_frame, text="Shutdown Server",
                                      command=self._shutdown_confirm)
        t.style_button(self.shutdown_btn)
        self.shutdown_btn.pack(fill="x", pady=4)

        # ── Wake-on-LAN ───────────────────────────────────────
        tk.Frame(left, bg=t.card_border, height=1).pack(fill="x", pady=(14, 10))
        tk.Label(left, text="WAKE-ON-LAN", bg=t.surface,
                 fg=t.text_muted, font=("Segoe UI", 8, "bold")).pack(anchor="w")

        self.wol_mac_var   = tk.StringVar(value=self.config_mgr.wol_mac)
        self.wol_bcast_var = tk.StringVar(value=self.config_mgr.wol_broadcast)
        self._field(left, "MAC Address", self.wol_mac_var)
        self._field(left, "Broadcast IP", self.wol_bcast_var)

        wol_btn = tk.Button(btn_frame, text="\U0001f4a4 Wake Server",
                            command=self._send_wol)
        t.style_button(wol_btn)
        wol_btn.pack(fill="x", pady=4)

        # ── Right panel: connection log ───────────────────────
        right = tk.Frame(self, bg=t.bg)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

        hdr = tk.Frame(right, bg=t.bg)
        hdr.pack(fill="x", pady=(0, 6))
        tk.Label(hdr, text="Connection Log", bg=t.bg,
                 fg=t.text, font=t.font_title).pack(side="left")
        clear_btn = tk.Button(hdr, text="Clear", command=self._clear)
        t.style_button(clear_btn)
        clear_btn.pack(side="right")

        log_frame = tk.Frame(right, bg=t.bg)
        log_frame.pack(fill="both", expand=True)

        self.output = tk.Text(
            log_frame, bg=t.surface_dark, fg=t.text,
            font=t.font_mono, wrap="word", state="disabled",
            relief="flat", padx=10, pady=8,
        )
        self.output.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(log_frame, command=self.output.yview)
        sb.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=sb.set)

        self._configure_tags()

    # ---------------------------------------------------------
    # FIELD BUILDER (WoL only)
    # ---------------------------------------------------------
    def _field(self, parent, label, var):
        tk.Label(parent, text=label, bg=self.theme.surface,
                 fg=self.theme.text_secondary, font=self.theme.font_small).pack(anchor="w")
        entry = tk.Entry(parent, textvariable=var, font=self.theme.font_regular)
        self.theme.style_entry(entry)
        entry.pack(fill="x", pady=(0, 10))

    # ---------------------------------------------------------
    # REFRESH FOR ACTIVE SERVER  (called by apply_config)
    # ---------------------------------------------------------
    def refresh_for_server(self, profile: dict):
        """Update WoL fields to match the active server's stored values."""
        self.wol_mac_var.set(self.config_mgr.wol_mac)
        self.wol_bcast_var.set(self.config_mgr.wol_broadcast)

    # ---------------------------------------------------------
    # DISCONNECT
    # ---------------------------------------------------------
    def _disconnect(self):
        host = self.config_mgr.last_host
        self.controller._stop_reconnect_watchdog()
        self.controller.ssh.disconnect()
        self._log("Disconnected from {0}".format(host), "info")
        self.controller.update_status(False)

    # ---------------------------------------------------------
    # SHUTDOWN SERVER
    # ---------------------------------------------------------
    def _shutdown_confirm(self):
        if not messagebox.askyesno(
                "Shutdown Server",
                "Are you sure you want to shut down the server?",
                parent=self):
            return

        def worker():
            try:
                self._log("Sending shutdown command…", "info")
                msg = self.controller.ssh.shutdown()
                self._log(msg, "info")
                time.sleep(1.5)
                self.controller._stop_reconnect_watchdog()
                self.controller.ssh.disconnect()
                self._log("Disconnected.", "info")
                self.after(0, lambda: self.controller.update_status(False))
            finally:
                self.after(0, lambda: self.shutdown_btn.config(state="normal"))

        self.shutdown_btn.config(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # WAKE-ON-LAN
    # ---------------------------------------------------------
    def _send_wol(self):
        mac   = self.wol_mac_var.get().strip()
        bcast = self.wol_bcast_var.get().strip() or "255.255.255.255"
        self.config_mgr.wol_mac       = mac
        self.config_mgr.wol_broadcast = bcast

        if not mac:
            self._log("Enter a MAC address first", "error")
            return

        clean = re.sub(r'[:\-\s]', '', mac).upper()
        if not re.fullmatch(r'[0-9A-F]{12}', clean):
            self._log("Invalid MAC address: {}".format(mac), "error")
            return

        def worker():
            try:
                mac_bytes = bytes.fromhex(clean)
                packet    = b'\xff' * 6 + mac_bytes * 16
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    s.connect((bcast, 9))
                    s.send(packet)
                self._log("Magic packet sent to {} via {}".format(mac, bcast), "success")
            except Exception as exc:
                self._log("WoL error: {}".format(exc), "error")

        threading.Thread(target=worker, daemon=True).start()
        self._log("Sending magic packet to {}…".format(mac), "info")

    # ---------------------------------------------------------
    # OUTPUT TAGS
    # ---------------------------------------------------------
    def _configure_tags(self):
        self.output.tag_config("info",      foreground=self.theme.console_info)
        self.output.tag_config("success",   foreground=self.theme.console_success)
        self.output.tag_config("error",     foreground=self.theme.console_error)
        self.output.tag_config("timestamp", foreground=self.theme.console_timestamp)

    # ---------------------------------------------------------
    # CLEAR
    # ---------------------------------------------------------
    def _clear(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    # ---------------------------------------------------------
    # LOG (thread-safe)
    # ---------------------------------------------------------
    def _log(self, text, tag="info"):
        timestamp = time.strftime("%H:%M:%S")
        self.after(0, lambda: self._append_safe(
            "{0}  {1}\n".format(timestamp, text), tag))

    def _append_safe(self, text, tag):
        autoscroll = self.output.yview()[1] >= 0.99
        self.output.configure(state="normal")
        self.output.insert("end", text[:8], "timestamp")
        self.output.insert("end", text[8:], tag)
        self.output.configure(state="disabled")
        if autoscroll:
            self.output.see("end")
