from core.watchdog_registry import WatchdogRegistry


def test_registered_watchdog_starts_with_no_last_run():
    reg = WatchdogRegistry()
    reg.register("Test Watchdog", 60)
    entry = reg.snapshot()["Test Watchdog"]
    assert entry["interval_s"] == 60
    assert entry["last_run"] is None
    assert entry["last_error"] is None
    assert entry["checks"] == 0
    assert entry["errors"] == 0


def test_record_ok_sets_last_run_and_clears_error():
    reg = WatchdogRegistry()
    reg.register("Test Watchdog", 60)
    reg.record_error("Test Watchdog", RuntimeError("boom"))
    reg.record_ok("Test Watchdog")
    entry = reg.snapshot()["Test Watchdog"]
    assert entry["last_run"] is not None
    assert entry["last_error"] is None
    assert entry["checks"] == 1
    assert entry["errors"] == 1  # errors counter is not reset by a later ok


def test_record_error_sets_last_error_and_increments_counter():
    reg = WatchdogRegistry()
    reg.register("Test Watchdog", 60)
    reg.record_error("Test Watchdog", RuntimeError("boom"))
    entry = reg.snapshot()["Test Watchdog"]
    assert entry["last_error"] == "boom"
    assert entry["errors"] == 1
    assert entry["checks"] == 0


def test_record_without_prior_register_still_creates_entry():
    reg = WatchdogRegistry()
    reg.record_ok("Unregistered Watchdog")
    entry = reg.snapshot()["Unregistered Watchdog"]
    assert entry["last_run"] is not None


def test_snapshot_is_a_copy_not_a_live_reference():
    reg = WatchdogRegistry()
    reg.register("Test Watchdog", 60)
    snap = reg.snapshot()
    snap["Test Watchdog"]["errors"] = 999
    assert reg.snapshot()["Test Watchdog"]["errors"] == 0


def test_multiple_watchdogs_tracked_independently():
    reg = WatchdogRegistry()
    reg.register("A", 60)
    reg.register("B", 120)
    reg.record_ok("A")
    reg.record_error("B", ValueError("bad"))
    snap = reg.snapshot()
    assert snap["A"]["last_error"] is None
    assert snap["B"]["last_error"] == "bad"
