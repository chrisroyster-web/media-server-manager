# ui/log_tail_window.py
"""
Floating log tail window.
Opens a Toplevel that streams SSH output (docker logs -f / journalctl -fu)
into a scrolling console. Kills the stream when the window closes.

Adds a Dozzle-style live filter box (plain substring or regex, case-
insensitive) that hides non-matching lines and highlights the match, plus
automatic ERROR/WARN highlighting on every line.
"""

import tkinter as tk
import threading
import time
import re
from collections import deque


# Word-boundary heuristics for auto-coloring lines — deliberately conservative
# so words like "errorless" or "warnock" don't get flagged.
_ERR_RE  = re.compile(r"\b(error|err|fatal|exception|panic|traceback|fail(?:ed|ure)?)\b", re.I)
_WARN_RE = re.compile(r"\b(warn(?:ing)?)\b", re.I)


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

        # Line buffer + filter state (background thread writes, main thread reads)
        self._lines_lock  = threading.Lock()
        self._all_lines   = deque(maxlen=self.MAX_LINES)   # [(text, tag)]
        self._pending      = ""      # partial line carried across recv() chunks
        self._total_count  = 0
        self._shown_count  = 0
        self._filter_re    = None    # compiled regex, or None for plain-substring mode
        self._filter_valid = True
        self._debounce_id  = None

        t   = controller.theme
        win = tk.Toplevel(controller)
        win.title(title)
        win.geometry("860x580")
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

        # Filter toolbar
        bar = tk.Frame(win, bg=t.surface, padx=12, pady=6)
        bar.pack(fill="x")
        tk.Label(bar, text="Filter:", bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 6))
        self._filter_var = tk.StringVar()
        self._filter_entry = tk.Entry(bar, textvariable=self._filter_var,
                                       font=t.font_mono, width=40)
        t.style_entry(self._filter_entry)
        self._filter_entry.pack(side="left", fill="x", expand=True)
        self._filter_var.trace_add("write", self._on_filter_changed)
        self._filter_entry.bind("<Escape>", lambda e: self._filter_var.set(""))

        self._regex_var = tk.BooleanVar(value=False)
        regex_chk = tk.Checkbutton(bar, text="Regex", variable=self._regex_var,
                                    command=self._on_filter_changed,
                                    bg=t.surface, fg=t.text_muted,
                                    activebackground=t.surface, selectcolor=t.surface,
                                    font=t.font_small)
        regex_chk.pack(side="left", padx=(8, 0))
        clear_filter_btn = tk.Button(bar, text="✕", width=2,
                                      command=lambda: self._filter_var.set(""))
        t.style_button(clear_filter_btn)
        clear_filter_btn.pack(side="left", padx=(6, 0))

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
        self._text.tag_config("ts",   foreground=t.console_timestamp)
        self._text.tag_config("err",  foreground=t.console_error)
        self._text.tag_config("warn", foreground=t.yellow)
        self._text.tag_config("match", background=t.yellow, foreground="#1a1a1a")
        # match highlight should paint over the err/warn foreground
        self._text.tag_raise("match")

        # Status bar
        self._bar = tk.Label(win, text="", bg=t.surface_dark, fg=t.text_muted,
                             font=t.font_small, anchor="w")
        self._bar.pack(fill="x", padx=8, pady=(0, 4))

        self._update_status()
        threading.Thread(target=self._stream, daemon=True).start()

    # -------------------------------------------------------
    # STREAMING (background thread)
    # -------------------------------------------------------
    def _stream(self):
        ssh = self.controller.ssh
        if not ssh.connected:
            self._insert_meta("[error] Not connected\n", "err")
            return
        try:
            chan = ssh.client.get_transport().open_session()
            chan.get_pty()
            chan.exec_command(self.cmd)
            chan.setblocking(False)

            self._insert_meta("[tail] {}\n".format(self.cmd), "ts")
            while not self._stop.is_set():
                try:
                    data = chan.recv(4096)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    self._feed(text)
                except Exception:
                    time.sleep(0.05)

            if self._pending:
                self._handle_line(self._pending)
                self._pending = ""
            chan.close()
        except Exception as exc:
            self._insert_meta("[error] {}\n".format(exc), "err")
        finally:
            self._win.after(0, lambda: self._status_lbl.config(
                text="● stopped", fg=self.controller.theme.status_stopped))

    def _feed(self, text):
        """Split freshly-received text into complete lines, carrying any
        trailing partial line over to the next chunk."""
        combined     = self._pending + text
        parts        = combined.split("\n")
        self._pending = parts.pop()
        for line in parts:
            self._handle_line(line)

    def _handle_line(self, line):
        tag = self._level_tag(line)
        with self._lines_lock:
            evicted = len(self._all_lines) == self._all_lines.maxlen
            self._all_lines.append((line, tag))
        self._total_count += 1
        self._win.after(0, lambda l=line, tg=tag, ev=evicted: self._render_line(l, tg, ev))

    @staticmethod
    def _level_tag(line):
        if _ERR_RE.search(line):
            return "err"
        if _WARN_RE.search(line):
            return "warn"
        return None

    # -------------------------------------------------------
    # RENDERING (main thread)
    # -------------------------------------------------------
    def _render_line(self, line, tag, evicted):
        if evicted and not self._filter_active():
            self._delete_first_display_line()
        if self._passes_filter(line):
            self._insert_line(line, tag)
            self._shown_count += 1
        self._update_status()

    def _insert_line(self, line, tag):
        autoscroll = self._text.yview()[1] >= 0.95
        self._text.configure(state="normal")
        start = self._text.index("end-1c")
        self._text.insert("end", line + "\n")
        if tag:
            self._text.tag_add(tag, start, "end-1c")
        for off, mlen in self._match_spans(line):
            self._text.tag_add("match", "{}+{}c".format(start, off),
                                        "{}+{}c".format(start, off + mlen))
        self._text.configure(state="disabled")
        if autoscroll:
            self._text.see("end")

    def _insert_meta(self, text, tag=None):
        """Control/error messages that always show regardless of filter."""
        def _do():
            autoscroll = self._text.yview()[1] >= 0.95
            self._text.configure(state="normal")
            self._text.insert("end", text, tag or "")
            self._text.configure(state="disabled")
            if autoscroll:
                self._text.see("end")
        self._win.after(0, _do)

    def _delete_first_display_line(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "2.0")
        self._text.configure(state="disabled")

    # -------------------------------------------------------
    # FILTER
    # -------------------------------------------------------
    def _filter_active(self):
        return bool(self._filter_var.get().strip())

    def _passes_filter(self, line):
        needle = self._filter_var.get().strip()
        if not needle:
            return True
        if self._regex_var.get():
            if self._filter_re is None:
                return not self._filter_valid  # invalid pattern -> show everything
            return self._filter_re.search(line) is not None
        return needle.lower() in line.lower()

    def _match_spans(self, line):
        needle = self._filter_var.get().strip()
        if not needle:
            return []
        if self._regex_var.get():
            if self._filter_re is None:
                return []
            spans = []
            for m in self._filter_re.finditer(line):
                if m.end() > m.start():
                    spans.append((m.start(), m.end() - m.start()))
            return spans
        spans = []
        lower_line = line.lower()
        lower_needle = needle.lower()
        start = 0
        while True:
            idx = lower_line.find(lower_needle, start)
            if idx == -1:
                break
            spans.append((idx, len(needle)))
            start = idx + len(needle)
        return spans

    def _on_filter_changed(self, *_):
        if self._debounce_id:
            self._win.after_cancel(self._debounce_id)
        self._debounce_id = self._win.after(150, self._apply_filter)

    def _apply_filter(self):
        self._debounce_id = None
        t = self.controller.theme
        needle = self._filter_var.get().strip()

        if needle and self._regex_var.get():
            try:
                self._filter_re = re.compile(needle, re.I)
                self._filter_valid = True
            except re.error:
                self._filter_re = None
                self._filter_valid = False
        else:
            self._filter_re = None
            self._filter_valid = True

        self._filter_entry.configure(
            highlightbackground=t.console_error if not self._filter_valid else t.card_border)

        with self._lines_lock:
            snapshot = list(self._all_lines)

        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")

        self._shown_count = 0
        for line, tag in snapshot:
            if self._passes_filter(line):
                self._insert_line(line, tag)
                self._shown_count += 1
        self._update_status()

    # -------------------------------------------------------
    def _update_status(self):
        if self._filter_active():
            text = "{} / {} lines match".format(self._shown_count, self._total_count)
        else:
            text = "{} lines".format(self._total_count)
        self._bar.config(text=text)

    def _clear(self):
        with self._lines_lock:
            self._all_lines.clear()
        self._total_count = 0
        self._shown_count = 0
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._update_status()

    def _close(self):
        self._stop.set()
        self._win.destroy()
