# core/forecasting.py
"""
Hand-rolled ordinary-least-squares slope for "days until disk full"
forecasting over core.metrics_store's collected history. No numpy/scipy
dependency -- neither is in requirements.txt, and the fit only ever needs
a few dozen points, so a plain-Python least-squares is plenty.
"""

import time


def _linreg_slope_intercept(xs, ys):
    """OLS slope/intercept for y = slope*x + intercept.
    Returns (slope, intercept), or None if there are fewer than 2 points
    or all x values are identical (a degenerate/vertical fit)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx == 0:
        return None
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    return slope, mean_y - slope * mean_x


def days_to_full(metrics_store, server_id: str, lookback_days: int = 14,
                  min_points: int = 5):
    """
    Fits a line to root-filesystem disk-% history over the last
    `lookback_days` (capped by metrics_store's own 30-day retention, see
    prune_old()) and projects forward to 100%.

    Returns days-from-now as a float, or None if there's not enough
    history (fewer than `min_points` samples), the trend is flat or
    shrinking (nothing to forecast), or the fit is degenerate. Returns
    0.0 if disk usage is already at or above 100%.
    """
    since_ts = int(time.time()) - lookback_days * 86400
    rows = [r for r in metrics_store.query_metrics(server_id, limit=100000, since_ts=since_ts)
            if r.get("disk") is not None]
    if len(rows) < min_points:
        return None

    t0 = rows[0]["ts"]
    xs = [(r["ts"] - t0) / 86400.0 for r in rows]
    ys = [r["disk"] for r in rows]

    fit = _linreg_slope_intercept(xs, ys)
    if fit is None:
        return None
    slope, intercept = fit
    if slope <= 0:
        return None   # flat or shrinking -- nothing to forecast

    current = ys[-1]
    if current >= 100:
        return 0.0

    days_from_t0 = (100 - intercept) / slope
    return max(0.0, days_from_t0 - xs[-1])
