# ui/base_tab.py

import tkinter as tk
import time


class CardConsoleTab(tk.Frame):
    """
    Shared base for tabs that display a scrollable card grid above a console panel.

    Subclasses must set:
        TITLE (str)               — header label text

    Subclasses must implement:
        _populate_cards()         — add card widgets to self.inner
        refresh_all()             — refresh all card statuses

    Shared for free:
        Mousewheel scrolling on the card canvas
        Full console (log, log_output, clear, color tags, auto-scroll)
        _bind_mousewheel(widget)  — propagate scroll from any child widget
        reload_cards()            — destroy and rebuild all cards from config
    """

    TITLE = ""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self.cards = {}
        self._build_ui()

    # ---------------------------------------------------------
    # BUILD UI
    # ---------------------------------------------------------
    def _build_ui(self):
        tk.Label(
            self,
            text=self.TITLE,
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(anchor="w", padx=10, pady=(10, 6))

        pane = tk.PanedWindow(
            self, orient="vertical",
            bg=self.theme.card_border,
            sashwidth=6, sashrelief="flat",
        )
        pane.pack(fill="both", expand=True)

        # ── Top: scrollable cards ─────────────────────────────
        top = tk.Frame(pane, bg=self.theme.bg)
        pane.add(top, stretch="always", minsize=120)

        self._canvas = tk.Canvas(top, bg=self.theme.bg, highlightthickness=0)
        _sb = tk.Scrollbar(top, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self._canvas, bg=self.theme.bg)
        self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )

        self._bind_mousewheel(self._canvas)
        self._bind_mousewheel(self.inner)

        self._populate_cards()

        # ── Bottom: output console ────────────────────────────
        bottom = tk.Frame(pane, bg=self.theme.bg)
        pane.add(bottom, stretch="never", minsize=80)

        hdr = tk.Frame(bottom, bg=self.theme.bg)
        hdr.pack(fill="x", padx=10, pady=(6, 4))

        tk.Label(hdr, text="Output", bg=self.theme.bg,
                 fg=self.theme.text, font=self.theme.font_title).pack(side="left")

        clear_btn = tk.Button(hdr, text="Clear", command=self._clear_output)
        self.theme.style_button(clear_btn)
        clear_btn.pack(side="right")

        cf = tk.Frame(bottom, bg=self.theme.bg)
        cf.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.output = tk.Text(
            cf,
            bg=self.theme.surface_dark,
            fg=self.theme.text,
            font=self.theme.font_mono,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.output.pack(side="left", fill="both", expand=True)

        sb2 = tk.Scrollbar(cf, command=self.output.yview)
        sb2.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=sb2.set)

        self._configure_tags()

    # ---------------------------------------------------------
    # MOUSEWHEEL
    # ---------------------------------------------------------
    def _bind_mousewheel(self, widget):
        """Bind scroll events on widget so they drive the card canvas."""
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>",   self._on_mousewheel)
        widget.bind("<Button-5>",   self._on_mousewheel)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------------------------------------------------------
    # OVERRIDE IN SUBCLASS
    # ---------------------------------------------------------
    def _populate_cards(self):
        """Add card widgets to self.inner. Called during _build_ui."""
        pass

    def refresh_all(self):
        """Refresh all card statuses. Override in subclass."""
        pass

    # ---------------------------------------------------------
    # RELOAD CARDS (after config change)
    # ---------------------------------------------------------
    def reload_cards(self):
        """Destroy all cards and rebuild from the current config."""
        for widget in self.inner.winfo_children():
            widget.destroy()
        self.cards = {}
        self._populate_cards()
        self.refresh_all()

    # ---------------------------------------------------------
    # CONSOLE
    # ---------------------------------------------------------
    def _configure_tags(self):
        self.output.tag_config("cmd",       foreground=self.theme.console_cmd)
        self.output.tag_config("info",      foreground=self.theme.console_info)
        self.output.tag_config("error",     foreground=self.theme.console_error)
        self.output.tag_config("timestamp", foreground=self.theme.console_timestamp)
        self.output.tag_config("output",    foreground=self.theme.console_output)

    def _clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _log(self, text, tag="info"):
        timestamp = time.strftime("%H:%M:%S")
        self._append(f"{timestamp}  {text}\n", tag, timestamp_prefix=True)

    def _log_output(self, label, stdout, stderr, code):
        self._log(f"[{label}] exit code: {code}", "info")
        if stdout.strip():
            for line in stdout.splitlines():
                self._append(f"{line}\n", "output")
        if stderr.strip():
            for line in stderr.splitlines():
                self._append(f"{line}\n", "error")
        self._append("\n", None)

    def _append(self, text, tag, timestamp_prefix=False):
        self.after(0, lambda: self._append_safe(text, tag, timestamp_prefix))

    def _append_safe(self, text, tag, timestamp_prefix=False):
        autoscroll = self.output.yview()[1] >= 0.99
        self.output.configure(state="normal")
        if timestamp_prefix and len(text) > 8:
            self.output.insert("end", text[:8], "timestamp")
            self.output.insert("end", text[8:], tag)
        else:
            self.output.insert("end", text, tag or "")
        self.output.configure(state="disabled")
        if autoscroll:
            self.output.see("end")
