import time

import pytest

from core.metrics_store import MetricsStore


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "metrics.db"))


def test_insert_and_query_metrics_orders_oldest_first(store):
    store.insert_metric("srv1", cpu=10, ram=20, disk=30)
    store.insert_metric("srv1", cpu=15, ram=25, disk=35)
    rows = store.query_metrics("srv1", limit=10)
    assert len(rows) == 2
    assert rows[0]["cpu"] == 10  # oldest first
    assert rows[1]["cpu"] == 15


def test_query_metrics_is_scoped_to_server_id(store):
    store.insert_metric("srv1", cpu=10, ram=20, disk=30)
    store.insert_metric("srv2", cpu=99, ram=99, disk=99)
    rows = store.query_metrics("srv1", limit=10)
    assert len(rows) == 1
    assert rows[0]["cpu"] == 10


def test_query_metrics_respects_limit(store):
    for i in range(5):
        store.insert_metric("srv1", cpu=i, ram=0, disk=0)
    rows = store.query_metrics("srv1", limit=3)
    assert len(rows) == 3
    # most recent 3, still oldest-first within that window
    assert [r["cpu"] for r in rows] == [2, 3, 4]


def test_get_last_metric_returns_the_most_recent_row(store):
    store.insert_metric("srv1", cpu=10, ram=20, disk=30)
    store.insert_metric("srv1", cpu=15, ram=25, disk=35)
    last = store.get_last_metric("srv1")
    assert last["cpu"] == 15


def test_get_last_metric_returns_none_when_empty(store):
    assert store.get_last_metric("nonexistent") is None


def test_notifications_round_trip_and_scope_by_server(store):
    store.insert_notification("srv1", "info", "Title A", "Message A")
    store.insert_notification("srv2", "error", "Title B", "Message B")

    all_notifs = store.get_notifications()
    assert len(all_notifs) == 2

    srv1_only = store.get_notifications(server_id="srv1")
    assert len(srv1_only) == 1
    assert srv1_only[0]["title"] == "Title A"
    assert srv1_only[0]["level"] == "info"


def test_clear_notifications_scoped_vs_all(store):
    store.insert_notification("srv1", "info", "A", "a")
    store.insert_notification("srv2", "info", "B", "b")

    store.clear_notifications(server_id="srv1")
    remaining = store.get_notifications()
    assert len(remaining) == 1
    assert remaining[0]["server_id"] == "srv2"

    store.clear_notifications()
    assert store.get_notifications() == []


def test_audit_log_round_trip(store):
    store.insert_audit("srv1", "chris", "service.restart", "sonarr",
                        detail="exit 0", result="ok")
    entries = store.get_audit_log()
    assert len(entries) == 1
    assert entries[0]["action"] == "service.restart"
    assert entries[0]["target"] == "sonarr"
    assert entries[0]["result"] == "ok"


def test_prune_old_removes_stale_metrics_and_notifications_but_not_audit_log(store):
    now = int(time.time())
    old_ts = now - (40 * 86400)  # 40 days ago, older than the 30-day retention

    con = store._connect()
    con.execute(
        "INSERT INTO server_metrics (server_id, ts, cpu, ram, disk) "
        "VALUES ('srv1', ?, 1, 1, 1)", (old_ts,))
    con.execute(
        "INSERT INTO notifications (server_id, ts, level, title, message) "
        "VALUES ('srv1', ?, 'info', 'old', 'old')", (old_ts,))
    con.execute(
        "INSERT INTO audit_log (server_id, ts, actor, action, target) "
        "VALUES ('srv1', ?, 'chris', 'old.action', 'x')", (old_ts,))
    con.commit()
    con.close()

    store.insert_metric("srv1", cpu=2, ram=2, disk=2)  # recent, should survive

    store.prune_old(retention_days=30)

    remaining_metrics = store.query_metrics("srv1", limit=10)
    assert len(remaining_metrics) == 1
    assert remaining_metrics[0]["cpu"] == 2  # the old row is gone, recent one survives
    assert store.get_notifications() == []
    # audit_log is a permanent trail — prune_old must never touch it
    audit_actions = [e["action"] for e in store.get_audit_log()]
    assert "old.action" in audit_actions
