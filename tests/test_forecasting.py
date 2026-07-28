import time

from core.forecasting import days_to_full


class _FakeMetricsStore:
    """Minimal stand-in for MetricsStore.query_metrics() -- returns whatever
    rows this test seeded, ignoring server_id/since_ts filtering (tests
    build already-filtered row lists directly)."""

    def __init__(self, rows):
        self._rows = rows

    def query_metrics(self, server_id, limit=30, since_ts=0):
        return [r for r in self._rows if r["ts"] >= since_ts][:limit]


def _rows_over_days(disk_values, start_ts=None):
    """One row per day, oldest first, `disk` set from disk_values."""
    now = start_ts if start_ts is not None else int(time.time())
    base = now - (len(disk_values) - 1) * 86400
    return [{"ts": base + i * 86400, "disk": d} for i, d in enumerate(disk_values)]


def test_returns_none_with_too_few_points():
    store = _FakeMetricsStore(_rows_over_days([50, 52, 54]))
    assert days_to_full(store, "srv", min_points=5) is None


def test_returns_none_for_flat_trend():
    store = _FakeMetricsStore(_rows_over_days([60] * 10))
    assert days_to_full(store, "srv") is None


def test_returns_none_for_declining_trend():
    store = _FakeMetricsStore(_rows_over_days([70, 68, 66, 64, 62, 60]))
    assert days_to_full(store, "srv") is None


def test_returns_zero_when_already_full():
    store = _FakeMetricsStore(_rows_over_days([92, 95, 97, 99, 100]))
    assert days_to_full(store, "srv") == 0.0


def test_clean_linear_growth_matches_hand_computed_value():
    # disk grows by exactly 1%/day for 10 days, starting at 50%.
    # Fit should recover slope=1, intercept=50 (within float tolerance),
    # so days-to-full from the last point (day 9, disk=59) is (100-59)/1 = 41.
    store = _FakeMetricsStore(_rows_over_days([50 + i for i in range(10)]))
    result = days_to_full(store, "srv")
    assert result is not None
    assert abs(result - 41.0) < 0.01


def test_lookback_window_excludes_older_points():
    # 20 days of flat-then-growing data; only the growing tail should be
    # visible once since_ts (derived from lookback_days) excludes the flat
    # part -- if the flat data leaked in, the fit would be pulled toward
    # flat and likely return None instead of a forecast.
    now = int(time.time())
    flat = _rows_over_days([80] * 10, start_ts=now - 15 * 86400)
    growing = _rows_over_days([50 + i for i in range(10)], start_ts=now)
    store = _FakeMetricsStore(flat + growing)
    result = days_to_full(store, "srv", lookback_days=9)
    assert result is not None
