from core.alert_engine import AlertEngine


class _FakeConfigManager:
    def __init__(self, rules):
        self._rules = rules

    def get_alert_rules(self):
        return self._rules


def _rule(**overrides):
    rule = {
        "id": "rule_cpu", "name": "High CPU", "metric": "cpu",
        "operator": ">=", "threshold": 80,
        "duration_minutes": 0, "cooldown_minutes": 60,
        "enabled": True,
    }
    rule.update(overrides)
    return rule


def test_rule_fires_when_threshold_breached_with_no_duration_requirement():
    engine = AlertEngine(_FakeConfigManager([_rule()]))
    fired = engine.evaluate({"cpu": 85})
    assert len(fired) == 1
    rule, value = fired[0]
    assert rule["id"] == "rule_cpu"
    assert value == 85


def test_rule_does_not_fire_below_threshold():
    engine = AlertEngine(_FakeConfigManager([_rule()]))
    assert engine.evaluate({"cpu": 50}) == []


def test_disabled_rule_never_fires():
    engine = AlertEngine(_FakeConfigManager([_rule(enabled=False)]))
    assert engine.evaluate({"cpu": 99}) == []


def test_missing_metric_does_not_fire_and_resets_breach_state():
    engine = AlertEngine(_FakeConfigManager([_rule(duration_minutes=5)]))
    engine.evaluate({"cpu": 90})  # starts a breach timer
    assert "rule_cpu" in engine._breach_start
    assert engine.evaluate({}) == []  # metric absent this cycle
    assert "rule_cpu" not in engine._breach_start


def test_duration_requirement_delays_firing_until_sustained(monkeypatch):
    """A rule with duration_minutes=5 shouldn't fire the instant the
    threshold is crossed — only once it's stayed breached for that long."""
    fake_now = [1_000_000.0]
    monkeypatch.setattr("core.alert_engine.time.time", lambda: fake_now[0])

    engine = AlertEngine(_FakeConfigManager([_rule(duration_minutes=5, cooldown_minutes=0)]))

    assert engine.evaluate({"cpu": 90}) == []  # first breach tick, timer just started

    fake_now[0] += 60 * 3  # 3 minutes later — still not enough
    assert engine.evaluate({"cpu": 90}) == []

    fake_now[0] += 60 * 3  # 6 minutes total — now past the 5-minute requirement
    fired = engine.evaluate({"cpu": 90})
    assert len(fired) == 1


def test_condition_clearing_resets_the_duration_clock(monkeypatch):
    fake_now = [1_000_000.0]
    monkeypatch.setattr("core.alert_engine.time.time", lambda: fake_now[0])

    engine = AlertEngine(_FakeConfigManager([_rule(duration_minutes=5, cooldown_minutes=0)]))
    engine.evaluate({"cpu": 90})  # breach starts
    fake_now[0] += 60 * 4  # 4 minutes in, still breached
    engine.evaluate({"cpu": 90})

    fake_now[0] += 60 * 1  # condition clears before the 5-minute mark
    assert engine.evaluate({"cpu": 50}) == []

    fake_now[0] += 60 * 10  # breach again — should need another full 5 minutes,
    assert engine.evaluate({"cpu": 90}) == []  # not fire immediately just because
    fake_now[0] += 60 * 6   # 10 minutes have passed since the *original* breach
    fired = engine.evaluate({"cpu": 90})
    assert len(fired) == 1  # confirms the clock really did restart


def test_cooldown_prevents_immediate_refire(monkeypatch):
    fake_now = [1_000_000.0]
    monkeypatch.setattr("core.alert_engine.time.time", lambda: fake_now[0])

    engine = AlertEngine(_FakeConfigManager([_rule(duration_minutes=0, cooldown_minutes=30)]))

    fired = engine.evaluate({"cpu": 90})
    assert len(fired) == 1

    fake_now[0] += 60 * 10  # still breached, only 10 of 30 cooldown minutes have passed
    assert engine.evaluate({"cpu": 90}) == []

    fake_now[0] += 60 * 25  # now 35 minutes since the fire — cooldown has elapsed
    fired = engine.evaluate({"cpu": 90})
    assert len(fired) == 1


def test_reset_clears_all_state():
    engine = AlertEngine(_FakeConfigManager([_rule(duration_minutes=5, cooldown_minutes=60)]))
    engine.evaluate({"cpu": 90})
    assert engine._breach_start

    engine.reset()
    assert engine._breach_start == {}
    assert engine._last_fired == {}


def test_operators():
    for op, value, threshold, should_fire in [
        (">=", 80, 80, True), (">=", 79, 80, False),
        (">", 81, 80, True), (">", 80, 80, False),
        ("<=", 80, 80, True), ("<=", 81, 80, False),
        ("<", 79, 80, True), ("<", 80, 80, False),
        ("=", 80, 80, True), ("=", 81, 80, False),
    ]:
        engine = AlertEngine(_FakeConfigManager(
            [_rule(operator=op, threshold=threshold, duration_minutes=0)]))
        fired = engine.evaluate({"cpu": value})
        assert bool(fired) == should_fire, f"operator {op}: {value} vs {threshold}"
