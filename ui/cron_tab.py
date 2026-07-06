# ui/cron_tab.py
"""
Server Jobs tab.
Reads and manages scheduled jobs on the connected server:
  - Cron jobs  (user crontab, root crontab, /etc/crontab, /etc/cron.d/*)
  - Systemd timers  (systemctl list-timers)
  - Docker schedulers  (Watchtower and similar interval-based containers)

Actions: Run Now · Disable/Enable · Delete
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import base64
import json
import re
import shlex


# ---------------------------------------------------------------------------
# Schedule parsing helpers  (cron)
# ---------------------------------------------------------------------------

_WEEKDAYS = {
    "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
    "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun",
    "sun": "Sun", "mon": "Mon", "tue": "Tue", "wed": "Wed",
    "thu": "Thu", "fri": "Fri", "sat": "Sat",
}

_MONTHS = {
    "1": "Jan", "2": "Feb", "3": "Mar", "4": "Apr",
    "5": "May", "6": "Jun", "7": "Jul", "8": "Aug",
    "9": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}


def _describe_field(val, kind):
    if val == "*":
        return None
    if val.startswith("*/"):
        units = {"minute": "min", "hour": "hr", "day": "day",
                 "month": "month", "weekday": "weekday"}
        return f"every {val[2:]} {units.get(kind, kind)}s"
    if "," in val:
        parts = val.split(",")
        if kind == "weekday":
            return "/".join(_WEEKDAYS.get(p.lower(), p) for p in parts)
        if kind == "month":
            return "/".join(_MONTHS.get(p, p) for p in parts)
        return val
    if kind == "weekday":
        return _WEEKDAYS.get(val.lower(), val)
    if kind == "month":
        return _MONTHS.get(val, val)
    return val


def _human_schedule(minute, hour, dom, month, dow):
    if (minute, hour, dom, month, dow) == ("0", "0", "*", "*", "*"):
        return "Daily midnight"
    if (minute, hour, dom, month, dow) == ("0", "0", "*", "*", "0"):
        return "Weekly Sun"
    if (minute, hour, dom, month, dow) == ("0", "0", "1", "*", "*"):
        return "Monthly 1st"
    if (minute, hour, dom, month, dow) == ("*", "*", "*", "*", "*"):
        return "Every minute"
    parts = []
    if hour != "*" and minute != "*":
        try:
            parts.append(f"at {int(hour):02d}:{int(minute):02d}")
        except ValueError:
            parts.append(f"{hour}:{minute}")
    elif minute != "*":
        d = _describe_field(minute, "minute")
        parts.append(d or "every minute")
    if dow != "*":
        d = _describe_field(dow, "weekday")
        if d:
            parts.append("on " + d)
    elif dom != "*":
        d = _describe_field(dom, "day")
        if d:
            parts.append("day " + d)
    if month != "*":
        d = _describe_field(month, "month")
        if d:
            parts.append("in " + d)
    return ", ".join(parts) if parts else f"{minute} {hour} {dom} {month} {dow}"


def _parse_crontab_lines(raw, source):
    jobs = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            parts = stripped.split(None, 2)
            if len(parts) >= 2:
                shorthand = parts[0]
                is_system = source.startswith("/etc")
                if is_system and len(parts) == 3:
                    user, cmd = parts[1], parts[2]
                else:
                    user = ""
                    cmd = parts[1] if len(parts) == 2 else parts[2]
                jobs.append({
                    "type": "cron", "source": source, "user": user,
                    "minute": shorthand, "hour": "", "dom": "",
                    "month": "", "dow": "",
                    "schedule": shorthand, "command": cmd, "raw": stripped,
                    "enabled": True,
                })
            continue
        if re.match(r'^\s*\w+=', stripped) and not re.match(r'^\s*\d', stripped):
            continue
        parts = stripped.split()
        if len(parts) < 6:
            continue
        minute, hour, dom, month, dow = parts[:5]
        is_system = source.startswith("/etc")
        if is_system and len(parts) >= 7:
            user, cmd = parts[5], " ".join(parts[6:])
        else:
            user, cmd = "", " ".join(parts[5:])
        jobs.append({
            "type": "cron", "source": source, "user": user,
            "minute": minute, "hour": hour, "dom": dom,
            "month": month, "dow": dow,
            "schedule": _human_schedule(minute, hour, dom, month, dow),
            "command": cmd, "raw": stripped,
            "enabled": True,
        })
    return jobs


# ---------------------------------------------------------------------------
# Systemd timer parsing (folded in from the retired systemd_timers_tab.py)
# ---------------------------------------------------------------------------

_TIMER_LINE_RE = re.compile(
    r'^(?P<next>-|\w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+)\s+'
    r'(?P<left>-|.*?)\s+'
    r'(?P<last>-|\w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+)\s+'
    r'(?P<passed>-|.*? ago)\s+'
    r'(?P<unit>\S+\.timer)\s+'
    r'(?P<activates>\S+)$'
)


def _parse_systemd_timers(output):
    """
    Parse `systemctl list-timers --all` output into structured dicts.
    Columns: NEXT  LEFT  LAST  PASSED  UNIT  ACTIVATES

    NEXT/LEFT/LAST/PASSED are right-aligned with variable-width padding —
    slicing by the header label's character position (what the retired
    systemd_timers_tab.py did) silently misaligns values, since a
    right-aligned value's start position shifts with its own content
    width, not the label's. Anchoring on the two fixed, unambiguous
    markers instead — the "Www YYYY-MM-DD HH:MM:SS TZ" date format for
    NEXT/LAST, and the literal " ago" suffix on PASSED — lets regex
    backtracking correctly capture LEFT/PASSED's own variable-width,
    sometimes-multi-word values (e.g. "1h 33min", "1 day 13h ago").
    Verified against real `systemctl list-timers --all` output.
    """
    timers = []
    for line in output.splitlines():
        s = line.strip()
        if not s or ("NEXT" in s and "UNIT" in s) or "timers listed" in s or "timer listed" in s:
            continue
        m = _TIMER_LINE_RE.match(s)
        if not m:
            continue
        is_active = m["next"] != "-"
        timers.append({
            "unit":      m["unit"],
            "activates": m["activates"],
            "next":      m["next"],
            "left":      m["left"],
            "last":      m["last"],
            "passed":    m["passed"],
            "active":    is_active,
            "raw":       s,
        })
    return timers


# ---------------------------------------------------------------------------
# Tab class
# ---------------------------------------------------------------------------

_TYPE_TAG = {
    "cron":    "CRON",
    "systemd": "TIMER",
    "docker":  "DOCKER",
}
_TYPE_COLOR = {
    "cron":    "#f97316",
    "systemd": "#5b8ef0",
    "docker":  "#22c55e",
}


class CronTab(tk.Frame):

    COLS = [
        ("Type",     62,  "center"),
        ("Source",  160,  "w"),
        ("Schedule",170,  "w"),
        ("Next Run", 130, "w"),
        ("Left",      80, "w"),
        ("Last Run", 130, "w"),
        ("Passed",    80, "w"),
        ("Command",   0,  "w"),
    ]

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._jobs      = []           # all fetched job dicts
        self._iid_map   = {}           # tree iid → job dict
        self._selected  = None         # currently selected job dict
        self._build_ui()
        self.after(600, self.refresh)

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------

    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⏰  Server Jobs",
                 bg=t.surface_dark, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", padx=18, pady=14)
        self._count_lbl = tk.Label(hdr, text="",
                                   bg=t.surface_dark, fg=t.text_muted,
                                   font=t.font_small)
        self._count_lbl.pack(side="right", padx=18)
        tk.Button(hdr, text="⟳  Refresh", command=self.refresh,
                  bg=t.blue, fg="#ffffff", bd=0, relief="flat",
                  font=t.font_small, padx=12, pady=4,
                  cursor="hand2").pack(side="right", padx=(0, 10), pady=10)
        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Filter bar
        fbar = tk.Frame(self, bg=t.surface, padx=14, pady=7)
        fbar.pack(fill="x")
        tk.Label(fbar, text="Filter:", bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        fe = tk.Entry(fbar, textvariable=self._filter_var,
                      font=t.font_regular, width=30)
        t.style_entry(fe)
        fe.pack(side="left", padx=8)
        tk.Button(fbar, text="✕", command=lambda: self._filter_var.set(""),
                  bg=t.surface, fg=t.text_muted, bd=0, relief="flat",
                  font=t.font_small, cursor="hand2").pack(side="left")

        # Type filter checkboxes
        self._show_cron    = tk.BooleanVar(value=True)
        self._show_systemd = tk.BooleanVar(value=True)
        self._show_docker  = tk.BooleanVar(value=True)
        for lbl, var, color in [
            ("Cron",   self._show_cron,    _TYPE_COLOR["cron"]),
            ("Timers", self._show_systemd, _TYPE_COLOR["systemd"]),
            ("Docker", self._show_docker,  _TYPE_COLOR["docker"]),
        ]:
            tk.Checkbutton(
                fbar, text=lbl, variable=var, command=self._apply_filter,
                bg=t.surface, fg=color, selectcolor=t.surface_light,
                activebackground=t.surface, activeforeground=color,
                font=t.font_small, bd=0,
            ).pack(side="left", padx=8)

        # Folded in from the retired systemd_timers_tab.py, which had the
        # same "show inactive" toggle for timer units.
        self._show_inactive_timers = tk.BooleanVar(value=True)
        tk.Checkbutton(
            fbar, text="Inactive Timers", variable=self._show_inactive_timers,
            command=self._apply_filter,
            bg=t.surface, fg=t.text_muted, selectcolor=t.surface_light,
            activebackground=t.surface, activeforeground=t.text_muted,
            font=t.font_small, bd=0,
        ).pack(side="left", padx=8)

        # Vertical split: list + actions (top) / console (bottom)
        pane = tk.PanedWindow(self, orient="vertical",
                              sashwidth=5, sashrelief="flat",
                              bg=t.card_border)
        pane.pack(fill="both", expand=True)

        # ── Top: tree + action bar ────────────────────────────────────
        top = tk.Frame(pane, bg=t.bg)
        pane.add(top, minsize=200, stretch="always")

        tree_frame = tk.Frame(top, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(10, 4))

        style = ttk.Style()
        style.configure("Jobs.Treeview",
                        background=t.surface, foreground=t.text,
                        fieldbackground=t.surface, rowheight=26,
                        font=t.font_regular)
        style.configure("Jobs.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("Jobs.Treeview",
                  background=[("selected", t.blue)],
                  foreground=[("selected", "#ffffff")])

        col_ids = [c[0] for c in self.COLS]
        self._tree = ttk.Treeview(tree_frame, columns=col_ids,
                                  show="headings", style="Jobs.Treeview",
                                  selectmode="browse")
        for col_id, width, anchor in self.COLS:
            self._tree.heading(col_id, text=col_id,
                               command=lambda c=col_id: self._sort(c))
            self._tree.column(col_id,
                              width=width if width else 1,
                              minwidth=40,
                              stretch=(width == 0),
                              anchor=anchor)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Action bar
        abar = tk.Frame(top, bg=t.bg, padx=14, pady=6)
        abar.pack(fill="x")

        self._run_btn = tk.Button(abar, text="▶  Run Now",
                                  command=self._do_run_now,
                                  bg=t.surface_dark, fg=t.text_dim,
                                  bd=0, relief="flat", font=t.font_small,
                                  padx=12, pady=4, cursor="hand2",
                                  state="disabled")
        self._run_btn.pack(side="left", padx=(0, 6))

        self._tog_btn = tk.Button(abar, text="Disable",
                                  command=self._do_toggle,
                                  bg=t.surface_dark, fg=t.text_dim,
                                  bd=0, relief="flat", font=t.font_small,
                                  padx=12, pady=4, cursor="hand2",
                                  state="disabled")
        self._tog_btn.pack(side="left", padx=(0, 6))

        self._del_btn = tk.Button(abar, text="Delete",
                                  command=self._do_delete,
                                  bg=t.surface_dark, fg=t.text_dim,
                                  bd=0, relief="flat", font=t.font_small,
                                  padx=12, pady=4, cursor="hand2",
                                  state="disabled")
        self._del_btn.pack(side="left")

        self._sel_lbl = tk.Label(abar, text="Select a job to manage it.",
                                 bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._sel_lbl.pack(side="left", padx=14)

        # ── Bottom: console ───────────────────────────────────────────
        bot = tk.Frame(pane, bg=t.bg)
        pane.add(bot, minsize=100, stretch="never")

        con_hdr = tk.Frame(bot, bg=t.surface_dark, padx=14, pady=5)
        con_hdr.pack(fill="x")
        tk.Label(con_hdr, text="OUTPUT",
                 bg=t.surface_dark, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(con_hdr, text="Clear", command=self._clear_console,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small,
                  cursor="hand2").pack(side="right")

        con_frame = tk.Frame(bot, bg=t.bg)
        con_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._console = tk.Text(
            con_frame, bg=t.surface_dark, fg=t.text, font=t.font_mono,
            wrap="word", state="disabled", relief="flat",
            padx=10, pady=8, height=8)
        self._console.pack(side="left", fill="both", expand=True)
        csb = tk.Scrollbar(con_frame, command=self._console.yview)
        csb.pack(side="right", fill="y")
        self._console.configure(yscrollcommand=csb.set)
        self._console.tag_config("ok",    foreground=t.status_running)
        self._console.tag_config("error", foreground=t.status_stopped)
        self._console.tag_config("cmd",   foreground=t.cyan)
        self._console.tag_config("dim",   foreground=t.text_muted)

        self._sort_col = None
        self._sort_rev = False

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------

    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._count_lbl.config(text="Loading…")
        self._tree.delete(*self._tree.get_children())
        self._iid_map.clear()
        self._selected = None
        self._set_buttons_enabled(False)
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            if not ssh.connected:
                self.after(0, lambda: self._count_lbl.config(
                    text="Not connected", fg=self.theme.status_stopped))
                return

            jobs = []

            # ── Cron jobs ─────────────────────────────────────────────────
            out, _, code = ssh.run("crontab -l 2>/dev/null")
            if code == 0 and out.strip():
                jobs += _parse_crontab_lines(out, "user crontab")

            out, _, code = ssh.run_sudo("crontab -l 2>/dev/null")
            if code == 0 and out.strip():
                jobs += _parse_crontab_lines(out, "root crontab")

            out, _, code = ssh.run("cat /etc/crontab 2>/dev/null")
            if code == 0 and out.strip():
                jobs += _parse_crontab_lines(out, "/etc/crontab")

            out, _, _ = ssh.run("ls /etc/cron.d/ 2>/dev/null")
            for fname in out.split():
                fname = fname.strip()
                content, _, fc = ssh.run(f"cat {shlex.quote('/etc/cron.d/' + fname)} 2>/dev/null")
                if fc == 0 and content.strip():
                    jobs += _parse_crontab_lines(content, f"/etc/cron.d/{fname}")

            # ── Systemd timers ────────────────────────────────────────────
            # Column-position parsing (not whitespace-split) so LEFT/LAST/
            # PASSED — folded in from the retired systemd_timers_tab.py —
            # parse correctly even though date fields contain spaces.
            out, _, _ = ssh.run("systemctl list-timers --all --no-pager 2>/dev/null")
            timers = _parse_systemd_timers(out)
            units = [tm["unit"] for tm in timers]
            enabled_map = {}
            if units:
                en_out, _, _ = ssh.run(
                    "systemctl is-enabled {} 2>/dev/null".format(
                        " ".join(shlex.quote(u) for u in units)))
                for u, state in zip(units, en_out.splitlines()):
                    enabled_map[u] = (state.strip() == "enabled")
            for tm in timers:
                unit, activates = tm["unit"], tm["activates"]
                jobs.append({
                    "type":     "systemd",
                    "source":   "systemd",
                    "unit":     unit,
                    "activates": activates,
                    "schedule": activates.replace(".service", "") or unit.replace(".timer", ""),
                    "next_run": tm["next"],
                    "left":     tm["left"],
                    "last":     tm["last"],
                    "passed":   tm["passed"],
                    "timer_active": tm["active"],
                    "command":  activates or unit,
                    "enabled":  enabled_map.get(unit, True),
                    "raw":      tm["raw"],
                })

            # ── Docker schedulers ─────────────────────────────────────────
            out, _, code = ssh.run(
                "docker inspect watchtower 2>/dev/null || echo not_found")
            if code == 0 and out.strip() not in ("not_found", ""):
                try:
                    data = json.loads(out.strip())
                    if data:
                        c     = data[0]
                        state = c.get("State", {}).get("Status", "unknown")
                        args  = c.get("Args", [])
                        interval = None
                        for i, a in enumerate(args):
                            if a == "--interval" and i + 1 < len(args):
                                interval = int(args[i + 1])
                            elif a.startswith("--interval="):
                                interval = int(a.split("=", 1)[1])
                        if interval:
                            if interval % 86400 == 0:
                                sched = f"every {interval // 86400}d"
                            elif interval % 3600 == 0:
                                sched = f"every {interval // 3600}h"
                            else:
                                sched = f"every {interval}s"
                        else:
                            sched = "on restart"
                        jobs.append({
                            "type":     "docker",
                            "source":   "docker",
                            "unit":     "watchtower",
                            "schedule": sched,
                            "next_run": "",
                            "command":  "auto-update Docker images",
                            "enabled":  state == "running",
                            "raw":      f"watchtower [{state}]",
                        })
                except Exception:
                    pass

            self._jobs = jobs
            self.after(0, lambda: self._render(jobs))
        finally:
            self._fetching = False

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------

    def _render(self, jobs):
        self._count_lbl.config(
            text=f"{len(jobs)} job{'s' if len(jobs) != 1 else ''}",
            fg=self.theme.text_muted)
        self._apply_filter()

    def _apply_filter(self):
        q          = self._filter_var.get().lower()
        show_cron  = self._show_cron.get()
        show_timer = self._show_systemd.get()
        show_dock  = self._show_docker.get()
        show_inactive_timers = self._show_inactive_timers.get()

        self._tree.delete(*self._tree.get_children())
        self._iid_map.clear()

        for job in self._jobs:
            jtype = job["type"]
            if jtype == "cron"    and not show_cron:  continue
            if jtype == "systemd" and not show_timer: continue
            if jtype == "docker"  and not show_dock:  continue
            if (jtype == "systemd" and not show_inactive_timers
                    and not job.get("timer_active", True)):
                continue

            text_blob = (job.get("command", "") + job.get("schedule", "") +
                         job.get("source",  "") + job.get("raw", "")).lower()
            if q and q not in text_blob:
                continue

            badge = _TYPE_TAG.get(jtype, jtype.upper())
            src   = job.get("source", job.get("unit", ""))
            sched = job.get("schedule", "")
            nxt   = job.get("next_run", "")
            left  = job.get("left", "--")
            last  = job.get("last", "--")
            passed= job.get("passed", "--")
            cmd   = job.get("command", "")

            iid = self._tree.insert("", "end", tags=(jtype,), values=(
                badge, src, sched, nxt, left, last, passed, cmd))
            self._iid_map[iid] = job

        t = self.theme
        self._tree.tag_configure("cron",    foreground=_TYPE_COLOR["cron"])
        self._tree.tag_configure("systemd", foreground=_TYPE_COLOR["systemd"])
        self._tree.tag_configure("docker",  foreground=_TYPE_COLOR["docker"])

    def _sort(self, col):
        rows = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        rev  = (self._sort_col == col) and not self._sort_rev
        rows.sort(reverse=rev)
        for i, (_, k) in enumerate(rows):
            self._tree.move(k, "", i)
        self._sort_col = col
        self._sort_rev = rev

    # ------------------------------------------------------------------
    # SELECTION
    # ------------------------------------------------------------------

    def _on_select(self, event):
        sel = self._tree.selection()
        if not sel:
            self._selected = None
            self._set_buttons_enabled(False)
            return
        iid  = sel[0]
        job  = self._iid_map.get(iid)
        self._selected = job
        if job:
            self._set_buttons_enabled(True)
            enabled = job.get("enabled", True)
            self._tog_btn.config(text="Disable" if enabled else "Enable")
            self._sel_lbl.config(text=f"{job.get('source','?')}  ·  {job.get('command','')[:60]}")

    def _set_buttons_enabled(self, on):
        t = self.theme
        if on:
            self._run_btn.config(state="normal", bg=t.blue,           fg="#ffffff")
            self._tog_btn.config(state="normal", bg=t.surface_light,  fg=t.text)
            self._del_btn.config(state="normal", bg=t.status_stopped,  fg="#ffffff")
        else:
            for btn in (self._run_btn, self._tog_btn, self._del_btn):
                btn.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
            self._sel_lbl.config(text="Select a job to manage it.")

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _do_run_now(self):
        job = self._selected
        if not job:
            return
        name = job.get("unit") or job.get("source", "job")
        self._log(f"▶ Run Now: {name}", "cmd")
        threading.Thread(target=self._run_worker, args=(job,), daemon=True).start()

    def _run_worker(self, job):
        ssh   = self.controller.ssh
        jtype = job["type"]
        if jtype == "cron":
            cmd = job["command"]
            is_root = "root" in job.get("source", "")
            if is_root:
                out, err, code = ssh.run_sudo(f"sh -c {shlex.quote(cmd)}")
            else:
                out, err, code = ssh.run(cmd)
        elif jtype == "systemd":
            svc = job.get("activates") or job["unit"].replace(".timer", ".service")
            out, err, code = ssh.run_sudo(f"systemctl start {shlex.quote(svc)}")
        elif jtype == "docker":
            unit = job.get("unit", "")
            out, err, code = ssh.run(f"docker restart {shlex.quote(unit)} 2>&1")
        else:
            out, err, code = "", "Unknown job type", 1
        self.controller.audit_log(
            "cron.run", job.get("unit") or job.get("source", "job"),
            detail=(err or out or "").strip()[:200],
            result="ok" if code == 0 else "fail")
        self._log_result("run", out, err, code)

    def _do_toggle(self):
        job = self._selected
        if not job:
            return
        enabled = job.get("enabled", True)
        action  = "disable" if enabled else "enable"
        name    = job.get("unit") or job.get("source", "job")
        if enabled and not messagebox.askyesno(
                "Disable Job", f"Disable '{name}'?", parent=self):
            return
        self._log(f"{'■' if enabled else '▶'}  {action.title()}: {name}", "cmd")
        threading.Thread(target=self._toggle_worker, args=(job, enabled),
                         daemon=True).start()

    def _toggle_worker(self, job, currently_enabled):
        ssh   = self.controller.ssh
        jtype = job["type"]
        if jtype == "cron":
            out, err, code = self._cron_set_enabled(job, not currently_enabled)
        elif jtype == "systemd":
            # enable/disable (not stop/start) — this toggles whether the
            # timer is enabled to start on boot, matching what the
            # retired systemd_timers_tab.py's Enable/Disable buttons
            # actually did; stop/start would only affect the timer's
            # current run state, not what this button implies.
            unit = job["unit"]
            if currently_enabled:
                out, err, code = ssh.run_sudo(f"systemctl disable {shlex.quote(unit)}")
            else:
                out, err, code = ssh.run_sudo(f"systemctl enable {shlex.quote(unit)}")
        elif jtype == "docker":
            unit = job.get("unit", "")
            if currently_enabled:
                out, err, code = ssh.run(f"docker stop {shlex.quote(unit)} 2>&1")
            else:
                out, err, code = ssh.run(f"docker start {shlex.quote(unit)} 2>&1")
        else:
            out, err, code = "", "Unknown job type", 1
        self.controller.audit_log(
            "cron.toggle", job.get("unit") or job.get("source", "job"),
            detail="disable" if currently_enabled else "enable",
            result="ok" if code == 0 else "fail")
        self._log_result("toggle", out, err, code)
        if code == 0:
            job["enabled"] = not currently_enabled
            self.after(0, lambda: self._tog_btn.config(
                text="Disable" if job["enabled"] else "Enable"))

    def _do_delete(self):
        job = self._selected
        if not job:
            return
        name = job.get("unit") or job.get("source", "job")
        if not messagebox.askyesno(
                "Delete Job",
                f"Permanently delete job from '{name}'?\n\nThis cannot be undone.",
                parent=self):
            return
        self._log(f"✕  Delete: {name}", "cmd")
        threading.Thread(target=self._delete_worker, args=(job,),
                         daemon=True).start()

    def _delete_worker(self, job):
        ssh   = self.controller.ssh
        jtype = job["type"]
        if jtype == "cron":
            out, err, code = self._cron_remove(job)
        elif jtype == "systemd":
            unit = job["unit"]
            out, err, code = ssh.run_sudo(f"systemctl disable --now {shlex.quote(unit)} 2>&1; true")
        elif jtype == "docker":
            unit = job.get("unit", "")
            o1, e1, _  = ssh.run(f"docker stop {shlex.quote(unit)} 2>&1")
            o2, e2, c2 = ssh.run(f"docker rm   {shlex.quote(unit)} 2>&1")
            out, err, code = o1 + o2, e1 + e2, c2
        else:
            out, err, code = "", "Unknown job type", 1
        self.controller.audit_log(
            "cron.delete", job.get("unit") or job.get("source", "job"),
            detail=(err or out or "").strip()[:200],
            result="ok" if code == 0 else "fail")
        self._log_result("delete", out, err, code)
        if code == 0:
            self.after(0, self.refresh)

    # ------------------------------------------------------------------
    # CRONTAB EDITING
    # ------------------------------------------------------------------

    def _cron_write(self, lines, source):
        """Write a modified crontab back to the appropriate location."""
        content = "\n".join(lines) + "\n"
        encoded = base64.b64encode(content.encode()).decode()
        ssh     = self.controller.ssh
        if source == "user crontab":
            cmd = f"echo '{encoded}' | base64 -d | crontab -"
            return ssh.run(cmd)
        if source == "root crontab":
            cmd = f"echo '{encoded}' | base64 -d > /tmp/.cron_edit && sudo crontab /tmp/.cron_edit && rm /tmp/.cron_edit"
            return ssh.run(cmd)
        if source.startswith("/etc/cron.d/") or source == "/etc/crontab":
            path = source if source != "/etc/crontab" else "/etc/crontab"
            cmd  = f"echo '{encoded}' | base64 -d | sudo tee {shlex.quote(path)} > /dev/null"
            return ssh.run(cmd)
        return "", f"Cannot edit source: {source}", 1

    def _cron_current_lines(self, source):
        ssh = self.controller.ssh
        if source == "user crontab":
            out, _, _ = ssh.run("crontab -l 2>/dev/null")
        elif source == "root crontab":
            out, _, _ = ssh.run_sudo("crontab -l 2>/dev/null")
        else:
            path = source if source.startswith("/") else f"/etc/crontab"
            out, _, _ = ssh.run(f"cat {shlex.quote(path)} 2>/dev/null")
        return out.splitlines()

    def _cron_set_enabled(self, job, enable: bool):
        raw    = job["raw"]
        source = job["source"]
        lines  = self._cron_current_lines(source)
        new_lines = []
        changed   = False
        for line in lines:
            stripped = line.strip()
            bare = stripped.lstrip("#").strip()
            if bare == raw or bare == raw.lstrip("#").strip():
                if enable:
                    new_lines.append(bare)
                else:
                    new_lines.append("# " + bare)
                changed = True
            else:
                new_lines.append(line)
        if not changed:
            return "", "Entry not found in crontab", 1
        return self._cron_write(new_lines, source)

    def _cron_remove(self, job):
        raw    = job["raw"]
        source = job["source"]
        lines  = self._cron_current_lines(source)
        new_lines = [l for l in lines
                     if l.strip().lstrip("#").strip() != raw.lstrip("#").strip()]
        if len(new_lines) == len(lines):
            return "", "Entry not found in crontab", 1
        return self._cron_write(new_lines, source)

    # ------------------------------------------------------------------
    # CONSOLE
    # ------------------------------------------------------------------

    def _log(self, text, tag="dim"):
        def _do():
            self._console.configure(state="normal")
            self._console.insert("end", text + "\n", tag)
            self._console.see("end")
            self._console.configure(state="disabled")
        self.after(0, _do)

    def _log_result(self, label, out, err, code):
        tag    = "ok" if code == 0 else "error"
        status = "OK" if code == 0 else f"FAILED (exit {code})"
        self._log(f"[{label}] {status}", tag)
        combined = "\n".join(
            [l for l in (out or "").splitlines() if l.strip()] +
            [l for l in (err or "").splitlines() if l.strip()])
        if combined:
            self._log(combined, "error" if code != 0 else "dim")

    def _clear_console(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")
