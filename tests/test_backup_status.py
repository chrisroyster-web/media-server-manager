import json
import datetime

from core.backup_status import check_backup_jobs, _parse_rsync_log, _parse_cron_backup_log


class _FakeSSH:
    def __init__(self):
        self._responses = []  # list of (out, err, code), consumed in order

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def _empty_tail_probes(ssh):
    """Queue empty responses for rsync-find, systemd-list, cron-find, duplicati."""
    ssh._responses += [("", "", 0), ("", "", 0), ("", "", 0), ("", "", 1)]


# ---------------------------------------------------------------------------
# check_backup_jobs — nothing installed
# ---------------------------------------------------------------------------

def test_check_backup_jobs_returns_empty_when_nothing_found():
    ssh = _FakeSSH()
    ssh._responses = [
        ("MISSING", "", 0),   # restic check
        ("", "", 0),          # rsync log find
        ("", "", 0),          # systemd list
        ("", "", 0),          # cron log find
        ("", "", 1),          # duplicati curl
    ]
    assert check_backup_jobs(ssh) == []


# ---------------------------------------------------------------------------
# check_backup_jobs — restic
# ---------------------------------------------------------------------------

def test_check_backup_jobs_restic_recent_snapshot_is_ok():
    recent = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat()
    snap_json = json.dumps([{"time": recent, "summary": {"total_files_processed": 42}}])
    ssh = _FakeSSH()
    ssh._responses = [
        ("FOUND", "", 0),          # restic check
        ("", "", 0),               # repos file (none found -> falls back to "(default)")
        (snap_json, "", 0),        # restic snapshots --json
    ]
    _empty_tail_probes(ssh)
    jobs = check_backup_jobs(ssh)
    assert len(jobs) == 1
    assert jobs[0]["tool"] == "restic"
    assert jobs[0]["status"] == "ok"
    assert jobs[0]["files"] == "42"


def test_check_backup_jobs_restic_old_snapshot_is_fail():
    old = (datetime.datetime.utcnow() - datetime.timedelta(days=10)).isoformat()
    snap_json = json.dumps([{"time": old, "summary": {}}])
    ssh = _FakeSSH()
    ssh._responses = [
        ("FOUND", "", 0),
        ("", "", 0),
        (snap_json, "", 0),
    ]
    _empty_tail_probes(ssh)
    jobs = check_backup_jobs(ssh)
    assert jobs[0]["status"] == "fail"


def test_check_backup_jobs_restic_moderately_stale_snapshot_is_warn():
    stale = (datetime.datetime.utcnow() - datetime.timedelta(days=4)).isoformat()
    snap_json = json.dumps([{"time": stale, "summary": {}}])
    ssh = _FakeSSH()
    ssh._responses = [
        ("FOUND", "", 0),
        ("", "", 0),
        (snap_json, "", 0),
    ]
    _empty_tail_probes(ssh)
    jobs = check_backup_jobs(ssh)
    assert jobs[0]["status"] == "warn"


# ---------------------------------------------------------------------------
# check_backup_jobs — systemd units
# ---------------------------------------------------------------------------

def test_check_backup_jobs_systemd_unit_success():
    ssh = _FakeSSH()
    ssh._responses = [
        ("MISSING", "", 0),                                   # restic
        ("", "", 0),                                           # rsync find
        ("backup.service\n", "", 0),                          # systemd list
        ("ActiveState=inactive\nExecMainStatus=0\nInactiveEnterTimestamp=Mon 2026-07-06 02:00:00 UTC\n", "", 0),
        ("", "", 0),                                           # cron find
        ("", "", 1),                                           # duplicati
    ]
    jobs = check_backup_jobs(ssh)
    assert len(jobs) == 1
    assert jobs[0]["tool"] == "systemd"
    assert jobs[0]["name"] == "backup"
    assert jobs[0]["status"] == "ok"


def test_check_backup_jobs_systemd_unit_failure():
    ssh = _FakeSSH()
    ssh._responses = [
        ("MISSING", "", 0),
        ("", "", 0),
        ("backup.service\n", "", 0),
        ("ActiveState=failed\nExecMainStatus=1\nInactiveEnterTimestamp=\n", "", 0),
        ("", "", 0),
        ("", "", 1),
    ]
    jobs = check_backup_jobs(ssh)
    assert jobs[0]["status"] == "fail"


# ---------------------------------------------------------------------------
# check_backup_jobs — Duplicati
# ---------------------------------------------------------------------------

def test_check_backup_jobs_duplicati_entry():
    dup_json = json.dumps([{"Backup": {"Name": "nightly", "TargetURL": "file:///backups"},
                             "Progress": {}}])
    ssh = _FakeSSH()
    ssh._responses = [
        ("MISSING", "", 0),
        ("", "", 0),
        ("", "", 0),
        ("", "", 0),
        (dup_json, "", 0),
    ]
    jobs = check_backup_jobs(ssh)
    assert len(jobs) == 1
    assert jobs[0]["tool"] == "duplicati"
    assert jobs[0]["name"] == "nightly"


# ---------------------------------------------------------------------------
# _parse_rsync_log
# ---------------------------------------------------------------------------

def test_parse_rsync_log_success():
    text = (
        "2026-07-08 02:00:01 starting\n"
        "Number of files: 1,234\n"
        "Total transferred file size: 5,678 bytes\n"
        "sent 100 bytes  received 200 bytes  300.00 bytes/sec\n"
        "2026-07-08 02:00:05 done\n"
    )
    job = _parse_rsync_log("/var/log/nightly.log", text)
    assert job["tool"] == "rsync"
    assert job["name"] == "nightly"
    assert job["status"] == "ok"
    assert job["files"] == "1,234"


def test_parse_rsync_log_failure_when_no_success_marker():
    job = _parse_rsync_log("/var/log/nightly.log", "rsync: some error occurred\n")
    assert job["status"] == "fail"


# ---------------------------------------------------------------------------
# _parse_cron_backup_log
# ---------------------------------------------------------------------------

def test_parse_cron_backup_log_ok():
    text = (
        "[2026-07-08 02:00:00] === Backup started ===\n"
        "[2026-07-08 02:05:00] === Backup completed OK — 1.2G written to /mnt/nas ===\n"
    )
    job = _parse_cron_backup_log("/var/log/full-backup.log", text)
    assert job["status"] == "ok"
    assert job["size"] == "1.2G"
    assert job["dest"] == "/mnt/nas"


def test_parse_cron_backup_log_failure():
    text = (
        "[2026-07-08 02:00:00] === Backup started ===\n"
        "[2026-07-08 02:05:00] === Backup completed with 2 errors ===\n"
    )
    job = _parse_cron_backup_log("/var/log/full-backup.log", text)
    assert job["status"] == "fail"


def test_parse_cron_backup_log_still_running_is_warn():
    text = "[2026-07-08 02:00:00] === Backup started ===\n"
    job = _parse_cron_backup_log("/var/log/full-backup.log", text)
    assert job["status"] == "warn"


def test_parse_cron_backup_log_returns_none_without_marker():
    assert _parse_cron_backup_log("/var/log/full-backup.log", "nothing relevant here\n") is None


def test_parse_cron_backup_log_stale_ok_downgrades_to_warn():
    old_ts = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    text = (
        "[{ts}] === Backup started ===\n"
        "[{ts}] === Backup completed OK — 1.2G written to /mnt/nas ===\n"
    ).format(ts=old_ts)
    job = _parse_cron_backup_log("/var/log/full-backup.log", text)
    assert job["status"] == "warn"
