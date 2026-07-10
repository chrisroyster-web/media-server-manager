# ui/theme.py
"""
Microsoft Fluent Design dark theme.

Palette:
  • bg / surface hierarchy uses neutral dark grays (not blue-black)
  • Primary accent: #0078d4  (Microsoft / Fluent blue)
  • Text hierarchy mirrors Office 365 dark mode contrast ratios
  • Buttons, cards and sidebar follow Teams / Office 365 visual language
"""

import re
import tkinter as tk
from tkinter import ttk

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# ── Custom ttk style capture ───────────────────────────────────────────
# ~44 tab modules each call ttk.Style().configure()/.map() with their own
# style name (e.g. "MR.TNotebook.Tab", "Jobs.Treeview") instead of reusing
# the generic names apply_ttk_styles() refreshes below. Wrapping the two
# ttk.Style methods once, here, records every such call (style name +
# kwargs, with whatever literal colors were live at the time) so a live
# theme toggle can replay them with old colors swapped for new — without
# every one of those 44 files needing to know this mechanism exists.
_style_calls = {}   # style_name -> [("configure"|"map", {opt: value, ...}), ...]

if not getattr(ttk.Style, "_theme_capture_installed", False):
    _orig_style_configure = ttk.Style.configure
    _orig_style_map = ttk.Style.map

    def _capturing_configure(self, style, query_opt=None, **kw):
        result = _orig_style_configure(self, style, query_opt, **kw)
        if kw:
            _style_calls.setdefault(style, []).append(("configure", dict(kw)))
        return result

    def _capturing_map(self, style, query_opt=None, **kw):
        result = _orig_style_map(self, style, query_opt, **kw)
        if kw:
            _style_calls.setdefault(style, []).append(("map", dict(kw)))
        return result

    ttk.Style.configure = _capturing_configure
    ttk.Style.map = _capturing_map
    ttk.Style._theme_capture_installed = True

# Row-striping/source-color tags on ttk.Treeview (e.g. play_history_tab's
# "odd"/"even"/"plex" tags) live per-widget-instance via tag_configure(),
# a completely different API from ttk.Style — so the capture above never
# sees them, and recolor_widget_tree()'s existing tk.Text tag_configure()
# handling doesn't apply either (Treeview isn't a tk.Text). Without this,
# a live toggle recolors the Treeview's own background/header (generic
# "Treeview" style) but every already-inserted row keeps its old-mode tag
# colors — e.g. dark-mode near-black row backgrounds surviving a toggle
# to light, reading as content stuck on a black screen. Recorded per
# widget instance (not a module-level dict like the style capture above)
# since tags are scoped to one Treeview, not shared globally by name.
if not getattr(ttk.Treeview, "_theme_capture_installed", False):
    _orig_treeview_tag_configure = ttk.Treeview.tag_configure

    def _capturing_tag_configure(self, tagname, option=None, **kw):
        if option is not None:
            result = _orig_treeview_tag_configure(self, tagname, option, **kw)
        else:
            result = _orig_treeview_tag_configure(self, tagname, **kw)
        if kw:
            if not hasattr(self, "_captured_tag_calls"):
                self._captured_tag_calls = {}
            self._captured_tag_calls[tagname] = dict(kw)
        return result

    ttk.Treeview.tag_configure = _capturing_tag_configure
    ttk.Treeview._theme_capture_installed = True

# Generic style names apply_ttk_styles() already refreshes directly —
# skip these during replay so a stale recorded call can't clobber the
# freshly (and sometimes mode-conditionally) computed values it just set.
_GENERIC_STYLE_NAMES = {
    "Treeview", "Treeview.Heading",
    "Vertical.TScrollbar", "Horizontal.TScrollbar",
    "TNotebook", "TNotebook.Tab",
    "TCombobox", "TSeparator", "TProgressbar",
}


def _remap_style_value(value, remap):
    """Apply {old_hex: new_hex} to a single ttk configure()/map() value —
    either a literal color string, or (for .map()) a list of
    (state_spec, value) tuples."""
    if isinstance(value, str):
        return remap.get(value, value)
    if isinstance(value, (list, tuple)):
        new_items = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                state_spec, color = item
                new_items.append((state_spec, remap.get(color, color)
                                   if isinstance(color, str) else color))
            else:
                new_items.append(item)
        return new_items
    return value

