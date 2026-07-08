from datetime import datetime, timedelta

import pytest

from core.scheduler import TaskScheduler


class _FakeConfigManager:
    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class _FakeSSH:
    def __init__(self, connected=True):
        self.connected = connected
        self.run_calls = []
        self._result = ("output text", "", 0)

    def run(self, cmd):
        self.run_calls.append(cmd)
        return self._result


@pytest.fixture
def cfg():
    return _FakeConfigManager()


@pytest.fixture
def ssh():
    return _FakeSSH()


@pytest.fixture
def sched(cfg, ssh):
    return TaskScheduler(cfg, ssh)


def _fixed_now(monkeypatch, when):
    """Make core.scheduler's datetime.now() return a fixed value while
    leaving fromisoformat() etc. working normally (a real datetime
    subclass, not a bare mock, so every other classmethod still works)."""
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr("core.scheduler.datetime", _FrozenDateTime)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_add_task_creates_expected_defaults(sched):
    task = sched.add_task("Nightly backup", "backup.sh", schedule_type="daily")
    assert task["name"] == "Nightly backup"
    assert task["command"] == "backup.sh"
    assert task["schedule_type"] == "daily"
    assert task["enabled"] is True
    assert task["last_run"] is None
    assert task["last_status"] == "never"
    assert task["output_log"] == []
    assert task in sched.get_tasks()


def test_update_task_preserves_other_fields(sched):
    task = sched.add_task("A", "cmd")
    sched.update_task(task["id"], enabled=False)
    updated = sched.get_tasks()[0]
    assert updated["enabled"] is False
    assert updated["name"] == "A"


def test_delete_task_removes_only_the_matching_task(sched):
    t1 = sched.add_task("A", "cmd1")
    sched.add_task("B", "cmd2")
    sched.delete_task(t1["id"])
    remaining = sched.get_tasks()
    assert len(remaining) == 1
    assert remaining[0]["name"] == "B"


# ---------------------------------------------------------------------------
# _next_run — interval schedules
# ---------------------------------------------------------------------------

def test_interval_task_with_no_last_run_runs_immediately(sched):
    task = sched.add_task("A", "cmd", schedule_type="interval", interval_minutes=60)
    assert sched._next_run(task) is not None


def test_interval_task_next_run_is_last_run_plus_interval(sched, monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, 0)
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="interval", interval_minutes=30)
    task["last_run"] = (now - timedelta(minutes=10)).isoformat()
    nr = sched._next_run(task)
    assert nr == now - timedelta(minutes=10) + timedelta(minutes=30)


def test_interval_minutes_is_clamped_to_at_least_one(sched):
    task = sched.add_task("A", "cmd", schedule_type="interval", interval_minutes=0)
    task["last_run"] = datetime(2026, 1, 1, 12, 0, 0).isoformat()
    nr = sched._next_run(task)
    assert nr == datetime(2026, 1, 1, 12, 1, 0)


# ---------------------------------------------------------------------------
# _next_run — daily schedules
# ---------------------------------------------------------------------------

def test_daily_task_time_not_yet_passed_today_runs_today(sched, monkeypatch):
    now = datetime(2026, 1, 1, 1, 0, 0)  # 1am
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="daily", daily_time="02:00")
    nr = sched._next_run(task)
    assert nr == datetime(2026, 1, 1, 2, 0, 0)


def test_daily_task_time_already_passed_today_rolls_to_tomorrow(sched, monkeypatch):
    now = datetime(2026, 1, 1, 3, 0, 0)  # 3am, past the 2am slot
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="daily", daily_time="02:00")
    nr = sched._next_run(task)
    assert nr == datetime(2026, 1, 2, 2, 0, 0)


def test_daily_task_with_invalid_time_returns_none(sched):
    task = sched.add_task("A", "cmd", schedule_type="daily", daily_time="not-a-time")
    assert sched._next_run(task) is None


# ---------------------------------------------------------------------------
# _next_run — weekly schedules
# ---------------------------------------------------------------------------

def test_weekly_task_computes_next_occurrence_of_target_day(sched, monkeypatch):
    # 2026-01-01 is a Thursday (weekday()==3); target Monday (0)
    now = datetime(2026, 1, 1, 12, 0, 0)
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="weekly",
                          daily_time="02:00", weekly_day=0)
    nr = sched._next_run(task)
    assert nr.weekday() == 0
    assert nr > now


def test_weekly_task_on_target_day_but_time_passed_rolls_a_full_week(sched, monkeypatch):
    # 2026-01-01 is target day itself, but 2am has already passed (now=noon)
    now = datetime(2026, 1, 1, 12, 0, 0)
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="weekly",
                          daily_time="02:00", weekly_day=now.weekday())
    nr = sched._next_run(task)
    assert (nr - now).days >= 6


# ---------------------------------------------------------------------------
# next_run_str
# ---------------------------------------------------------------------------

def test_next_run_str_disabled_task(sched):
    task = sched.add_task("A", "cmd", enabled=False)
    assert sched.next_run_str(task) == "—"


def test_next_run_str_formats_relative_time(sched, monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, 0)
    _fixed_now(monkeypatch, now)
    task = sched.add_task("A", "cmd", schedule_type="interval", interval_minutes=90)
    task["last_run"] = now.isoformat()
    result = sched.next_run_str(task)
    assert result == "in 1h"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_run_task_records_success(sched, ssh, cfg):
    sched.add_task("A", "echo hi")
    ssh._result = ("hello\n", "", 0)
    sched._run_task(sched.get_tasks()[0])

    updated = sched.get_tasks()[0]
    assert updated["last_status"] == "ok"
    assert updated["last_exit_code"] == 0
    assert len(updated["output_log"]) == 1
    assert updated["output_log"][0]["output"] == "hello\n"
    assert ssh.run_calls == ["echo hi"]


def test_run_task_records_failure_and_includes_stderr(sched, ssh):
    sched.add_task("A", "false")
    ssh._result = ("", "boom", 1)
    sched._run_task(sched.get_tasks()[0])

    updated = sched.get_tasks()[0]
    assert updated["last_status"] == "error"
    assert "boom" in updated["output_log"][0]["output"]


def test_run_task_calls_on_run_done_callback(cfg, ssh):
    calls = []
    sched = TaskScheduler(cfg, ssh, on_run_done=lambda *a: calls.append(a))
    sched.add_task("A", "echo hi", notify_on_failure=False)
    sched._run_task(sched.get_tasks()[0])

    assert len(calls) == 1
    task_id, name, code, output, notify_on_failure = calls[0]
    assert name == "A"
    assert code == 0
    assert notify_on_failure is False


def test_run_task_clears_running_flag_when_done(sched):
    task = sched.add_task("A", "echo hi")
    sched._running.add(task["id"])
    sched._run_task(sched.get_tasks()[0])
    assert not sched.is_running(task["id"])


def test_run_now_starts_a_task_and_returns_true(sched):
    task = sched.add_task("A", "echo hi")
    started = sched.run_now(task["id"])
    assert started is True


def test_run_now_returns_false_for_unknown_task(sched):
    assert sched.run_now("no-such-id") is False


def test_run_now_returns_false_if_already_running(sched):
    task = sched.add_task("A", "echo hi")
    sched._running.add(task["id"])
    assert sched.run_now(task["id"]) is False
