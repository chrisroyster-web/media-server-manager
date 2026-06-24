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

    def __init__(self):
        # ── Core backgrounds  (neutral dark gray, not blue-black) ─────
        self.bg           = "#202020"
        self.panel_bg     = "#202020"
        self.sidebar_bg   = "#252525"

        # ── Surfaces ──────────────────────────────────────────────────
        self.surface       = "#2d2d2d"
        self.surface_dark  = "#1a1a1a"
        self.surface_light = "#383838"

        # ── Cards ─────────────────────────────────────────────────────
        self.card_bg          = "#2d2d2d"
        self.card_border      = "#3d3d3d"
        self.card_border_glow = "#0078d4"

        # (kept for compat — no longer used for "glass" effect)
        self.glass_accent  = "#2d2d2d"
        self.glass_shimmer = "#383838"

        # ── Text hierarchy ────────────────────────────────────────────
        self.text           = "#f3f3f3"   # primary  — Office near-white
        self.text_secondary = "#d0d0d0"   # body     — light gray
        self.text_muted     = "#9e9e9e"   # captions
        self.text_dim       = "#6e6e6e"   # timestamps / placeholders

        # ── Sidebar (Teams-style) ─────────────────────────────────────
        self.sidebar_icon         = "#c8c8c8"
        self.sidebar_icon_hover   = "#ffffff"
        self.sidebar_icon_active  = "#ffffff"
        self.sidebar_active_bg    = "#0078d4"   # full-width Office blue
        self.sidebar_active_bar   = "#0078d4"
        self.sidebar_section_text = "#808080"

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
        self.status_running = "#57a300"   # Office green
        self.status_stopped = "#d13438"   # Office red
        self.status_unknown = "#767676"

        self.glow_green = "#57a300"
        self.glow_blue  = "#0078d4"
        self.glow_red   = "#d13438"

        # ── Console ───────────────────────────────────────────────────
        self.console_cmd       = "#9cdcfe"   # VS Code parameter blue
        self.console_info      = "#d4d4d4"
        self.console_success   = "#57a300"
        self.console_error     = "#f14c4c"
        self.console_timestamp = "#608b4e"   # VS Code comment green
        self.console_output    = "#f3f3f3"

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
            background=[("selected", "#094771")],   # Office selection blue
            foreground=[("selected", "#ffffff")],
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
            "default": ("#383838", self.text,       "#4a4a4a", "#ffffff"),
            "primary": (self.blue,  "#ffffff",       self.blue_bright, "#ffffff"),
            "danger":  ("#c42b1c", "#ffffff",        "#d13438", "#ffffff"),
            "ghost":   (self.bg,   self.text_secondary, self.surface_light, self.text),
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
