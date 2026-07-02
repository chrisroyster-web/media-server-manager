# core/scheduler.py
"""
In-process task scheduler. Runs SSH commands on configurable schedules,
logs output, and fires a callback on completion (success or failure).
"""

import threading
import uuid
from datetime import datetime, timedelta


class TaskScheduler:

    MAX_LOG_ENTRIES = 20

    def __init__(self, config_manager, ssh, on_run_done=None):
        """
        on_run_done(task_id, task_name, exit_code, output, notify_on_failure)
        Called from a background thread after each run completes.
        """
        self.cfg         = config_manager
        self.ssh         = ssh
        self.on_run_done = on_run_done
        self._stop       = threading.Event()
        self._running    = set()
        self._lock       = threading.Lock()

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True,
                         name="TaskScheduler").start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # SCHEDULER LOOP  (runs every 30 s)
    # ------------------------------------------------------------------

    def _loop(self):
        while not self._stop.wait(30):
            if not self.ssh.connected:
                continue
            for task in self.get_tasks():
                if not task.get("enabled", True):
                    continue
                tid = task["id"]
                with self._lock:
                    if tid in self._running:
                        continue
                nr = self._next_run(task)
                if nr and datetime.now() >= nr:
                    with self._lock:
                        self._running.add(tid)
                    threading.Thread(target=self._run_task,
                                     args=(task,), daemon=True).start()

    # ------------------------------------------------------------------
    # NEXT-RUN CALCULATION
    # ------------------------------------------------------------------

    def _next_run(self, task):
        stype        = task.get("schedule_type", "interval")
        last_run_str = task.get("last_run")

        if stype == "interval":
            if not last_run_str:
                return datetime.now()   # run immediately on first use
            last = self._parse_dt(last_run_str)
            interval_m = max(1, int(task.get("interval_minutes", 60)))
            return last + timedelta(minutes=interval_m)

        elif stype == "daily":
            h, m = self._parse_time(task.get("daily_time", "02:00"))
            if h is None:
                return None
            ref = datetime.now() if not last_run_str else self._parse_dt(last_run_str)
            candidate = ref.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= ref:
                candidate += timedelta(days=1)
            return candidate

        elif stype == "weekly":
            h, m = self._parse_time(task.get("daily_time", "02:00"))
            if h is None:
                return None
            target_day = int(task.get("weekly_day", 0))   # 0=Mon … 6=Sun
            ref = datetime.now() if not last_run_str else self._parse_dt(last_run_str)
            candidate = ref.replace(hour=h, minute=m, second=0, microsecond=0)
            days_ahead = (target_day - candidate.weekday()) % 7
            if days_ahead == 0 and candidate <= ref:
                days_ahead = 7
            candidate += timedelta(days=days_ahead)
            return candidate

        return None

    @staticmethod
    def _parse_time(s):
        try:
            parts = s.split(":")
            return int(parts[0]), int(parts[1])
        except Exception:
            return None, None

    @staticmethod
    def _parse_dt(s):
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.now()

    # ------------------------------------------------------------------
    # EXECUTE A TASK
    # ------------------------------------------------------------------

    def _run_task(self, task):
        task_id = task["id"]
        now_str = datetime.now().isoformat(timespec="seconds")

        self._patch_task(task_id, {"last_run": now_str, "last_status": "running"})

        try:
            out, err, code = self.ssh.run(task["command"])
            combined = out
            if err.strip():
                combined += "\n--- stderr ---\n" + err
            status = "ok" if code == 0 else "error"
        except Exception as exc:
            combined = str(exc)
            code     = -1
            status   = "error"

        log_entry = {
            "ts":        now_str,
            "exit_code": code,
            "output":    combined[:8000],
        }

        tasks = self.get_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["last_run"]       = now_str
                t["last_status"]    = status
                t["last_exit_code"] = code
                history = t.get("output_log", [])
                history.insert(0, log_entry)
                t["output_log"] = history[:self.MAX_LOG_ENTRIES]
                break
        self._save_tasks(tasks)

        if self.on_run_done:
            self.on_run_done(task_id, task.get("name", "Task"),
                             code, combined, task.get("notify_on_failure", True))

        with self._lock:
            self._running.discard(task_id)

    def _patch_task(self, task_id, updates):
        tasks = self.get_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t.update(updates)
                break
        self._save_tasks(tasks)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_tasks(self):
        return list(self.cfg.get("scheduled_tasks", []))

    def _save_tasks(self, tasks):
        self.cfg.set("scheduled_tasks", tasks)

    def add_task(self, name, command, schedule_type="interval",
                 interval_minutes=60, daily_time="02:00", weekly_day=0,
                 enabled=True, notify_on_failure=True):
        task = {
            "id":                str(uuid.uuid4()),
            "name":              name,
            "command":           command,
            "schedule_type":     schedule_type,
            "interval_minutes":  interval_minutes,
            "daily_time":        daily_time,
            "weekly_day":        weekly_day,
            "enabled":           enabled,
            "notify_on_failure": notify_on_failure,
            "last_run":          None,
            "last_status":       "never",
            "last_exit_code":    None,
            "output_log":        [],
        }
        tasks = self.get_tasks()
        tasks.append(task)
        self._save_tasks(tasks)
        return task

    def update_task(self, task_id, **kwargs):
        tasks = self.get_tasks()
        for t in tasks:
            if t["id"] == task_id:
                # Preserve runtime state fields
                for key, val in kwargs.items():
                    t[key] = val
                break
        self._save_tasks(tasks)

    def delete_task(self, task_id):
        tasks = [t for t in self.get_tasks() if t["id"] != task_id]
        self._save_tasks(tasks)

    def run_now(self, task_id):
        """Trigger immediate execution regardless of schedule. Returns True if started."""
        for task in self.get_tasks():
            if task["id"] == task_id:
                with self._lock:
                    if task_id in self._running:
                        return False
                    self._running.add(task_id)
                threading.Thread(target=self._run_task,
                                 args=(task,), daemon=True).start()
                return True
        return False

    def is_running(self, task_id):
        with self._lock:
            return task_id in self._running

    def next_run_str(self, task):
        """Return a human-readable next-run string for a task."""
        if not task.get("enabled", True):
            return "—"
        nr = self._next_run(task)
        if nr is None:
            return "—"
        now  = datetime.now()
        diff = nr - now
        secs = diff.total_seconds()
        if secs < 0:
            return "soon"
        if secs < 60:
            return f"in {int(secs)}s"
        if secs < 3600:
            return f"in {int(secs / 60)}m"
        if secs < 86400:
            return f"in {int(secs / 3600)}h"
        return nr.strftime("%m/%d %H:%M")
