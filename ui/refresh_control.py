# ui/refresh_control.py
"""
Reusable per-tab auto-refresh control.

Usage in a tab header:
    self._rc = RefreshControl(hdr, controller, "dashboard",
                              default=30, on_refresh=self.refresh)
    self._rc.pack(side="right")

    # At the end of each refresh cycle, re-arm the timer:
    self._rc.schedule()

    # On tab destroy / app close:
    self._rc.cancel()
"""

import tkinter as tk


# Interval options shown in the dropdown: (label, seconds)
INTERVALS = [
    ("5 s",  5),
    ("10 s", 10),
    ("15 s", 15),
    ("30 s", 30),
    ("1 m",  60),
    ("2 m",  120),
    ("5 m",  300),
]
_LABELS   = [i[0] for i in INTERVALS]
_SECONDS  = {i[0]: i[1] for i in INTERVALS}
_LABEL_OF = {i[1]: i[0] for i in INTERVALS}   # seconds → label


def _nearest_label(seconds):
    """Return the label whose interval is closest to `seconds`."""
    best = min(INTERVALS, key=lambda i: abs(i[1] - seconds))
    return best[0]


class RefreshControl(tk.Frame):
    """
    Compact header widget:  Auto-refresh [✓]  [30 s ▾]

    Saves its state to config under the key  tab_refresh_<tab_name>
    as  {"enabled": bool, "interval_s": int}.
    """

    def __init__(self, parent, controller, tab_name,
                 default=30, on_refresh=None):
        t = controller.theme
        super().__init__(parent, bg=parent.cget("bg"))

        self._controller  = controller
        self._tab_name    = tab_name
        self._on_refresh  = on_refresh
        self._after_id    = None

        # ── Load saved state ──────────────────────────────────
        saved   = controller.config_manager.get_tab_refresh(tab_name)
        enabled = saved.get("enabled", True)
        interval_s = saved.get("interval_s", default)
        label   = _nearest_label(interval_s)

        # ── Vars ──────────────────────────────────────────────
        self._enabled_var  = tk.BooleanVar(value=enabled)
        self._interval_var = tk.StringVar(value=label)

        # ── Widgets ───────────────────────────────────────────
        tk.Label(self, text="Auto-refresh",
                 bg=self.cget("bg"), fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 4))

        self._chk = tk.Checkbutton(
            self,
            variable=self._enabled_var,
            command=self._on_toggle,
            bg=self.cget("bg"),
            fg=t.text_muted,
            selectcolor=self.cget("bg"),
            activebackground=self.cget("bg"),
            relief="flat", bd=0,
        )
        self._chk.pack(side="left")

        self._menu_btn = tk.OptionMenu(
            self, self._interval_var, *_LABELS,
            command=self._on_interval_change,
        )
        self._menu_btn.configure(
            bg=self.cget("bg"), fg=t.text_muted,
            activebackground=self.cget("bg"),
            relief="flat", bd=0,
            font=t.font_small,
            highlightthickness=0,
            padx=2, pady=0,
        )
        self._menu_btn["menu"].configure(
            bg=t.surface, fg=t.text,
            font=t.font_small,
        )
        self._menu_btn.pack(side="left")

        self._update_sensitivity()

    # =========================================================
    # PUBLIC API
    # =========================================================
    def schedule(self):
        """Re-arm the auto-refresh timer. Call at the END of each refresh."""
        self.cancel()
        if self._enabled_var.get():
            ms = self._interval_seconds() * 1000
            self._after_id = self.after(ms, self._fire)

    def cancel(self):
        """Cancel any pending scheduled refresh."""
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    @property
    def enabled(self):
        return self._enabled_var.get()

    @property
    def interval_ms(self):
        return self._interval_seconds() * 1000

    # =========================================================
    # INTERNAL
    # =========================================================
    def _interval_seconds(self):
        return _SECONDS.get(self._interval_var.get(), 30)

    def _fire(self):
        self._after_id = None
        if self._on_refresh:
            self._on_refresh()

    def _on_toggle(self):
        self._update_sensitivity()
        self._save()
        if self._enabled_var.get():
            self.schedule()
        else:
            self.cancel()

    def _on_interval_change(self, *_):
        self._save()
        # Re-arm with new interval (cancel current then schedule)
        if self._enabled_var.get():
            self.cancel()
            self.schedule()

    def _update_sensitivity(self):
        state = "normal" if self._enabled_var.get() else "disabled"
        self._menu_btn.configure(state=state)

    def _save(self):
        self._controller.config_manager.set_tab_refresh(
            self._tab_name,
            self._enabled_var.get(),
            self._interval_seconds(),
        )
