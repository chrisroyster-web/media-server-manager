# core/remediation_tracker.py
"""
Tracks per-target auto-remediation attempts (service restarts, container
restarts) so main.py's watchdogs can rate-limit themselves independently
of WatchdogRegistry, which only tracks per-watchdog (not per-target)
liveness. A "target" is a stable string key like "service:sonarr" or
"docker:radarr".

The safety property this exists for: a watchdog's edge-trigger (only
firing on a running->stopped transition) already means a *steady* down
state doesn't retrigger every check cycle -- only genuine flapping
(running->stopped->running->stopped...) does. This tracker is what turns
that flapping into a bounded number of restart attempts followed by a
cooldown, instead of an unbounded restart loop.
"""

import threading
import time

MAX_ATTEMPTS = 3        # per target, per rolling window
WINDOW_S     = 1800     # 30 min rolling window
BACKOFF_S    = 3600     # 1 hour cooldown once MAX_ATTEMPTS is hit


class RemediationTracker:

    def __init__(self, max_attempts=MAX_ATTEMPTS, window_s=WINDOW_S,
                 backoff_s=BACKOFF_S, clock=time.time):
        self._lock = threading.Lock()
        self._state = {}   # target -> {"attempts": [ts, ...], "backoff_until": 0}
        self.max_attempts = max_attempts
        self.window_s = window_s
        self.backoff_s = backoff_s
        self._clock = clock   # injectable for tests

    def should_attempt(self, target) -> bool:
        """True if `target` hasn't exceeded max_attempts within the rolling
        window and isn't currently in a post-limit backoff period."""
        with self._lock:
            now = self._clock()
            entry = self._state.setdefault(target, {"attempts": [], "backoff_until": 0})
            if now < entry["backoff_until"]:
                return False
            entry["attempts"] = [t for t in entry["attempts"] if now - t < self.window_s]
            return len(entry["attempts"]) < self.max_attempts

    def record_attempt(self, target):
        """Record that a remediation attempt was just made for `target`.
        Enters backoff once this attempt pushes the window over the limit."""
        with self._lock:
            now = self._clock()
            entry = self._state.setdefault(target, {"attempts": [], "backoff_until": 0})
            entry["attempts"].append(now)
            entry["attempts"] = [t for t in entry["attempts"] if now - t < self.window_s]
            if len(entry["attempts"]) >= self.max_attempts:
                entry["backoff_until"] = now + self.backoff_s

    def last_info(self, target):
        """Snapshot of a single target's state, or None if never attempted."""
        with self._lock:
            entry = self._state.get(target)
            if not entry:
                return None
            now = self._clock()
            return {
                "attempts_in_window": len(entry["attempts"]),
                "last_attempt": entry["attempts"][-1] if entry["attempts"] else None,
                "backing_off": now < entry["backoff_until"],
                "backoff_until": entry["backoff_until"],
            }

    def snapshot(self):
        """{target: {...}} for every target with any recorded state, for
        display in ui/watchdog_tab.py."""
        with self._lock:
            return {k: dict(v, attempts=list(v["attempts"])) for k, v in self._state.items()}

    def reset(self):
        """Clear all tracked state -- called on server switch/disconnect so
        counters from one connection don't leak into the next."""
        with self._lock:
            self._state.clear()
