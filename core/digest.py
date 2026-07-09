# core/digest.py
"""
Assembles the daily notification digest: backup status, a disk/CPU/RAM
snapshot (with a same-time-yesterday comparison when history exists), and
alerts fired in the last 24h. Sent via NotificationManager.send_alert() from
main.py's start_daily_digest_watchdog().
"""

import time

from core.backup_status import check_backup_jobs

_DAY_SECONDS = 86400


def build_digest(ssh, metrics_store, server_id: str) -> str:
    sections = [
        _backup_section(ssh),
        _metrics_section(metrics_store, server_id),
        _alerts_section(metrics_store, server_id),
    ]
    return "\n\n".join(sections)


def _backup_section(ssh) -> str:
    jobs = check_backup_jobs(ssh)
    if not jobs:
        return "Backups: no backup tools detected."

    ok   = sum(1 for j in jobs if j["status"] == "ok")
    warn = sum(1 for j in jobs if j["status"] == "warn")
    fail = sum(1 for j in jobs if j["status"] == "fail")

    line = "Backups: {} ok, {} warn, {} fail".format(ok, warn, fail)
    failing = [j for j in jobs if j["status"] in ("warn", "fail")]
    if failing:
        line += "\n  " + "\n  ".join(
            "{} ({}): {}".format(j["name"], j["tool"], j["status"]) for j in failing)
    return line


def _metrics_section(metrics_store, server_id: str) -> str:
    current = metrics_store.get_last_metric(server_id)
    if not current:
        return "Metrics: no data collected yet."

    prior = metrics_store.get_metric_near(server_id, int(time.time()) - _DAY_SECONDS)
    # A "prior" point within a few minutes of *now* isn't a real day-over-day
    # comparison — it just means there's under 24h of history yet.
    if prior and abs(prior["ts"] - current["ts"]) < 3600:
        prior = None

    parts = []
    for key, label, unit in (("cpu", "CPU", "%"), ("ram", "RAM", "%"), ("disk", "Disk", "%")):
        value = current.get(key)
        if value is None:
            continue
        text = "{}: {:.0f}{}".format(label, value, unit)
        if prior and prior.get(key) is not None:
            delta = value - prior[key]
            if abs(delta) >= 1:
                text += " ({}{:.0f}{} vs. yesterday)".format(
                    "+" if delta > 0 else "", delta, unit)
        parts.append(text)

    return "Metrics: " + ", ".join(parts) if parts else "Metrics: no data collected yet."


def _alerts_section(metrics_store, server_id: str) -> str:
    since_ts = int(time.time()) - _DAY_SECONDS
    rows = metrics_store.get_notifications(server_id=server_id)
    recent = [r for r in rows if r["ts"] >= since_ts and r["level"] in ("warn", "error")]
    if not recent:
        return "Alerts (last 24h): none."

    seen = []
    for r in recent:
        if r["title"] not in seen:
            seen.append(r["title"])
    return "Alerts (last 24h): {} fired\n  ".format(len(recent)) + "\n  ".join(seen)
