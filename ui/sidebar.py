# ui/sidebar.py

import tkinter as tk


class Sidebar(tk.Frame):
    """
    Microsoft Fluent / Teams-style navigation sidebar.
    - Expanded: icon + label, 240 px wide.
    - Collapsed: icon only, 52 px wide, with hover tooltips.
    - Active item: full-width Office-blue background (Teams style).
    - Nav items grouped into labelled sections.
    - Nav area is scrollable via mousewheel.
    """

    EXPANDED_WIDTH  = 240
    COLLAPSED_WIDTH = 52
    ANIM_STEPS      = 12
    ANIM_MS         = 12

    # (icon, label, tab_index, section)
    _NAV_ITEMS = [
        ("\U0001f50c", "Connection",      0,  "CORE"),
        ("⚡",         "Quick Commands",  1,  None),
        ("\U0001f4ca", "Dashboard",       2,  None),

        ("\U0001f3b5", "Emby",            14,  "MEDIA"),
        ("\U0001f7e1", "Plex",           17,  None),
        ("\U0001f9ca", "Jellyfin",       18,  None),
        ("\U0001f3ac", "Arr",            11,  None),
        ("\U0001f4e5", "SABnzbd",         7,  None),

        ("\U0001f9e9", "Services",        3,  "INFRA"),
        ("\U0001f433", "Docker",          4,  None),
        ("\U0001f40b", "Compose",        15,  None),
        ("⏰",         "Cron Jobs",      16,  None),
        ("\U0001f4bf", "Disk Health",    10,  None),

        ("\U0001f4c2", "Files",           9,  "TOOLS"),
        ("\U0001f4cb", "Log Viewer",      6,  None),
        (">_",         "Custom Commands", 5,  None),
        ("\U0001f504", "Updates",        12,  None),
        ("\U0001f465", "Sessions",       13,  None),

        ("⚙",         "Config",          8,  "SETTINGS"),
    ]

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.sidebar_bg, width=self.EXPANDED_WIDTH)
        self.pack_propagate(False)

        self.controller  = controller
        self.theme       = t
        self._collapsed  = False
        self._animating  = False
        self._buttons    = []
        self._active_idx = 0

        # Right-edge separator
        tk.Frame(self, bg="#1a1a1a", width=1).place(
            relx=1.0, rely=0, relheight=1, anchor="ne")

        self._build_sidebar()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        t = self.theme

        # ── Logo / header row ─────────────────────────────────────────
        logo_frame = tk.Frame(self, bg=t.sidebar_bg, height=56)
        logo_frame.pack(fill="x", side="top")
        logo_frame.pack_propagate(False)

        self._icon_lbl = tk.Label(
            logo_frame,
            text="\U0001f5a5",
            bg=t.sidebar_bg, fg=t.blue,
            font=("Segoe UI", 16),
        )
        self._icon_lbl.pack(side="left", padx=(14, 4), pady=14)

        self._app_lbl = tk.Label(
            logo_frame,
            text="All Clear",
            bg=t.sidebar_bg, fg=t.text,
            font=("Segoe UI Semibold", 12),
            anchor="w",
        )
        self._app_lbl.pack(side="left")

        self._toggle_btn = tk.Button(
            logo_frame,
            text="☰",
            command=self.toggle,
            bg=t.sidebar_bg, fg=t.sidebar_icon,
            bd=0, relief="flat",
            font=("Segoe UI", 13),
            cursor="hand2",
            padx=10,
        )
        self._toggle_btn.pack(side="right", padx=4)
        self._toggle_btn.bind("<Enter>",
            lambda e: self._toggle_btn.configure(fg=t.sidebar_icon_hover,
                                                  bg=t.surface_light))
        self._toggle_btn.bind("<Leave>",
            lambda e: self._toggle_btn.configure(fg=t.sidebar_icon,
                                                  bg=t.sidebar_bg))

        # Thin separator under header
        tk.Frame(self, bg="#1a1a1a", height=1).pack(fill="x", side="top")

        # ── Bottom version label (packed before canvas to stay fixed) ──
        tk.Frame(self, bg="#1a1a1a", height=1).pack(fill="x", side="bottom")
        self._ver_lbl = tk.Label(
            self,
            text="Media Server Manager",
            bg=t.sidebar_bg, fg=t.text_dim,
            font=("Segoe UI", 9),
            anchor="center",
        )
        self._ver_lbl.pack(side="bottom", pady=10)

        # ── Scrollable nav canvas ─────────────────────────────────────
        self._nav_canvas = tk.Canvas(
            self,
            bg=t.sidebar_bg,
            highlightthickness=0,
            bd=0,
        )
        self._nav_canvas.pack(fill="both", expand=True, side="top")

        self._nav_frame = tk.Frame(self._nav_canvas, bg=t.sidebar_bg)
        self._canvas_win = self._nav_canvas.create_window(
            (0, 0), window=self._nav_frame, anchor="nw")

        self._nav_canvas.bind("<Configure>", self._on_canvas_resize)
        self._nav_frame.bind("<Configure>", self._on_frame_resize)
        self._nav_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._nav_frame.bind("<MouseWheel>", self._on_mousewheel)

        # ── Build nav items ───────────────────────────────────────────
        self._section_widgets = []
        current_section = None

        for icon, label, idx, section in self._NAV_ITEMS:
            if section and section != current_section:
                current_section = section
                spacer = tk.Frame(self._nav_frame, bg=t.sidebar_bg, height=4)
                spacer.pack(fill="x")
                spacer.bind("<MouseWheel>", self._on_mousewheel)

                sec_lbl = tk.Label(
                    self._nav_frame,
                    text=section,
                    bg=t.sidebar_bg, fg=t.sidebar_section_text,
                    font=("Segoe UI", 8, "bold"),
                    anchor="w", padx=16,
                )
                sec_lbl.pack(fill="x", pady=(4, 2))
                sec_lbl.bind("<MouseWheel>", self._on_mousewheel)
                self._section_widgets.append((sec_lbl, spacer))

            row = tk.Frame(self._nav_frame, bg=t.sidebar_bg)
            row.pack(fill="x", padx=6, pady=1)
            row.bind("<MouseWheel>", self._on_mousewheel)

            btn = tk.Button(
                row,
                text="{0}  {1}".format(icon, label),
                anchor="w",
                command=lambda i=idx: self._nav_click(i),
                bg=t.sidebar_bg, fg=t.sidebar_icon,
                bd=0, relief="flat",
                font=("Segoe UI", 11),
                padx=10, pady=6,
                cursor="hand2",
            )
            btn.pack(fill="x", expand=True)

            btn.bind("<Enter>",
                lambda e, b=btn, r=row, i=idx: self._on_hover(b, r, i, True))
            btn.bind("<Leave>",
                lambda e, b=btn, r=row, i=idx: self._on_hover(b, r, i, False))
            btn.bind("<MouseWheel>", self._on_mousewheel)

            self._create_tooltip(btn, label)
            self._buttons.append((btn, icon, label, idx, row))

        self.set_active(0)

    # ------------------------------------------------------------------
    # SCROLLING
    # ------------------------------------------------------------------
    def _on_canvas_resize(self, event):
        self._nav_canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_frame_resize(self, event):
        self._nav_canvas.configure(scrollregion=self._nav_canvas.bbox("all"))

    def _on_mousewheel(self, event):
        self._nav_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # ACTIVE STATE  (Teams-style: full-width blue row, no accent bar)
    # ------------------------------------------------------------------
    def set_active(self, idx):
        self._active_idx = idx
        t = self.theme
        for btn, icon, label, btn_idx, row in self._buttons:
            is_active = (btn_idx == idx)
            if is_active:
                row.configure(bg=t.sidebar_active_bg)
                btn.configure(bg=t.sidebar_active_bg,
                              fg=t.sidebar_icon_active)
            else:
                row.configure(bg=t.sidebar_bg)
                btn.configure(bg=t.sidebar_bg, fg=t.sidebar_icon)

    def show_item(self, idx):
        """Make a hidden nav item visible (re-pack its row)."""
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx == idx:
                row.pack(fill="x", padx=6, pady=1)
                break

    def hide_item(self, idx):
        """Hide a nav item (pack_forget its row)."""
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx == idx:
                row.pack_forget()
                break

    def set_badge(self, idx, count):
        """Show or hide a small count badge on the nav item at `idx`."""
        t = self.theme
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx != idx:
                continue
            # Remove any existing badge on this row
            for child in row.winfo_children():
                if getattr(child, "_is_badge", False):
                    child.destroy()
            if count and count > 0:
                badge = tk.Label(
                    row,
                    text=str(count),
                    bg=t.yellow, fg="#000000",
                    font=("Segoe UI", 8, "bold"),
                    padx=4, pady=0,
                )
                badge._is_badge = True
                badge.pack(side="right", padx=(0, 6))
            break

    def _nav_click(self, idx):
        self.set_active(idx)
        self.controller.tabs.select(idx)

    def _on_hover(self, btn, row, idx, entering):
        t = self.theme
        is_active = (idx == self._active_idx)
        if entering and not is_active:
            btn.configure(fg=t.sidebar_icon_hover, bg=t.surface_light)
            row.configure(bg=t.surface_light)
        elif not entering and not is_active:
            btn.configure(fg=t.sidebar_icon, bg=t.sidebar_bg)
            row.configure(bg=t.sidebar_bg)

    # ------------------------------------------------------------------
    # TOOLTIP (shown only when collapsed)
    # ------------------------------------------------------------------
    def _create_tooltip(self, widget, text):
        tip = {"win": None}

        def show(e):
            if not self._collapsed:
                return
            w = tk.Toplevel(self)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            t = self.theme
            w.configure(bg=t.card_border)
            tk.Label(
                w, text=text,
                bg=t.surface_light,
                fg=t.text,
                font=t.font_small,
                padx=10, pady=6,
            ).pack(padx=1, pady=1)
            w.update_idletasks()
            x = widget.winfo_rootx() + widget.winfo_width() + 8
            y = widget.winfo_rooty() + (widget.winfo_height() - w.winfo_height()) // 2
            w.geometry("+{0}+{1}".format(x, y))
            tip["win"] = w

        def hide(e):
            if tip["win"]:
                tip["win"].destroy()
                tip["win"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    # ------------------------------------------------------------------
    # TOGGLE / ANIMATION
    # ------------------------------------------------------------------
    def toggle(self):
        if self._animating:
            return
        self._collapsed = not self._collapsed
        start = self.winfo_width()
        end   = self.COLLAPSED_WIDTH if self._collapsed else self.EXPANDED_WIDTH
        if not self._collapsed:
            self._update_labels()
        self._animate(start, end, 0)

    def _animate(self, start, end, step):
        self._animating = True
        t = step / self.ANIM_STEPS
        t = t * t * (3 - 2 * t)   # smooth-step
        self.configure(width=int(start + (end - start) * t))
        if step < self.ANIM_STEPS:
            self.after(self.ANIM_MS, self._animate, start, end, step + 1)
        else:
            self.configure(width=end)
            self._animating = False
            if self._collapsed:
                self._update_labels()

    def _update_labels(self):
        for btn, icon, label, idx, row in self._buttons:
            if self._collapsed:
                btn.configure(text=icon, anchor="center", padx=0)
            else:
                btn.configure(text="{0}  {1}".format(icon, label),
                              anchor="w", padx=10)

        for sec_lbl, spacer in self._section_widgets:
            if self._collapsed:
                sec_lbl.pack_forget()
                spacer.pack_forget()
            else:
                spacer.pack(fill="x")
                sec_lbl.pack(fill="x", pady=(4, 2))

        if self._collapsed:
            self._icon_lbl.pack_forget()
            self._app_lbl.pack_forget()
            self._ver_lbl.pack_forget()
            self._toggle_btn.configure(anchor="center", padx=0, width=3)
        else:
            self._icon_lbl.pack(side="left", padx=(14, 4), pady=14)
            self._app_lbl.pack(side="left")
            self._ver_lbl.pack(side="bottom", pady=10)
            self._toggle_btn.configure(anchor="e", padx=10, width=0)
