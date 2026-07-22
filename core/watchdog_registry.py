# core/watchdog_registry.py
"""
Tracks liveness for main.py's background watchdog threads.

Every watchdog's per-cycle body already either completes cleanly or hits a
`continue` for a benign reason (not connected, not due yet, ...) -- neither
of those should count as a "check". record_ok()/record_error() are only
meant to be called by the try/except wrapper in each start_X_watchdog()'s
_loop(), which only reaches them when a cycle actually ran past its early
guards. Without this, a watchdog whose check logic starts raising every
cycle (a parsing regression, a changed CLI output format, ...) goes quiet
forever with no trace anywhere in the app.
"""

import threading
import time


class WatchdogRegistry:
    def __init__(self):
        self._lock  = threading.Lock()
        self._state = {}

    def register(self, name, interval_s):
        with self._lock:
            self._state[name] = {
                "interval_s": interval_s,
                "started_at": time.time(),
                "last_run":   None,
                "last_error": None,
                "checks":     0,
                "errors":     0,
            }

    def record_ok(self, name):
        with self._lock:
            entry = self._state.setdefault(name, {"interval_s": 0, "started_at": time.time()})
            entry["last_run"]   = time.time()
            entry["last_error"] = None
            entry["checks"]     = entry.get("checks", 0) + 1

    def record_error(self, name, err):
        with self._lock:
            entry = self._state.setdefault(name, {"interval_s": 0, "started_at": time.time()})
            entry["last_run"]   = time.time()
            entry["last_error"] = str(err)
            entry["errors"]     = entry.get("errors", 0) + 1

    def snapshot(self):
        """Returns a deep-enough copy for the UI thread to read safely."""
        with self._lock:
            return {name: dict(v) for name, v in self._state.items()}