# Color-bearing widget options worth checking during a live theme switch.
# Every plain tk widget bakes its bg=/fg=/etc. in as a literal string at
# construction time (unlike ttk, there's no dynamic style to just
# reconfigure), so recoloring in place means finding every widget whose
# *current value* matches an old palette color and rewriting it.
#
# "bg"/"background" and "fg"/"foreground" are Tk aliases for the exact
# same underlying option, not two different options — listing both used
# to mean this got read-and-rewritten twice per widget under two names.
# Since the first pass's *new* color can itself be a valid source key
# elsewhere in the remap (many palette values collide across unrelated
# attributes), the second pass could hop it again through an unrelated
# mapping and land on the wrong color entirely. Only one name per alias.
_COLOR_OPTS = (
    "bg", "fg",
    "activebackground", "activeforeground",
    "disabledforeground", "disabledbackground",
    "highlightbackground", "highlightcolor",
    "insertbackground", "selectbackground", "selectforeground",
    "readonlybackground", "troughcolor",
    # Checkbutton/Radiobutton indicator-box fill — distinct from
    # selectbackground/selectforeground (Entry/Listbox text selection).
    # Missing this meant a live toggle left the indicator box on whatever
    # mode it was built under (e.g. dark mode's near-black surface_dark),
    # reading as a solid black box regardless of checked state once the
    # rest of the tab had recolored to light.
    "selectcolor",
    # Spinbox's up/down arrow background (config_tab's numeric spinboxes) —
    # same class of gap as selectcolor above, found by auditing every
    # color-bearing widget option against this tuple.
    "buttonbackground",
)


def recolor_widget_tree(widget, remap):
    """Walk the widget tree from `widget` and rewrite any color option
    whose current value is a key in `remap` (old hex -> new hex). Used by
    MediaServerManager.toggle_theme() to re-skin the whole already-built
    UI in place instead of restarting the process. Canvas-drawn items
    (fill=/outline=) are handled separately since their colors live on
    the drawn item, not a widget option.

    Known limitation: this matches by literal color value, not by which
    theme attribute a widget's color came from. If two palette attributes
    ever share the same hex string in one mode but diverge in the other,
    only one of them can win the remap for that value — give any
    widely-used attribute its own distinct value rather than reusing
    another attribute's (this bit _button_default_bg once: it shared
    dark mode's "#383838" with surface_light/glass_shimmer, so every
    default-styled button's remap silently landed on surface_light's
    target instead of its own). What's left (surface_light/glass_shimmer
    still share a value) is genuinely cosmetic — glass_shimmer has no
    direct call sites in the codebase.
    """
    try:
        keys = widget.keys()
    except Exception:
        keys = []
    for opt in _COLOR_OPTS:
        if opt not in keys:
            continue
        try:
            # cget() can hand back a _tkinter.Tcl_Obj instead of a plain
            # str for some widget/option combinations — unhashable, so it
            # blows up a dict lookup unless coerced first.
            cur = str(widget.cget(opt))
        except Exception:
            continue
        new = remap.get(cur)
        if new:
            try:
                widget.configure(**{opt: new})
            except Exception:
                pass

    if isinstance(widget, tk.Canvas):
        for item in widget.find_all():
            for opt in ("fill", "outline"):
                try:
                    cur = str(widget.itemcget(item, opt))
                except Exception:
                    continue
                new = remap.get(cur)
                if new:
                    try:
                        widget.itemconfigure(item, **{opt: new})
                    except Exception:
                        pass

    if isinstance(widget, tk.Text):
        # tag_config() colors (console/log output tags — cmd/info/error/
        # etc. across ~40 tabs) live on the tag, not a widget option, so
        # the .cget() walk above never sees them. Left unhandled, a tab's
        # own base bg/fg gets corrected by the walk above but any text
        # already inserted with a color tag keeps its color from whichever
        # mode the tab was built in — e.g. a dark-mode-bright tag color
        # sitting on a now-light background reads as barely-there, near
        # enough to invisible that a command's output looks like it never
        # ran.
        for tagname in widget.tag_names():
            for opt in ("foreground", "background"):
                try:
                    cur = str(widget.tag_cget(tagname, opt))
                except Exception:
                    continue
                new = remap.get(cur)
                if new:
                    try:
                        widget.tag_configure(tagname, **{opt: new})
                    except Exception:
                        pass

    if isinstance(widget, ttk.Treeview):
        for tagname, kw in getattr(widget, "_captured_tag_calls", {}).items():
            new_kw = {opt: (remap.get(val, val) if isinstance(val, str) else val)
                      for opt, val in kw.items()}
            if new_kw != kw:
                try:
                    widget.tag_configure(tagname, **new_kw)
                except Exception:
                    pass

    for child in widget.winfo_children():
        recolor_widget_tree(child, remap)


