# ui/media_requests_tab.py
"""
Unified Media Requests tab — Overseerr and Jellyseerr share the same API,
so a single tab with a server picker replaces two identical tabs.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import json
import time

from ui.refresh_control import RefreshControl
from ui.empty_state import EmptyState

_STATUS     = {1: "Pending", 2: "Approved", 3: "Declined", 4: "Available", 5: "Processing"}
_STATUS_TAG = {1: "pending", 2: "approved", 3: "declined", 4: "available", 5: "processing"}

_SERVER_OVERSEERR  = "Overseerr"
_SERVER_JELLYSEERR = "Jellyseerr"


def _api(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url  = "http://{}:{}/api/v1/{}".format(host, port, path)
    req  = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


class MediaRequestsTab(tk.Frame):
    """Unified Overseerr / Jellyseerr requests management."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="MEDIA REQUESTS",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "media_requests",
                                  default=120, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Server picker
        picker = tk.Frame(self, bg=t.surface_dark)
        picker.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(picker, text="Server:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(12, 6), pady=8)
        self._server_var = tk.StringVar()
        self._server_menu = ttk.Combobox(picker, textvariable=self._server_var,
                                          state="readonly", width=14,
                                          font=t.font_small)
        self._server_menu.pack(side="left", pady=6)
        self._server_var.trace_add("write", lambda *_: self.refresh())

        # Summary cards
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._card_total      = self._stat_card(cards, "Total",      "--", t.cyan)
        self._card_pending    = self._stat_card(cards, "Pending",    "--", t.yellow)
        self._card_processing = self._stat_card(cards, "Processing", "--", t.purple)
        self._card_available  = self._stat_card(cards, "Available",  "--", t.status_running)

        # Sub-tabs: Requests / Users
        nb_style = ttk.Style()
        nb_style.configure("MR.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("MR.TNotebook.Tab",
                           background=t.surface, foreground=t.text_muted,
                           padding=[12, 6], font=t.font_small)
        nb_style.map("MR.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="MR.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._req_frame  = tk.Frame(self._nb, bg=t.bg)
        self._user_frame = tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._req_frame,  text="  Recent Requests  ")
        self._nb.add(self._user_frame, text="  Top Requestors  ")

        self._build_requests_tab()
        self._build_users_tab()

        self._status = tk.Label(self, text="Select a server above to load requests.",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        # Empty state overlay — shown when no servers are configured
        self._empty = EmptyState(
            self, t,
            icon="📬",
            title="No request server configured",
            subtitle="Add an Overseerr or Jellyseerr API key in Settings to manage media requests.",
            action_text="⚙ Open Settings",
            action_cmd=lambda: self.controller.tabs.select(8),
        )
        self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._empty.place_forget()
        self._populate_server_menu()

    def _populate_server_menu(self):
        cfg     = self.controller.config_manager
        servers = []
        if cfg.overseerr_apikey:    servers.append(_SERVER_OVERSEERR)
        if cfg.jellyseerr_apikey:   servers.append(_SERVER_JELLYSEERR)
        self._server_menu["values"] = servers
        if servers:
            if not self._server_var.get():
                self._server_var.set(servers[0])
            self._empty.place_forget()
        else:
            self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._empty.lift()

    def _stat_card(self, parent, label, value, color):
        t    = self.theme
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
        style.configure("MR.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("MR.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("MR.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("date", "type", "title", "requestor", "status")
        self._req_tree = ttk.Treeview(self._req_frame, columns=cols,
                                       show="headings", style="MR.Treeview")
        for col, w, lbl, anch in [
            ("date",      130, "Requested",    "w"),
            ("type",       60, "Type",         "w"),
            ("title",     320, "Title",        "w"),
            ("requestor", 150, "Requested By", "w"),
            ("status",    110, "Status",       "w"),
        ]:
            self._req_tree.heading(col, text=lbl, anchor=anch)
            self._req_tree.column(col, width=w, minwidth=40,
                                  anchor=anch, stretch=(col == "title"))

        for tag, fg in [("pending", t.yellow), ("approved", t.cyan),
                        ("available", t.status_running), ("processing", t.purple),
                        ("declined", t.status_stopped)]:
            self._req_tree.tag_configure(tag, foreground=fg)

        vsb = ttk.Scrollbar(self._req_frame, orient="vertical",
                            command=self._req_tree.yview)
        self._req_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._req_tree.pack(fill="both", expand=True)

    def _build_users_tab(self):
        cols = ("rank", "name", "requests")
        self._user_tree = ttk.Treeview(self._user_frame, columns=cols,
                                        show="headings", style="MR.Treeview")
        for col, w, lbl, anch in [
            ("rank",     50,  "#",        "center"),
            ("name",    280,  "User",     "w"),
            ("requests", 80,  "Requests", "e"),
        ]:
            self._user_tree.heading(col, text=lbl, anchor=anch)
            self._user_tree.column(col, width=w, minwidth=40,
                                   anchor=anch, stretch=(col == "name"))
        vsb2 = ttk.Scrollbar(self._user_frame, orient="vertical",
                             command=self._user_tree.yview)
        self._user_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self._user_tree.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def on_show(self):
        self._populate_server_menu()
        self.refresh()

    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        server = self._server_var.get()
        if not server:
            return
        cfg = self.controller.config_manager
        apikey = (cfg.overseerr_apikey if server == _SERVER_OVERSEERR
                  else cfg.jellyseerr_apikey)
        if not apikey:
            self._status.config(
                text="No API key configured for {}.  →  Add it in Settings (Config tab).".format(server),
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, args=(server,), daemon=True).start()

    def _fetch(self, server):
        try:
            cfg  = self.controller.config_manager
            if server == _SERVER_OVERSEERR:
                host, port, key = cfg.overseerr_host, cfg.overseerr_port, cfg.overseerr_apikey
            else:
                host, port, key = cfg.jellyseerr_host, cfg.jellyseerr_port, cfg.jellyseerr_apikey

            try:
                counts = _api(host, port, key, "request/count")
            except Exception as e:
                self.after(0, lambda err=str(e): self._status.config(
                    text="Cannot reach {}: {}".format(server, err),
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped))
                return

            try:
                req_data = _api(host, port, key,
                                "request?take=50&skip=0&sort=added&requestedBy=0")
                requests = req_data.get("results", [])
            except Exception:
                requests = []

            try:
                user_data = _api(host, port, key, "user?take=25&skip=0&sort=requests")
                users = user_data.get("results", [])
            except Exception:
                users = []

            self.after(0, lambda: self._populate(server, counts, requests, users))
            self.after(0, lambda: self._last_lbl.config(
                text="{} · {}".format(server, time.strftime("%H:%M"))))
        finally:
            self._fetching = False
            self.after(0, self._rc.schedule)

    # ------------------------------------------------------------------
    # POPULATE
    # ------------------------------------------------------------------
    def _populate(self, server, counts, requests, users):
        t = self.theme
        total      = counts.get("total", 0)
        pending    = counts.get("pending", 0)
        processing = counts.get("processing", 0)
        available  = counts.get("available", 0)

        self._card_total.config(text=str(total))
        self._card_pending.config(text=str(pending),
                                   fg=t.yellow if pending else t.text_muted)
        try:
            self.controller.set_requests_badge(pending)
        except Exception:
            pass
        self._card_processing.config(text=str(processing))
        self._card_available.config(text=str(available))

        self._req_tree.delete(*self._req_tree.get_children())
        for req in requests:
            code   = req.get("status", 1)
            media  = req.get("media", {}) or {}
            title  = (media.get("originalTitle") or media.get("title") or
                      media.get("name") or "--")
            rname  = ((req.get("requestedBy") or {}).get("displayName") or
                      (req.get("requestedBy") or {}).get("username") or "--")
            self._req_tree.insert("", "end", tags=(_STATUS_TAG.get(code, "pending"),),
                                  values=(req.get("createdAt", "")[:10],
                                          req.get("type", "").capitalize(),
                                          title, rname, _STATUS.get(code, "?")))

        self._user_tree.delete(*self._user_tree.get_children())
        for i, user in enumerate(users, 1):
            name = (user.get("displayName") or user.get("username") or "--")
            self._user_tree.insert("", "end",
                                   values=(i, name, user.get("requestCount", 0)))

        self._status.config(
            text="{} total | {} pending | {} available  ({})".format(
                total, pending, available, server),
            bg=t.surface_dark, fg=t.yellow if pending else t.status_running)
