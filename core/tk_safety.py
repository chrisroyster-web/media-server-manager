# core/tk_safety.py
"""
Every tab in this app follows the same pattern: kick off SSH/API work on a
background thread, then call self.after(0, lambda: self._apply(result)) to
marshal the result back onto the Tk thread. If the window gets closed (or
the app is still mid-splash) while one of those background calls is still
in flight, the widget's Tcl interpreter is gone or not yet pumping events by
the time after() actually runs, and Python 3.13+ raises
RuntimeError("main thread is not in main loop") instead of the older
silent/segfault behavior — as an uncaught exception on that daemon thread.

install() patches tkinter.Misc.after once, centrally, instead of adding a
winfo_exists() guard to every self.after(0, ...) call site across ~50 tab
files: if the underlying call raises that RuntimeError, retry briefly
(covers "mainloop hasn't started pumping yet") and give up quietly once the
widget no longer exists (covers "window was closed while work was pending").
"""

import threading
import tkinter

_original_after = tkinter.Misc.after
_installed = False


def _safe_after(self, ms, func=None, *args):
    try:
        return _original_after(self, ms, func, *args)
    except RuntimeError:
        if func is None:
            return None
        try:
            alive = self.winfo_exists()
        except Exception:
            alive = True  # can't ask from this thread either — assume alive, keep retrying
        if not alive:
            return None
        timer = threading.Timer(0.05, _safe_after, args=(self, ms, func) + args)
        timer.daemon = True
        timer.start()
        return None


def install():
    global _installed
    if _installed:
        return
    tkinter.Misc.after = _safe_after
    _installed = True
