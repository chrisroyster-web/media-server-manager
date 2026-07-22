# ui/watchdog_tab.py
"""
Status view for main.py's background watchdog threads (service, backup,
SSL expiry, disk/pool health, docker health, mount drop, VPN, security,
vuln scan, media integrity, recyclarr, daily digest, SAB completion).

Reads core.watchdog_registry.WatchdogRegistry.snapshot() -- an in-memory
dict, not an SSH round trip -- so this never needs the tab's usual
"not connected" gating. Exists so a watchdog that starts silently erroring
(or, before the registry existed, dying outright on an uncaught exception)
is visible somewhere instead of invisible forever.
"""

import tkinter as tk
from tkinter import ttk
import time


class WatchdogTab(tk.Frame):

    # Grace factor applied to a watchdog's own interval before its silence
    # is flagged as "stale" rather than just "hasn't ticked yet".
    STALE_FACTOR = 3

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="WATCHDOGS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_ok     = self._stat_card(s_row, "OK",       "--", t.status_running)
        self._card_stale  = self._stat_card(s_row, "Stale",    "--", t.yellow)
        self._card_error  = self._stat_card(s_row, "Error",    "--", t.status_stopped)
        self._card_never  = self._stat_card(s_row, "Never Run","--", t.text_muted)

        # Table
        tbl_frame = tk.Frame(self, bg=t.bg)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        style.configure("Watchdog.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=28, font=t.font_mono)
        style.configure("Watchdog.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("Watchdog.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("name", "status", "interval", "last_run", "checks", "errors", "last_error")
        self._tree = ttk.Treeview(tbl_frame, columns=cols,
                                   show="headings", style="Watchdog.Treeview")
        for col, w, lbl, anchor in [
            ("name",       200, "Watchdog",    "w"),
            ("status",      80, "Status",      "center"),
            ("interval",    90, "Interval",    "e"),
            ("last_run",   150, "Last Run",    "w"),
            ("checks",      70, "Checks",      "e"),
            ("errors",      70, "Errors",      "e"),
            ("last_error", 320, "Last Error",  "w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anchor)
            self._tree.column(col, width=w, minwidth=50,
                              anchor=anchor, stretch=(col == "last_error"))

        self._tree.tag_configure("ok",    foreground=t.status_running)
        self._tree.tag_configure("stale", foreground=t.yellow)
        self._tree.tag_configure("error", foreground=t.status_stopped_text)
        self._tree.tag_configure("never", foreground=t.text_muted)

        vsb = tk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status bar
        self._status = tk.Label(self, text="", bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        self.refresh()

    def _stat_card(self, parent, label, value, color):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    # =========================================================
    # REFRESH  (in-memory read, no SSH round trip)
    # =========================================================
    def refresh(self):
        snapshot = self.controller.watchdog_registry.snapshot()
        self._populate(snapshot)
        self._last_lbl.config(text="Updated {}".format(time.strftime("%H:%M:%S")))

    def on_show(self):
        self.refresh()

    def _classify(self, name, entry):
        interval_s = entry.get("interval_s") or 0
        last_run   = entry.get("last_run")
        last_error = entry.get("last_error")

        if last_run is None:
            return "never"
        if last_error:
            return "error"
        if interval_s and (time.time() - last_run) > interval_s * self.STALE_FACTOR:
            return "stale"
        return "ok"

    def _populate(self, snapshot):
        self._tree.delete(*self._tree.get_children())

        counts = {"ok": 0, "stale": 0, "error": 0, "never": 0}
        for name, entry in sorted(snapshot.items()):
            state = self._classify(name, entry)
            counts[state] += 1

            interval_s = entry.get("interval_s") or 0
            interval_text = self._fmt_duration(interval_s) if interval_s else "--"

            last_run = entry.get("last_run")
            last_run_text = self._fmt_ago(last_run) if last_run else "never"

            status_labels = {"ok": "OK", "stale": "STALE", "error": "ERROR", "never": "—"}

            self._tree.insert("", "end", values=(
                name,
                status_labels[state],
                interval_text,
                last_run_text,
                entry.get("checks", 0),
                entry.get("errors", 0),
                entry.get("last_error") or "",
            ), tags=(state,))

        self._card_ok.config(text=str(counts["ok"]))
        self._card_stale.config(text=str(counts["stale"]),
                                fg=self.theme.yellow if counts["stale"] else self.theme.text_muted)
        self._card_error.config(text=str(counts["error"]),
                                fg=self.theme.status_stopped if counts["error"] else self.theme.text_muted)
        self._card_never.config(text=str(counts["never"]))

        if counts["error"]:
            self._status.config(text="{} watchdog{} reporting errors".format(
                counts["error"], "s" if counts["error"] != 1 else ""),
                fg=self.theme.status_stopped_text)
        elif counts["stale"]:
            self._status.config(text="{} watchdog{} overdue for a check".format(
                counts["stale"], "s" if counts["stale"] != 1 else ""),
                fg=self.theme.yellow)
        else:
            self._status.config(text="All watchdogs healthy", fg=self.theme.status_running)

    @staticmethod
    def _fmt_duration(seconds):
        if seconds < 60:
            return "{}s".format(seconds)
        if seconds < 3600:
            return "{}m".format(seconds // 60)
        return "{}h".format(seconds // 3600)

    @staticmethod
    def _fmt_ago(ts):
        secs = max(0, int(time.time() - ts))
        if secs < 60:
            return "{}s ago".format(secs)
        if secs < 3600:
            return "{}m ago".format(secs // 60)
        if secs < 86400:
            return "{}h ago".format(secs // 3600)
        return "{}d ago".format(secs // 86400)
