# ui/notification_history_tab.py

import tkinter as tk
from tkinter import messagebox
import time


class NotificationHistoryTab(tk.Frame):
    """
    Scrollable log of every toast notification fired during the session.
    Entries are added via add_entry() called from main.show_toast().
    Supports filtering by level and keyword search.
    """

    # Darkened slightly from the original #4c9ef5/#4caf50/#f5a623 — those
    # fell short of WCAG's 3:1 minimum for large/icon-sized content against
    # a white (light-mode) card background (2.79/2.78/2.03:1).
    LEVEL_COLORS = {
        "info":  "#3d96f4",
        "ok":    "#48a74c",
        "warn":  "#cc8309",
        "error": "#e53935",
    }
    LEVEL_ICONS = {
        "info":  "ℹ",
        "ok":    "✔",
        "warn":  "⚠",
        "error": "✖",
    }
    MAX_ENTRIES = 200

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller  = controller
        self.theme       = controller.theme
        self._entries    = []          # list of dicts: ts, level, title, message
        self._filter_var = tk.StringVar()
        self._level_var  = tk.StringVar(value="All")
        self._build_ui()
        self._load_from_db()

    # =========================================================
    # BUILD
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="NOTIFICATION HISTORY",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        ctrl = tk.Frame(hdr, bg=t.bg)
        ctrl.pack(side="right")

        # Level filter
        tk.Label(ctrl, text="Level:", bg=t.bg,
                 fg=t.text_muted, font=t.font_small).pack(side="left")
        level_menu = tk.OptionMenu(ctrl, self._level_var,
                                   "All", "info", "ok", "warn", "error",
                                   command=lambda _: self._render())
        level_menu.configure(
            bg=t.surface, fg=t.text, relief="flat",
            font=t.font_small, highlightthickness=0,
            activebackground=t.surface_light, activeforeground=t.text,
        )
        level_menu["menu"].configure(bg=t.surface, fg=t.text)
        level_menu.pack(side="left", padx=(4, 12))

        # Keyword filter
        tk.Label(ctrl, text="Search:", bg=t.bg,
                 fg=t.text_muted, font=t.font_small).pack(side="left")
        fe = tk.Entry(ctrl, textvariable=self._filter_var,
                      font=t.font_small, width=20)
        t.style_entry(fe)
        fe.pack(side="left", padx=(4, 12))
        self._filter_var.trace_add("write", lambda *_: self._render())

        # Clear button
        clr = tk.Button(ctrl, text="Clear All", command=self._clear)
        t.style_button(clr)
        clr.pack(side="left", padx=4)

        # Count label
        self._count_lbl = tk.Label(hdr, text="0 notifications",
                                    bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._count_lbl.pack(side="left", padx=(12, 0))

        # Scrollable list
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
    # LOAD FROM SQLITE (called once on init)
    # =========================================================
    def _load_from_db(self):
        try:
            rows = self.controller.metrics_store.get_notifications(
                limit=self.MAX_ENTRIES)
            self._entries = [
                {
                    "ts":      time.strftime("%H:%M:%S", time.localtime(r["ts"])),
                    "date":    time.strftime("%Y-%m-%d",  time.localtime(r["ts"])),
                    "level":   r["level"],
                    "title":   r["title"],
                    "message": r["message"],
                    "server":  r.get("server_id", ""),
                }
                for r in rows
            ]
            self._render()
        except Exception:
            pass

    # =========================================================
    # ADD ENTRY (called from main.show_toast)
    # =========================================================
    def add_entry(self, title, message, level="info"):
        self._entries.insert(0, {
            "ts":      time.strftime("%H:%M:%S"),
            "date":    time.strftime("%Y-%m-%d"),
            "level":   level,
            "title":   title,
            "message": message or "",
            "server":  "",
        })
        # Cap list size
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[:self.MAX_ENTRIES]
        self._render()

    # =========================================================
    # RENDER
    # =========================================================
    def _render(self):
        for w in self._list_frame.winfo_children():
            w.destroy()

        keyword = self._filter_var.get().strip().lower()
        level   = self._level_var.get()

        filtered = [
            e for e in self._entries
            if (level == "All" or e["level"] == level)
            and (not keyword or keyword in e["title"].lower()
                 or keyword in e["message"].lower())
        ]

        self._count_lbl.config(
            text="{} notification{}".format(
                len(filtered), "s" if len(filtered) != 1 else ""))

        if not filtered:
            tk.Label(self._list_frame,
                     text="No notifications yet." if not self._entries
                          else "No matches for current filter.",
                     bg=self.theme.bg, fg=self.theme.text_muted,
                     font=("Segoe UI", 12)).pack(pady=40)
            return

        for entry in filtered:
            self._build_row(entry)

    def _build_row(self, entry):
        t      = self.theme
        level  = entry["level"]
        color  = self.LEVEL_COLORS.get(level, t.blue)
        icon   = self.LEVEL_ICONS.get(level, "ℹ")

        row = tk.Frame(self._list_frame, bg=t.card_bg,
                       highlightbackground=t.card_border, highlightthickness=1)
        row.pack(fill="x", pady=3, padx=2)

        # Colored left accent
        tk.Frame(row, bg=color, width=4).pack(side="left", fill="y")

        # Icon
        tk.Label(row, text=icon, bg=t.card_bg, fg=color,
                 font=("Segoe UI", 14), width=2).pack(side="left", padx=(6, 4), pady=8)

        # Content
        content = tk.Frame(row, bg=t.card_bg)
        content.pack(side="left", fill="both", expand=True, pady=6)

        title_row = tk.Frame(content, bg=t.card_bg)
        title_row.pack(fill="x")
        tk.Label(title_row, text=entry["title"],
                 bg=t.card_bg, fg=t.text,
                 font=("Segoe UI Semibold", 10), anchor="w").pack(side="left")

        if entry["message"]:
            tk.Label(content, text=entry["message"],
                     bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small, anchor="w",
                     wraplength=600, justify="left").pack(fill="x", pady=(2, 0))

        # Timestamp + server
        ts_text = "{} {}".format(entry.get("date", ""), entry.get("ts", ""))
        right = tk.Frame(row, bg=t.card_bg)
        right.pack(side="right", padx=(8, 12))
        tk.Label(right, text=ts_text, bg=t.card_bg, fg=t.text_dim,
                 font=t.font_small, anchor="e").pack(anchor="e")
        server = entry.get("server", "")
        if server:
            tk.Label(right, text=server, bg=t.card_bg, fg=t.text_dim,
                     font=t.font_small, anchor="e").pack(anchor="e")

        # Mousewheel on row children
        def _mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        for w in (row, content, title_row):
            w.bind("<MouseWheel>", _mw)

    # =========================================================
    # CLEAR
    # =========================================================
    def _clear(self):
        if not self._entries:
            return
        if not messagebox.askyesno(
                "Clear Notification History",
                "Permanently delete all {} notification(s)? This cannot be undone.".format(
                    len(self._entries)),
                parent=self):
            return
        self._entries.clear()
        try:
            self.controller.metrics_store.clear_notifications()
        except Exception:
            pass
        self._render()
