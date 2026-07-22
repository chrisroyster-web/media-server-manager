# core/arr_backup_status.py
"""
Checks Sonarr/Radarr's own scheduled config backups via their REST API
(GET /api/v3/system/backup), so the unified Backup Status tab shows whether
each *arr's built-in backup is current alongside restic/rsync/Hyper Backup.

Uses the same config already wired for ArrTab (host/port/apikey per active
server profile) -- no new settings, no new connection type.
"""

import datetime

from core.arr_client import api_get

_APPS = [
    ("sonarr", "sonarr_host", "sonarr_port", "sonarr_apikey"),
    ("radarr", "radarr_host", "radarr_port", "radarr_apikey"),
]


def check_arr_backup_jobs(config_manager) -> list:
    """
    Returns 0-2 job dicts (one per configured *arr) in the same shape used
    by core/backup_status.py's check_backup_jobs(): {"tool", "name",
    "status", "last_run", "duration", "size", "files", "dest", "log"}.

    An app with no API key configured is skipped entirely (same as a
    genuinely-absent backup tool), but a configured app that fails to
    respond produces a "fail" job -- that's worth surfacing, not hiding.
    """
    jobs = []
    cfg = config_manager

    for tool, host_attr, port_attr, key_attr in _APPS:
        apikey = getattr(cfg, key_attr)
        if not apikey:
            continue
        host = getattr(cfg, host_attr)
        port = getattr(cfg, port_attr)

        try:
            backups = api_get(host, port, apikey, "system/backup")
        except Exception as e:
            jobs.append({
                "tool": tool, "name": "{} config backup".format(tool.capitalize()),
                "status": "fail", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": "{}:{}".format(host, port),
                "log": "Could not reach {}: {}".format(tool, e),
            })
            continue

        scheduled = [b for b in backups if b.get("type") == "scheduled"] or backups
        if not scheduled:
            jobs.append({
                "tool": tool, "name": "{} config backup".format(tool.capitalize()),
                "status": "none", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": "{}:{}".format(host, port),
                "log": "No backups found yet.",
            })
            continue

        latest = max(scheduled, key=lambda b: b.get("time", ""))
        ts = latest.get("time", "")
        try:
            dt = datetime.datetime.fromisoformat(ts[:19])
            age_days = (datetime.datetime.utcnow() - dt).total_seconds() / 86400
            last_run = dt.strftime("%Y-%m-%d %H:%M")
            # *arr's own default backup interval is 7 days, and its exact
            # configured interval isn't exposed via the API -- thresholds are
            # loosened relative to restic/Hyper Backup's 2/7-day ones so a
            # default-interval setup reads "ok" all week instead of "warn".
            status = "ok" if age_days < 8 else ("warn" if age_days < 10 else "fail")
        except (ValueError, TypeError):
            last_run = "--"
            status = "fail"

        jobs.append({
            "tool": tool, "name": "{} config backup".format(tool.capitalize()),
            "status": status, "last_run": last_run, "duration": "--",
            "size": "--", "files": "--",
            "dest": latest.get("path", "--"),
            "log": "type={} name={}".format(
                latest.get("type", "--"), latest.get("name", "--")),
        })

    return jobs
