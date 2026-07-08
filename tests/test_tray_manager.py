import sys
from unittest.mock import MagicMock, patch

from core.tray_manager import TrayManager, _make_icon_image


class _FakeController:
    def __init__(self):
        self.after_calls = []
        self.deiconify = MagicMock()
        self.lift = MagicMock()
        self.focus_force = MagicMock()
        self.destroy = MagicMock()
        self.tabs = MagicMock()
        self.dashboard_tab = MagicMock()

    def after(self, delay, fn):
        self.after_calls.append(fn)
        fn()  # run immediately — tests don't need real Tk scheduling


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------

def test_start_falls_back_to_deiconify_when_pystray_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    controller = _FakeController()
    tm = TrayManager(controller)
    tm.start()

    assert tm._icon is None
    controller.deiconify.assert_called_once()


def test_start_falls_back_to_deiconify_when_icon_image_cannot_be_built(monkeypatch):
    controller = _FakeController()
    tm = TrayManager(controller)
    fake_pystray = MagicMock()
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    with patch("core.tray_manager._make_icon_image", return_value=None):
        tm.start()

    assert tm._icon is None
    controller.deiconify.assert_called_once()


def test_start_creates_icon_and_starts_a_thread(monkeypatch):
    controller = _FakeController()
    tm = TrayManager(controller)

    fake_pystray = MagicMock()
    fake_icon_instance = MagicMock()
    fake_pystray.Icon.return_value = fake_icon_instance
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)

    fake_thread = MagicMock()
    with patch("core.tray_manager._make_icon_image", return_value=MagicMock()), \
         patch("core.tray_manager.threading.Thread", return_value=fake_thread) as thread_cls:
        tm.start()

    assert tm._icon is fake_icon_instance
    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["daemon"] is True
    fake_thread.start.assert_called_once()
    controller.deiconify.assert_not_called()  # only the fallback path calls this directly


# ---------------------------------------------------------------------------
# stop() / notify()
# ---------------------------------------------------------------------------

def test_stop_is_a_no_op_without_an_icon():
    tm = TrayManager(_FakeController())
    tm.stop()  # must not raise


def test_stop_calls_icon_stop():
    tm = TrayManager(_FakeController())
    tm._icon = MagicMock()
    tm.stop()
    tm._icon.stop.assert_called_once()


def test_stop_swallows_exceptions():
    tm = TrayManager(_FakeController())
    tm._icon = MagicMock()
    tm._icon.stop.side_effect = RuntimeError("boom")
    tm.stop()  # must not raise


def test_notify_is_a_no_op_without_an_icon():
    tm = TrayManager(_FakeController())
    tm.notify("Title", "Message")  # must not raise


def test_notify_calls_icon_notify_with_message_then_title():
    tm = TrayManager(_FakeController())
    tm._icon = MagicMock()
    tm.notify("Title", "Message")
    tm._icon.notify.assert_called_once_with("Message", "Title")


def test_notify_swallows_exceptions():
    tm = TrayManager(_FakeController())
    tm._icon = MagicMock()
    tm._icon.notify.side_effect = RuntimeError("boom")
    tm.notify("Title", "Message")  # must not raise


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def test_restore_calls_deiconify_lift_and_focus():
    controller = _FakeController()
    tm = TrayManager(controller)
    tm._restore()
    controller.deiconify.assert_called_once()
    controller.lift.assert_called_once()
    controller.focus_force.assert_called_once()


def test_restore_swallows_exceptions():
    controller = _FakeController()
    controller.deiconify.side_effect = RuntimeError("boom")
    tm = TrayManager(controller)
    tm._restore()  # must not raise


def test_tray_connect_restores_and_selects_connection_tab():
    controller = _FakeController()
    tm = TrayManager(controller)
    tm._tray_connect()
    controller.deiconify.assert_called_once()
    controller.tabs.select.assert_called_once_with(0)


def test_tray_connect_swallows_exceptions():
    controller = _FakeController()
    controller.tabs.select.side_effect = RuntimeError("boom")
    tm = TrayManager(controller)
    tm._tray_connect()  # must not raise


def test_tray_refresh_calls_dashboard_refresh():
    controller = _FakeController()
    tm = TrayManager(controller)
    tm._tray_refresh()
    controller.dashboard_tab.refresh.assert_called_once()


def test_tray_refresh_swallows_exceptions():
    controller = _FakeController()
    controller.dashboard_tab.refresh.side_effect = RuntimeError("boom")
    tm = TrayManager(controller)
    tm._tray_refresh()  # must not raise


def test_tray_quit_stops_icon_destroys_controller_and_exits_process():
    """_tray_quit() ends with an unconditional os._exit(0) — os._exit must
    be mocked here, or this test would actually terminate the test run."""
    controller = _FakeController()
    tm = TrayManager(controller)
    tm._icon = MagicMock()

    with patch("os._exit") as fake_exit:
        tm._tray_quit()

    tm._icon.stop.assert_called_once()
    controller.destroy.assert_called_once()
    fake_exit.assert_called_once_with(0)


def test_tray_quit_still_exits_process_even_if_stop_or_destroy_raise():
    controller = _FakeController()
    controller.destroy.side_effect = RuntimeError("boom")
    tm = TrayManager(controller)

    with patch("os._exit") as fake_exit:
        tm._tray_quit()

    fake_exit.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# _make_icon_image()
# ---------------------------------------------------------------------------

def test_make_icon_image_returns_an_image_when_pil_available():
    image = _make_icon_image()
    assert image is not None


def test_make_icon_image_returns_none_when_pil_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", None)
    assert _make_icon_image() is None
