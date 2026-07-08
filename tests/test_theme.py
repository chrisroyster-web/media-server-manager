import tkinter as tk

from ui.theme import Theme, recolor_widget_tree


def test_every_theme_attribute_survives_live_retheme(app):
    """A dark-mode hex value shared by two palette attributes that map to
    *different* light-mode values means recolor_widget_tree() can only
    correctly restore one of them after a live toggle — the other lands
    on whichever attribute's target color wins the (documented, priority-
    ordered) collision. This bit _button_default_bg once (it shared
    "#383838" with surface_light/glass_shimmer, lost the priority
    ordering, and ended up on surface_light's near-white target instead
    of its own — every default-styled button went briefly invisible
    after a light-mode toggle). Rather than just flagging any collision,
    build a real widget per attribute and check each one lands on *that
    attribute's own* post-toggle value — the thing that actually
    matters. glass_shimmer is excluded: it has no call sites anywhere in
    the codebase, so nothing ever shows its color, wrong or otherwise.

    Parented under the shared `app` window rather than a fresh tk.Tk() —
    a second independent Tk root in the same process turned out to be
    order-dependent-flaky depending on what ran before it in the suite."""
    root = tk.Frame(app)
    try:
        theme = Theme(mode="dark")
        before = theme.snapshot()

        widgets = {}
        for attr, value in before.items():
            if attr == "glass_shimmer":
                continue
            w = tk.Frame(root, bg=value)
            widgets[attr] = w

        remap = theme.retheme("light")
        recolor_widget_tree(root, remap)

        wrong = [
            (attr, widgets[attr].cget("bg"), getattr(theme, attr))
            for attr in widgets
            if widgets[attr].cget("bg") != getattr(theme, attr)
        ]
        assert not wrong, "\n".join(
            f"{attr}: widget shows {got!r}, theme.{attr} is now {want!r}"
            for attr, got, want in wrong)
    finally:
        root.destroy()


def test_button_default_bg_survives_live_retheme(app):
    root = tk.Frame(app)
    try:
        theme = Theme(mode="dark")
        btn = tk.Button(root, text="Full Health Check")
        theme.style_button(btn)
        assert btn.cget("bg") == theme._btn_def_bg

        remap = theme.retheme("light")
        recolor_widget_tree(root, remap)

        assert btn.cget("bg") == theme._btn_def_bg
    finally:
        root.destroy()


def test_text_tag_colors_update_on_live_retheme(app):
    """Text widget tag_config() colors (console/log output across ~40
    tabs) live on the tag, not a widget option — recolor_widget_tree()'s
    generic .cget() walk never saw them until it grew explicit Text/tag
    handling. Without it, tagged text keeps its original mode's color
    after a toggle (e.g. dark mode's near-white on light mode's near-
    white background), making command output look like it never ran."""
    root = tk.Frame(app)
    try:
        theme = Theme(mode="dark")
        text = tk.Text(root, bg=theme.surface_dark, fg=theme.text)
        text.tag_config("output", foreground=theme.console_output)
        text.insert("end", "some command output\n", "output")

        remap = theme.retheme("light")
        recolor_widget_tree(root, remap)

        assert text.cget("bg") == theme.surface_dark
        assert text.tag_cget("output", "foreground") == theme.console_output
    finally:
        root.destroy()
