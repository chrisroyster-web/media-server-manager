import time

import core.hyperbackup_status as hb


class _FakeNAS:
    """Stand-in for core.ssh_manager.SSHManager, injected via monkeypatch
    since check_hyperbackup_status() constructs its own instance rather
    than taking one as a parameter (it's a separate connection from the
    media server's)."""

    def __init__(self):
        self.disconnected   = False
        self.connect_result = True
        self._responses     = []

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        return self.connect_result

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 1)

    def disconnect(self):
        self.disconnected = True


def _fake_nas(monkeypatch):
    """Pre-create the fake so the test can configure it before
    check_hyperbackup_status() constructs its (one and only) SSHManager."""
    fake = _FakeNAS()
    monkeypatch.setattr(hb, "SSHManager", lambda: fake)
    return fake


class _FakeCfg:
    nas_backup_enabled  = True
    nas_backup_host     = "nas.local"
    nas_backup_port     = 22
    nas_backup_username = "admin"
    nas_backup_password = "secret"
    nas_backup_key_path  = ""


def _conf(task_id="1", name="WSBACKUP Task", folders="/volume1/wsbackup"):
    return (
        '[task_{tid}]\n'
        'name="{name}"\n'
        'backup_folders="{folders}"\n'
    ).format(tid=task_id, name=name, folders=folders)


def _last_result(task_id="1", result="done", error_code="0", error="",
                 start_offset_s=3600, end_offset_s=0, size="123456789"):
    now = int(time.time())
    return (
        '[task_{tid}]\n'
        'result="{result}"\n'
        'error_code="{ec}"\n'
        'error="{err}"\n'
        'start_time="{start}"\n'
        'end_time="{end}"\n'
        'target_size="{size}"\n'
    ).format(tid=task_id, result=result, ec=error_code, err=error,
             start=now - start_offset_s, end=now - end_offset_s, size=size)


def test_returns_empty_when_disabled(monkeypatch):
    fake = _fake_nas(monkeypatch)
    cfg = _FakeCfg()
    cfg.nas_backup_enabled = False
    assert hb.check_hyperbackup_status(cfg) == []
    assert not hasattr(fake, "connect_kwargs")  # never even tries to connect


def test_returns_empty_when_host_or_username_missing(monkeypatch):
    _fake_nas(monkeypatch)
    cfg = _FakeCfg()
    cfg.nas_backup_host = ""
    assert hb.check_hyperbackup_status(cfg) == []


def test_connect_failure_yields_fail_job(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake.connect_result = "Auth failed"
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert len(jobs) == 1
    assert jobs[0]["status"] == "fail"
    assert jobs[0]["tool"] == "hyperbackup"
    assert "Could not connect" in jobs[0]["log"]


def test_unreadable_config_yields_fail_job(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [("", "err", 1)]  # cat synobackup.conf fails
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "fail"
    assert "Could not read Hyper Backup config" in jobs[0]["log"]
    assert fake.disconnected is True


def test_no_matching_task_yields_fail_job(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(task_id="1", name="Other", folders="/volume1/other"), "", 0),
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "fail"
    assert "No Hyper Backup task found" in jobs[0]["log"]


def test_task_with_no_run_history_yields_none_status(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(), "", 0),
        ("", "", 1),  # cat backup.last fails
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "none"
    assert "no run history yet" in jobs[0]["log"]


def test_recent_successful_run_is_ok(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(), "", 0),
        (_last_result(end_offset_s=3600), "", 0),  # finished 1h ago
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert len(jobs) == 1
    job = jobs[0]
    assert job["status"] == "ok"
    assert job["name"] == "WSBACKUP Task"
    assert job["dest"] == "Synology C2 (cloud)"
    assert job["size"] != "--"


def test_stale_successful_run_is_warn(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(), "", 0),
        (_last_result(end_offset_s=4 * 86400), "", 0),  # 4 days ago
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "warn"


def test_very_stale_run_is_fail(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(), "", 0),
        (_last_result(end_offset_s=10 * 86400), "", 0),  # 10 days ago
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "fail"


def test_failed_run_result_is_fail_even_if_recent(monkeypatch):
    fake = _fake_nas(monkeypatch)
    fake._responses = [
        (_conf(), "", 0),
        (_last_result(result="failed", error_code="20", error="disk full",
                      end_offset_s=60), "", 0),
    ]
    jobs = hb.check_hyperbackup_status(_FakeCfg())
    assert jobs[0]["status"] == "fail"
    assert "disk full" in jobs[0]["log"]
