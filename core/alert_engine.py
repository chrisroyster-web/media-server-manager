# core/alert_engine.py
"""
Stateful alert rule evaluator.
Call evaluate(metrics) on each dashboard refresh to get rules that fired.
Tracks breach start times (for duration-based alerts) and last-fired times
(for cooldown) entirely in memory — no DB writes.
"""

import time

_OPS = {
    ">=": lambda a, b: a >= b,
    ">":  lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<":  lambda a, b: a < b,
    "=":  lambda a, b: a == b,
}

METRIC_META = {
    "cpu":     ("CPU",         "%"),
    "ram":     ("RAM",         "%"),
    "disk":    ("Disk",        "%"),
    "temp":    ("CPU Temp",    "°C"),
    "rx_mbps": ("Network In",  " MB/s"),
    "tx_mbps": ("Network Out", " MB/s"),
}


class AlertEngine:
    """
    Evaluates alert rules against current metric values.

    State per rule ID:
      _breach_start[rid]  — time.time() when the condition first became true
      _last_fired[rid]    — time.time() when the last notification was sent

    A rule fires when:
      1. condition_met AND
      2. breach has lasted >= duration_minutes AND
      3. at least cooldown_minutes have passed since last fire
    """

    def __init__(self, config_manager):
        self.cfg = config_manager
        self._breach_start: dict = {}
        self._last_fired:   dict = {}

    def evaluate(self, metrics: dict) -> list:
        """
        metrics: dict with keys matching METRIC_META (cpu, ram, disk, temp, …)
        Returns list of (rule_dict, current_value) for rules that fired this cycle.
        """
        now   = time.time()
        fired = []

        for rule in self.cfg.get_alert_rules():
            if not rule.get("enabled", True):
                continue

            rid       = rule.get("id") or rule.get("name", "")
            metric    = rule.get("metric", "cpu")
            value     = metrics.get(metric)

            if value is None:
                self._breach_start.pop(rid, None)
                continue

            op_fn     = _OPS.get(rule.get("operator", ">="))
            threshold = float(rule.get("threshold", 80))

            if op_fn is None or not op_fn(float(value), threshold):
                # Condition cleared — reset breach timer so duration clock restarts next time
                self._breach_start.pop(rid, None)
                continue

            # Condition is met — start the breach clock if this is the first breach tick
            if rid not in self._breach_start:
                self._breach_start[rid] = now

            duration_sec = float(rule.get("duration_minutes", 0)) * 60
            if now - self._breach_start[rid] < duration_sec:
                continue  # condition true but not sustained long enough yet

            cooldown_sec = float(rule.get("cooldown_minutes", 60)) * 60
            if now - self._last_fired.get(rid, 0) < cooldown_sec:
                continue  # still within the re-fire cooldown window

            # All checks passed — fire this rule
            self._last_fired[rid]   = now
            # Reset breach_start so cooldown applies from fire time forward
            self._breach_start[rid] = now
            fired.append((rule, float(value)))

        return fired

    def reset(self):
        """Clear all state (call when switching servers or on disconnect)."""
        self._breach_start.clear()
        self._last_fired.clear()
