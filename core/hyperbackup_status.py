# core/hyperbackup_status.py
"""
Checks the status of a Synology NAS's Hyper Backup task (specifically the
one backing up the wsbackup share to Synology C2) over its own dedicated
SSH connection -- separate from the media server's SSHManager, since the
NAS is a different host with its own credentials.

Reads Hyper Backup's own on-disk state directly (synobackup.conf for the
task definition, last_result/backup.last for the most recent run outcome).
Both are readable without root on stock DSM, so this needs no sudo/webapi
access -- see the app's own troubleshooting notes on why triggering a run
does need root, which this module deliberately does not attempt.
"""

import re
import time

from core.ssh_manager import SSHManager

_CONF_PATH = "/volume1/@appconf/HyperBackup/synobackup.conf"
_LAST_RESULT_PATH = "/volume1/@appdata/HyperBackup/last_result/backup.last"


def _split_sections(text):
    """'[name]\\nkey=val\\n...' blocks -> {name: body_text}."""
    sections = {}
    current = None
    body = []
    for line in text.splitlines():
        m = re.match(r'^\[(\w+)\]\s*$', line)
        if m:
            if current is not None:
                sections[current] = "\n".join(body)
            current = m.group(1)
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body)
    return sections


def _field(body, name):
    m = re.search(r'^{}=(.*)$'.format(re.escape(name)), body, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip('"')


def _human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "--"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "{:.1f} {}".format(n, unit)
        n /= 1024
    return "{:.1f} PB".format(n)


def check_hyperbackup_status(config_manager) -> list:
    """
    Returns a list of 0 or 1 job dicts in the same shape used by
    core/backup_status.py's check_backup_jobs(): {"tool", "name", "status",
    "last_run", "duration", "size", "files", "dest", "log"}.

    Connection failures produce a "fail" job rather than an empty list --
    "the NAS is unreachable" is itself something worth surfacing, not a
    silent skip like a genuinely-absent backup tool would be.
    """
    cfg = config_manager
    if not cfg.nas_backup_enabled or not cfg.nas_backup_host or not cfg.nas_backup_username:
        return []

    nas = SSHManager()
    result = nas.connect(
        host=cfg.nas_backup_host,
        port=cfg.nas_backup_port or 22,
        username=cfg.nas_backup_username,
        password=cfg.nas_backup_password or None,
        key_path=cfg.nas_backup_key_path or None,
    )
    if result is not True:
        return [{
            "tool": "hyperbackup", "name": "NAS Hyper Backup",
            "status": "fail", "last_run": "--", "duration": "--",
            "size": "--", "files": "--", "dest": cfg.nas_backup_host,
            "log": "Could not connect to NAS: {}".format(result),
        }]

    try:
        conf_out, _, conf_code = nas.run("cat {}".format(_CONF_PATH))
        if conf_code != 0 or not conf_out.strip():
            return [{
                "tool": "hyperbackup", "name": "NAS Hyper Backup",
                "status": "fail", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": cfg.nas_backup_host,
                "log": "Could not read Hyper Backup config at {}".format(_CONF_PATH),
            }]

        sections = _split_sections(conf_out)

        # Find the task whose backup_folders mentions wsbackup, or whose
        # own name does -- robust to the task/repo ID changing if the job
        # is ever recreated, rather than hardcoding a numeric task_NN.
        task_id = None
        task_name = "WSBACKUP"
        for sect_name, body in sections.items():
            if not sect_name.startswith("task_"):
                continue
            folders = _field(body, "backup_folders") or ""
            name    = _field(body, "name") or ""
            if "wsbackup" in folders.lower() or "wsbackup" in name.lower():
                task_id   = sect_name.split("_", 1)[1]
                task_name = name or task_name
                break

        if task_id is None:
            return [{
                "tool": "hyperbackup", "name": "NAS Hyper Backup",
                "status": "fail", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": cfg.nas_backup_host,
                "log": "No Hyper Backup task found targeting /wsbackup.",
            }]

        last_out, _, last_code = nas.run("cat {}".format(_LAST_RESULT_PATH))
        if last_code != 0 or not last_out.strip():
            return [{
                "tool": "hyperbackup", "name": task_name,
                "status": "none", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": "Synology C2 (cloud)",
                "log": "Task found but has no run history yet.",
            }]

        last_sections = _split_sections(last_out)
        run_body = last_sections.get("task_" + task_id)
        if run_body is None:
            return [{
                "tool": "hyperbackup", "name": task_name,
                "status": "none", "last_run": "--", "duration": "--",
                "size": "--", "files": "--", "dest": "Synology C2 (cloud)",
                "log": "Task found but has no run history yet.",
            }]

        result_str = (_field(run_body, "result") or "").lower()
        error      = _field(run_body, "error") or ""
        error_code = _field(run_body, "error_code") or "0"
        start_s    = _field(run_body, "start_time")
        end_s      = _field(run_body, "end_time")
        size_s     = _field(run_body, "target_size")

        start_ts = int(start_s) if start_s and start_s.isdigit() else None
        end_ts   = int(end_s) if end_s and end_s.isdigit() else None

        last_run = time.strftime("%Y-%m-%d %H:%M", time.localtime(end_ts)) if end_ts else "--"
        duration = "--"
        if start_ts and end_ts and end_ts >= start_ts:
            secs = end_ts - start_ts
            duration = "{}m {}s".format(secs // 60, secs % 60)

        ok = (result_str == "done" and error_code == "0")
        status = "fail"
        if ok:
            age_days = ((time.time() - end_ts) / 86400) if end_ts else 999
            status = "ok" if age_days < 2 else ("warn" if age_days < 7 else "fail")

        return [{
            "tool": "hyperbackup", "name": task_name,
            "status": status, "last_run": last_run, "duration": duration,
            "size": _human_size(size_s), "files": "--",
            "dest": "Synology C2 (cloud)",
            "log": "result={} error_code={} error={}".format(
                result_str or "--", error_code, error or "(none)"),
        }]
    finally:
        nas.disconnect()
