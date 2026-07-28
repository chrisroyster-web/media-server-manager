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

        # Auto-remediation toggles
        remediation_row = tk.Frame(self, bg=t.bg)
        remediation_row.pack(fill="x", padx=16, pady=(0, 8))
        cfg = self.controller.config_manager
        self._svc_auto_var = tk.BooleanVar(value=cfg.get_service_watchdog_auto_restart())
        tk.Checkbutton(remediation_row, text="Auto-restart stopped/failed services",
                       variable=self._svc_auto_var, command=self._on_svc_auto_toggle,
                       bg=t.bg, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.bg, font=t.font_small, bd=0,
                       highlightthickness=0).pack(side="left", padx=(0, 16))
        self._docker_auto_var = tk.BooleanVar(value=cfg.get_docker_watchdog_auto_restart())
        tk.Checkbutton(remediation_row, text="Auto-restart unhealthy/dead containers",
                       variable=self._docker_auto_var, command=self._on_docker_auto_toggle,
                       bg=t.bg, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.bg, font=t.font_small, bd=0,
                       highlightthickness=0).pack(side="left")

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

        # Recent Auto-Remediation
        tk.Label(self, text="Recent Auto-Remediation", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=16, pady=(4, 0))
        rem_frame = tk.Frame(self, bg=t.bg)
        rem_frame.pack(fill="x", padx=16, pady=(0, 8))

        style.configure("Remediation.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("Remediation.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)

        rem_cols = ("target", "last_attempt", "attempts_in_window", "backing_off")
        self._rem_tree = ttk.Treeview(rem_frame, columns=rem_cols,
                                       show="headings", style="Remediation.Treeview",
                                       height=4)
        for col, w, lbl, anchor in [
            ("target",              220, "Target",              "w"),
            ("last_attempt",        150, "Last Attempt",        "w"),
            ("attempts_in_window",  120, "Attempts (30 min)",   "center"),
            ("backing_off",         100, "Backing Off",         "center"),
        ]:
            self._rem_tree.heading(col, text=lbl, anchor=anchor)
            self._rem_tree.column(col, width=w, minwidth=50,
                                  anchor=anchor, stretch=(col == "target"))
        self._rem_tree.tag_configure("backing_off", foreground=t.status_stopped_text)
        self._rem_tree.pack(fill="x")

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
        self._populate_remediation(self.controller.remediation_tracker.snapshot())
        self._last_lbl.config(text="Updated {}".format(time.strftime("%H:%M:%S")))

    def on_show(self):
        self.refresh()

    def _on_svc_auto_toggle(self):
        enabled = self._svc_auto_var.get()
        self.controller.config_manager.set_service_watchdog_auto_restart(enabled)
        self.controller.audit_log("watchdog.auto_restart_toggle", "service",
                                  detail="enabled={}".format(enabled))

    def _on_docker_auto_toggle(self):
        enabled = self._docker_auto_var.get()
        self.controller.config_manager.set_docker_watchdog_auto_restart(enabled)
        self.controller.audit_log("watchdog.auto_restart_toggle", "docker",
                                  detail="enabled={}".format(enabled))

    def _populate_remediation(self, snapshot):
        """snapshot() returns raw per-target state ({"attempts": [ts, ...],
        "backoff_until": ts}) rather than the friendlier last_info() shape,
        since it needs to stay a plain copy of internal state (see
        RemediationTracker.snapshot()'s own docstring/tests) -- derive the
        display fields here instead."""
        self._rem_tree.delete(*self._rem_tree.get_children())
        now = time.time()
        for target, entry in sorted(snapshot.items()):
            attempts = entry.get("attempts") or []
            last_attempt_text = self._fmt_ago(attempts[-1]) if attempts else "--"
            backing_off = now < entry.get("backoff_until", 0)
            self._rem_tree.insert("", "end", values=(
                target,
                last_attempt_text,
                len(attempts),
                "yes" if backing_off else "no",
            ), tags=("backing_off",) if backing_off else ())

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
