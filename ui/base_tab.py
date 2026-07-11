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
        hdr_row = tk.Frame(self, bg=self.theme.bg)
        hdr_row.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(
            hdr_row,
            text=self.TITLE,
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(side="left")
        self._populate_header(hdr_row)

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
        self._canvas_win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        # Keep inner frame width in sync with canvas so grid columns fill correctly
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(self._canvas_win, width=e.width),
        )

        self._bind_mousewheel(self._canvas)
        self._bind_mousewheel(self.inner)
        # Scrollbar has a built-in Tk class-level <MouseWheel> binding
        # (tk::ScrollByUnits) that calls canvas.yview directly, bypassing
        # _on_mousewheel's guard entirely. Binding the same handler onto it
        # (return "break" in _on_mousewheel stops that default) closes that.
        self._bind_mousewheel(_sb)

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

    def _populate_header(self, hdr_row):
        """Override in subclasses to add controls (e.g. RefreshControl) to the header row."""
        pass

    # ---------------------------------------------------------
    # MOUSEWHEEL
    # ---------------------------------------------------------
    def _bind_mousewheel(self, widget):
        """Bind scroll events on widget so they drive the card canvas."""
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>",   self._on_mousewheel)
        widget.bind("<Button-5>",   self._on_mousewheel)

    def _on_mousewheel(self, event):
        # A fast physical scroll delivers many wheel events in one burst,
        # faster than Tk can settle canvas geometry between them. Calling
        # yview_scroll() once per event let repeated rapid calls desync the
        # embedded inner window's actual on-screen position from what
        # yview()/bbox() reported. Coalescing the whole burst into a single
        # net delta, applied once after it settles, avoids that. Same fix
        # as ui/sidebar.py's nav scroll.
        delta = 120 if event.num == 4 else -120 if event.num == 5 else event.delta
        self._wheel_delta_pending = getattr(self, "_wheel_delta_pending", 0) + delta
        if not getattr(self, "_wheel_scroll_scheduled", False):
            self._wheel_scroll_scheduled = True
            self.after_idle(self._apply_pending_wheel_scroll)
        # Scrollbar has a built-in Tk class-level <MouseWheel> binding
        # (tk::ScrollByUnits) that calls canvas.yview directly, bypassing
        # this guard entirely. Binding this handler onto the scrollbar too
        # and returning "break" here stops that default from also firing.
        return "break"

    def _apply_pending_wheel_scroll(self):
        delta = self._wheel_delta_pending
        self._wheel_delta_pending = 0
        self._wheel_scroll_scheduled = False
        bbox = self._canvas.bbox("all")
        if bbox:
            self._canvas.configure(scrollregion=bbox)
            if (bbox[3] - bbox[1]) <= self._canvas.winfo_height():
                self._canvas.yview_moveto(0.0)
                return
        self._canvas.yview_scroll(int(-1 * (delta / 120)), "units")

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
        # Rebuilding can shrink the list (fewer configured services/containers
        # than before); the canvas keeps its old scroll fraction otherwise,
        # which now points past the shorter content and shows as blank space
        # above the cards. Pin back to the top on every rebuild.
        self._canvas.yview_moveto(0)
        self.cards = {}
        self._populate_cards()

        # The scrollregion is normally kept in sync by the <Configure>
        # binding on inner, but that fires on Tk's own schedule -- relying
        # on it left stale (too-tall) scrollregions in place after a
        # rebuild, so a short list could still be scrolled down into blank
        # space even though yview_moveto(0) above put it back at the top.
        # Force the geometry pass now and recompute directly so the region
        # always matches what was actually just built.
        self.inner.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.yview_moveto(0)

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
        tag = "info" if code == 0 else "error"
        status = "OK" if code == 0 else f"FAILED (exit {code})"
        self._log(f"[{label}] {status}", tag)
        combined = "\n".join(
            [l for l in (stdout or "").splitlines() if l.strip()] +
            [l for l in (stderr or "").splitlines() if l.strip()]
        )
        if combined:
            for line in combined.splitlines():
                self._append(f"  {line}\n", "error" if code != 0 else "output")
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
