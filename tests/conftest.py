import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _pump(widget, seconds):
    """Let real time pass while draining Tk's event queue, so .after()
    chains (the splash sequence, section animations, ...) actually fire.
    A plain .update() only processes what's *already* due; the splash
    chain and animations are scheduled several hundred ms out, so without
    letting real wall-clock time pass in between, none of it ever runs.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        widget.update()
        time.sleep(0.01)


@pytest.fixture(scope="session")
def app_session(tmp_path_factory):
    """One real MediaServerManager instance for the whole test session.

    Rebuilding it per-test would mean re-paying the ~3-4s splash sequence
    for every single test; tests are expected to leave shared sidebar/
    theme state the way they found it (see the `app` fixture below,
    which resets the common bits between tests).
    """
    tmp_dir = tmp_path_factory.mktemp("config")

    from core.config_manager import ConfigManager
    # Point at an isolated config.json (and, since metrics_store derives
    # its path from this, an isolated metrics.db too) instead of the
    # real assets/config.json — a real user's server list/credentials
    # have no business being read by the test suite, and a stray section-
    # collapsed state left over from manual testing is exactly what
    # produced a false-positive "bug" earlier in this app's development.
    ConfigManager.CONFIG_PATH = str(tmp_dir / "config.json")
    ConfigManager.save = lambda self: None  # never touch disk after the initial write

    import main as appmod
    appmod.MediaServerManager._auto_connect = lambda self: None
    appmod.MediaServerManager.start_service_watchdog = lambda self: None
    appmod.MediaServerManager.start_sab_toast_watcher = lambda self: None
    appmod.MediaServerManager._check_for_update_bg = lambda self: None

    instance = appmod.MediaServerManager()
    instance.scheduler.start = lambda: None
    instance.geometry("1516x1039+40+40")
    _pump(instance, 4.0)  # let the splash sequence finish and the window map

    # A real user always has at least one server profile; without one,
    # get_active_server() returns None and per-server settings (Config
    # tab's Save & Apply, VPN/proxy toggles, ...) silently fall back to
    # writing into the *global* config dict instead of a server's own
    # settings — not representative of what the app actually does.
    instance.config_manager.upsert_server("test-server.local", username="test")
    instance.sidebar.rebuild_servers(instance.config_manager)

    yield instance

    try:
        instance.destroy()
    except Exception:
        pass


@pytest.fixture
def app(app_session):
    """Per-test handle on the shared app instance.

    Resets the bits individual tests are most likely to perturb (theme
    mode, sidebar section collapse state, active tab) before and after
    each test, so tests can be run in any order without depending on
    what the previous test left behind.
    """
    sb = app_session.sidebar
    if app_session.theme.mode != "dark":
        app_session.toggle_theme()
    for section in list(sb._section_bodies.keys()):
        if not app_session.config_manager.sidebar_section_collapsed.get(section, False):
            sb._toggle_section(section)
    _pump(app_session, 0.5)

    yield app_session

    # best-effort cleanup so the next test starts from the same baseline
    for section in list(sb._section_bodies.keys()):
        if section in sb._section_animating:
            _pump(app_session, 0.3)
