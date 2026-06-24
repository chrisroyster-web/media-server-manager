# ui/cron_tab.py
"""
Cron Job Viewer tab.
Reads crontabs for the current user, root, and /etc/cron.d/* via SSH.
Displays parsed jobs in a sortable table with human-readable schedule.
Double-click a row to see the raw entry and a next-run estimate.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import re


# ---------------------------------------------------------------------------
# Schedule parsing helpers
# ---------------------------------------------------------------------------

_FIELD_NAMES = ("minute", "hour", "day", "month", "weekday")

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
    """Turn a single cron field into a human-readable phrase."""
    if val == "*":
        return None   # "every X" implied
    if val.startswith("*/"):
        step = val[2:]
        units = {"minute": "min", "hour": "hr", "day": "day",
                 "month": "month", "weekday": "weekday"}
        return "every {} {}s".format(step, units.get(kind, kind))
    if "," in val:
        parts = val.split(",")
        if kind == "weekday":
            return "/".join(_WEEKDAYS.get(p.lower(), p) for p in parts)
        if kind == "month":
            return "/".join(_MONTHS.get(p, p) for p in parts)
        return val
    # single value
    if kind == "weekday":
        return _WEEKDAYS.get(val.lower(), val)
    if kind == "month":
        return _MONTHS.get(val, val)
    return val


def _human_schedule(minute, hour, dom, month, dow):
    """Convert 5 cron fields to a short human-readable string."""
    # Common shortcuts
    if (minute, hour, dom, month, dow) == ("0", "0", "*", "*", "*"):
        return "Daily at midnight"
    if (minute, hour, dom, month, dow) == ("0", "0", "*", "*", "0"):
        return "Weekly on Sunday"
    if (minute, hour, dom, month, dow) == ("0", "0", "1", "*", "*"):
        return "Monthly (1st)"
    if (minute, hour, dom, month, dow) == ("*", "*", "*", "*", "*"):
        return "Every minute"

    parts = []

    # Time
    if hour != "*" and minute != "*":
        try:
            h, m = int(hour), int(minute)
            parts.append("at {:02d}:{:02d}".format(h, m))
        except ValueError:
            parts.append("{}:{}".format(hour, minute))
    elif hour != "*":
        d = _describe_field(hour, "hour")
        if d:
            parts.append(d)
    elif minute != "*":
        d = _describe_field(minute, "minute")
        if d:
            parts.append(d)
        else:
            parts.append("every minute")

    # Day / weekday
    if dow != "*":
        d = _describe_field(dow, "weekday")
        if d:
            parts.append("on " + d)
    elif dom != "*":
        d = _describe_field(dom, "day")
        if d:
            parts.append("day " + d)

    # Month
    if month != "*":
        d = _describe_field(month, "month")
        if d:
            parts.append("in " + d)

    return ", ".join(parts) if parts else "{} {} {} {} {}".format(
        minute, hour, dom, month, dow)


def _parse_crontab_lines(raw, source):
    """
    Parse raw crontab text into list of dicts:
    {source, user, minute, hour, dom, month, dow, schedule, command, raw}
    """
    jobs = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Handle @reboot, @daily, etc.
        if stripped.startswith("@"):
            parts = stripped.split(None, 2)
            if len(parts) >= 2:
                shorthand = parts[0]
                # system crontab has user field after shorthand
                if len(parts) == 3 and source.startswith("/etc"):
                    user = parts[1]
                    cmd  = parts[2]
                else:
                    user = ""
                    cmd  = parts[1] if len(parts) == 2 else parts[2]
                jobs.append({
                    "source":   source,
                    "user":     user,
                    "minute":   shorthand,
                    "hour":     "", "dom": "", "month": "", "dow": "",
                    "schedule": shorthand,
                    "command":  cmd,
                    "raw":      stripped,
                })
            continue

        # Skip environment variable lines (KEY=VALUE)
        if re.match(r'^\s*\w+=', stripped) and not re.match(r'^\s*\d', stripped):
            continue

        # Standard 5-field or 6-field (system crontabs have user after fields)
        parts = stripped.split()
        if len(parts) < 6:
            continue

        # Detect system crontab format: field[5] is a username (non-numeric, no /)
        is_system = source.startswith("/etc")
        min_fields = 6 if not is_system else 7

        if len(parts) < 6:
            continue

        minute, hour, dom, month, dow = parts[0], parts[1], parts[2], parts[3], parts[4]

        # Try to detect user field in system crontabs
        if is_system and len(parts) >= 7:
            # parts[5] is user if it looks like a username
            user = parts[5]
            cmd  = " ".join(parts[6:])
        else:
            user = ""
            cmd  = " ".join(parts[5:])

        schedule = _human_schedule(minute, hour, dom, month, dow)

        jobs.append({
            "source":   source,
            "user":     user,
            "minute":   minute,
            "hour":     hour,
            "dom":      dom,
            "month":    month,
            "dow":      dow,
            "schedule": schedule,
            "command":  cmd,
            "raw":      stripped,
        })

    return jobs


# ---------------------------------------------------------------------------
# Tab class
# ---------------------------------------------------------------------------

class CronTab(tk.Frame):

    COLS = [
        ("Source",   160, "w"),
        ("User",      80, "w"),
        ("Schedule", 180, "w"),
        ("Command",    0, "w"),
    ]

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._jobs      = []
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

        tk.Label(
            hdr, text="⏰  Cron Jobs",
            bg=t.surface_dark, fg=t.text,
            font=t.font_title, anchor="w",
        ).pack(side="left", padx=18, pady=14)

        self._count_lbl = tk.Label(
            hdr, text="",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small,
        )
        self._count_lbl.pack(side="right", padx=18)

        tk.Button(
            hdr, text="⟳  Refresh",
            command=self.refresh,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat",
            font=t.font_small, padx=12, pady=4,
        ).pack(side="right", padx=(0, 10), pady=10)

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Filter bar
        filter_bar = tk.Frame(self, bg=t.surface, padx=14, pady=8)
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Filter:", bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(side="left")

        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        filter_entry = tk.Entry(filter_bar, textvariable=self._filter_var,
                                font=t.font_regular, width=30)
        t.style_entry(filter_entry)
        filter_entry.pack(side="left", padx=8)

        tk.Button(filter_bar, text="✕", command=lambda: self._filter_var.set(""),
                  bg=t.surface, fg=t.text_muted, bd=0, relief="flat",
                  font=t.font_small).pack(side="left")

        # Source filter checkboxes
        self._show_user   = tk.BooleanVar(value=True)
        self._show_root   = tk.BooleanVar(value=True)
        self._show_system = tk.BooleanVar(value=True)
        for text, var in [("User", self._show_user),
                          ("Root", self._show_root),
                          ("System", self._show_system)]:
            tk.Checkbutton(
                filter_bar, text=text, variable=var,
                command=self._apply_filter,
                bg=t.surface, fg=t.text, selectcolor=t.surface_light,
                activebackground=t.surface, activeforeground=t.text,
                font=t.font_small, bd=0,
            ).pack(side="left", padx=8)

        # Treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=12)

        style = ttk.Style()
        style.configure("Cron.Treeview",
            background=t.surface, foreground=t.text,
            fieldbackground=t.surface, rowheight=28,
            font=t.font_regular,
        )
        style.configure("Cron.Treeview.Heading",
            background=t.surface_dark, foreground=t.text_muted,
            font=t.font_small, relief="flat",
        )
        style.map("Cron.Treeview", background=[("selected", t.blue)])

        col_ids = [c[0] for c in self.COLS]
        self._tree = ttk.Treeview(
            tree_frame,
            columns=col_ids,
            show="headings",
            style="Cron.Treeview",
            selectmode="browse",
        )

        for col_id, width, anchor in self.COLS:
            self._tree.heading(col_id, text=col_id,
                               command=lambda c=col_id: self._sort(c))
            self._tree.column(col_id,
                              width=width if width else 1,
                              minwidth=60,
                              stretch=(width == 0),
                              anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<Double-1>", self._on_double_click)

        # Detail panel (hidden until row selected)
        self._detail_frame = tk.Frame(self, bg=t.surface, padx=14, pady=10)
        self._detail_lbl   = tk.Label(
            self._detail_frame, text="",
            bg=t.surface, fg=t.text_muted,
            font=("Consolas", 10), justify="left", anchor="w", wraplength=900,
        )
        self._detail_lbl.pack(fill="x")

        self._sort_col  = None
        self._sort_rev  = False

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------
    def refresh(self):
        self._count_lbl.config(text="Loading…")
        self._tree.delete(*self._tree.get_children())
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        ssh = self.controller.ssh
        if not ssh.connected:
            self.after(0, lambda: self._count_lbl.config(
                text="Not connected", fg=self.theme.status_stopped))
            return

        jobs = []

        # 1. Current user's crontab
        out, _, code = ssh.run("crontab -l 2>/dev/null")
        if code == 0 and out.strip():
            jobs += _parse_crontab_lines(out, "user crontab")

        # 2. Root crontab
        out, _, code = ssh.run("sudo crontab -l 2>/dev/null")
        if code == 0 and out.strip():
            jobs += _parse_crontab_lines(out, "root crontab")

        # 3. /etc/crontab
        out, _, code = ssh.run("cat /etc/crontab 2>/dev/null")
        if code == 0 and out.strip():
            jobs += _parse_crontab_lines(out, "/etc/crontab")

        # 4. /etc/cron.d/*
        out, _, code = ssh.run("ls /etc/cron.d/ 2>/dev/null")
        if code == 0:
            for fname in out.split():
                fname = fname.strip()
                if fname:
                    content, _, fc = ssh.run(
                        "cat /etc/cron.d/{} 2>/dev/null".format(fname))
                    if fc == 0 and content.strip():
                        jobs += _parse_crontab_lines(
                            content, "/etc/cron.d/{}".format(fname))

        self._jobs = jobs
        self.after(0, lambda j=jobs: self._render(j))

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def _render(self, jobs):
        self._count_lbl.config(
            text="{} job{}".format(len(jobs), "s" if len(jobs) != 1 else ""),
            fg=self.theme.text_muted,
        )
        self._apply_filter()

    def _apply_filter(self):
        q = self._filter_var.get().lower()

        show_user   = self._show_user.get()
        show_root   = self._show_root.get()
        show_system = self._show_system.get()

        self._tree.delete(*self._tree.get_children())

        for job in self._jobs:
            src = job["source"]
            # Source filter
            if "user crontab" in src and not show_user:
                continue
            if "root crontab" in src and not show_root:
                continue
            if ("/etc/cron" in src or "/etc/crontab" == src) and not show_system:
                continue

            # Text filter
            if q and q not in (job["command"] + job["schedule"] + src + job.get("user","")).lower():
                continue

            tag = "root" if "root" in src else ("system" if "/etc" in src else "user")
            self._tree.insert("", "end", values=(
                src,
                job.get("user", ""),
                job["schedule"],
                job["command"],
            ), tags=(tag,), iid=str(id(job)))

            # Store full job ref for double-click
            self._tree.set(str(id(job)), "Source", src)

        # Color tags
        t = self.theme
        self._tree.tag_configure("root",   foreground=t.status_stopped)
        self._tree.tag_configure("system", foreground=t.yellow)
        self._tree.tag_configure("user",   foreground=t.text)

    def _sort(self, col):
        rows = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        rev  = (self._sort_col == col) and not self._sort_rev
        rows.sort(reverse=rev)
        for i, (_, k) in enumerate(rows):
            self._tree.move(k, "", i)
        self._sort_col = col
        self._sort_rev = rev

    def _on_double_click(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]

        # Find matching job by iid (which is str(id(job)))
        job = None
        for j in self._jobs:
            if str(id(j)) == iid:
                job = j
                break
        if not job:
            return

        t = self.theme
        detail_text = (
            "Source:   {source}\n"
            "User:     {user}\n"
            "Schedule: {schedule}  ({minute} {hour} {dom} {month} {dow})\n"
            "Command:  {command}\n\n"
            "Raw:      {raw}"
        ).format(**job)

        self._detail_lbl.config(text=detail_text)
        self._detail_frame.pack(fill="x", padx=16, pady=(0, 12))
