# ui/connection_panel.py

import tkinter as tk
from tkinter import messagebox
import threading
import os
import time


class ConnectionPanel(tk.Frame):
    """
    SSH connection panel with embedded mini console.
    - Auto-detect SSH key or password auth
    - Threaded connect/disconnect/shutdown
    - Updates the main window status bar on connect/disconnect
    - Starts/stops the auto-reconnect watchdog
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
        left = tk.Frame(self, bg=self.theme.surface, padx=16, pady=16)
        left.pack(side="left", fill="y")

        tk.Label(left, text="SSH CONNECTION", bg=self.theme.surface,
                 fg=self.theme.text, font=self.theme.font_title,
                 ).pack(anchor="w", pady=(0, 10))

        self.host_var = tk.StringVar(value=self.config_mgr.last_host)
        self._field(left, "Host", self.host_var)

        self.port_var = tk.StringVar(value="22")
        self._field(left, "Port", self.port_var)

        self.user_var = tk.StringVar(value=self.config_mgr.last_username)
        self._field(left, "Username", self.user_var)

        self.pass_var = tk.StringVar()
        self._field(left, "Password", self.pass_var, show="*")

        self.use_password_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            left,
            text="Use password instead of SSH key",
            variable=self.use_password_var,
            bg=self.theme.surface, fg=self.theme.text_muted,
            activebackground=self.theme.surface, activeforeground=self.theme.text,
            selectcolor=self.theme.surface, font=self.theme.font_small,
        ).pack(anchor="w", pady=(4, 12))

        btn_frame = tk.Frame(left, bg=self.theme.surface)
        btn_frame.pack(fill="x", pady=(10, 0))

        self.connect_btn = tk.Button(btn_frame, text="Connect",
                                      command=self._connect_threaded)
        self.theme.style_button(self.connect_btn)
        self.connect_btn.pack(fill="x", pady=4)

        self.disconnect_btn = tk.Button(btn_frame, text="Disconnect",
                                         command=self._disconnect)
        self.theme.style_button(self.disconnect_btn)
        self.disconnect_btn.pack(fill="x", pady=4)

        self.shutdown_btn = tk.Button(btn_frame, text="Shutdown Server",
                                       command=self._shutdown_confirm)
        self.theme.style_button(self.shutdown_btn)
        self.shutdown_btn.pack(fill="x", pady=4)

        # Right panel: mini console
        right = tk.Frame(self, bg=self.theme.bg)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

        console_header = tk.Frame(right, bg=self.theme.bg)
        console_header.pack(fill="x", pady=(0, 6))

        tk.Label(console_header, text="Connection Log", bg=self.theme.bg,
                  fg=self.theme.text, font=self.theme.font_title).pack(side="left")

        clear_btn = tk.Button(console_header, text="Clear", command=self._clear)
        self.theme.style_button(clear_btn)
        clear_btn.pack(side="right")

        console_frame = tk.Frame(right, bg=self.theme.bg)
        console_frame.pack(fill="both", expand=True)

        self.output = tk.Text(
            console_frame, bg=self.theme.surface_dark, fg=self.theme.text,
            font=self.theme.font_mono, wrap="word", state="disabled",
            relief="flat", padx=10, pady=8,
        )
        self.output.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(console_frame, command=self.output.yview)
        sb.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=sb.set)

        self._configure_tags()

    # ---------------------------------------------------------
    # FIELD BUILDER
    # ---------------------------------------------------------
    def _field(self, parent, label, var, show=None):
        tk.Label(parent, text=label, bg=self.theme.surface,
                  fg=self.theme.text_secondary, font=self.theme.font_small).pack(anchor="w")
        entry = tk.Entry(parent, textvariable=var, show=show or "",
                          font=self.theme.font_regular)
        self.theme.style_entry(entry)
        entry.pack(fill="x", pady=(0, 10))

    # ---------------------------------------------------------
    # CONNECT (THREADED)
    # ---------------------------------------------------------
    def _connect_threaded(self):
        self.connect_btn.config(text="Connecting...", state="disabled")

        def worker():
            try:
                host     = self.host_var.get().strip()
                port     = self.port_var.get().strip()
                user     = self.user_var.get().strip()
                password = self.pass_var.get().strip()

                self.config_mgr.last_host     = host
                self.config_mgr.last_username = user

                if self.use_password_var.get() or password:
                    result = self.controller.ssh.connect(
                        host=host, port=port, username=user, password=password)
                else:
                    key_path = os.path.expanduser("~/.ssh/id_rsa")
                    if not os.path.exists(key_path):
                        self._log(
                            "No SSH key found at ~/.ssh/id_rsa. "
                            "Tick 'Use password' and enter your password.", "error")
                        return
                    result = self.controller.ssh.connect(
                        host=host, port=port, username=user, key_path=key_path)

                if result is True:
                    self._log("Connected to {0} as {1}".format(host, user), "success")
                    # All UI updates MUST go through self.after() — never touch
                    # Tkinter widgets directly from a background thread.
                    self.after(0, lambda: self.controller.update_status(True, host))
                    self.after(0, self.controller._start_reconnect_watchdog)
                    self.after(200, self.controller.services_tab.refresh_all)
                    self.after(400, self.controller.dashboard_tab.refresh)
                else:
                    self._log("Connection failed: {0}".format(result), "error")
                    self.after(0, lambda: self.controller.update_status(False))

            except Exception as exc:
                self._log("Unexpected error: {0}".format(exc), "error")
                self.after(0, lambda: self.controller.update_status(False))
            finally:
                self._reset_connect_btn()

        threading.Thread(target=worker, daemon=True).start()

    def _reset_connect_btn(self):
        self.after(0, lambda: self.connect_btn.config(text="Connect", state="normal"))

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
            "Shutdown Server", "Are you sure you want to shut down the server?"):
            return

        def worker():
            self._log("Sending shutdown command...", "info")
            msg = self.controller.ssh.shutdown()
            self._log(msg, "info")
            time.sleep(1.5)
            self.controller._stop_reconnect_watchdog()
            self.controller.ssh.disconnect()
            self._log("Disconnected.", "info")
            self.after(0, lambda: self.controller.update_status(False))

        threading.Thread(target=worker, daemon=True).start()

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
    # LOG (THREAD-SAFE)
    # ---------------------------------------------------------
    def _log(self, text, tag="info"):
        timestamp = time.strftime("%H:%M:%S")
        self.after(0, lambda: self._append_safe("{0}  {1}\n".format(timestamp, text), tag))

    def _append_safe(self, text, tag):
        autoscroll = self.output.yview()[1] >= 0.99
        self.output.configure(state="normal")
        self.output.insert("end", text[:8], "timestamp")
        self.output.insert("end", text[8:], tag)
        self.output.configure(state="disabled")
        if autoscroll:
            self.output.see("end")
