# ui/log_tail_window.py
"""
Floating log tail window.
Opens a Toplevel that streams SSH output (docker logs -f / journalctl -fu)
into a scrolling console. Kills the stream when the window closes.
"""

import tkinter as tk
import threading
import time


class LogTailWindow:
    """
    Usage:
        LogTailWindow(controller, title="docker logs -f myapp", cmd="docker logs -f --tail=200 myapp")
    """

    MAX_LINES = 2000

    def __init__(self, controller, title, cmd):
        self.controller = controller
        self.cmd        = cmd
        self._stop      = threading.Event()

        t   = controller.theme
        win = tk.Toplevel(controller)
        win.title(title)
        win.geometry("860x540")
        win.configure(bg=t.bg)
        win.protocol("WM_DELETE_WINDOW", self._close)
        self._win = win

        # Header
        hdr = tk.Frame(win, bg=t.surface, padx=12, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=t.surface, fg=t.text,
                 font=t.font_mono).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="● streaming", bg=t.surface,
                                     fg=t.status_running, font=t.font_small)
        self._status_lbl.pack(side="left", padx=12)
        btn_frame = tk.Frame(hdr, bg=t.surface)
        btn_frame.pack(side="right")
        clear_btn = tk.Button(btn_frame, text="Clear", command=self._clear)
        t.style_button(clear_btn)
        clear_btn.pack(side="left", padx=4)
        wrap_var = tk.BooleanVar(value=True)
        wrap_btn = tk.Checkbutton(btn_frame, text="Wrap", variable=wrap_var,
                                  command=lambda: self._text.configure(
                                      wrap="word" if wrap_var.get() else "none"),
                                  bg=t.surface, fg=t.text_muted,
                                  activebackground=t.surface, selectcolor=t.surface,
                                  font=t.font_small)
        wrap_btn.pack(side="left", padx=4)
        close_btn = tk.Button(btn_frame, text="✕ Close", command=self._close)
        t.style_button(close_btn)
        close_btn.pack(side="left", padx=4)

        # Console
        cf = tk.Frame(win, bg=t.bg)
        cf.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._text = tk.Text(
            cf, bg=t.surface_dark, fg=t.text, font=t.font_mono,
            wrap="word", state="disabled", relief="flat",
            padx=8, pady=6,
        )
        self._text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(cf, command=self._text.yview)
        sb.pack(side="right", fill="y")
        self._text.configure(yscrollcommand=sb.set)
        self._text.tag_config("ts",  foreground=t.console_timestamp)
        self._text.tag_config("err", foreground=t.console_error)

        # Status bar
        self._bar = tk.Label(win, text="", bg=t.surface_dark, fg=t.text_muted,
                             font=t.font_small, anchor="w")
        self._bar.pack(fill="x", padx=8, pady=(0, 4))

        self._line_count = 0
        threading.Thread(target=self._stream, daemon=True).start()

    # -------------------------------------------------------
    def _stream(self):
        ssh = self.controller.ssh
        if not ssh.connected:
            self._append("[error] Not connected\n", "err")
            return
        try:
            chan = ssh.client.get_transport().open_session()
            chan.get_pty()
            chan.exec_command(self.cmd)
            chan.setblocking(False)

            self._append("[tail] {}\n".format(self.cmd), "ts")
            while not self._stop.is_set():
                try:
                    data = chan.recv(4096)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    self._append(text)
                except Exception:
                    time.sleep(0.05)

            chan.close()
        except Exception as exc:
            self._append("[error] {}\n".format(exc), "err")
        finally:
            self._win.after(0, lambda: self._status_lbl.config(
                text="● stopped", fg=self.controller.theme.status_stopped))

    def _append(self, text, tag=None):
        def _do():
            autoscroll = self._text.yview()[1] >= 0.95
            self._text.configure(state="normal")
            self._text.insert("end", text, tag or "")
            self._line_count += text.count("\n")
            # Trim oldest lines if over limit
            if self._line_count > self.MAX_LINES:
                excess = self._line_count - self.MAX_LINES
                self._text.delete("1.0", "{}.0".format(excess + 1))
                self._line_count = self.MAX_LINES
            self._text.configure(state="disabled")
            if autoscroll:
                self._text.see("end")
            self._bar.config(text="{} lines".format(self._line_count))
        self._win.after(0, _do)

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._line_count = 0

    def _close(self):
        self._stop.set()
        self._win.destroy()
