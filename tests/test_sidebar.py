import random
import time


def _collapse_all(app):
    sb = app.sidebar
    for section in list(sb._section_bodies.keys()):
        if not app.config_manager.sidebar_section_collapsed.get(section, False):
            sb._toggle_section(section)
    deadline = time.monotonic() + 2.0
    while sb._section_animating and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    app.update()


def test_sidebar_scroll_does_not_drift_when_content_fits_viewport(app):
    """A fast physical scroll wheel delivers many wheel events in one
    burst, faster than Tk can settle canvas geometry between them.
    Calling yview_scroll() once per event (even with a post-hoc
    correction) let the embedded nav_frame window's actual on-screen
    position desync from what yview()/bbox() reported — verified live:
    after such a burst yview() still read (0.0, 1.0) throughout, yet the
    sidebar's content had visibly drifted anywhere from -600px to +550px
    off the top, persisting through further scrolling. Reproduces that
    burst synthetically and checks the real drift (winfo_rooty(), not
    yview()) rather than the misleading signal."""
    sb = app.sidebar
    canvas = sb._nav_canvas
    _collapse_all(app)

    bbox = canvas.bbox("all")
    assert bbox[3] - bbox[1] <= canvas.winfo_height(), (
        "test setup assumption violated: content should fit within the "
        "viewport with every section collapsed")

    core_lbl = sb._section_labels["CORE"]
    random.seed(42)
    for _ in range(150):
        delta = 120 if random.random() < 0.5 else -120
        core_lbl.event_generate("<MouseWheel>", delta=delta, when="tail")
    app.update()

    assert sb._server_section_frame.winfo_rooty() == canvas.winfo_rooty()


def test_sidebar_scroll_still_works_with_real_overflow(app):
    """The fix for the above must not turn scrolling into a no-op when
    there's genuine overflow content — only skip it when there's nothing
    to scroll."""
    sb = app.sidebar
    canvas = sb._nav_canvas
    try:
        for section in ("CORE", "MEDIA", "REQUESTS", "MONITORING"):
            if app.config_manager.sidebar_section_collapsed.get(section):
                sb._toggle_section(section)
        deadline = time.monotonic() + 2.0
        while sb._section_animating and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)
        app.geometry("1516x600+40+40")
        app.update()

        bbox = canvas.bbox("all")
        assert bbox[3] - bbox[1] > canvas.winfo_height(), (
            "test setup assumption violated: content should overflow "
            "the shrunk viewport")

        before = canvas.yview()
        for _ in range(5):
            class _Evt:
                delta = -120
            sb._on_mousewheel(_Evt())
        app.update()
        after = canvas.yview()
        assert after[0] > before[0], "scrolling down should move the view"
    finally:
        app.geometry("1516x1039+40+40")
        _collapse_all(app)


def test_section_toggle_completes_quickly(app):
    """A stacking-order (canvas.lower()/.lift()) "repaint fix" added
    earlier turned out to add ~750ms of latency per section toggle (and
    could hang outright under repeated use) without actually fixing
    anything — the real bug was the scroll-drift race above. Guards
    against that (or anything similarly expensive) creeping back into
    the toggle path."""
    sb = app.sidebar
    section = "INFRA"
    if app.config_manager.sidebar_section_collapsed.get(section):
        sb._toggle_section(section)
        deadline = time.monotonic() + 2.0
        while sb._section_animating and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)

    t0 = time.perf_counter()
    sb._toggle_section(section)
    deadline = time.monotonic() + 2.0
    while sb._section_animating and time.monotonic() < deadline:
        app.update()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 400, (
        f"section toggle took {elapsed_ms:.0f}ms, expected well under "
        f"{sb.ANIM_STEPS * sb.ANIM_MS}ms nominal animation time"
    )
