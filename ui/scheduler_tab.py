# ui/scheduler_tab.py
"""
Automation & Scheduling tab.
Define SSH commands or scripts to run on a cron-like schedule from the app.
Output is logged per-run and notifications fire on failure.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime


# ---------------------------------------------------------------------------
# Schedule display helpers
# ---------------------------------------------------------------------------

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_schedule(task):
    stype = task.get("schedule_type", "interval")
    if stype == "interval":
        m = int(task.get("interval_minutes", 60))
        if m >= 60 and m % 60 == 0:
            return f"Every {m // 60}h"
        return f"Every {m}m"
    if stype == "daily":
        return f"Daily at {task.get('daily_time', '02:00')}"
    if stype == "weekly":
        d = _DAYS_SHORT[int(task.get("weekly_day", 0)) % 7]
        return f"Weekly {d} {task.get('daily_time', '02:00')}"
    return "?"


def _format_last_run(task):
    lr = task.get("last_run")
    if not lr:
        return "Never"
    try:
        dt   = datetime.fromisoformat(lr)
        diff = datetime.now() - dt
        secs = diff.total_seconds()
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{int(secs / 60)}m ago"
        if secs < 86400:
            return f"{int(secs / 3600)}h ago"
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return lr


def _status_label(status):
    return {
        "ok":      "✓  ok",
        "error":   "✗  failed",
        "running": "⟳  running",
        "never":   "—",
    }.get(status, status)


# ---------------------------------------------------------------------------
# Add / Edit task dialog
# ---------------------------------------------------------------------------

def _show_task_dialog(parent_widget, theme, task=None):
    """
    Modal dialog for creating or editing a scheduled task.
    Blocks until closed; returns a kwargs dict for scheduler.add_task /
    scheduler.update_task, or None on cancel.
    """
    t      = theme
    is_edit = task is not None
    result  = [None]

    win = tk.Toplevel(parent_widget)
    win.title("Edit Task" if is_edit else "New Scheduled Task")
    win.configure(bg=t.bg)
    win.resizable(False, False)
    win.grab_set()
    win.attributes("-topmost", True)

    # Header
    tk.Frame(win, bg=t.blue, height=3).pack(fill="x")
    hdr = tk.Frame(win, bg=t.surface_dark, padx=20, pady=12)
    hdr.pack(fill="x")
    tk.Label(hdr,
             text="Edit Task" if is_edit else "New Scheduled Task",
             bg=t.surface_dark, fg=t.text, font=t.font_title).pack(side="left")

    # Body
    body = tk.Frame(win, bg=t.bg, padx=20, pady=14)
    body.pack(fill="both")

    def _lbl_row(label_text):
        f = tk.Frame(body, bg=t.bg)
        f.pack(fill="x", pady=(0, 10))
        tk.Label(f, text=label_text, bg=t.bg, fg=t.text_muted,
                 font=t.font_small, width=14, anchor="w").pack(side="left")
        return f

    # Name
    r = _lbl_row("Name")
    name_var   = tk.StringVar(value=task.get("name", "") if task else "")
    name_entry = tk.Entry(r, textvariable=name_var, font=t.font_regular, width=36)
    t.style_entry(name_entry)
    name_entry.pack(side="left", fill="x", expand=True)

    # Command
    tk.Label(body, text="Command", bg=t.bg, fg=t.text_muted,
             font=t.font_small, anchor="w").pack(anchor="w")
    cmd_frame = tk.Frame(body, bg=t.bg)
    cmd_frame.pack(fill="x", pady=(4, 10))
    cmd_text = tk.Text(cmd_frame, height=3, font=t.font_mono,
                       bg=t.surface_dark, fg=t.text, insertbackground=t.blue,
                       relief="solid", bd=1,
                       highlightthickness=1,
                       highlightbackground=t.card_border,
                       highlightcolor=t.blue,
                       padx=8, pady=6)
    cmd_text.pack(fill="x")
    cmd_text.bind("<FocusIn>",
                  lambda e: cmd_text.configure(highlightbackground=t.blue))
    cmd_text.bind("<FocusOut>",
                  lambda e: cmd_text.configure(highlightbackground=t.card_border))
    if task:
        cmd_text.insert("1.0", task.get("command", ""))

    # Schedule type radios
    tk.Frame(body, bg=t.card_border, height=1).pack(fill="x", pady=(0, 10))
    tk.Label(body, text="Schedule", bg=t.bg, fg=t.text_muted,
             font=t.font_small, anchor="w").pack(anchor="w")

    stype_var = tk.StringVar(
        value=task.get("schedule_type", "interval") if task else "interval")

    type_row = tk.Frame(body, bg=t.bg)
    type_row.pack(fill="x", pady=(4, 8))
    for val, lbl in [("interval", "Interval"), ("daily", "Daily"), ("weekly", "Weekly")]:
        tk.Radiobutton(
            type_row, text=lbl, variable=stype_var, value=val,
            command=lambda: _update_schedule_fields(),
            bg=t.bg, fg=t.text, selectcolor=t.surface,
            activebackground=t.bg, activeforeground=t.text,
            font=t.font_regular, bd=0,
        ).pack(side="left", padx=(0, 20))

    # --- Interval fields ---
    interval_frame = tk.Frame(body, bg=t.bg)
    raw_m = int(task.get("interval_minutes", 60)) if task else 60
    if raw_m >= 60 and raw_m % 60 == 0:
        _iv_val  = str(raw_m // 60)
        _iv_unit = "hours"
    else:
        _iv_val  = str(raw_m)
        _iv_unit = "minutes"
    interval_val_var  = tk.StringVar(value=_iv_val)
    interval_unit_var = tk.StringVar(value=_iv_unit)
    tk.Label(interval_frame, text="Every", bg=t.bg, fg=t.text,
             font=t.font_regular).pack(side="left", padx=(0, 6))
    iv_entry = tk.Entry(interval_frame, textvariable=interval_val_var,
                        font=t.font_regular, width=6)
    t.style_entry(iv_entry)
    iv_entry.pack(side="left")
    ttk.Combobox(interval_frame, textvariable=interval_unit_var,
                 values=["minutes", "hours"], state="readonly",
                 width=9, font=t.font_regular).pack(side="left", padx=(6, 0))

    # --- Daily fields ---
    daily_frame    = tk.Frame(body, bg=t.bg)
    daily_time_var = tk.StringVar(
        value=task.get("daily_time", "02:00") if task else "02:00")
    tk.Label(daily_frame, text="At", bg=t.bg, fg=t.text,
             font=t.font_regular).pack(side="left", padx=(0, 6))
    dt_entry = tk.Entry(daily_frame, textvariable=daily_time_var,
                        font=t.font_regular, width=8)
    t.style_entry(dt_entry)
    dt_entry.pack(side="left")
    tk.Label(daily_frame, text="  HH:MM", bg=t.bg, fg=t.text_muted,
             font=t.font_small).pack(side="left")

    # --- Weekly fields ---
    weekly_frame    = tk.Frame(body, bg=t.bg)
    weekly_day_var  = tk.StringVar(
        value=_DAYS[int(task.get("weekly_day", 0)) % 7] if task else "Monday")
    weekly_time_var = tk.StringVar(
        value=task.get("daily_time", "02:00") if task else "02:00")
    tk.Label(weekly_frame, text="On", bg=t.bg, fg=t.text,
             font=t.font_regular).pack(side="left", padx=(0, 6))
    ttk.Combobox(weekly_frame, textvariable=weekly_day_var,
                 values=_DAYS, state="readonly",
                 width=12, font=t.font_regular).pack(side="left")
    tk.Label(weekly_frame, text="  at", bg=t.bg, fg=t.text,
             font=t.font_regular).pack(side="left", padx=(6, 6))
    wt_entry = tk.Entry(weekly_frame, textvariable=weekly_time_var,
                        font=t.font_regular, width=8)
    t.style_entry(wt_entry)
    wt_entry.pack(side="left")
    tk.Label(weekly_frame, text="  HH:MM", bg=t.bg, fg=t.text_muted,
             font=t.font_small).pack(side="left")

    def _update_schedule_fields():
        interval_frame.pack_forget()
        daily_frame.pack_forget()
        weekly_frame.pack_forget()
        st = stype_var.get()
        if st == "interval":
            interval_frame.pack(fill="x", pady=(0, 10))
        elif st == "daily":
            daily_frame.pack(fill="x", pady=(0, 10))
        elif st == "weekly":
            weekly_frame.pack(fill="x", pady=(0, 10))

    _update_schedule_fields()

    # Checkboxes
    tk.Frame(body, bg=t.card_border, height=1).pack(fill="x", pady=(4, 10))
    check_row  = tk.Frame(body, bg=t.bg)
    check_row.pack(fill="x", pady=(0, 8))
    enabled_var = tk.BooleanVar(value=task.get("enabled", True) if task else True)
    notify_var  = tk.BooleanVar(
        value=task.get("notify_on_failure", True) if task else True)

    for text, var in [("Enabled", enabled_var), ("Notify on failure", notify_var)]:
        tk.Checkbutton(
            check_row, text=text, variable=var,
            bg=t.bg, fg=t.text, selectcolor=t.surface,
            activebackground=t.bg, activeforeground=t.text,
            font=t.font_regular, bd=0,
        ).pack(side="left", padx=(0, 24))

    # Buttons
    btn_row = tk.Frame(body, bg=t.bg)
    btn_row.pack(fill="x", pady=(4, 0))

    def _cancel():
        win.destroy()

    def _save():
        name = name_var.get().strip()
        cmd  = cmd_text.get("1.0", "end").strip()
        if not name:
            name_entry.configure(highlightbackground=t.status_stopped,
                                 highlightthickness=2)
            return
        if not cmd:
            cmd_text.configure(highlightbackground=t.status_stopped)
            return

        st = stype_var.get()
        if st == "interval":
            try:
                val       = int(interval_val_var.get())
                unit      = interval_unit_var.get()
                interval_m = val * (60 if unit == "hours" else 1)
            except ValueError:
                return
            result[0] = dict(
                name=name, command=cmd, schedule_type="interval",
                interval_minutes=interval_m, daily_time="02:00", weekly_day=0,
                enabled=enabled_var.get(), notify_on_failure=notify_var.get(),
            )
        elif st == "daily":
            result[0] = dict(
                name=name, command=cmd, schedule_type="daily",
                interval_minutes=60,
                daily_time=daily_time_var.get().strip(), weekly_day=0,
                enabled=enabled_var.get(), notify_on_failure=notify_var.get(),
            )
        elif st == "weekly":
            day_idx = _DAYS.index(weekly_day_var.get()) \
                      if weekly_day_var.get() in _DAYS else 0
            result[0] = dict(
                name=name, command=cmd, schedule_type="weekly",
                interval_minutes=60,
                daily_time=weekly_time_var.get().strip(), weekly_day=day_idx,
                enabled=enabled_var.get(), notify_on_failure=notify_var.get(),
            )
        win.destroy()

    cancel_btn = tk.Button(btn_row, text="Cancel", command=_cancel)
    t.style_button(cancel_btn)
    cancel_btn.pack(side="right")

    save_btn = tk.Button(btn_row, text="Save", command=_save)
    t.style_button(save_btn, "primary")
    save_btn.pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda e: win.destroy())
    win.bind("<Return>",  lambda e: _save())

    # Center on parent toplevel
    win.update_idletasks()
    root = parent_widget.winfo_toplevel()
    rx, ry = root.winfo_x(), root.winfo_y()
    rw, rh = root.winfo_width(), root.winfo_height()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"{ww}x{wh}+{rx + (rw - ww) // 2}+{ry + (rh - wh) // 2}")

    parent_widget.wait_window(win)
    return result[0]


# ---------------------------------------------------------------------------
# Tab class
# ---------------------------------------------------------------------------

class SchedulerTab(tk.Frame):

    COLUMNS = [
        ("Name",     190, "w"),
        ("Schedule", 150, "w"),
        ("Next Run", 110, "center"),
        ("Last Run", 110, "center"),
        ("Status",    90, "center"),
    ]

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller         = controller
        self.theme              = t
        self._selected_task_id  = None
        self._refresh_job       = None
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------

    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📅  Automation & Scheduling",
                 bg=t.surface_dark, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", padx=18, pady=14)
        self._count_lbl = tk.Label(hdr, text="",
                                   bg=t.surface_dark, fg=t.text_muted,
                                   font=t.font_small)
        self._count_lbl.pack(side="right", padx=18)
        add_btn = tk.Button(hdr, text="+ Add Task", command=self._add_task,
                            bg=t.blue, fg="#ffffff", bd=0, relief="flat",
                            font=t.font_small, padx=12, pady=4, cursor="hand2")
        add_btn.pack(side="right", padx=(0, 10), pady=10)
        add_btn.bind("<Enter>", lambda e: add_btn.configure(bg=t.blue_bright))
        add_btn.bind("<Leave>", lambda e: add_btn.configure(bg=t.blue))
        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Vertical paned window: task list (top) / output (bottom)
        pane = tk.PanedWindow(self, orient="vertical",
                              sashwidth=5, sashrelief="flat",
                              bg=t.card_border)
        pane.pack(fill="both", expand=True)

        # ── Top: task list + actions ───────────────────────────────────
        top = tk.Frame(pane, bg=t.bg)
        pane.add(top, minsize=200)

        list_frame = tk.Frame(top, bg=t.bg)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(10, 4))

        style = ttk.Style()
        style.configure("Sched.Treeview",
                        background=t.surface, foreground=t.text,
                        fieldbackground=t.surface, rowheight=28,
                        font=t.font_regular)
        style.configure("Sched.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("Sched.Treeview",
                  background=[("selected", t.blue)],
                  foreground=[("selected", "#ffffff")])

        col_ids = [c[0] for c in self.COLUMNS]
        self._tree = ttk.Treeview(list_frame, columns=col_ids, show="headings",
                                  style="Sched.Treeview", selectmode="browse")
        for col_id, width, anchor in self.COLUMNS:
            self._tree.heading(col_id, text=col_id)
            self._tree.column(col_id, width=width, minwidth=60,
                              stretch=(col_id == "Name"), anchor=anchor)

        vsb = ttk.Scrollbar(list_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", lambda e: self._edit_task())

        # Action bar
        actions = tk.Frame(top, bg=t.bg)
        actions.pack(fill="x", padx=16, pady=(0, 8))

        self._edit_btn   = tk.Button(actions, text="Edit",
                                     command=self._edit_task)
        self._del_btn    = tk.Button(actions, text="Delete",
                                     command=self._delete_task)
        self._run_btn    = tk.Button(actions, text="▶  Run Now",
                                     command=self._run_now)
        self._toggle_btn = tk.Button(actions, text="Enable / Disable",
                                     command=self._toggle_enable)

        for btn in (self._edit_btn, self._del_btn,
                    self._run_btn, self._toggle_btn):
            t.style_button(btn)
            btn.pack(side="left", padx=(0, 6))
            btn.configure(state="disabled")

        # ── Bottom: output / run history ───────────────────────────────
        bot = tk.Frame(pane, bg=t.bg)
        pane.add(bot, minsize=160)

        self._output_hdr = tk.Label(
            bot, text="Select a task to view output",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_title, anchor="w", padx=14, pady=8)
        self._output_hdr.pack(fill="x")
        tk.Frame(bot, bg=t.card_border, height=1).pack(fill="x")

        # Run history selector
        hist_bar = tk.Frame(bot, bg=t.surface_dark, padx=12, pady=6)
        hist_bar.pack(fill="x")
        tk.Label(hist_bar, text="Run:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 6))
        self._hist_var  = tk.StringVar()
        self._hist_list = ttk.Combobox(hist_bar, textvariable=self._hist_var,
                                       state="readonly", width=50,
                                       font=t.font_small)
        self._hist_list.pack(side="left")
        self._hist_list.bind("<<ComboboxSelected>>", self._on_history_select)

        # Output text
        out_frame = tk.Frame(bot, bg=t.bg)
        out_frame.pack(fill="both", expand=True, padx=14, pady=(6, 10))
        self._output = tk.Text(
            out_frame,
            bg=t.surface_dark, fg=t.text, font=t.font_mono,
            wrap="word", state="disabled", relief="flat", padx=10, pady=8)
        self._output.pack(side="left", fill="both", expand=True)
        osb = tk.Scrollbar(out_frame, command=self._output.yview)
        osb.pack(side="right", fill="y")
        self._output.configure(yscrollcommand=osb.set)
        self._output.tag_config("ok",      foreground=t.status_running)
        self._output.tag_config("error",   foreground=t.status_stopped)
        self._output.tag_config("running", foreground=t.blue)
        self._output.tag_config("dim",     foreground=t.text_muted)
        self._output.tag_config("hdr",     foreground=t.text_secondary)

    # ------------------------------------------------------------------
    # SHOW / HIDE  (called by main.py on tab switch)
    # ------------------------------------------------------------------

    def on_show(self):
        self.refresh()
        self._start_auto_refresh()

    def _start_auto_refresh(self):
        self._cancel_auto_refresh()
        self._refresh_job = self.after(10_000, self._auto_refresh)

    def _cancel_auto_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None

    def _auto_refresh(self):
        self.refresh()
        try:
            sel_idx = self.controller.tabs.index(self.controller.tabs.select())
            my_idx  = self.controller.tabs.index(self)
            if sel_idx == my_idx:
                self._refresh_job = self.after(10_000, self._auto_refresh)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------

    def refresh(self):
        scheduler = self.controller.scheduler
        tasks     = scheduler.get_tasks()
        sel_id    = self._selected_task_id

        self._tree.delete(*self._tree.get_children())

        for task in tasks:
            tid        = task["id"]
            is_running = scheduler.is_running(tid)
            status     = "running" if is_running else task.get("last_status", "never")

            name = task.get("name", "?")
            if not task.get("enabled", True):
                name = f"[off]  {name}"

            tag = {"ok": "ok", "error": "error",
                   "running": "running"}.get(status, "never")

            self._tree.insert("", "end", iid=tid, tags=(tag,), values=(
                name,
                _format_schedule(task),
                scheduler.next_run_str(task),
                _format_last_run(task),
                _status_label(status),
            ))

        t = self.theme
        self._tree.tag_configure("ok",      foreground=t.status_running)
        self._tree.tag_configure("error",   foreground=t.status_stopped)
        self._tree.tag_configure("running", foreground=t.blue)
        self._tree.tag_configure("never",   foreground=t.text_muted)

        n_active = sum(1 for t in tasks if t.get("enabled", True))
        n_total  = len(tasks)
        self._count_lbl.config(
            text=f"{n_total} task{'s' if n_total != 1 else ''}  ·  {n_active} active")

        # Restore selection
        has_sel = bool(sel_id and self._tree.exists(sel_id))
        if has_sel:
            self._tree.selection_set(sel_id)
            self._update_output_panel(sel_id)
        state = "normal" if has_sel else "disabled"
        for btn in (self._edit_btn, self._del_btn,
                    self._run_btn, self._toggle_btn):
            btn.configure(state=state)

    # ------------------------------------------------------------------
    # SELECTION & OUTPUT PANEL
    # ------------------------------------------------------------------

    def _on_select(self, event):
        sel = self._tree.selection()
        if sel:
            self._selected_task_id = sel[0]
            self._update_output_panel(sel[0])
            for btn in (self._edit_btn, self._del_btn,
                        self._run_btn, self._toggle_btn):
                btn.configure(state="normal")
        else:
            self._selected_task_id = None
            for btn in (self._edit_btn, self._del_btn,
                        self._run_btn, self._toggle_btn):
                btn.configure(state="disabled")

    def _update_output_panel(self, task_id):
        task = self._get_task(task_id)
        if not task:
            return
        name = task.get("name", "?")
        log  = task.get("output_log", [])

        n = len(log)
        self._output_hdr.config(
            text=f"Output — {name}  ({n} run{'s' if n != 1 else ''})")

        if log:
            entries = []
            for e in log:
                icon = "✓" if e.get("exit_code", 1) == 0 else "✗"
                entries.append(f"{e['ts']}  exit:{e['exit_code']}  {icon}")
            self._hist_list["values"] = entries
            self._hist_list.current(0)
            self._show_run_output(log[0])
        else:
            self._hist_list["values"] = []
            self._hist_var.set("")
            self._set_output("No runs yet.", "dim")

    def _on_history_select(self, event):
        task = self._get_task(self._selected_task_id)
        if not task:
            return
        idx = self._hist_list.current()
        log = task.get("output_log", [])
        if 0 <= idx < len(log):
            self._show_run_output(log[idx])

    def _show_run_output(self, entry):
        code = entry.get("exit_code", 0)
        out  = entry.get("output", "") or "(no output)"
        tag  = "ok" if code == 0 else "error"
        sep  = "─" * 50
        header = f"[{entry['ts']}]  exit: {code}\n{sep}\n"
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("end", header, "hdr")
        self._output.insert("end", out, tag)
        self._output.configure(state="disabled")

    def _set_output(self, text, tag=None):
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("end", text, tag or "")
        self._output.configure(state="disabled")

    def _get_task(self, task_id):
        if not task_id:
            return None
        for task in self.controller.scheduler.get_tasks():
            if task["id"] == task_id:
                return task
        return None

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _add_task(self):
        kwargs = _show_task_dialog(self, self.theme)
        if kwargs:
            self.controller.scheduler.add_task(**kwargs)
            self.refresh()

    def _edit_task(self):
        task = self._get_task(self._selected_task_id)
        if not task:
            return
        kwargs = _show_task_dialog(self, self.theme, task)
        if kwargs:
            self.controller.scheduler.update_task(task["id"], **kwargs)
            self.refresh()

    def _delete_task(self):
        task = self._get_task(self._selected_task_id)
        if not task:
            return
        if messagebox.askyesno(
                "Delete Task",
                f"Delete task '{task.get('name', '')}'?",
                parent=self):
            self.controller.scheduler.delete_task(task["id"])
            self._selected_task_id = None
            self.refresh()

    def _run_now(self):
        if not self._selected_task_id:
            return
        ok = self.controller.scheduler.run_now(self._selected_task_id)
        if ok:
            task = self._get_task(self._selected_task_id)
            name = task.get("name", "Task") if task else "Task"
            self.controller.show_toast(f"Running: {name}", "Started in background.",
                                       level="info")
            self.after(2000, self.refresh)
        else:
            self.controller.show_toast("Already running",
                                       "This task is still executing.", level="warn")

    def _toggle_enable(self):
        task = self._get_task(self._selected_task_id)
        if not task:
            return
        self.controller.scheduler.update_task(
            task["id"], enabled=not task.get("enabled", True))
        self.refresh()
