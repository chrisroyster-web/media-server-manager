from core.remediation_tracker import RemediationTracker


class _FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_allows_up_to_max_attempts_within_window():
    tracker = RemediationTracker(max_attempts=3, window_s=1800, backoff_s=3600)
    target = "service:sonarr"
    for _ in range(3):
        assert tracker.should_attempt(target) is True
        tracker.record_attempt(target)


def test_blocks_the_attempt_after_max_is_reached():
    tracker = RemediationTracker(max_attempts=3, window_s=1800, backoff_s=3600)
    target = "service:sonarr"
    for _ in range(3):
        tracker.record_attempt(target)
    assert tracker.should_attempt(target) is False


def test_backoff_expires_after_backoff_s():
    clock = _FakeClock()
    tracker = RemediationTracker(max_attempts=2, window_s=1800, backoff_s=3600, clock=clock)
    target = "docker:radarr"
    tracker.record_attempt(target)
    tracker.record_attempt(target)
    assert tracker.should_attempt(target) is False

    clock.advance(3601)
    assert tracker.should_attempt(target) is True


def test_attempts_outside_the_window_age_out():
    clock = _FakeClock()
    tracker = RemediationTracker(max_attempts=2, window_s=1800, backoff_s=3600, clock=clock)
    target = "service:radarr"
    tracker.record_attempt(target)
    clock.advance(1801)   # first attempt now outside the 30-minute window
    assert tracker.should_attempt(target) is True
    tracker.record_attempt(target)
    info = tracker.last_info(target)
    assert info["attempts_in_window"] == 1


def test_reset_clears_all_state():
    tracker = RemediationTracker(max_attempts=1)
    tracker.record_attempt("service:a")
    tracker.record_attempt("docker:b")
    tracker.reset()
    assert tracker.last_info("service:a") is None
    assert tracker.should_attempt("service:a") is True


def test_targets_are_tracked_independently():
    tracker = RemediationTracker(max_attempts=1, window_s=1800, backoff_s=3600)
    tracker.record_attempt("service:a")
    assert tracker.should_attempt("service:a") is False
    assert tracker.should_attempt("docker:b") is True


def test_last_info_returns_none_for_unknown_target():
    tracker = RemediationTracker()
    assert tracker.last_info("service:never-seen") is None


def test_snapshot_is_a_copy_not_a_live_reference():
    tracker = RemediationTracker()
    tracker.record_attempt("service:a")
    snap = tracker.snapshot()
    snap["service:a"]["attempts"].append(999999)
    assert len(tracker.snapshot()["service:a"]["attempts"]) == 1
