# ui/process_tab.py
"""
Process viewer tab.

Shows the top-60 processes from the remote server, with client-side
filtering by user or command name, column sorting, and kill/renice actions.
"""

import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from ui.refresh_control import RefreshControl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _try_int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Tab
# ---------------------------------------------------------------------------

class ProcessTab(tk.Frame):

    _COL_DEFS = [
        # (col_id, heading, width, stretch, anchor)
        ("pid",   "PID",      60, False, "e"),
        ("ppid",  "PPID",     60, False, "e"),
        ("user",  "User",    100, False, "w"),
        ("cpu",   "CPU%",     70, False, "e"),
        ("mem",   "MEM%",     70, False, "e"),
        ("vsz",   "VSZ",      80, False, "e"),
        ("rss",   "RSS",      80, False, "e"),
        ("state", "State",    60, False, "w"),
        ("comm",  "Command", 300, True,  "w"),
    ]

    _NUMERIC_COLS = {"pid", "ppid", "cpu", "mem", "vsz", "rss"}

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._all_rows  = []        # list of row dicts from last fetch
        self._sort_col  = "cpu"
        self._sort_rev  = True      # CPU% descending by default
        self._fetching  = False
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------

    def _build_ui(self):
        t = self.theme

        # ── Header row ────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(hdr, text="PROCESSES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "processes",
                                  default=5, on_refresh=self.refresh)
        self._rc.pack(side="right")

        self._ts_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                font=t.font_small)
        self._ts_lbl.pack(side="right", padx=10)

        btn_refresh = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn_refresh)
        btn_refresh.pack(side="right", padx=(0, 6))

        # ── Filter row ────────────────────────────────────────────────
        frow = tk.Frame(self, bg=t.bg)
        frow.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(frow, text="Filter:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")

        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        fe = tk.Entry(frow, textvariable=self._filter_var,
                      font=t.font_regular, width=28)
        t.style_entry(fe)
        fe.pack(side="left", padx=(6, 4))

        btn_clear = tk.Button(frow, text="✕",
                              command=lambda: self._filter_var.set(""))
        t.style_button(btn_clear)
        btn_clear.pack(side="left")

        # ── Treeview ──────────────────────────────────────────────────
        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Proc.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=22, font=t.font_mono)
        style.configure("Proc.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("Proc.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        col_ids = [c[0] for c in self._COL_DEFS]
        self._tree = ttk.Treeview(tree_fr, columns=col_ids, show="headings",
                                  style="Proc.Treeview", selectmode="browse")

        for col_id, heading, width, stretch, anchor in self._COL_DEFS:
            self._tree.heading(col_id, text=heading, anchor=anchor,
                               command=lambda c=col_id: self._sort(c))
            self._tree.column(col_id, width=width, minwidth=30,
                              anchor=anchor, stretch=stretch)

        self._tree.tag_configure("cpu_high", foreground=t.status_stopped_text)
        self._tree.tag_configure("cpu_med",  foreground=t.yellow)
        self._tree.tag_configure("normal",   foreground=t.text)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Action buttons ────────────────────────────────────────────
        arow = tk.Frame(self, bg=t.bg)
        arow.pack(fill="x", padx=16, pady=(2, 6))

        self._btn_sigterm = tk.Button(arow, text="⏹ Kill (SIGTERM)",
                                      command=self._kill_sigterm,
                                      state="disabled")
        t.style_button(self._btn_sigterm)
        self._btn_sigterm.pack(side="left", padx=(0, 6))

        self._btn_kill9 = tk.Button(arow, text="💀 Kill -9",
                                    command=self._kill9,
                                    state="disabled")
        t.style_button(self._btn_kill9)
        self._btn_kill9.pack(side="left", padx=(0, 6))

        self._btn_renice = tk.Button(arow, text="⟳ Renice…",
                                     command=self._renice,
                                     state="disabled")
        t.style_button(self._btn_renice)
        self._btn_renice.pack(side="left")

        # ── Status bar ────────────────────────────────────────────────
        self._status = tk.Label(self, text="Ready",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def on_show(self):
        # Always call refresh() — see docker_stats_tab.py for why gating
        # this on connection state hid the "Not connected" message too.
        self.refresh()

    # ------------------------------------------------------------------
    # REFRESH / FETCH
    # ------------------------------------------------------------------

    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected to SSH",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped_text)
            return
        self._status.config(text="Loading…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            cmd = ("ps -eo pid,ppid,user,pcpu,pmem,vsz,rss,stat,comm "
                   "--sort=-%cpu --no-headers 2>/dev/null | head -60")
            out, err, code = self.controller.ssh.run(cmd)
            rows = self._parse(out)
            self._all_rows = rows
            ts = time.strftime("%H:%M:%S")
            self.after(0, self._apply_filter)
            self.after(0, lambda: self._status.config(
                text="{} processes  |  Updated {}".format(len(rows), ts),
                bg=self.theme.surface_dark, fg=self.theme.text_muted))
            self.after(0, lambda: self._ts_lbl.config(
                text="Updated {}".format(ts)))
            self.after(0, self._rc.schedule)
        except Exception as e:
            self.after(0, lambda err=str(e): self._status.config(
                text="Error: {}".format(err),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped_text))
        finally:
            self._fetching = False

    # ------------------------------------------------------------------
    # PARSE
    # ------------------------------------------------------------------

    def _parse(self, output):
        rows = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Split into at most 9 tokens: 8 fixed fields + command (rest)
            parts = line.split(None, 8)
            if len(parts) < 8:
                continue
            pid, ppid, user, cpu, mem, vsz, rss, state = parts[:8]
            comm = parts[8].strip() if len(parts) > 8 else ""
            rows.append({
                "pid":   pid,
                "ppid":  ppid,
                "user":  user,
                "cpu":   cpu,
                "mem":   mem,
                "vsz":   vsz,
                "rss":   rss,
                "state": state,
                "comm":  comm,
            })
        return rows

    # ------------------------------------------------------------------
    # FILTER + RENDER
    # ------------------------------------------------------------------

    def _apply_filter(self):
        q = self._filter_var.get().strip().lower()
        if q:
            rows = [r for r in self._all_rows
                    if q in r["user"].lower() or q in r["comm"].lower()]
        else:
            rows = list(self._all_rows)
        self._render(rows)

    def _render(self, rows):
        col = self._sort_col
        rev = self._sort_rev
        if col in self._NUMERIC_COLS:
            rows = sorted(rows,
                          key=lambda r: _try_float(r.get(col, "0")),
                          reverse=rev)
        else:
            rows = sorted(rows,
                          key=lambda r: r.get(col, "").lower(),
                          reverse=rev)

        self._tree.delete(*self._tree.get_children())
        for r in rows:
            cpu_val = _try_float(r["cpu"])
            if cpu_val > 10.0:
                tag = "cpu_high"
            elif cpu_val > 2.0:
                tag = "cpu_med"
            else:
                tag = "normal"
            self._tree.insert("", "end", tags=(tag,),
                              values=(r["pid"], r["ppid"], r["user"],
                                      r["cpu"], r["mem"], r["vsz"], r["rss"],
                                      r["state"], r["comm"]))

    def _sort(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = True
        self._apply_filter()

    # ------------------------------------------------------------------
    # SELECTION
    # ------------------------------------------------------------------

    def _on_select(self, _=None):
        sel = self._tree.selection()
        state = "normal" if sel else "disabled"
        self._btn_sigterm.config(state=state)
        self._btn_kill9.config(state=state)
        self._btn_renice.config(state=state)

    def _selected_pid(self):
        sel = self._tree.selection()
        if not sel:
            return None
        return self._tree.set(sel[0], "pid")

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _kill_sigterm(self):
        pid = self._selected_pid()
        if pid is None:
            return
        if not messagebox.askyesno(
                "Kill Process",
                "Send SIGTERM to PID {}?".format(pid),
                parent=self):
            return
        threading.Thread(target=self._do_kill, args=(pid, 15),
                         daemon=True).start()

    def _kill9(self):
        pid = self._selected_pid()
        if pid is None:
            return
        if not messagebox.askyesno(
                "Force Kill",
                "Send SIGKILL (-9) to PID {}?\n\nThis cannot be undone.".format(pid),
                parent=self):
            return
        threading.Thread(target=self._do_kill, args=(pid, 9),
                         daemon=True).start()

    def _do_kill(self, pid, sig):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            self.after(0, lambda: self._status.config(
                text="Invalid PID: {}".format(pid),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
            return
        out, err, code = self.controller.ssh.run_sudo(
            "kill -{} {}".format(int(sig), pid))
        if code == 0:
            self.after(0, lambda: self._status.config(
                text="Sent signal {} to PID {}".format(sig, pid),
                bg=self.theme.surface_dark, fg=self.theme.text_muted))
            self.after(1200, self.refresh)
        else:
            msg = (err or out or "unknown error").strip()
            self.after(0, lambda: self._status.config(
                text="kill -{} {} failed: {}".format(sig, pid, msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped_text))

    def _renice(self):
        pid = self._selected_pid()
        if pid is None:
            return
        value = simpledialog.askinteger(
            "Renice", "Nice value (-20 to 19):",
            minvalue=-20, maxvalue=19, parent=self)
        if value is None:
            return
        threading.Thread(target=self._do_renice, args=(pid, value),
                         daemon=True).start()

    def _do_renice(self, pid, value):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            self.after(0, lambda: self._status.config(
                text="Invalid PID: {}".format(pid),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
            return
        out, err, code = self.controller.ssh.run_sudo(
            "renice {} -p {}".format(int(value), pid))
        if code == 0:
            self.after(0, lambda: self._status.config(
                text="Reniced PID {} to nice value {}".format(pid, value),
                bg=self.theme.surface_dark, fg=self.theme.text_muted))
            self.after(1200, self.refresh)
        else:
            msg = (err or out or "unknown error").strip()
            self.after(0, lambda: self._status.config(
                text="renice failed: {}".format(msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped_text))
