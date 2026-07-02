# core/metrics_store.py
"""
SQLite-backed store for metric history and persistent notification log.

Tables
------
server_metrics
    server_id TEXT   — server profile name (or "default" for the active server)
    ts        INTEGER — Unix timestamp (seconds)
    cpu       REAL    — CPU %
    ram       REAL    — RAM %
    disk      REAL    — primary disk %
    rx_bps    REAL    — network receive bytes/sec
    tx_bps    REAL    — network transmit bytes/sec
    gpu       REAL    — GPU % (-1 if not available)

notifications
    id        INTEGER PRIMARY KEY AUTOINCREMENT
    server_id TEXT
    ts        INTEGER
    level     TEXT    — info / ok / warn / error
    title     TEXT
    message   TEXT
"""

import sqlite3
import time
import threading
import os


class MetricsStore:
    """Thread-safe SQLite wrapper for metrics history and notification log."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock   = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _connect(self):
        """Return a new connection. Called inside lock."""
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._lock:
            con = self._connect()
            cur = con.cursor()
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS server_metrics (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT    NOT NULL DEFAULT 'default',
                    ts        INTEGER NOT NULL,
                    cpu       REAL    DEFAULT 0,
                    ram       REAL    DEFAULT 0,
                    disk      REAL    DEFAULT 0,
                    rx_bps    REAL    DEFAULT 0,
                    tx_bps    REAL    DEFAULT 0,
                    gpu       REAL    DEFAULT -1
                );

                CREATE INDEX IF NOT EXISTS idx_sm_server_ts
                    ON server_metrics (server_id, ts);

                CREATE TABLE IF NOT EXISTS notifications (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT    NOT NULL DEFAULT 'default',
                    ts        INTEGER NOT NULL,
                    level     TEXT    NOT NULL DEFAULT 'info',
                    title     TEXT    NOT NULL DEFAULT '',
                    message   TEXT    NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_notif_ts
                    ON notifications (ts);
            """)
            con.commit()
            con.close()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def insert_metric(self, server_id: str, cpu: float, ram: float,
                      disk: float, rx_bps: float = 0.0,
                      tx_bps: float = 0.0, gpu: float = -1.0):
        with self._lock:
            con = self._connect()
            con.execute(
                "INSERT INTO server_metrics "
                "(server_id, ts, cpu, ram, disk, rx_bps, tx_bps, gpu) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (server_id, int(time.time()), cpu, ram, disk, rx_bps, tx_bps, gpu)
            )
            con.commit()
            con.close()

    def query_metrics(self, server_id: str, limit: int = 30,
                      since_ts: int = 0) -> list:
        """
        Return up to `limit` most-recent rows for `server_id` as dicts,
        ordered oldest-first so charts can plot left-to-right.
        """
        with self._lock:
            con = self._connect()
            rows = con.execute(
                "SELECT ts, cpu, ram, disk, rx_bps, tx_bps, gpu "
                "FROM server_metrics "
                "WHERE server_id = ? AND ts >= ? "
                "ORDER BY ts DESC LIMIT ?",
                (server_id, since_ts, limit)
            ).fetchall()
            con.close()
        # Reverse so oldest is first
        return [dict(r) for r in reversed(rows)]

    def get_last_metric(self, server_id: str) -> dict | None:
        """Return the most-recent single metric row for a server, or None."""
        with self._lock:
            con = self._connect()
            row = con.execute(
                "SELECT ts, cpu, ram, disk, rx_bps, tx_bps, gpu "
                "FROM server_metrics WHERE server_id = ? "
                "ORDER BY ts DESC LIMIT 1",
                (server_id,)
            ).fetchone()
            con.close()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def insert_notification(self, server_id: str, level: str,
                            title: str, message: str):
        with self._lock:
            con = self._connect()
            con.execute(
                "INSERT INTO notifications (server_id, ts, level, title, message) "
                "VALUES (?, ?, ?, ?, ?)",
                (server_id, int(time.time()), level, title, message)
            )
            con.commit()
            con.close()

    def get_notifications(self, limit: int = 500,
                          server_id: str | None = None) -> list:
        """
        Return up to `limit` most-recent notifications, newest first.
        If server_id is None, return all servers.
        """
        with self._lock:
            con = self._connect()
            if server_id:
                rows = con.execute(
                    "SELECT id, server_id, ts, level, title, message "
                    "FROM notifications WHERE server_id = ? "
                    "ORDER BY ts DESC LIMIT ?",
                    (server_id, limit)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, server_id, ts, level, title, message "
                    "FROM notifications ORDER BY ts DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            con.close()
        return [dict(r) for r in rows]

    def clear_notifications(self, server_id: str | None = None):
        with self._lock:
            con = self._connect()
            if server_id:
                con.execute("DELETE FROM notifications WHERE server_id = ?",
                            (server_id,))
            else:
                con.execute("DELETE FROM notifications")
            con.commit()
            con.close()

    # ------------------------------------------------------------------
    # Retention / pruning
    # ------------------------------------------------------------------
    def prune_old(self, retention_days: int = 30):
        """Delete rows older than retention_days. Call on startup."""
        cutoff = int(time.time()) - retention_days * 86400
        with self._lock:
            con = self._connect()
            con.execute("DELETE FROM server_metrics WHERE ts < ?", (cutoff,))
            con.execute("DELETE FROM notifications  WHERE ts < ?", (cutoff,))
            con.commit()
            con.close()
