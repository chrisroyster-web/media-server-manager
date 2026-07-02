# ui/overseerr_tab.py
"""
Overseerr request management tab.
Shows pending/available requests, recent activity, and top requestors.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import json
import time

from ui.refresh_control import RefreshControl

# Request status codes
_STATUS = {1: "Pending", 2: "Approved", 3: "Declined", 4: "Available", 5: "Processing"}
_STATUS_TAG = {1: "pending", 2: "approved", 3: "declined", 4: "available", 5: "processing"}


def _api(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v1/{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


class OverseerrTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._name      = "Overseerr"
        self._cfg_key   = "overseerr"
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text=self._name.upper(), bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, self._cfg_key,
                                  default=120, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._card_total     = self._stat_card(cards, "Total",      "--", t.cyan)
        self._card_pending   = self._stat_card(cards, "Pending",    "--", t.yellow)
        self._card_processing= self._stat_card(cards, "Processing", "--", t.purple)
        self._card_available = self._stat_card(cards, "Available",  "--", t.status_running)

        # Notebook
        nb_style = ttk.Style()
        nb_style.configure("OV.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("OV.TNotebook.Tab",
                           background=t.surface, foreground=t.text_muted,
                           padding=[12, 6], font=t.font_small)
        nb_style.map("OV.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="OV.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._req_frame  = tk.Frame(self._nb, bg=t.bg)
        self._user_frame = tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._req_frame,  text="  Recent Requests  ")
        self._nb.add(self._user_frame, text="  Top Requestors  ")

        self._build_requests_tab()
        self._build_users_tab()

        # Status bar
        self._status = tk.Label(
            self,
            text="Configure {} in Settings to get started".format(self._name),
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

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

    def _build_requests_tab(self):
        t = self.theme
        style = ttk.Style()
        style.configure("OV.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("OV.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("OV.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("date", "type", "title", "requestor", "status")
        self._req_tree = ttk.Treeview(self._req_frame, columns=cols,
                                       show="headings", style="OV.Treeview")
        for col, w, lbl, anch in [
            ("date",      130, "Requested",   "w"),
            ("type",       60, "Type",        "w"),
            ("title",     320, "Title",       "w"),
            ("requestor", 150, "Requested By","w"),
            ("status",    110, "Status",      "w"),
        ]:
            self._req_tree.heading(col, text=lbl, anchor=anch)
            self._req_tree.column(col, width=w, minwidth=40,
                                  anchor=anch, stretch=(col == "title"))

        self._req_tree.tag_configure("pending",    foreground=t.yellow)
        self._req_tree.tag_configure("approved",   foreground=t.cyan)
        self._req_tree.tag_configure("available",  foreground=t.status_running)
        self._req_tree.tag_configure("processing", foreground=t.purple)
        self._req_tree.tag_configure("declined",   foreground=t.status_stopped)

        vsb = ttk.Scrollbar(self._req_frame, orient="vertical",
                            command=self._req_tree.yview)
        self._req_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._req_tree.pack(fill="both", expand=True)

    def _build_users_tab(self):
        t = self.theme
        cols = ("rank", "name", "requests")
        self._user_tree = ttk.Treeview(self._user_frame, columns=cols,
                                        show="headings", style="OV.Treeview")
        for col, w, lbl, anch in [
            ("rank",      50,  "#",        "center"),
            ("name",     280,  "User",     "w"),
            ("requests",  80,  "Requests", "e"),
        ]:
            self._user_tree.heading(col, text=lbl, anchor=anch)
            self._user_tree.column(col, width=w, minwidth=40,
                                   anchor=anch, stretch=(col == "name"))
        vsb2 = ttk.Scrollbar(self._user_frame, orient="vertical",
                             command=self._user_tree.yview)
        self._user_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self._user_tree.pack(fill="both", expand=True)

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.overseerr_apikey:
            self._status.config(
                text="No API key — add it in Settings > {}".format(self._name),
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            cfg  = self.controller.config_manager
            host = cfg.overseerr_host
            port = cfg.overseerr_port
            key  = cfg.overseerr_apikey

            try:
                counts = _api(host, port, key, "request/count")
            except Exception as e:
                self.after(0, lambda: self._status.config(
                    text="Cannot reach {}: {}".format(self._name, e),
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped))
                return

            try:
                req_data = _api(host, port, key,
                                "request?take=50&skip=0&sort=added&requestedBy=0")
                requests = req_data.get("results", [])
            except Exception:
                requests = []

            try:
                user_data = _api(host, port, key,
                                 "user?take=25&skip=0&sort=requests")
                users = user_data.get("results", [])
            except Exception:
                users = []

            self.after(0, lambda: self._populate(counts, requests, users))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, counts, requests, users):
        t = self.theme

        total      = counts.get("total", 0)
        pending    = counts.get("pending", 0)
        processing = counts.get("processing", 0)
        available  = counts.get("available", 0)

        self._card_total.config(text=str(total))
        self._card_pending.config(
            text=str(pending),
            fg=t.yellow if pending else t.text_muted)
        self._card_processing.config(text=str(processing))
        self._card_available.config(text=str(available))

        # Requests table
        self._req_tree.delete(*self._req_tree.get_children())
        for req in requests:
            status_code = req.get("status", 1)
            tag    = _STATUS_TAG.get(status_code, "pending")
            status = _STATUS.get(status_code, "Unknown")

            media  = req.get("media", {}) or {}
            title  = (media.get("originalTitle") or
                      media.get("title") or
                      media.get("name") or "--")
            mtype  = req.get("type", "").capitalize()

            requestor = req.get("requestedBy") or {}
            rname = (requestor.get("displayName") or
                     requestor.get("username") or "--")

            date = req.get("createdAt", "")[:10]

            self._req_tree.insert("", "end", tags=(tag,), values=(
                date, mtype, title, rname, status))

        # Users table
        self._user_tree.delete(*self._user_tree.get_children())
        for i, user in enumerate(users, 1):
            name = (user.get("displayName") or user.get("username") or "--")
            count = user.get("requestCount", 0)
            self._user_tree.insert("", "end", values=(i, name, count))

        self._status.config(
            text="{} total requests | {} pending | {} available".format(
                total, pending, available),
            bg=t.surface_dark, fg=t.yellow if pending else t.status_running)
