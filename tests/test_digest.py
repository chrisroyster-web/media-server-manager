import sqlite3
import time

import pytest

from core.metrics_store import MetricsStore
from core.digest import build_digest


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "metrics.db"))


class _FakeSSH:
    def __init__(self):
        self._responses = []

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def _no_backup_tools_responses():
    return [
        ("MISSING", "", 0),   # restic check
        ("", "", 0),          # rsync log find
        ("", "", 0),          # systemd list
        ("", "", 0),          # cron log find
        ("", "", 1),          # duplicati curl
    ]


def _insert_metric_at(store, server_id, ts, cpu, ram, disk):
    con = sqlite3.connect(store.db_path)
    con.execute(
        "INSERT INTO server_metrics (server_id, ts, cpu, ram, disk) "
        "VALUES (?, ?, ?, ?, ?)",
        (server_id, ts, cpu, ram, disk))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# MetricsStore.get_metric_near
# ---------------------------------------------------------------------------

def test_get_metric_near_picks_closest_row(store):
    _insert_metric_at(store, "srv1", 1000, 10, 1, 1)
    _insert_metric_at(store, "srv1", 2000, 20, 1, 1)
    _insert_metric_at(store, "srv1", 3000, 30, 1, 1)
    near = store.get_metric_near("srv1", 2100)
    assert near["cpu"] == 20


def test_get_metric_near_returns_none_when_no_history(store):
    assert store.get_metric_near("srv1", 12345) is None


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------

def test_digest_reports_no_data_when_nothing_collected(store):
    ssh = _FakeSSH()
    ssh._responses = _no_backup_tools_responses()
    body = build_digest(ssh, store, "srv1")
    assert "Backups: no backup tools detected." in body
    assert "Metrics: no data collected yet." in body
    assert "Alerts (last 24h): none." in body


def test_digest_reports_current_metrics_without_prior_history(store):
    now = int(time.time())
    _insert_metric_at(store, "srv1", now, 55, 60, 40)
    ssh = _FakeSSH()
    ssh._responses = _no_backup_tools_responses()
    body = build_digest(ssh, store, "srv1")
    assert "CPU: 55%" in body
    assert "vs. yesterday" not in body  # no real prior-day point exists yet


def test_digest_reports_delta_against_prior_day(store):
    now = int(time.time())
    _insert_metric_at(store, "srv1", now - 86400, 40, 50, 30)   # ~24h ago
    _insert_metric_at(store, "srv1", now, 55, 60, 40)           # now

    ssh = _FakeSSH()
    ssh._responses = _no_backup_tools_responses()
    body = build_digest(ssh, store, "srv1")
    assert "CPU: 55%" in body
    assert "vs. yesterday" in body
    assert "+15%" in body  # 55 - 40


def test_digest_alerts_section_filters_by_level_and_recency(store):
    now = int(time.time())
    con = sqlite3.connect(store.db_path)
    con.execute("INSERT INTO notifications (server_id, ts, level, title, message) "
                "VALUES (?, ?, ?, ?, ?)", ("srv1", now, "error", "Disk full", ""))
    con.execute("INSERT INTO notifications (server_id, ts, level, title, message) "
                "VALUES (?, ?, ?, ?, ?)", ("srv1", now, "info", "Just FYI", ""))
    con.execute("INSERT INTO notifications (server_id, ts, level, title, message) "
                "VALUES (?, ?, ?, ?, ?)",
                ("srv1", now - 200000, "error", "Old stale alert", ""))
    con.commit()
    con.close()

    ssh = _FakeSSH()
    ssh._responses = _no_backup_tools_responses()
    body = build_digest(ssh, store, "srv1")
    assert "Disk full" in body
    assert "Just FYI" not in body        # info level excluded
    assert "Old stale alert" not in body  # outside the 24h window


def test_digest_includes_failing_backup_job_name(store):
    ssh = _FakeSSH()
    ssh._responses = [
        ("MISSING", "", 0),
        ("", "", 0),
        ("backup.service\n", "", 0),
        ("ActiveState=failed\nExecMainStatus=1\nInactiveEnterTimestamp=\n", "", 0),
        ("", "", 0),
        ("", "", 1),
    ]
    body = build_digest(ssh, store, "srv1")
    assert "0 ok, 0 warn, 1 fail" in body
    assert "backup (systemd): fail" in body
