# ui/sidebar.py

import tkinter as tk
from tkinter import ttk


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

    # Accent color for each sidebar section header bar + label
    _SECTION_COLORS = {
        "SERVERS":    "#38bdf8",
        "CORE":       "#5b8ef0",
        "MEDIA":      "#a855f7",
        "REQUESTS":   "#f97316",
        "MONITORING": "#22c55e",
        "INFRA":      "#64748b",
        "TOOLS":      "#06b6d4",
        "SETTINGS":   "#6b7280",
    }

    # (icon, label, tab_index, section)
    # Connection (0) and Quick Commands (1) are accessible via status bar / keyboard only.
    _NAV_ITEMS = [
        ("\U0001f4ca", "Dashboard",       2,  "CORE"),
        ("\U0001f5a5", "All Servers",    37,  None),
        ("⚡",         "Quick Commands",  1,  None),

        ("\U0001f3a5", "Now Playing",    43,  "MEDIA"),
        ("\U0001f4da", "Media Library",  40,  None),
        ("\U0001f4fa", "Play History",   21,  None),
        ("\U0001f465", "Media Users",    42,  None),

        ("\U0001f3ac", "Arr",            11,  "REQUESTS"),
        ("\U0001f50d", "Prowlarr",       30,  None),
        ("\U0001f4e5", "Requests",       41,  None),
        ("\U0001f4e5", "SABnzbd",         7,  None),
        ("\U0001f9f2", "qBittorrent",   48,  None),

        ("\U0001f4ca", "Tautulli",       33,  "MONITORING"),
        ("\U0001f7e2", "Uptime Kuma",    34,  None),
        ("\U0001f4c8", "Monitoring",     35,  None),
        ("\U0001f4ca", "Bandwidth",      28,  None),
        ("\U0001f4f6", "Speedtest",      24,  None),
        ("\U0001f321", "Sensors",        54,  None),
        ("\U0001f6e1", "Pi-hole",        55,  None),
        ("\U0001f501", "Watchstate",     59,  None),

        ("\U0001f9e9", "Services",        3,  "INFRA"),
        ("\U0001f433", "Docker",          4,  None),
        ("\U0001f40b", "Compose",        15,  None),
        ("⏰",         "Scheduled Tasks", 16,  None),
        ("📦",         "Install Apps",   45,  None),
        ("\U0001f465", "Sessions",       13,  None),
        ("\U0001f5a5", "Processes",      50,  None),
        ("\U0001f4bf", "Storage",        10,  None),
        ("\U0001f6e1", "VPN",            22,  None),
        ("\U0001f310", "Reverse Proxy",  23,  None),
        ("☁",          "Cloudflare",     60,  None),
        ("\U0001f4a0", "Tailscale",      27,  None),
        ("\U0001f6e1", "UFW Firewall",   51,  None),
        ("\U0001f50c", "Ports",          53,  None),
        ("\U0001f527", "Net Toolkit",    56,  None),

        ("\U0001f4c2", "Files",           9,  "TOOLS"),
        ("\U0001f4cb", "Log Viewer",      6,  None),
        (">_",         "Custom Commands", 5,  None),
        ("\U0001f510", "SSL Certs",      26,  None),
        ("\U0001f6ab", "Fail2ban",       46,  None),
        ("\U0001f4be", "Backups",        29,  None),
        ("\U0001f504", "Updates",        12,  None),
        ("\U0001f514", "Notifications",  19,  None),
        ("\U0001f4dc", "Audit Log",      61,  None),

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
        # {idx: {"label": str, "reason": str}}
        self._dimmed     = {}
        self._section_animating = set()   # section names currently mid-collapse/expand
        self._row_height = None           # measured once _build_sidebar finishes
        self._last_nav_frame_height = None   # tracked by _on_frame_resize

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
            bg=t.sidebar_bg, fg=t.blue_bright,
            font=("Segoe UI", 16),
        )
        self._icon_lbl.pack(side="left", padx=(14, 4), pady=14)

        self._app_lbl = tk.Label(
            logo_frame,
            text="All Clear",
            # sidebar_bg stays dark in both themes by design, but t.text
            # flips to a dark color in light mode — was landing at a 1.2:1
            # contrast ratio there. sidebar_icon_hover is the sidebar's own
            # always-bright color, meant for exactly this.
            bg=t.sidebar_bg, fg=t.sidebar_icon_hover,
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

        # Theme toggle ☀️ / 🌙
        _is_dark = (self.controller.config_manager.theme_mode == "dark")
        self._theme_btn = tk.Button(
            logo_frame,
            text="☀" if _is_dark else "🌙",
            command=self.controller.toggle_theme,
            bg=t.sidebar_bg, fg=t.sidebar_icon,
            bd=0, relief="flat",
            font=("Segoe UI", 12),
            cursor="hand2",
            padx=6,
        )
        self._theme_btn.pack(side="right")
        self._theme_btn.bind("<Enter>",
            lambda e: self._theme_btn.configure(fg=t.sidebar_icon_hover,
                                                 bg=t.surface_light))
        self._theme_btn.bind("<Leave>",
            lambda e: self._theme_btn.configure(fg=t.sidebar_icon,
                                                 bg=t.sidebar_bg))

        # Thin separator under header
        tk.Frame(self, bg="#1a1a1a", height=1).pack(fill="x", side="top")

        # ── Bottom version + shortcut hint ────────────────────────────
        tk.Frame(self, bg="#1a1a1a", height=1).pack(fill="x", side="bottom")
        self._shortcut_hint = tk.Label(
            self,
            text="Ctrl+?  shortcuts  ·  Ctrl+F  search",
            # sidebar_icon (not text_dim) — this sits on sidebar_bg, which
            # stays dark in both themes, so it needs the sidebar's own
            # mode-invariant color rather than the general text hierarchy.
            bg=t.sidebar_bg, fg=t.sidebar_icon,
            font=("Segoe UI", 8),
            anchor="center",
            cursor="hand2",
        )
        self._shortcut_hint.pack(side="bottom", pady=(0, 4))
        self._shortcut_hint.bind(
            "<Button-1>", lambda e: self.controller._show_shortcut_help())
        self._ver_lbl = tk.Label(
            self,
            text="All Clear  ·  v{}".format(self.controller.APP_VERSION),
            bg=t.sidebar_bg, fg=t.sidebar_icon,
            font=("Segoe UI", 9),
            anchor="center",
            cursor="hand2",
        )
        self._ver_lbl.pack(side="bottom", pady=(6, 2))
        self._ver_lbl.bind("<Button-1>", self.controller._show_about)

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

        # Dedicated frame for dynamic SERVERS section (always at top, initially hidden)
        self._server_section_frame = tk.Frame(self._nav_frame, bg=t.sidebar_bg)
        self._server_section_frame.pack(fill="x")   # pack first = always on top
        self._server_section_frame.pack_forget()     # hidden until servers are added

        self._nav_canvas.bind("<Configure>", self._on_canvas_resize)
        self._nav_frame.bind("<Configure>", self._on_frame_resize)
        self._nav_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._nav_frame.bind("<MouseWheel>", self._on_mousewheel)

        # ── Build nav items ───────────────────────────────────────────
        self._section_widgets     = []
        self._section_rows        = {}   # section name -> [row frames] (its own items)
        self._section_bodies      = {}   # section name -> body frame (holds those rows)
        self._section_labels      = {}   # section name -> header label (for chevron text)
        self._first_nav_row       = None   # anchor for collapse/expand re-pack
        self._first_section_spacer = None  # anchor for _server_section_frame re-pack
        current_section = None
        current_body    = None
        section_collapsed = self.controller.config_manager.sidebar_section_collapsed

        for icon, label, idx, section in self._NAV_ITEMS:
            if section and section != current_section:
                current_section = section
                color   = self._SECTION_COLORS.get(section, t.blue)
                sec_bg  = self._tint(color, t.sidebar_bg, 0.30)

                spacer = tk.Frame(self._nav_frame, bg=t.sidebar_bg, height=6)
                spacer.pack(fill="x")
                spacer.bind("<MouseWheel>", self._on_mousewheel)
                if self._first_section_spacer is None:
                    self._first_section_spacer = spacer

                sec_frame = tk.Frame(self._nav_frame, bg=sec_bg, cursor="hand2")
                sec_frame.pack(fill="x", pady=(0, 2))
                sec_frame.bind("<MouseWheel>", self._on_mousewheel)

                tk.Frame(sec_frame, bg=color, width=3).pack(side="left", fill="y")
                is_collapsed = bool(section_collapsed.get(section))
                sec_lbl = tk.Label(
                    sec_frame,
                    text=self._section_label_text(section, is_collapsed),
                    bg=sec_bg, fg=color,
                    font=("Segoe UI", 9, "bold"),
                    anchor="w", padx=10, cursor="hand2",
                )
                sec_lbl.pack(side="left", fill="x", expand=True, pady=4)
                sec_lbl.bind("<MouseWheel>", self._on_mousewheel)
                sec_lbl.bind("<Button-1>", lambda e, s=section: self._toggle_section(s))
                sec_frame.bind("<Button-1>", lambda e, s=section: self._toggle_section(s))
                self._section_labels[section] = sec_lbl

                # This section's item rows live in their own body frame (kept
                # always packed — a stable sibling of sec_frame/spacer usable
                # as the before= anchor _apply_collapsed_state relies on for
                # the whole-sidebar case). Collapsing a section instead
                # pack_forget()s the *rows* inside it, so the body frame's own
                # pack state never changes and that anchor stays valid even
                # when this section is individually collapsed.
                current_body = tk.Frame(self._nav_frame, bg=t.sidebar_bg)
                current_body.pack(fill="x")
                current_body.bind("<MouseWheel>", self._on_mousewheel)
                self._section_rows[section] = []
                self._section_bodies[section] = current_body
                self._section_widgets.append((sec_frame, spacer, current_body))

            row = tk.Frame(current_body, bg=t.sidebar_bg)
            if not section_collapsed.get(current_section):
                row.pack(fill="x", padx=6, pady=1)
            row.bind("<MouseWheel>", self._on_mousewheel)
            self._section_rows[current_section].append(row)
            if self._first_nav_row is None:
                self._first_nav_row = row

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

        self.set_active(2)

        # All nav rows share the same button style/font, so one measurement
        # (taken while the very first row is still naturally packed) gives
        # a standard row height reused by every section's collapse/expand
        # animation, rather than measuring per-section.
        self.update_idletasks()
        if self._first_nav_row is not None:
            self._row_height = self._first_nav_row.winfo_reqheight()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    @staticmethod
    def _tint(color: str, base: str, ratio: float) -> str:
        """Blend *color* into *base* at *ratio* (0 = all base, 1 = all color)."""
        def _c(h, i): return int(h[i:i+2], 16)
        cr, cg, cb = _c(color, 1), _c(color, 3), _c(color, 5)
        br, bg, bb = _c(base,  1), _c(base,  3), _c(base,  5)
        r = int(cr * ratio + br * (1 - ratio))
        g = int(cg * ratio + bg * (1 - ratio))
        b = int(cb * ratio + bb * (1 - ratio))
        return "#{:02x}{:02x}{:02x}".format(r, g, b)

    # ------------------------------------------------------------------
    # SCROLLING
    # ------------------------------------------------------------------
    def _on_canvas_resize(self, event):
        self._nav_canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_frame_resize(self, event):
        self._nav_canvas.configure(scrollregion=self._nav_canvas.bbox("all"))
        # <Configure> on this frame fires not only when its actual height
        # changes (section collapse/expand, rebuild_servers(), etc.) but
        # also just from the canvas being scrolled — scrolling moves the
        # embedded window on screen, and Tk reports that as a Configure
        # event on the child too, even though its size didn't change.
        # Resetting the scroll here unconditionally means every mousewheel
        # tick would immediately snap back to the top, since scrolling
        # itself re-triggers this handler. Only reset when the height
        # actually changed — that's the real signal that the reclamping
        # problem this guards against (see git history) could happen.
        new_height = event.height
        if new_height != self._last_nav_frame_height:
            self._last_nav_frame_height = new_height
            self._nav_canvas.yview_moveto(0.0)

    def _on_mousewheel(self, event):
        # A fast physical scroll delivers many wheel events in one burst,
        # dispatched to Tk faster than it can settle canvas geometry
        # between them. Calling yview_scroll() once per event (even with
        # a post-hoc correction afterwards) let repeated rapid calls
        # desync the embedded nav_frame window's actual on-screen position
        # from what yview()/bbox() reported — verified directly: after a
        # burst of ~150 synthetic events, yview() still read (0.0, 1.0)
        # the whole time, yet the window had drifted anywhere from -600px
        # to +550px depending on the exact sequence. Coalescing the whole
        # burst into a single net delta, applied once after it settles,
        # means yview_scroll() (or the "nothing to scroll" skip) only
        # ever runs once per burst instead of once per tick, so there's
        # nothing left to desync between repeated calls.
        self._wheel_delta_pending = getattr(self, "_wheel_delta_pending", 0) + event.delta
        if not getattr(self, "_wheel_scroll_scheduled", False):
            self._wheel_scroll_scheduled = True
            self.after_idle(self._apply_pending_wheel_scroll)

    def _apply_pending_wheel_scroll(self):
        delta = self._wheel_delta_pending
        self._wheel_delta_pending = 0
        self._wheel_scroll_scheduled = False
        bbox = self._nav_canvas.bbox("all")
        if bbox:
            self._nav_canvas.configure(scrollregion=bbox)
            if (bbox[3] - bbox[1]) <= self._nav_canvas.winfo_height():
                # Nothing to scroll — make sure it's pinned at the top
                # rather than calling yview_scroll() at all.
                self._nav_canvas.yview_moveto(0.0)
                return
        self._nav_canvas.yview_scroll(int(-1 * (delta / 120)), "units")

    # ------------------------------------------------------------------
    # ACTIVE STATE  (Teams-style: full-width blue row, no accent bar)
    # ------------------------------------------------------------------
    def set_active(self, idx):
        # Don't activate a dimmed item
        if idx in self._dimmed:
            return
        self._active_idx = idx
        t = self.theme
        for btn, icon, label, btn_idx, row in self._buttons:
            is_active = (btn_idx == idx)
            is_dimmed = (btn_idx in self._dimmed)
            if is_active:
                row.configure(bg=t.sidebar_active_bg)
                btn.configure(bg=t.sidebar_active_bg,
                              fg=t.sidebar_icon_active)
            elif is_dimmed:
                row.configure(bg=t.sidebar_bg)
                btn.configure(bg=t.sidebar_bg, fg=t.sidebar_section_text)
            else:
                row.configure(bg=t.sidebar_bg)
                btn.configure(bg=t.sidebar_bg, fg=t.sidebar_icon)

    def show_item(self, idx):
        """Make a hidden nav item visible, restoring its original position."""
        pos = next((i for i, (_, __, ___, bi, ____) in enumerate(self._buttons)
                    if bi == idx), None)
        if pos is None:
            return

        row = self._buttons[pos][4]

        # Insert AFTER the closest preceding sibling that is still packed.
        # Using after= avoids crossing section-header labels that sit between
        # rows as separate widgets in the pack order.
        prev_row = None
        for entry in reversed(self._buttons[:pos]):
            sibling_row = entry[4]
            if sibling_row.winfo_manager():   # non-empty = currently managed
                prev_row = sibling_row
                break

        if prev_row:
            row.pack(fill="x", padx=6, pady=1, after=prev_row)
        else:
            row.pack(fill="x", padx=6, pady=1)

    def hide_item(self, idx):
        """Hide a nav item (pack_forget its row)."""
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx == idx:
                row.pack_forget()
                break

    def dim_item(self, idx, reason="Configure in Settings → Config to enable"):
        """Grey out a nav item. It stays visible but clicking shows a setup hint."""
        t = self.theme
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx != idx:
                continue
            self._dimmed[idx] = {"label": label, "reason": reason}
            row.configure(bg=t.sidebar_bg)
            btn.configure(
                fg=t.sidebar_section_text,
                bg=t.sidebar_bg,
                cursor="arrow",
                command=lambda i=idx: self._dimmed_click(i),
            )
            break

    def undim_item(self, idx):
        """Restore a dimmed nav item to its normal clickable state."""
        t = self.theme
        self._dimmed.pop(idx, None)
        for btn, icon, label, btn_idx, row in self._buttons:
            if btn_idx != idx:
                continue
            btn.configure(
                fg=t.sidebar_icon,
                bg=t.sidebar_bg,
                cursor="hand2",
                command=lambda i=idx: self._nav_click(i),
            )
            break

    def _dimmed_click(self, idx):
        """Called when the user clicks a dimmed (unconfigured) nav item."""
        info = self._dimmed.get(idx, {})
        label  = info.get("label", "This tab")
        reason = info.get("reason", "Configure in Settings → Config to enable")
        self.controller.show_toast(
            "{} not configured".format(label),
            reason,
            duration_ms=4000,
            level="info",
        )

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
                # place() instead of pack(): the row's button already fills
                # the row via pack(fill="x", expand=True), so a badge packed
                # afterwards gets shoved into the leftover cavity *below* the
                # button instead of overlaying it. place() floats the badge
                # on top, anchored to the row's right edge, independent of
                # the button's own pack geometry.
                badge.place(relx=1.0, rely=0.5, anchor="e", x=-10)
            break

    def _nav_click(self, idx):
        self.set_active(idx)
        self.controller.tabs.select(idx)

    def _on_hover(self, btn, row, idx, entering):
        t = self.theme
        is_active = (idx == self._active_idx)
        is_dimmed = (idx in self._dimmed)
        if is_dimmed:
            # Subtle tint on hover to indicate it's interactive, but don't
            # brighten the text — keeps it clearly "not enabled"
            if entering:
                row.configure(bg=t.surface_dark)
                btn.configure(bg=t.surface_dark)
            else:
                row.configure(bg=t.sidebar_bg)
                btn.configure(bg=t.sidebar_bg)
        elif entering and not is_active:
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
    # DYNAMIC SERVER SECTION
    # ------------------------------------------------------------------
    def rebuild_servers(self, cfg):
        """
        Rebuild the server picker at the top of the sidebar from the server
        profiles in cfg. A single dropdown (not a per-server nav-style list)
        so it reads as a standalone control rather than another entry in the
        CORE section directly below it. Uses a dedicated
        _server_section_frame that is always at the top of the nav.
        """
        t = self.theme

        # Clear existing content
        for w in self._server_section_frame.winfo_children():
            w.destroy()

        servers    = cfg.get_servers()
        active_idx = cfg.get_active_server_index()

        pad = tk.Frame(self._server_section_frame, bg=t.sidebar_bg)
        pad.pack(fill="x", padx=10, pady=(10, 8))
        pad.bind("<MouseWheel>", self._on_mousewheel)

        color = self._SECTION_COLORS.get("SERVERS", t.blue)

        hdr_row = tk.Frame(pad, bg=t.sidebar_bg)
        hdr_row.pack(fill="x")
        hdr_row.bind("<MouseWheel>", self._on_mousewheel)
        tk.Label(
            hdr_row, text="SERVERS",
            bg=t.sidebar_bg, fg=color,
            font=("Segoe UI", 9, "bold"), anchor="w",
        ).pack(side="left")

        add_btn = tk.Button(
            hdr_row, text="+",
            command=lambda: self.controller.open_server_dialog(),
            bg=t.sidebar_bg, fg=t.sidebar_section_text,
            bd=0, relief="flat",
            font=("Segoe UI", 12, "bold"),
            padx=4, pady=0,
            cursor="hand2",
        )
        add_btn.pack(side="right")
        add_btn.bind("<Enter>", lambda e: add_btn.configure(fg=t.sidebar_icon_hover))
        add_btn.bind("<Leave>", lambda e: add_btn.configure(fg=t.sidebar_section_text))
        self._create_tooltip(add_btn, "Add server")

        if not servers:
            empty_btn = tk.Button(
                pad, text="+ Add a server to get started",
                command=lambda: self.controller.open_server_dialog(),
                bg=t.sidebar_bg, fg=t.sidebar_section_text,
                bd=0, relief="flat",
                font=("Segoe UI", 9), anchor="w",
                padx=0, pady=6,
                cursor="hand2",
            )
            empty_btn.pack(fill="x", pady=(4, 0))
            empty_btn.bind("<Enter>", lambda e: empty_btn.configure(fg=t.sidebar_icon_hover))
            empty_btn.bind("<Leave>", lambda e: empty_btn.configure(fg=t.sidebar_section_text))
        else:
            names = [s.get("name") or s.get("host", "Server {}".format(i + 1))
                     for i, s in enumerate(servers)]
            active_name = names[active_idx] if 0 <= active_idx < len(names) else names[0]

            picker_row = tk.Frame(pad, bg=t.sidebar_bg)
            picker_row.pack(fill="x", pady=(4, 0))
            picker_row.bind("<MouseWheel>", self._on_mousewheel)

            self._server_var = tk.StringVar(value=active_name)
            cb = ttk.Combobox(
                picker_row, textvariable=self._server_var,
                values=names, state="readonly",
                font=("Segoe UI", 10),
            )
            cb.pack(side="left", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>",
                    lambda e: self._server_selected(servers, names))

            edit_btn = tk.Button(
                picker_row, text="\u270e",
                command=lambda: self._edit_selected_server(servers, names),
                bg=t.sidebar_bg, fg=t.sidebar_section_text,
                bd=0, relief="flat",
                font=("Segoe UI", 10),
                padx=6, pady=0,
                cursor="hand2",
            )
            edit_btn.pack(side="left", padx=(4, 0))
            edit_btn.bind("<Enter>", lambda e: edit_btn.configure(fg=t.sidebar_icon_hover))
            edit_btn.bind("<Leave>", lambda e: edit_btn.configure(fg=t.sidebar_section_text))
            self._create_tooltip(edit_btn, "Edit / delete server")

        # Separator to visually detach the picker from the CORE nav below it
        tk.Frame(self._server_section_frame, bg="#1a1a1a", height=1).pack(
            fill="x", pady=(0, 2))

        # Show the frame (was hidden if no servers before). before= restores
        # it to the very top of the nav instead of appending it after every
        # other section if this runs after _build_sidebar already packed the
        # rest of the nav (e.g. adding the first server after startup).
        # Anchor on the first section's spacer (packed before its colored
        # header bar) rather than its first item row — anchoring on the row
        # would insert this frame after the CORE header but before CORE's
        # first row, splitting the CORE section in two.
        if self._first_section_spacer is not None:
            self._server_section_frame.pack(fill="x", before=self._first_section_spacer)
        else:
            self._server_section_frame.pack(fill="x")

    def _server_selected(self, servers, names):
        name = self._server_var.get()
        try:
            idx = names.index(name)
        except ValueError:
            return
        try:
            self.controller.config_manager.set_active_server_index(idx)
            self.controller.switch_server(servers[idx])
        except Exception:
            pass

    def _edit_selected_server(self, servers, names):
        name = self._server_var.get()
        idx  = names.index(name) if name in names else 0
        if 0 <= idx < len(servers):
            self.controller.open_server_dialog(servers[idx])

    # ------------------------------------------------------------------
    # TOGGLE / ANIMATION
    # ------------------------------------------------------------------
    def toggle(self):
        if self._animating:
            return
        self._collapsed = not self._collapsed
        start_w = self.EXPANDED_WIDTH if self._collapsed else self.COLLAPSED_WIDTH
        end_w   = self.COLLAPSED_WIDTH if self._collapsed else self.EXPANDED_WIDTH
        self._animating = True
        self._animate(start_w, end_w, 0)

    def _animate(self, start_w, end_w, step):
        frac  = step / self.ANIM_STEPS
        # Ease-in-out cubic
        frac  = frac * frac * (3 - 2 * frac)
        w     = int(start_w + (end_w - start_w) * frac)
        self.configure(width=w)
        if step < self.ANIM_STEPS:
            self.after(self.ANIM_MS,
                       lambda: self._animate(start_w, end_w, step + 1))
        else:
            self._animating = False
            self.configure(width=end_w)
            self._apply_collapsed_state()

    @staticmethod
    def _section_label_text(section, collapsed):
        return "{}  {}".format("▸" if collapsed else "▾", section)

    def _toggle_section(self, section):
        """Collapse/expand one sidebar section independently of the others,
        persisting the choice so it survives an app restart. Animates each
        row's height down/up to zero — the same step-count/easing as the
        whole-sidebar width animation (_animate) — rather than instantly
        pack_forget()/pack()ing rows, which just made items disappear in
        one frame instead of visibly collapsing. The section's body frame
        itself stays packed at all times (see _build_sidebar) — only its
        row children are shown/hidden — so this section's entry in
        _section_widgets stays a valid before= anchor for the whole-sidebar
        collapse case even while individually collapsed."""
        if section in self._section_animating or not self._row_height:
            return
        cfg = self.controller.config_manager
        state = dict(cfg.sidebar_section_collapsed)
        collapsed = not state.get(section, False)
        state[section] = collapsed
        cfg.sidebar_section_collapsed = state

        lbl = self._section_labels.get(section)
        if lbl is not None:
            lbl.config(text=self._section_label_text(section, collapsed))

        rows = self._section_rows.get(section, [])
        if not rows:
            return
        self._section_animating.add(section)

        if collapsed:
            for row in rows:
                row.pack_propagate(False)
                row.configure(height=self._row_height)
            self._animate_section(section, rows, self._row_height, 0, 0)
        else:
            for row in rows:
                row.pack_propagate(False)
                row.configure(height=0)
                row.pack(fill="x", padx=6, pady=1)
            self._animate_section(section, rows, 0, self._row_height, 0)

    def _animate_section(self, section, rows, start_h, end_h, step):
        frac = step / self.ANIM_STEPS
        frac = frac * frac * (3 - 2 * frac)   # same ease-in-out cubic as _animate
        h = int(start_h + (end_h - start_h) * frac)
        for row in rows:
            row.configure(height=h)
        if step < self.ANIM_STEPS:
            self.after(self.ANIM_MS, lambda: self._animate_section(
                section, rows, start_h, end_h, step + 1))
        else:
            self._section_animating.discard(section)
            if end_h == 0:
                for row in rows:
                    row.pack_forget()
                # A Tk Frame that once sized itself around packed children
                # doesn't shrink its own geometry cache after the last one
                # is pack_forget()'d — verified directly: winfo_reqheight()
                # keeps reporting the old size even after update_idletasks().
                # Toggling pack_propagate forces a real recompute, which is
                # what made every collapsed section's leftover height scale
                # with its row count instead of collapsing to ~0.
                body = self._section_bodies.get(section)
                if body is not None:
                    body.pack_propagate(False)
                    body.configure(height=1)
                    body.pack_propagate(True)
            else:
                for row in rows:
                    row.pack_propagate(True)
                # Rows that were just re-packed after sitting pack_forget()'d
                # (and animated up from height=0) can be left showing a
                # stale/unpainted look — the same underlying Tk-on-Windows
                # quirk as the startup white-flash bug (see main.py's
                # _splash_step): a widget resized/mapped while not fully
                # visible doesn't always get a real repaint until something
                # marks it dirty again. Re-asserting each button's own
                # current colors is a harmless no-op value-wise, but forces
                # that repaint, matching the same fix used there.
                rows_set = set(rows)
                for btn, icon, label, idx, row in self._buttons:
                    if row in rows_set:
                        btn.configure(bg=btn.cget("bg"), fg=btn.cget("fg"))

            # A previous fix here called self._nav_canvas.lower()/.lift()
            # to try to force a repaint of the area above the toggled
            # section, based on a gap-above-SERVERS report that turned out
            # to actually be caused by _on_mousewheel's scroll correction
            # running reentrantly mid-burst (fixed there instead — see
            # _settle_nav_scroll). Z-order-cycling the nav canvas on every
            # single section toggle measured at ~750ms of added latency
            # per toggle in this app's widget tree, and — worse — could
            # hang the process outright when called back-to-back. Removed;
            # nothing here actually needed it once the real bug was fixed.

    def _apply_collapsed_state(self):
        """Show/hide labels and section headers after animation completes."""
        collapsed = self._collapsed

        # Header: collapsed = only the toggle button, centered
        if collapsed:
            self._icon_lbl.pack_forget()
            self._app_lbl.pack_forget()
            self._theme_btn.pack_forget()
            self._toggle_btn.pack_forget()
            self._toggle_btn.pack(expand=True)
            self._ver_lbl.config(text="")
            self._shortcut_hint.pack_forget()
        else:
            self._toggle_btn.pack_forget()
            self._icon_lbl.pack(side="left", padx=(14, 4), pady=14)
            self._app_lbl.pack(side="left")
            self._theme_btn.pack(side="right")
            self._toggle_btn.pack(side="right", padx=4)
            self._ver_lbl.config(text="All Clear  ·  v{}".format(self.controller.APP_VERSION))
            self._shortcut_hint.pack(side="bottom", pady=(0, 4))

        # Section header frames — re-pack with before= to restore each
        # header to its original slot (a bare pack() would instead append
        # it after every already-packed nav row, dumping every section
        # label at the bottom of the sidebar).
        for sec_frame, spacer, anchor_row in self._section_widgets:
            if collapsed:
                sec_frame.pack_forget()
                spacer.pack_forget()
            else:
                spacer.pack(fill="x", before=anchor_row)
                sec_frame.pack(fill="x", pady=(0, 2), before=anchor_row)

        # Nav button text: icon only vs icon + label
        for btn, icon, label, idx, row in self._buttons:
            is_active = (idx == self._active_idx)
            is_dimmed = (idx in self._dimmed)
            if collapsed:
                btn.configure(text=icon, width=3, anchor="center",
                               padx=0, pady=10)
            else:
                btn.configure(text="{} {}".format(icon, label),
                               width=0, anchor="w", padx=16, pady=8)
                if is_active:
                    btn.configure(bg=self.theme.sidebar_active_bg,
                                   fg=self.theme.sidebar_icon_active)
                elif is_dimmed:
                    btn.configure(bg=self.theme.sidebar_bg,
                                  fg=self.theme.sidebar_section_text)
                else:
                    btn.configure(bg=self.theme.sidebar_bg,
                                  fg=self.theme.sidebar_icon)