class Theme:

    _DARK = dict(
        bg="#202020", panel_bg="#202020", sidebar_bg="#252525",
        surface="#2d2d2d", surface_dark="#1a1a1a", surface_light="#383838",
        card_bg="#2d2d2d", card_border="#3d3d3d",
        glass_accent="#2d2d2d", glass_shimmer="#383838",
        text="#f3f3f3", text_secondary="#d0d0d0",
        # was #8a8a8a — 3.99:1 against card_bg, just under WCAG AA's 4.5:1
        # for normal-size text (this shows up on ~300 widgets: timestamps,
        # secondary labels, etc.)
        text_muted="#9e9e9e", text_dim="#949494",
        sidebar_icon="#c8c8c8", sidebar_icon_hover="#ffffff",
        sidebar_icon_active="#ffffff", sidebar_active_bg="#0078d4",
        # Mode-invariant like sidebar_icon/sidebar_icon_hover — the
        # sidebar itself stays dark in both themes, so its own "dim
        # chrome text" (footer hint, version label, dimmed nav items)
        # needs one fixed color that's readable against sidebar_bg in
        # either mode, not the general (mode-swinging) text_dim.
        # #929292 is the least-bright gray that still clears 4.5:1
        # against both sidebar_bg shades (#252525 dark / #2b2b2b light).
        sidebar_active_bar="#0078d4", sidebar_section_text="#929292",
        # Mode-invariant for the same reason as sidebar_icon_hover above —
        # the hover tint on a nav row must stay a dark tone in both themes
        # since the sidebar itself never lightens. Reusing surface_light
        # here used to pick up light mode's near-white #f9f9f9, which paired
        # with sidebar_icon_hover's white text made hovered labels unreadable.
        sidebar_hover_bg="#333333", sidebar_dim_hover_bg="#161616",
        console_cmd="#9cdcfe", console_info="#d4d4d4",
        console_success="#57a300", console_error="#f14c4c",
        console_timestamp="#608b4e", console_output="#f3f3f3",
        # #363636, not #383838 — that's surface_light/glass_shimmer's dark
        # value too, and a live theme switch (Theme.retheme()) can only
        # map one old->new pair per source color. Every default-styled
        # button (t.style_button(), used app-wide) was colliding with
        # surface_light's remap and landing on light mode's near-white
        # #f9f9f9 instead of its own #e0e0e0 — invisible against a white
        # card until the button was hovered (whose handler reads the
        # theme live, correcting it). One unit darker is imperceptible.
        _button_default_bg="#363636", _button_default_hover="#4a4a4a",
        _button_ghost_bg_ref="bg",   # resolved at runtime
        _treeview_sel="#094771",
    )

    _LIGHT = dict(
        bg="#f3f3f3", panel_bg="#f3f3f3", sidebar_bg="#2b2b2b",
        surface="#ffffff", surface_dark="#e5e5e5", surface_light="#f9f9f9",
        card_bg="#ffffff", card_border="#d8d8d8",
        glass_accent="#ffffff", glass_shimmer="#f0f0f0",
        text="#1a1a1a", text_secondary="#3d3d3d",
        # was #6e6e6e — 4.05:1 against surface_dark, just under 4.5:1
        text_muted="#666666", text_dim="#666666",
        sidebar_icon="#c8c8c8", sidebar_icon_hover="#ffffff",
        sidebar_icon_active="#ffffff", sidebar_active_bg="#0078d4",
        sidebar_active_bar="#0078d4", sidebar_section_text="#929292",
        sidebar_hover_bg="#333333", sidebar_dim_hover_bg="#161616",
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
        self.sidebar_hover_bg     = palette["sidebar_hover_bg"]
        self.sidebar_dim_hover_bg = palette["sidebar_dim_hover_bg"]

        # ── Internal button palette refs ──────────────────────────────
        self._btn_def_bg    = palette["_button_default_bg"]
        self._btn_def_hover = palette["_button_default_hover"]
        self._treeview_sel  = palette["_treeview_sel"]

        # ── Accent / brand ────────────────────────────────────────────
        self.blue        = "#0078d4"   # Microsoft Fluent blue
        self.blue_bright = "#1a8cf3"   # hover / lighter blue
        # blue_bright itself is a mode-constant (used as a hover glow /
        # icon accent, where that's fine), but as small NORMAL-text on a
        # surface it fails WCAG AA in one mode or the other depending on
        # which surface it's testing against (e.g. Config's "Test
        # Connection" / "+ Add..." buttons) — 4.5:1 needs a genuinely
        # different value per mode, same as the rest of the text palette.
        self.link_text = "#4fa6f5" if self.mode == "dark" else "#0a6fca"
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

        # #57a301, not #57a300 — that's console_success/status_running's
        # dark-mode value too, and unlike those two this one doesn't
        # change between modes. A live retheme's remap can only carry one
        # target per source color, and status_running's (correctly) wins
        # the shared "#57a300" — which meant a widget colored with
        # glow_green specifically (the status-dot glow ring in main.py's
        # status bar) got incorrectly dragged to light mode's "#107c10"
        # instead of staying put. One unit off is imperceptible; found via
        # tests/test_theme.py's per-attribute retheme check.
        self.glow_green = "#57a301"
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

    def snapshot(self):
        """{attr: hex_str} for every color attribute currently set."""
        return {k: v for k, v in vars(self).items()
                if isinstance(v, str) and _HEX_RE.match(v)}

    def retheme(self, mode):
        """Re-run __init__ on this SAME instance for a new mode, in place.
        Every tab stashed `self.theme = controller.theme` at construction
        (a reference to this one shared object, not a copy) and every
        hover-lambda closes over that same reference and re-reads colors
        off it on each call — so mutating this instance in place means
        the whole app picks up the new palette immediately, without
        hunting down and reassigning `self.theme` on ~90 tab objects.
        Returns {old_hex: new_hex} for recolor_widget_tree() to apply to
        widgets that already baked the old colors in as literal strings."""
        before = self.snapshot()
        self.__init__(mode=mode)
        after = self.snapshot()
        remap = {}
        # Foundational attributes (bg/surface/text/.... assigned early in
        # __init__) should win over later internal helpers (_btn_def_bg
        # etc.) on the rare occasion two attributes share an old hex value
        # but diverge in the new one — iterate in reverse assignment
        # order so the foundational ones are written last.
        for k in reversed(list(before)):
            old_v = before[k]
            new_v = after.get(k)
            if new_v and new_v != old_v:
                remap[old_v] = new_v
        return remap

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

    def refresh_custom_styles(self, root, remap):
        """Replay every custom-named ttk style call captured by the
        ttk.Style.configure()/.map() wrapper above, substituting any color
        that changed value in this retheme via `remap` (the same dict
        recolor_widget_tree() uses). Covers the ~44 tab modules' own
        "Foo.TNotebook.Tab" / "Foo.Treeview" styles that apply_ttk_styles()
        doesn't know the names of, so they stop being stuck in the old
        theme's colors until the next full restart."""
        s = ttk.Style(root)
        for style_name, calls in _style_calls.items():
            if style_name in _GENERIC_STYLE_NAMES:
                continue
            for method, kw in calls:
                new_kw = {opt: _remap_style_value(val, remap) for opt, val in kw.items()}
                if new_kw != kw:
                    getattr(s, method)(style_name, **new_kw)

    # ── Button styling ────────────────────────────────────────────────
    def style_button(self, btn, variant="default"):
        """
        Office-style flat button with crisp hover transition.
        default  — subtle surface button (like Office secondary)
        primary  — solid blue (like Office primary action)
        danger   — red for destructive actions
        ghost    — text-only, no background
        """
        # Colors are resolved through this closure instead of being
        # unpacked into plain local variables once, so the <Enter>/<Leave>
        # handlers below re-read the CURRENT theme (self.xxx) on every
        # hover rather than the palette that was active when the button
        # was first built — otherwise a live theme switch (see
        # Theme.retheme()) would get silently undone the next time the
        # user's mouse touches any button, snapping it back to the old
        # mode's colors.
        def _colors():
            configs = {
                "default": (self._btn_def_bg,  self.text,           self._btn_def_hover, "#ffffff" if self.mode == "dark" else self.text),
                "primary": (self.blue,          "#ffffff",           self.blue_bright,    "#ffffff"),
                "danger":  ("#c42b1c",          "#ffffff",           "#d13438",           "#ffffff"),
                "ghost":   (self.bg,            self.text_secondary, self.surface_light,  self.text),
            }
            return configs.get(variant, configs["default"])

        bg, fg, hover_bg, hover_fg = _colors()
        btn.configure(
            bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=hover_fg,
            bd=0, relief="flat",
            font=self.font_regular,
            padx=14, pady=5,
            cursor="hand2",
        )

        def _on_enter(_e):
            _, _, hb, hf = _colors()
            btn.configure(bg=hb, fg=hf)

        def _on_leave(_e):
            b, f, _, _ = _colors()
            btn.configure(bg=b, fg=f)

        btn.bind("<Enter>", _on_enter)
        btn.bind("<Leave>", _on_leave)

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
