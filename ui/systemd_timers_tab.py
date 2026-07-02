# ui/systemd_timers_tab.py
"""
Systemd Timers tab — shows all active and inactive timer units with
next fire time, last trigger, and the service they activate.
"""

import re
import shlex
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from ui.refresh_control import RefreshControl


def _color_next(left_str, theme):
    """Pick a colour based on the 'LEFT' field (time until next trigger)."""
    if not left_str or left_str in ("-", "n/a", ""):
        return theme.text_muted
    s = left_str.lower()
    if "passed" in s or "ago" in s:
        return theme.status_stopped   # overdue
    for unit in ("sec", "min"):
        if unit in s:
            return theme.yellow        # firing soon
    return theme.status_running        # hours/days away — fine


class SystemdTimersTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._timers    = []
        self._sort_col  = "next"
        self._sort_rev  = False
        self._show_all  = tk.BooleanVar(value=True)
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="SYSTEMD TIMERS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "systemd_timers",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Toolbar
        toolbar = tk.Frame(self, bg=t.bg)
        toolbar.pack(fill="x", padx=16, pady=(0, 6))
        tk.Checkbutton(toolbar, text="Show inactive timers",
                       variable=self._show_all,
                       command=self._redraw,
                       bg=t.bg, fg=t.text, selectcolor=t.bg,
                       activebackground=t.bg, font=t.font_small
                       ).pack(side="left")
        self._enable_btn = tk.Button(toolbar, text="✓ Enable",
                                      command=lambda: self._timer_action("enable"),
                                      state="disabled")
        t.style_button(self._enable_btn)
        self._enable_btn.pack(side="right", padx=(4, 0))
        self._disable_btn = tk.Button(toolbar, text="✕ Disable",
                                       command=lambda: self._timer_action("disable"),
                                       state="disabled")
        t.style_button(self._disable_btn)
        self._disable_btn.pack(side="right", padx=(4, 0))
        self._run_btn = tk.Button(toolbar, text="▶ Run Now",
                                   command=self._run_now,
                                   state="disabled")
        t.style_button(self._run_btn)
        self._run_btn.pack(side="right")

        # Treeview
        cols   = ("unit", "activates", "next", "left", "last", "passed")
        hdgs   = ("Timer Unit", "Activates", "Next Trigger", "In",
                  "Last Trigger", "Ago")
        widths = (220, 200, 180, 100, 180, 100)
        stretches = {"unit", "activates"}

        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("ST.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("ST.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("ST.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings",
                                   style="ST.Treeview", selectmode="browse")
        for col, hdr_txt, w in zip(cols, hdgs, widths):
            self._tree.heading(col, text=hdr_txt, anchor="w",
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, minwidth=40, anchor="w",
                              stretch=(col in stretches))

        self._tree.tag_configure("soon",     foreground=t.yellow)
        self._tree.tag_configure("ok",       foreground=t.status_running)
        self._tree.tag_configure("overdue",  foreground=t.status_stopped)
        self._tree.tag_configure("inactive", foreground=t.text_muted)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-Button-1>",  self._on_double_click)

        # Status bar
        self._status = tk.Label(self, text="Connect to server to view timers",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            return
        self._status.config(text="Loading timers…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            # --all includes inactive timers; --no-pager avoids less
            out, _, code = ssh.run(
                "systemctl list-timers --all --no-pager 2>/dev/null")
            if code != 0 or not out.strip():
                self.after(0, lambda: self._status.config(
                    text="No timer data returned (systemd not available?)",
                    bg=self.theme.surface_dark, fg=self.theme.yellow))
                return
            timers = self._parse(out)
            self._timers = timers
            self.after(0, self._redraw)
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Could not read systemd timers: {}".format(msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # PARSE
    # -----------------------------------------------------------------------
    def _parse(self, output):
        """
        Parse `systemctl list-timers --all` output.
        Columns: NEXT  LEFT  LAST  PASSED  UNIT  ACTIVATES
        The header row identifies column positions by word start.
        """
        lines  = output.splitlines()
        timers = []

        # Find header line to get column offsets
        header_idx = None
        for i, line in enumerate(lines):
            if "NEXT" in line and "UNIT" in line:
                header_idx = i
                break
        if header_idx is None:
            return timers

        h = lines[header_idx]
        # Column starts (best-effort)
        col_starts = {}
        for col in ("NEXT", "LEFT", "LAST", "PASSED", "UNIT", "ACTIVATES"):
            pos = h.find(col)
            if pos >= 0:
                col_starts[col] = pos

        def _field(line, col, next_col=None):
            start = col_starts.get(col, 0)
            end   = col_starts.get(next_col, None) if next_col else None
            return line[start:end].strip() if end else line[start:].strip()

        col_order = ["NEXT", "LEFT", "LAST", "PASSED", "UNIT", "ACTIVATES"]

        for line in lines[header_idx + 1:]:
            if not line.strip() or line.startswith("timers listed"):
                break
            row = {}
            for i, col in enumerate(col_order):
                next_col = col_order[i + 1] if i + 1 < len(col_order) else None
                row[col] = _field(line, col, next_col)
            if not row.get("UNIT"):
                continue
            # Detect inactive: NEXT and LEFT both empty/n/a
            is_active = bool(row.get("NEXT") and row["NEXT"] not in ("-", "n/a"))
            timers.append({
                "unit":      row.get("UNIT", ""),
                "activates": row.get("ACTIVATES", ""),
                "next":      row.get("NEXT", "-"),
                "left":      row.get("LEFT", "-"),
                "last":      row.get("LAST", "-"),
                "passed":    row.get("PASSED", "-"),
                "active":    is_active,
            })
        return timers

    # -----------------------------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------------------------
    def _redraw(self):
        timers = self._timers
        if not self._show_all.get():
            timers = [t for t in timers if t["active"]]

        key = self._sort_col
        rev = self._sort_rev
        timers = sorted(timers, key=lambda r: r.get(key, ""), reverse=rev)

        self._tree.delete(*self._tree.get_children())
        t = self.theme
        for r in timers:
            left = r["left"]
            s = left.lower()
            if not r["active"]:
                tag = "inactive"
            elif "passed" in s or ("ago" in s):
                tag = "overdue"
            elif any(u in s for u in ("sec", "min")):
                tag = "soon"
            else:
                tag = "ok"

            self._tree.insert("", "end", iid=r["unit"], tags=(tag,), values=(
                r["unit"],
                r["activates"],
                r["next"],
                r["left"],
                r["last"],
                r["passed"],
            ))

        active_count = sum(1 for t in self._timers if t["active"])
        self._status.config(
            text="{} timer{}  |  {} active".format(
                len(self._timers),
                "s" if len(self._timers) != 1 else "",
                active_count),
            bg=self.theme.surface_dark, fg=self.theme.text_muted)

    def _sort(self, col):
        self._sort_rev = not self._sort_rev if self._sort_col == col else False
        self._sort_col = col
        self._redraw()

    # -----------------------------------------------------------------------
    # SELECTION & ACTIONS
    # -----------------------------------------------------------------------
    def _on_select(self, _=None):
        has = bool(self._tree.selection())
        state = "normal" if has else "disabled"
        for btn in (self._enable_btn, self._disable_btn, self._run_btn):
            btn.config(state=state)

    def _on_double_click(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        unit = sel[0]
        r = next((t for t in self._timers if t["unit"] == unit), None)
        if not r:
            return
        msg = "\n".join([
            "Unit:      {}".format(r["unit"]),
            "Activates: {}".format(r["activates"]),
            "Next:      {} ({} from now)".format(r["next"], r["left"]),
            "Last:      {} ({} ago)".format(r["last"], r["passed"]),
            "Active:    {}".format("Yes" if r["active"] else "No"),
        ])
        messagebox.showinfo("Timer: {}".format(unit), msg, parent=self)

    def _timer_action(self, action):
        sel = self._tree.selection()
        if not sel:
            return
        unit = sel[0]
        if action == "disable" and not messagebox.askyesno(
                "Disable Timer", "Disable {}?".format(unit), parent=self):
            return
        def _run():
            out, err, code = self.controller.ssh.run_sudo(
                "systemctl {} {}".format(action, shlex.quote(unit)))
            if code == 0:
                self.after(800, self.refresh)
            else:
                self.after(0, lambda: messagebox.showerror(
                    action.capitalize() + " Failed",
                    err or out, parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _run_now(self):
        sel = self._tree.selection()
        if not sel:
            return
        unit = sel[0]
        # Start the associated .service unit (strip .timer → .service)
        service = re.sub(r"\.timer$", ".service", unit)
        if not messagebox.askyesno(
                "Run Now",
                "Start {} immediately?".format(service),
                parent=self):
            return
        def _run():
            out, err, code = self.controller.ssh.run_sudo(
                "systemctl start {}".format(shlex.quote(service)))
            if code == 0:
                self.after(1000, self.refresh)
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Start Failed", err or out, parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def on_show(self):
        if self.controller.ssh.connected:
            self.refresh()
