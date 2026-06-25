# core/tray_manager.py
"""
System tray icon using pystray.
Runs in a background thread; communicates back to the Tk main thread
via the controller's .after() method.

Install dependency:  pip install pystray pillow
"""

import threading


def _make_icon_image():
    """Generate a simple 64x64 tray icon using Pillow."""
    try:
        from PIL import Image, ImageDraw
        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Dark background circle
        draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 30, 40, 255))
        # Blue monitor outline
        draw.rounded_rectangle([10, 14, 54, 44], radius=4,
                                outline=(76, 158, 245, 255), width=3)
        # Screen glow
        draw.rounded_rectangle([14, 17, 50, 41], radius=2,
                                fill=(20, 40, 80, 200))
        # Stand
        draw.rectangle([28, 44, 36, 52], fill=(76, 158, 245, 255))
        draw.rectangle([22, 51, 42, 54], fill=(76, 158, 245, 255))
        return img
    except ImportError:
        return None


class TrayManager:
    """
    Wraps pystray to provide a system-tray icon.
    Call start() after the Tk window is shown.
    Call stop() on app quit.
    """

    def __init__(self, controller):
        self.controller = controller
        self._icon      = None
        self._thread    = None

    def start(self):
        try:
            import pystray
        except ImportError:
            return   # pystray not installed — tray silently disabled

        img = _make_icon_image()
        if img is None:
            return   # Pillow not installed

        import pystray

        def _open(_icon=None, _item=None):
            self.controller.after(0, self._restore)

        def _connect(_icon=None, _item=None):
            self.controller.after(0, self._tray_connect)

        def _refresh(_icon=None, _item=None):
            self.controller.after(0, self._tray_refresh)

        def _quit(_icon=None, _item=None):
            self.controller.after(0, self._tray_quit)

        menu = pystray.Menu(
            pystray.MenuItem("Open",    _open,    default=True),
            pystray.MenuItem("Connect", _connect),
            pystray.MenuItem("Refresh", _refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",    _quit),
        )

        self._icon = pystray.Icon(
            "AllClear",
            img,
            "All Clear Server Services",
            menu,
        )

        self._thread = threading.Thread(
            target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def notify(self, title, message):
        """Show a tray balloon/notification (platform-dependent)."""
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Callbacks (run on main Tk thread via .after(0, ...))
    # ------------------------------------------------------------------
    def _restore(self):
        try:
            self.controller.deiconify()
            self.controller.lift()
            self.controller.focus_force()
        except Exception:
            pass

    def _tray_connect(self):
        try:
            self._restore()
            self.controller.tabs.select(0)   # Connection tab
        except Exception:
            pass

    def _tray_refresh(self):
        try:
            self.controller.dashboard_tab.refresh()
        except Exception:
            pass

    def _tray_quit(self):
        try:
            self.stop()
            self.controller.destroy()
        except Exception:
            pass
