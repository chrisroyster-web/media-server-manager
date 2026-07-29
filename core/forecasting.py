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


def disk_trend(metrics_store, server_id: str, lookback_days: int = 14,
                min_points: int = 5):
    """
    Fits a line to root-filesystem disk-% history over the last
    `lookback_days` (capped by metrics_store's own 30-day retention, see
    prune_old()). Returns the historical points and fit parameters (for
    charting) rather than just the scalar forecast -- see days_to_full()
    for that.

    Returns {"points": [(ts, disk), ...], "slope": float,
    "intercept": float, "t0": int} where disk = slope*(ts-t0)/86400 +
    intercept, or None if there's fewer than `min_points` samples or the
    fit is degenerate.

    Does NOT gate on slope <= 0 -- a flat/declining trend still has valid
    historical points to plot, it just has nothing to project forward.
    Callers decide what that means for their use case.
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
    return {"points": [(r["ts"], r["disk"]) for r in rows],
            "slope": slope, "intercept": intercept, "t0": t0}


def days_to_full(metrics_store, server_id: str, lookback_days: int = 14,
                  min_points: int = 5):
    """
    Projects disk_trend()'s fit forward to 100% full.

    Returns days-from-now as a float, or None if there's not enough
    history (fewer than `min_points` samples), the trend is flat or
    shrinking (nothing to forecast), or the fit is degenerate. Returns
    0.0 if disk usage is already at or above 100%.
    """
    trend = disk_trend(metrics_store, server_id, lookback_days, min_points)
    if trend is None or trend["slope"] <= 0:
        return None   # not enough history, or flat/shrinking -- nothing to forecast

    current = trend["points"][-1][1]
    if current >= 100:
        return 0.0

    last_x = (trend["points"][-1][0] - trend["t0"]) / 86400.0
    days_from_t0 = (100 - trend["intercept"]) / trend["slope"]
    return max(0.0, days_from_t0 - last_x)
