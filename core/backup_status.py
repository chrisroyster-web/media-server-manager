# core/backup_status.py
"""
Checks restic / rsync / systemd / cron-script / Duplicati backup jobs on the
connected server over SSH. Extracted from ui/backup_tab.py so this data is
reusable outside the Backup tab (e.g. the daily digest in core/digest.py).
"""

import re
import json
import shlex
import datetime


def check_backup_jobs(ssh) -> list:
    """
    Probe every backup mechanism this app knows how to detect and return a
    list of job dicts: {"tool", "name", "status", "last_run", "duration",
    "size", "files", "dest", "log"}. status is one of "ok"/"warn"/"fail"/"none".
    Never raises — a probe that fails to detect its tool just contributes no
    entries, same as if that tool weren't installed.
    """
    jobs = []

    # ── restic ──────────────────────────────────────────────────────
    rout, _, rcode = ssh.run(
        "command -v restic >/dev/null 2>&1 && echo FOUND || echo MISSING")
    if "FOUND" in (rout or ""):
        repos_out, _, _ = ssh.run(
            "cat ~/.config/restic-repos 2>/dev/null || "
            "grep -r 'RESTIC_REPOSITORY' /etc/cron* /etc/systemd/system "
            "~/.local/share/systemd/user 2>/dev/null | "
            "grep -o 'RESTIC_REPOSITORY=[^ ]*' | head -6")
        repos = re.findall(r'RESTIC_REPOSITORY=(\S+)', repos_out or "")
        for repo in repos or ["(default)"]:
            env = "RESTIC_REPOSITORY={} RESTIC_PASSWORD_FILE=~/.restic-password".format(
                shlex.quote(repo)) if repo != "(default)" else ""
            snap_out, _, snap_code = ssh.run(
                "{} restic snapshots --last --json 2>/dev/null".format(env))
            if snap_code == 0 and snap_out.strip():
                try:
                    snaps = json.loads(snap_out)
                    last = snaps[-1] if snaps else {}
                    ts   = last.get("time", "")
                    if ts:
                        dt   = datetime.datetime.fromisoformat(ts[:19])
                        age  = (datetime.datetime.utcnow() - dt).total_seconds()
                        days = age / 86400
                        st   = "ok" if days < 2 else ("warn" if days < 7 else "fail")
                        jobs.append({
                            "tool": "restic", "name": repo.split("/")[-1] or "repo",
                            "status": st, "last_run": dt.strftime("%Y-%m-%d %H:%M"),
                            "duration": "--", "size": "--",
                            "files": str(last.get("summary", {}).get("total_files_processed", "--")),
                            "dest": repo, "log": str(last),
                        })
                except Exception:
                    pass

    # ── rsync (via log files) ────────────────────────────────────────
    # Only look in directories likely to contain real backup logs.
    # Exclude /var/log/apt, /var/log/installer, /var/log/unattended-upgrades
    # which contain system package logs that mention rsync incidentally.
    log_dirs = ["/var/log/rsync", "/home", "/root", "/opt", "/srv"]
    rsync_logs, _, _ = ssh.run(
        "find {} -maxdepth 4 -name '*.log' 2>/dev/null "
        "| xargs grep -l '^rsync:' 2>/dev/null | head -6".format(
            " ".join(log_dirs)))
    for log_path in (rsync_logs or "").splitlines():
        log_path = log_path.strip()
        if not log_path:
            continue
        # Skip system/package-manager log paths
        skip_paths = ("/var/log/apt", "/var/log/installer",
                      "/var/log/unattended", "/var/log/dpkg")
        if any(log_path.startswith(s) for s in skip_paths):
            continue
        tail, _, _ = ssh.run("tail -40 {}".format(shlex.quote(log_path)))
        job = _parse_rsync_log(log_path, tail or "")
        if job:
            jobs.append(job)

    # ── systemd backup units ─────────────────────────────────────────
    svc_out, _, _ = ssh.run(
        "systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | "
        "grep -iE 'backup|rsync|restic|borg|rclone|duplicati' | awk '{print $1}'")
    for svc in (svc_out or "").splitlines():
        svc = svc.strip()
        if not svc:
            continue
        status_out, _, _ = ssh.run(
            "systemctl show {} --property=ActiveState,ExecMainStatus,"
            "InactiveEnterTimestamp 2>/dev/null".format(shlex.quote(svc)))
        props = dict(re.findall(r'(\w+)=(.*)', status_out or ""))
        active = props.get("ActiveState", "unknown")
        code   = props.get("ExecMainStatus", "")
        ts     = props.get("InactiveEnterTimestamp", "").strip()
        st     = "ok" if (active in ("active", "inactive") and code == "0") else (
                 "fail" if code not in ("0", "") else "none")
        jobs.append({
            "tool": "systemd", "name": svc.replace(".service", ""),
            "status": st, "last_run": ts[:16] if ts else "--",
            "duration": "--", "size": "--", "files": "--",
            "dest": svc, "log": status_out or "",
        })

    # ── Cron backup scripts (structured log format) ──────────────────
    # Finds any *backup*.log in /var/log that uses our timestamped format:
    #   [YYYY-MM-DD HH:MM:SS] === Backup started ===
    #   [YYYY-MM-DD HH:MM:SS] === Backup completed OK — SIZE written to PATH ===
    cron_logs, _, _ = ssh.run(
        "find /var/log -maxdepth 1 -name '*backup*.log' 2>/dev/null")
    for log_path in (cron_logs or "").splitlines():
        log_path = log_path.strip()
        if not log_path:
            continue
        tail, _, _ = ssh.run(
            "grep -a '=== Backup' {} 2>/dev/null | tail -20".format(shlex.quote(log_path)))
        job = _parse_cron_backup_log(log_path, tail or "")
        if job:
            jobs.append(job)

    # ── Duplicati REST API ───────────────────────────────────────────
    dup_out, _, dup_code = ssh.run(
        "curl -sf http://localhost:8200/api/v1/backups 2>/dev/null")
    if dup_code == 0 and dup_out.strip():
        try:
            dup_data = json.loads(dup_out)
            for bk in (dup_data if isinstance(dup_data, list) else []):
                backup = bk.get("Backup", {})
                prog   = bk.get("Progress", {})
                name   = backup.get("Name", "--")
                dest   = backup.get("TargetURL", "--")
                jobs.append({
                    "tool": "duplicati", "name": name,
                    "status": "ok", "last_run": "--",
                    "duration": "--", "size": "--", "files": "--",
                    "dest": dest, "log": json.dumps(prog, indent=2),
                })
        except Exception:
            pass

    return jobs


