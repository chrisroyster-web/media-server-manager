# ui/prowlarr_tab.py
"""
Prowlarr indexer management tab.
Shows indexer status, grab stats, recent history, and health issues.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import json
import time

from ui.refresh_control import RefreshControl


def _api(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v1/{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def _api_post(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v1/{}".format(host, port, path)
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"X-Api-Key": apikey,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


class ProwlarrTab(tk.Frame):

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

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="PROWLARR", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "prowlarr",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._test_btn = tk.Button(hdr, text="Test All Indexers",
                                   command=self._test_all)
        t.style_button(self._test_btn)
        self._test_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._card_total   = self._stat_card(cards, "Indexers", "--", t.cyan)
        self._card_enabled = self._stat_card(cards, "Enabled",  "--", t.status_running)
        self._card_failing = self._stat_card(cards, "Failing",  "--", t.status_stopped)
        self._card_grabs   = self._stat_card(cards, "Grabs (7d)","--", t.purple)

        # Main notebook: Indexers / History / Health
        nb_style = ttk.Style()
        nb_style.configure("PW.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("PW.TNotebook.Tab",
                           background=t.surface, foreground=t.text_muted,
                           padding=[12, 6], font=t.font_small)
        nb_style.map("PW.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="PW.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._idx_frame  = tk.Frame(self._nb, bg=t.bg)
        self._hist_frame = tk.Frame(self._nb, bg=t.bg)
        self._health_frame = tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._idx_frame,    text="  Indexers  ")
        self._nb.add(self._hist_frame,   text="  Recent Grabs  ")
        self._nb.add(self._health_frame, text="  Health  ")

        self._build_indexers_tab()
        self._build_history_tab()
        self._build_health_tab()

        # Status bar
        self._status = tk.Label(self, text="Configure Prowlarr in Settings to get started",
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

    def _build_indexers_tab(self):
        t = self.theme
        style = ttk.Style()
        style.configure("PW.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("PW.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("PW.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("name", "enabled", "privacy", "protocol",
                "grabs", "last_grab", "status")
        self._idx_tree = ttk.Treeview(self._idx_frame, columns=cols,
                                       show="headings", style="PW.Treeview")
        for col, w, lbl, anch in [
            ("name",      200, "Indexer",    "w"),
            ("enabled",    70, "Enabled",    "center"),
            ("privacy",    80, "Privacy",    "w"),
            ("protocol",   70, "Protocol",   "w"),
            ("grabs",      70, "Grabs",      "e"),
            ("last_grab", 150, "Last Grab",  "w"),
            ("status",    120, "Status",     "w"),
        ]:
            self._idx_tree.heading(col, text=lbl, anchor=anch)
            self._idx_tree.column(col, width=w, minwidth=40,
                                  anchor=anch, stretch=(col == "name"))

        self._idx_tree.tag_configure("ok",      foreground=t.status_running)
        self._idx_tree.tag_configure("disabled",foreground=t.text_muted)
        self._idx_tree.tag_configure("error",   foreground=t.status_stopped)

        vsb = ttk.Scrollbar(self._idx_frame, orient="vertical",
                            command=self._idx_tree.yview)
        self._idx_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._idx_tree.pack(fill="both", expand=True, padx=0, pady=0)

    def _build_history_tab(self):
        t = self.theme
        cols = ("date", "indexer", "title", "type", "app")
        self._hist_tree = ttk.Treeview(self._hist_frame, columns=cols,
                                        show="headings", style="PW.Treeview")
        for col, w, lbl, anch in [
            ("date",    150, "Date",     "w"),
            ("indexer", 130, "Indexer",  "w"),
            ("title",   340, "Title",    "w"),
            ("type",     80, "Type",     "w"),
            ("app",     100, "App",      "w"),
        ]:
            self._hist_tree.heading(col, text=lbl, anchor=anch)
            self._hist_tree.column(col, width=w, minwidth=40,
                                   anchor=anch, stretch=(col == "title"))
        vsb2 = ttk.Scrollbar(self._hist_frame, orient="vertical",
                             command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self._hist_tree.pack(fill="both", expand=True)

    def _build_health_tab(self):
        t = self.theme
        self._health_text = tk.Text(self._health_frame, bg=t.surface_dark,
                                     fg=t.text, font=t.font_mono,
                                     state="disabled", relief="flat",
                                     padx=12, pady=10, wrap="word")
        self._health_text.pack(fill="both", expand=True)

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        srv = (cfg.get_active_server() or {}).get("settings", {})
        self._active_srv = srv
        if not srv.get("prowlarr_apikey", ""):
            self._status.config(
                text="No API key — add it in Settings > Prowlarr",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            srv  = getattr(self, "_active_srv", {})
            host = srv.get("prowlarr_host", "localhost")
            port = srv.get("prowlarr_port", "9797")
            key  = srv.get("prowlarr_apikey", "")

            try:
                indexers = _api(host, port, key, "indexer")
            except Exception as e:
                self.after(0, lambda: self._status.config(
                    text="Cannot reach Prowlarr: {}".format(e),
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped))
                return

            try:
                stats_list = _api(host, port, key, "indexerstats")
                # indexerstats returns {"indexers": [...], "userAgents": [...]}
                stats_by_id = {s["indexerId"]: s
                               for s in stats_list.get("indexers", [])}
            except Exception:
                stats_by_id = {}

            try:
                history = _api(host, port, key, "history?pageSize=50&sortKey=date&sortDir=desc")
                hist_records = history.get("records", [])
            except Exception:
                hist_records = []

            try:
                health = _api(host, port, key, "health")
            except Exception:
                health = []

            self.after(0, lambda: self._populate(indexers, stats_by_id,
                                                  hist_records, health))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, indexers, stats_by_id, hist_records, health):
        t = self.theme

        enabled = [i for i in indexers if i.get("enable")]
        failing = [i for i in indexers
                   if i.get("enable") and not i.get("status", {}).get("isRedirect", False)
                   and i.get("status", {}).get("disabledTill")]

        total_grabs = sum(s.get("numberOfGrabs", 0) for s in stats_by_id.values())

        self._card_total.config(text=str(len(indexers)))
        self._card_enabled.config(
            text=str(len(enabled)),
            fg=t.status_running if enabled else t.text_muted)
        self._card_failing.config(
            text=str(len(failing)),
            fg=t.status_stopped if failing else t.text_muted)
        self._card_grabs.config(text=str(total_grabs))

        # Indexers table
        self._idx_tree.delete(*self._idx_tree.get_children())
        for idx in sorted(indexers, key=lambda x: x.get("name", "").lower()):
            iid     = idx.get("id")
            s       = stats_by_id.get(iid, {})
            enabled_flag = idx.get("enable", False)
            disabled_till = (idx.get("status") or {}).get("disabledTill", "")
            if not enabled_flag:
                tag    = "disabled"
                status = "Disabled"
            elif disabled_till:
                tag    = "error"
                status = "Failing"
            else:
                tag    = "ok"
                status = "OK"

            grabs      = s.get("numberOfGrabs", "--")
            last_grab  = s.get("mostRecentGrab", "")
            if last_grab:
                last_grab = last_grab[:16].replace("T", " ")

            self._idx_tree.insert("", "end", tags=(tag,), values=(
                idx.get("name", "--"),
                "Yes" if enabled_flag else "No",
                idx.get("privacy", "--").capitalize(),
                idx.get("protocol", "--").capitalize(),
                grabs,
                last_grab or "--",
                status,
            ))

        # History table
        self._hist_tree.delete(*self._hist_tree.get_children())
        for rec in hist_records:
            date = rec.get("date", "")[:16].replace("T", " ")
            self._hist_tree.insert("", "end", values=(
                date,
                rec.get("indexer", "--"),
                rec.get("sourceTitle", "--"),
                rec.get("eventType", "--"),
                rec.get("downloadClientName") or rec.get("data", {}).get("downloadClient", "--"),
            ))

        # Health
        self._health_text.config(state="normal")
        self._health_text.delete("1.0", "end")
        if not health:
            self._health_text.insert("end", "No health issues — all good.")
        else:
            for item in health:
                lvl = item.get("type", "info").upper()
                msg = item.get("message", "")
                src = item.get("source", "")
                self._health_text.insert("end",
                    "[{}] {} — {}\n\n".format(lvl, src, msg))
        self._health_text.config(state="disabled")

        n = len(indexers)
        self._status.config(
            text="{} indexer{} | {} enabled | {} grabs total".format(
                n, "s" if n != 1 else "", len(enabled), total_grabs),
            bg=t.surface_dark, fg=t.status_stopped if failing else t.status_running)

    # =========================================================
    # TEST ALL
    # =========================================================
    def _test_all(self):
        srv = getattr(self, "_active_srv", {})
        if not srv.get("prowlarr_apikey", ""):
            return
        self._test_btn.config(state="disabled", text="Testing…")
        self._status.config(text="Testing all indexers…", bg=self.theme.blue, fg="#ffffff")

        def _run():
            try:
                _api_post(srv.get("prowlarr_host", "localhost"),
                          srv.get("prowlarr_port", "9797"),
                          srv.get("prowlarr_apikey", ""), "indexer/testall")
                self.after(0, lambda: self._status.config(
                    text="Test complete — refreshing…",
                    bg=self.theme.surface_dark, fg=self.theme.status_running))
                self.after(500, self.refresh)
            except Exception as e:
                self.after(0, lambda: self._status.config(
                    text="Test failed: {}".format(e),
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            finally:
                self.after(0, lambda: self._test_btn.config(
                    state="normal", text="Test All Indexers"))

        threading.Thread(target=_run, daemon=True).start()
