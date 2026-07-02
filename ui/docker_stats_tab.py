# ui/docker_stats_tab.py
"""
Docker container live-stats tab.

Runs `docker stats --no-stream` on the remote server and displays per-container
CPU, memory, network, and block I/O metrics in a sortable Treeview.
Double-clicking a row shows a full-detail dialog for that container.
"""

import json
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from ui.refresh_control import RefreshControl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_pct(s):
    """Remove trailing '%' and convert to float."""
    try:
        return float(s.strip().rstrip("%"))
    except (ValueError, TypeError):
        return 0.0


def _try_int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


def _try_float_col(row, key):
    return _strip_pct(row.get(key, "0"))


# ---------------------------------------------------------------------------
# Tab
# ---------------------------------------------------------------------------

_DOCKER_STATS_CMD = (
    "docker stats --no-stream --format "
    "'{\"n\":\"{{.Name}}\",\"c\":\"{{.CPUPerc}}\",\"mu\":\"{{.MemUsage}}\","
    "\"mp\":\"{{.MemPerc}}\",\"net\":\"{{.NetIO}}\",\"blk\":\"{{.BlockIO}}\","
    "\"p\":\"{{.PIDs}}\"}' 2>/dev/null"
)


class DockerStatsTab(tk.Frame):

    _COL_DEFS = [
        # (col_id, heading, width, stretch, anchor)
        ("name",    "Name",       200, True,  "w"),
        ("cpu",     "CPU%",        80, False, "e"),
        ("mem_pct", "MEM%",        80, False, "e"),
        ("mem_use", "MEM Usage",  160, False, "w"),
        ("net",     "NET I/O",    140, False, "w"),
        ("blk",     "Block I/O",  140, False, "w"),
        ("pids",    "PIDs",        50, False, "e"),
    ]

    _NUMERIC_COLS = {"cpu", "mem_pct", "pids"}

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._all_rows  = []        # list of parsed row dicts
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

        tk.Label(hdr, text="DOCKER STATS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "docker_stats",
                                  default=10, on_refresh=self.refresh)
        self._rc.pack(side="right")

        self._ts_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                font=t.font_small)
        self._ts_lbl.pack(side="right", padx=10)

        btn_refresh = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn_refresh)
        btn_refresh.pack(side="right", padx=(0, 6))

        # ── Summary cards row ─────────────────────────────────────────
        cards_row = tk.Frame(self, bg=t.bg)
        cards_row.pack(fill="x", padx=16, pady=(0, 10))

        self._card_total   = self._make_summary_card(cards_row, "Containers", "—")
        self._card_running = self._make_summary_card(cards_row, "Running",    "—")
        self._card_cpu     = self._make_summary_card(cards_row, "Total CPU%", "—")
        self._card_mem     = self._make_summary_card(cards_row, "Total MEM%", "—")

        # ── Treeview ──────────────────────────────────────────────────
        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("DS.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=24, font=t.font_mono)
        style.configure("DS.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("DS.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        col_ids = [c[0] for c in self._COL_DEFS]
        self._tree = ttk.Treeview(tree_fr, columns=col_ids, show="headings",
                                  style="DS.Treeview", selectmode="browse")

        for col_id, heading, width, stretch, anchor in self._COL_DEFS:
            self._tree.heading(col_id, text=heading, anchor=anchor,
                               command=lambda c=col_id: self._sort(c))
            self._tree.column(col_id, width=width, minwidth=30,
                              anchor=anchor, stretch=stretch)

        self._tree.tag_configure("high", foreground=t.status_stopped)
        self._tree.tag_configure("med",  foreground=t.yellow)
        self._tree.tag_configure("low",  foreground=t.status_running)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-Button-1>", self._on_double_click)

        # ── Status bar ────────────────────────────────────────────────
        self._status = tk.Label(self, text="Ready",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    def _make_summary_card(self, parent, label, value):
        """Create a small summary card and return a dict with its value label."""
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border,
                        highlightthickness=1)
        card.pack(side="left", padx=(0, 10), pady=4, ipadx=14, ipady=8)

        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=10, pady=(6, 0))

        val_lbl = tk.Label(card, text=value, bg=t.card_bg, fg=t.text,
                           font=t.font_title)
        val_lbl.pack(anchor="w", padx=10, pady=(2, 6))

        return val_lbl

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def on_show(self):
        if self.controller.ssh.connected:
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
                                fg=self.theme.status_stopped)
            return
        self._status.config(text="Loading…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            out, err, code = self.controller.ssh.run(_DOCKER_STATS_CMD)
            rows = self._parse(out)
            self._all_rows = rows
            ts = time.strftime("%H:%M:%S")
            self.after(0, lambda: self._render(rows))
            self.after(0, lambda: self._update_summary(rows))
            self.after(0, lambda: self._status.config(
                text="{} container{}  |  Updated {}".format(
                    len(rows), "s" if len(rows) != 1 else "", ts),
                bg=self.theme.surface_dark, fg=self.theme.text_muted))
            self.after(0, lambda: self._ts_lbl.config(
                text="Updated {}".format(ts)))
            self.after(0, self._rc.schedule)
        except Exception as e:
            self.after(0, lambda: self._status.config(
                text="Error: {}".format(e),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
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
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append({
                "name":    obj.get("n", ""),
                "cpu":     obj.get("c", "0%"),
                "mem_pct": obj.get("mp", "0%"),
                "mem_use": obj.get("mu", ""),
                "net":     obj.get("net", ""),
                "blk":     obj.get("blk", ""),
                "pids":    obj.get("p", "0"),
            })
        return rows

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------

    def _render(self, rows):
        col = self._sort_col
        rev = self._sort_rev

        if col in self._NUMERIC_COLS:
            rows = sorted(rows,
                          key=lambda r: _try_float_col(r, col),
                          reverse=rev)
        else:
            rows = sorted(rows,
                          key=lambda r: r.get(col, "").lower(),
                          reverse=rev)

        self._tree.delete(*self._tree.get_children())
        for r in rows:
            cpu_val = _strip_pct(r["cpu"])
            if cpu_val > 50.0:
                tag = "high"
            elif cpu_val > 10.0:
                tag = "med"
            else:
                tag = "low"

            # Display CPU% and MEM% stripped of the '%' suffix for sorting;
            # keep original strings with '%' in the display.
            cpu_disp = r["cpu"].strip()
            mem_disp = r["mem_pct"].strip()

            self._tree.insert("", "end", tags=(tag,),
                              values=(r["name"], cpu_disp, mem_disp,
                                      r["mem_use"], r["net"], r["blk"],
                                      r["pids"]))

    def _sort(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = True
        self._render(list(self._all_rows))

    # ------------------------------------------------------------------
    # SUMMARY CARDS
    # ------------------------------------------------------------------

    def _update_summary(self, rows):
        total = len(rows)
        running = sum(
            1 for r in rows
            if _strip_pct(r["cpu"]) > 0 or _try_int(r["pids"]) > 0
        )
        total_cpu = sum(_strip_pct(r["cpu"]) for r in rows)
        total_mem = sum(_strip_pct(r["mem_pct"]) for r in rows)

        self._card_total.config(text=str(total))
        self._card_running.config(text=str(running))
        self._card_cpu.config(text="{:.1f}%".format(total_cpu))
        self._card_mem.config(text="{:.1f}%".format(total_mem))

    # ------------------------------------------------------------------
    # DOUBLE-CLICK DETAIL
    # ------------------------------------------------------------------

    def _on_double_click(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        vals = self._tree.item(iid, "values")
        if not vals:
            return
        name, cpu, mem_pct, mem_use, net, blk, pids = vals

        detail = (
            "Container:  {}\n"
            "CPU%:       {}\n"
            "MEM%:       {}\n"
            "MEM Usage:  {}\n"
            "NET I/O:    {}\n"
            "Block I/O:  {}\n"
            "PIDs:       {}"
        ).format(name, cpu, mem_pct, mem_use, net, blk, pids)

        messagebox.showinfo(
            "Container Details — {}".format(name),
            detail,
            parent=self)
