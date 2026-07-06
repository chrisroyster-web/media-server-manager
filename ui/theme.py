# ui/theme.py
"""
Microsoft Fluent Design dark theme.

Palette:
  • bg / surface hierarchy uses neutral dark grays (not blue-black)
  • Primary accent: #0078d4  (Microsoft / Fluent blue)
  • Text hierarchy mirrors Office 365 dark mode contrast ratios
  • Buttons, cards and sidebar follow Teams / Office 365 visual language
"""

import tkinter as tk
from tkinter import ttk


class Theme:

    _DARK = dict(
        bg="#202020", panel_bg="#202020", sidebar_bg="#252525",
        surface="#2d2d2d", surface_dark="#1a1a1a", surface_light="#383838",
        card_bg="#2d2d2d", card_border="#3d3d3d",
        glass_accent="#2d2d2d", glass_shimmer="#383838",
        text="#f3f3f3", text_secondary="#d0d0d0",
        text_muted="#9e9e9e", text_dim="#8a8a8a",
        sidebar_icon="#c8c8c8", sidebar_icon_hover="#ffffff",
        sidebar_icon_active="#ffffff", sidebar_active_bg="#0078d4",
        sidebar_active_bar="#0078d4", sidebar_section_text="#808080",
        console_cmd="#9cdcfe", console_info="#d4d4d4",
        console_success="#57a300", console_error="#f14c4c",
        console_timestamp="#608b4e", console_output="#f3f3f3",
        _button_default_bg="#383838", _button_default_hover="#4a4a4a",
        _button_ghost_bg_ref="bg",   # resolved at runtime
        _treeview_sel="#094771",
    )

    _LIGHT = dict(
        bg="#f3f3f3", panel_bg="#f3f3f3", sidebar_bg="#2b2b2b",
        surface="#ffffff", surface_dark="#e5e5e5", surface_light="#f9f9f9",
        card_bg="#ffffff", card_border="#d8d8d8",
        glass_accent="#ffffff", glass_shimmer="#f0f0f0",
        text="#1a1a1a", text_secondary="#3d3d3d",
        text_muted="#666666", text_dim="#6e6e6e",
        sidebar_icon="#c8c8c8", sidebar_icon_hover="#ffffff",
        sidebar_icon_active="#ffffff", sidebar_active_bg="#0078d4",
        sidebar_active_bar="#0078d4", sidebar_section_text="#888888",
        console_cmd="#0070c1", console_info="#1a1a1a",
        console_success="#107c10", console_error="#c50f1f",
        console_timestamp="#498205", console_output="#1a1a1a",
        _button_default_bg="#e0e0e0", _button_default_hover="#c8c8c8",
        _button_ghost_bg_ref="bg",
        _treeview_sel="#cce4f7",
    )

    def __init__(self, mode="dark"):
        self.mode = mode
        palette   = self._LIGHT if mode == "light" else self._DARK

        # ── Core backgrounds ──────────────────────────────────────────
        self.bg           = palette["bg"]
        self.panel_bg     = palette["panel_bg"]
        self.sidebar_bg   = palette["sidebar_bg"]

        # ── Surfaces ──────────────────────────────────────────────────
        self.surface       = palette["surface"]
        self.surface_dark  = palette["surface_dark"]
        self.surface_light = palette["surface_light"]

        # ── Cards ─────────────────────────────────────────────────────
        self.card_bg          = palette["card_bg"]
        self.card_border      = palette["card_border"]
        self.card_border_glow = "#0078d4"

        # (kept for compat)
        self.glass_accent  = palette["glass_accent"]
        self.glass_shimmer = palette["glass_shimmer"]

        # ── Text hierarchy ────────────────────────────────────────────
        self.text           = palette["text"]
        self.text_secondary = palette["text_secondary"]
        self.text_muted     = palette["text_muted"]
        self.text_dim       = palette["text_dim"]

        # ── Sidebar (Teams-style, always dark) ────────────────────────
        self.sidebar_icon         = palette["sidebar_icon"]
        self.sidebar_icon_hover   = palette["sidebar_icon_hover"]
        self.sidebar_icon_active  = palette["sidebar_icon_active"]
        self.sidebar_active_bg    = palette["sidebar_active_bg"]
        self.sidebar_active_bar   = palette["sidebar_active_bar"]
        self.sidebar_section_text = palette["sidebar_section_text"]

        # ── Internal button palette refs ──────────────────────────────
        self._btn_def_bg    = palette["_button_default_bg"]
        self._btn_def_hover = palette["_button_default_hover"]
        self._treeview_sel  = palette["_treeview_sel"]

        # ── Accent / brand ────────────────────────────────────────────
        self.blue        = "#0078d4"   # Microsoft Fluent blue
        self.blue_bright = "#1a8cf3"   # hover / lighter blue
        self.cyan        = "#00b4d8"
        self.yellow      = "#ffb900"   # Office amber
        self.orange      = "#da3b01"   # Office orange-red
        self.purple      = "#8764b8"   # Office purple
        self.red         = "#d13438"
        self.accent      = self.blue

        # ── Status colors ─────────────────────────────────────────────
        # status_running was previously a fixed "#57a300" in both modes —
        # fine against a dark background (5.15:1) but only 2.85:1 against
        # light mode's near-white bg, well under WCAG's 4.5:1 for normal
        # text. console_success/console_error already carry correctly
        # tuned per-mode shades of the same two hues (they were only ever
        # wired to console output), so status colors now reuse them
        # instead of inventing new values.
        self.status_running = palette["console_success"]
        self.status_stopped = "#d13438"   # Office red — fine for dots/borders/cards (3.3:1 dark, 4.44:1 light; WCAG's large-text/UI threshold is 3:1)
        self.status_unknown = "#767676"

        # Text-only variant: status_stopped is used as small fg=/foreground=
        # text (88 sites) far more than as a dot/fill/border color, and at
        # that size 3.3:1 isn't enough. console_error is the same red hue
        # already tuned for legibility at text size in both modes.
        self.status_stopped_text = palette["console_error"]

        self.glow_green = "#57a300"
        self.glow_blue  = "#0078d4"
        self.glow_red   = "#d13438"

        # ── Console ───────────────────────────────────────────────────
        self.console_cmd       = palette["console_cmd"]
        self.console_info      = palette["console_info"]
        self.console_success   = palette["console_success"]
        self.console_error     = palette["console_error"]
        self.console_timestamp = palette["console_timestamp"]
        self.console_output    = palette["console_output"]

        # ── Typography ────────────────────────────────────────────────
        self.font_display = ("Segoe UI Semibold", 20)
        self.font_title   = ("Segoe UI Semibold", 13)
        self.font_heading = ("Segoe UI Semibold", 11)
        self.font_regular = ("Segoe UI", 11)
        self.font_small   = ("Segoe UI", 10)
        self.font_tiny    = ("Segoe UI", 10)
        self.font_mono    = ("Cascadia Code", 10) if self._font_exists("Cascadia Code") \
                            else ("Consolas", 10)

    @staticmethod
    def _font_exists(name):
        try:
            import tkinter.font as tkfont
            return name in tkfont.families()
        except Exception:
            return False

    # ── Global ttk style pass ─────────────────────────────────────────
    def apply_ttk_styles(self, root):
        s = ttk.Style(root)
        s.theme_use("clam")

        # ── Treeview ──────────────────────────────────────────────────
        s.configure("Treeview",
            background=self.surface,
            foreground=self.text,
            fieldbackground=self.surface,
            borderwidth=0,
            relief="flat",
            rowheight=26,
            font=self.font_regular,
        )
        s.configure("Treeview.Heading",
            background=self.surface_dark,
            foreground=self.text_secondary,
            relief="flat",
            borderwidth=0,
            font=self.font_heading,
        )
        s.map("Treeview",
            background=[("selected", self._treeview_sel)],
            foreground=[("selected", "#ffffff" if self.mode == "dark" else "#1a1a1a")],
        )
        s.map("Treeview.Heading",
            background=[("active", self.surface_light)],
            foreground=[("active", self.text)],
        )

        # ── Scrollbar ─────────────────────────────────────────────────
        s.configure("Vertical.TScrollbar",
            background=self.surface_light,
            troughcolor=self.surface_dark,
            borderwidth=0,
            relief="flat",
            arrowsize=0,
            width=8,
        )
        s.configure("Horizontal.TScrollbar",
            background=self.surface_light,
            troughcolor=self.surface_dark,
            borderwidth=0,
            relief="flat",
            arrowsize=0,
            width=8,
        )
        s.map("Vertical.TScrollbar",
            background=[("active", self.blue)],
        )
        s.map("Horizontal.TScrollbar",
            background=[("active", self.blue)],
        )

        # ── Notebook ──────────────────────────────────────────────────
        # Tab strip hidden via clipping in main.py
        s.configure("TNotebook", borderwidth=0, padding=0)

        # Inner notebook tabs (Arr tab, etc.) — Office-style
        s.configure("TNotebook.Tab",
            background=self.surface,
            foreground=self.text_muted,
            padding=[14, 6],
            font=self.font_small,
            borderwidth=0,
        )
        s.map("TNotebook.Tab",
            background=[("selected", self.surface_light)],
            foreground=[("selected", self.text)],
        )

        # ── Combobox ─────────────────────────────────────────────────
        s.configure("TCombobox",
            fieldbackground=self.surface_dark,
            background=self.surface_light,
            foreground=self.text,
            selectbackground="#094771",
            selectforeground="#ffffff",
            borderwidth=1,
            relief="solid",
            arrowsize=14,
        )
        s.map("TCombobox",
            fieldbackground=[("readonly", self.surface)],
            foreground=[("disabled", self.text_dim)],
        )

        # ── Separator ─────────────────────────────────────────────────
        s.configure("TSeparator", background=self.card_border)

        # ── Progressbar ───────────────────────────────────────────────
        s.configure("TProgressbar",
            troughcolor=self.surface_dark,
            background=self.blue,
            borderwidth=0,
            relief="flat",
            thickness=4,
        )

    # ── Button styling ────────────────────────────────────────────────
    def style_button(self, btn, variant="default"):
        """
        Office-style flat button with crisp hover transition.
        default  — subtle surface button (like Office secondary)
        primary  — solid blue (like Office primary action)
        danger   — red for destructive actions
        ghost    — text-only, no background
        """
        configs = {
            "default": (self._btn_def_bg,  self.text,           self._btn_def_hover, "#ffffff" if self.mode == "dark" else self.text),
            "primary": (self.blue,          "#ffffff",           self.blue_bright,    "#ffffff"),
            "danger":  ("#c42b1c",          "#ffffff",           "#d13438",           "#ffffff"),
            "ghost":   (self.bg,            self.text_secondary, self.surface_light,  self.text),
        }
        bg, fg, hover_bg, hover_fg = configs.get(variant, configs["default"])
        btn.configure(
            bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=hover_fg,
            bd=0, relief="flat",
            font=self.font_regular,
            padx=14, pady=5,
            cursor="hand2",
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg, fg=hover_fg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg, fg=fg))

    # ── Entry styling ─────────────────────────────────────────────────
    def style_entry(self, entry):
        entry.configure(
            bg=self.surface_dark,
            fg=self.text,
            insertbackground=self.blue,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightcolor=self.blue,
            highlightbackground=self.card_border,
            font=self.font_regular,
        )
        entry.bind("<FocusIn>",
            lambda e: entry.configure(highlightbackground=self.blue))
        entry.bind("<FocusOut>",
            lambda e: entry.configure(highlightbackground=self.card_border))

    # ── Card (flat, Office-style) ─────────────────────────────────────
    def make_glass_card(self, parent, **kwargs):
        """Flat card — retains the old name for backward compatibility."""
        defaults = dict(
            bg=self.surface,
            highlightbackground=self.card_border,
            highlightthickness=1,
        )
        defaults.update(kwargs)
        card = tk.Frame(parent, **defaults)
        card.bind("<Enter>",
            lambda e: card.configure(highlightbackground=self.card_border_glow))
        card.bind("<Leave>",
            lambda e: card.configure(highlightbackground=self.card_border))
        return card

    # ── Section label ─────────────────────────────────────────────────
    def make_section_label(self, parent, text):
        return tk.Label(
            parent,
            text=text.upper(),
            bg=parent.cget("bg"),
            fg=self.text_muted,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )

    # ── Pill badge ────────────────────────────────────────────────────
    def make_badge(self, parent, text, color=None):
        color = color or self.blue
        return tk.Label(
            parent,
            text=text,
            bg=color,
            fg="#ffffff",
            font=self.font_tiny,
            padx=6, pady=2,
        )
