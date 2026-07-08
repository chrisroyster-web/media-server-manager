def test_status_bar_is_mapped_and_visible(app):
    """A ttk.Notebook packed with fill="both", expand=True (holding all
    ~60 tab pages) triggered a Tk geometry quirk on Windows where a
    sibling built later in __init__ — the status bar — computed a
    correct position/size but never actually mapped: winfo_ismapped()/
    winfo_viewable() stayed false forever, so it was invisible despite
    "existing". Switching the notebook to place() instead of pack()
    fixed it; this guards against that regressing."""
    assert app._status_lbl.winfo_ismapped()
    assert app._status_lbl.winfo_viewable()


def test_tab_strip_has_no_clickable_area(app):
    """The notebook's native tab strip is fully hidden via an empty ttk
    style layout (Hidden.TNotebook.Tab), not just clipped out of view —
    verifies there's nothing left to accidentally click along the top
    edge of the content area."""
    w = app.tabs.winfo_width()
    h_probe_range = (0, 2, 4)
    hits = 0
    for x in (5, max(w // 2, 6), max(w - 5, 6)):
        for y in h_probe_range:
            elem = app.tabs.identify(x, y)
            if "tab" in elem.lower():
                hits += 1
    assert hits == 0


def test_toast_positions_relative_to_app_window_not_screen(app):
    """show_toast() used to position notifications using
    winfo_screenwidth()/winfo_screenheight() — the full physical
    monitor — instead of the app's own window bounds. On a large or
    multi-monitor desktop, a screen-corner toast could land far from a
    smaller/off-to-one-side app window and go unnoticed."""
    app.show_toast("Test", "positioning check", duration_ms=100)
    app.update()

    import tkinter as tk
    toplevels = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    assert toplevels, "show_toast() should have created a Toplevel"
    toast = toplevels[-1]

    ax, ay = app.winfo_rootx(), app.winfo_rooty()
    aw, ah = app.winfo_width(), app.winfo_height()
    tx, ty = toast.winfo_rootx(), toast.winfo_rooty()

    assert ax <= tx <= ax + aw
    assert ay <= ty <= ay + ah

    try:
        toast.destroy()
    except Exception:
        pass
