# ui/audit_log_tab.py

import tkinter as tk
import time


class AuditLogTab(tk.Frame):
    """
    Scrollable, unclearable trail of destructive/consequential actions taken
    through the app (service restarts, container removals, fail2ban unbans,
    firewall changes, backups/restores, installs, cron/compose changes).
    Entries are written via controller.audit_log() from the tabs that
    perform those actions, and read back here on load/refresh.

    Deliberately has no "Clear All" — unlike Notification History, which is
    a dismissable alert feed, this is meant to be a durable record.
    """

    RESULT_COLORS = {"ok": "#4caf50", "fail": "#e53935"}
    RESULT_ICONS  = {"ok": "✔", "fail": "✖"}
    MAX_ENTRIES = 500

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller  = controller
        self.theme       = controller.theme
        self._entries    = []          # list of dicts: ts, actor, action, target, detail, result, server
        self._filter_var = tk.StringVar()
        self._build_ui()
        self._load_from_db()

    # =========================================================
    # BUILD
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="AUDIT LOG",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        ctrl = tk.Frame(hdr, bg=t.bg)
        ctrl.pack(side="right")

        tk.Label(ctrl, text="Search:", bg=t.bg,
                 fg=t.text_muted, font=t.font_small).pack(side="left")
        fe = tk.Entry(ctrl, textvariable=self._filter_var,
                      font=t.font_small, width=20)
        t.style_entry(fe)
        fe.pack(side="left", padx=(4, 12))
        self._filter_var.trace_add("write", lambda *_: self._render())

        refresh_btn = tk.Button(ctrl, text="⟳ Refresh", command=self._load_from_db)
        t.style_button(refresh_btn)
        refresh_btn.pack(side="left", padx=4)

        self._count_lbl = tk.Label(hdr, text="0 entries",
                                    bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._count_lbl.pack(side="left", padx=(12, 0))

        outer = tk.Frame(self, bg=t.bg)
        outer.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self._canvas = tk.Canvas(outer, bg=t.bg, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._list_frame = tk.Frame(self._canvas, bg=t.bg)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw")

        self._list_frame.bind("<Configure>", self._on_frame_resize)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._canvas.bind("<MouseWheel>", _mw)
        self._list_frame.bind("<MouseWheel>", _mw)

        self._render()

    def _on_frame_resize(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self._canvas.itemconfig(self._canvas_win, width=e.width)

    # =========================================================
    # LOAD FROM SQLITE
    # =========================================================
    def _load_from_db(self):
        try:
            rows = self.controller.metrics_store.get_audit_log(limit=self.MAX_ENTRIES)
            self._entries = [
                {
                    "ts":      time.strftime("%H:%M:%S", time.localtime(r["ts"])),
                    "date":    time.strftime("%Y-%m-%d",  time.localtime(r["ts"])),
                    "actor":   r["actor"],
                    "action":  r["action"],
                    "target":  r["target"],
                    "detail":  r["detail"],
                    "result":  r["result"],
                    "server":  r.get("server_id", ""),
                }
                for r in rows
            ]
        except Exception:
            pass
        self._render()

    def on_show(self):
        self._load_from_db()

    # =========================================================
    # RENDER
    # =========================================================
    def _render(self):
        for w in self._list_frame.winfo_children():
            w.destroy()

        keyword = self._filter_var.get().strip().lower()

        filtered = [
            e for e in self._entries
            if not keyword or keyword in e["action"].lower()
               or keyword in e["target"].lower()
               or keyword in e["actor"].lower()
        ]

        self._count_lbl.config(
            text="{} entr{}".format(
                len(filtered), "y" if len(filtered) == 1 else "ies"))

        if not filtered:
            tk.Label(self._list_frame,
                     text="No admin actions logged yet." if not self._entries
                          else "No matches for current filter.",
                     bg=self.theme.bg, fg=self.theme.text_muted,
                     font=("Segoe UI", 12)).pack(pady=40)
            return

        for entry in filtered:
            self._build_row(entry)

    def _build_row(self, entry):
        t      = self.theme
        result = entry["result"]
        color  = self.RESULT_COLORS.get(result, t.text_muted)
        icon   = self.RESULT_ICONS.get(result, "•")

        row = tk.Frame(self._list_frame, bg=t.card_bg,
                       highlightbackground=t.card_border, highlightthickness=1)
        row.pack(fill="x", pady=3, padx=2)

        tk.Frame(row, bg=color, width=4).pack(side="left", fill="y")

        tk.Label(row, text=icon, bg=t.card_bg, fg=color,
                 font=("Segoe UI", 14), width=2).pack(side="left", padx=(6, 4), pady=8)

        content = tk.Frame(row, bg=t.card_bg)
        content.pack(side="left", fill="both", expand=True, pady=6)

        title_row = tk.Frame(content, bg=t.card_bg)
        title_row.pack(fill="x")
        tk.Label(title_row, text="{}  →  {}".format(entry["action"], entry["target"]),
                 bg=t.card_bg, fg=t.text,
                 font=("Segoe UI Semibold", 10), anchor="w").pack(side="left")
        if entry["actor"]:
            tk.Label(title_row, text="by {}".format(entry["actor"]),
                     bg=t.card_bg, fg=t.text_dim,
                     font=t.font_small, anchor="w").pack(side="left", padx=(8, 0))

        if entry["detail"]:
            tk.Label(content, text=entry["detail"],
                     bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small, anchor="w",
                     wraplength=600, justify="left").pack(fill="x", pady=(2, 0))

        ts_text = "{} {}".format(entry.get("date", ""), entry.get("ts", ""))
        right = tk.Frame(row, bg=t.card_bg)
        right.pack(side="right", padx=(8, 12))
        tk.Label(right, text=ts_text, bg=t.card_bg, fg=t.text_dim,
                 font=t.font_small, anchor="e").pack(anchor="e")
        server = entry.get("server", "")
        if server:
            tk.Label(right, text=server, bg=t.card_bg, fg=t.text_dim,
                     font=t.font_small, anchor="e").pack(anchor="e")

        def _mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        for w in (row, content, title_row):
            w.bind("<MouseWheel>", _mw)