def _parse_rsync_log(path, text):
    name = re.sub(r'\.log$', '', path.split("/")[-1])
    # Look for rsync summary line
    m = re.search(r'Number of files: ([\d,]+)', text)
    files = m.group(1) if m else "--"
    m = re.search(r'Total transferred file size: ([\d,]+ bytes)', text)
    size = m.group(1) if m else "--"
    # Success marker
    ok = bool(re.search(r'sent \d+ bytes.*received \d+ bytes', text))
    # Timestamp from last line
    lines = [l for l in text.splitlines() if l.strip()]
    last  = lines[-1] if lines else ""
    ts_m  = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}', last)
    ts    = ts_m.group(0) if ts_m else "--"
    return {
        "tool": "rsync", "name": name,
        "status": "ok" if ok else "fail",
        "last_run": ts, "duration": "--",
        "size": size, "files": files,
        "dest": path, "log": text[-800:],
    }


def _parse_cron_backup_log(path, text):
    """Parse logs written by our timestamped backup.sh format."""
    if "=== Backup" not in text:
        return None
    name = re.sub(r'[-_]backup.*\.log$', '', path.split("/")[-1]) or path.split("/")[-1]
    # Find last start timestamp
    starts = re.findall(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] === Backup started', text)
    ts = starts[-1] if starts else "--"
    # Determine status and size from last completion line
    ok_m   = re.search(r'=== Backup completed OK.*?(\d+[\.\d]*[KMGTP]?) written to (\S+)', text)
    fail_m = re.search(r'=== Backup completed with (\d+) error', text)
    if ok_m:
        st   = "ok"
        size = ok_m.group(1)
        dest = ok_m.group(2)
    elif fail_m:
        st   = "fail"
        size = "--"
        dest = path
    else:
        # Started but no completion line yet (currently running)
        st   = "warn"
        size = "--"
        dest = path
    # Compute staleness from last start time
    if ts != "--":
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            age = (datetime.datetime.now() - dt).total_seconds()
            if st == "ok" and age > 8 * 86400:
                st = "warn"
        except Exception:
            pass
    return {
        "tool": "cron", "name": name,
        "status": st, "last_run": ts,
        "duration": "--", "size": size,
        "files": "--", "dest": dest,
        "log": text,
    }
