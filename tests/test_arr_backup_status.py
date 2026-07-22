import time

import core.arr_backup_status as ab


class _FakeCfg:
    sonarr_host   = "localhost"
    sonarr_port   = "8989"
    sonarr_apikey = ""
    radarr_host   = "localhost"
    radarr_port   = "7878"
    radarr_apikey = ""


def _backup(name="sonarr_backup.zip", path="/backup/scheduled/sonarr_backup.zip",
           type_="scheduled", age_s=3600):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
    return {"name": name, "path": path, "type": type_, "time": ts, "id": 1}


def _patch_api_get(monkeypatch, fn):
    monkeypatch.setattr(ab, "api_get", fn)


def test_skips_app_with_no_apikey(monkeypatch):
    calls = []
    _patch_api_get(monkeypatch, lambda *a: calls.append(a) or [])
    jobs = ab.check_arr_backup_jobs(_FakeCfg())
    assert jobs == []
    assert calls == []


def test_unreachable_app_yields_fail_job(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"

    def _raise(*a):
        raise ConnectionError("refused")
    _patch_api_get(monkeypatch, _raise)

    jobs = ab.check_arr_backup_jobs(cfg)
    assert len(jobs) == 1
    assert jobs[0]["tool"] == "sonarr"
    assert jobs[0]["status"] == "fail"
    assert "refused" in jobs[0]["log"]


def test_no_backups_yields_none_status(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    _patch_api_get(monkeypatch, lambda *a: [])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert jobs[0]["status"] == "none"


def test_recent_backup_is_ok(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    _patch_api_get(monkeypatch, lambda *a: [_backup(age_s=3600)])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "ok"
    assert jobs[0]["tool"] == "sonarr"
    assert jobs[0]["name"] == "Sonarr config backup"


def test_backup_within_default_interval_is_still_ok(monkeypatch):
    # *arr's own default backup interval is 7 days -- the whole point of
    # loosening these thresholds (vs. restic/Hyper Backup's 2-day one) was
    # so a default-interval setup doesn't sit in "warn" all week.
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    _patch_api_get(monkeypatch, lambda *a: [_backup(age_s=6 * 86400)])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert jobs[0]["status"] == "ok"


def test_moderately_stale_backup_is_warn(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    _patch_api_get(monkeypatch, lambda *a: [_backup(age_s=9 * 86400)])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert jobs[0]["status"] == "warn"


def test_very_stale_backup_is_fail(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    _patch_api_get(monkeypatch, lambda *a: [_backup(age_s=15 * 86400)])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert jobs[0]["status"] == "fail"


def test_picks_latest_of_multiple_backups(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    backups = [
        _backup(name="old.zip", age_s=10 * 86400),
        _backup(name="new.zip", age_s=3600),
    ]
    _patch_api_get(monkeypatch, lambda *a: backups)

    jobs = ab.check_arr_backup_jobs(cfg)
    assert jobs[0]["status"] == "ok"
    assert "new.zip" in jobs[0]["log"]


def test_both_apps_configured_returns_two_jobs(monkeypatch):
    cfg = _FakeCfg()
    cfg.sonarr_apikey = "abc123"
    cfg.radarr_apikey = "def456"
    _patch_api_get(monkeypatch, lambda *a: [_backup(age_s=60)])

    jobs = ab.check_arr_backup_jobs(cfg)
    assert {j["tool"] for j in jobs} == {"sonarr", "radarr"}
