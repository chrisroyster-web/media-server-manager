# ui/arr_tab.py
"""
Sonarr / Radarr queue and activity tab.
Pulls data directly from their REST APIs (no SSH needed).
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import json
import time


def _api_get(host, port, apikey, path):
    """GET /api/v3/<path> and return parsed JSON, or raise on error."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v3/{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _api_post(host, port, apikey, path, body=None):
    """POST /api/v3/<path> with optional JSON body."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v3/{}".format(host, port, path)
    data = json.dumps(body).encode() if body else b"{}"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"X-Api-Key": apikey, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _fmt_size(mb):
    try:
        mb = float(mb)
        if mb >= 1024:
            return "{:.1f} GB".format(mb / 1024)
        return "{:.0f} MB".format(mb)
    except Exception:
        return "--"


def _fmt_pct(done, total):
    try:
        return "{:.0f}%".format(100 * float(done) / float(total))
    except Exception:
        return "--"


class ArrTab(tk.Frame):
    """Sonarr + Radarr download queue and recent activity."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller   = controller
        self.theme        = controller.theme
        self._missing_ids = {}   # tree iid -> (app, item_id) for Search Now
        self._cal_days    = tk.IntVar(value=30)
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="SONARR  &  RADARR",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Stats row
        self._stats_frame = tk.Frame(self, bg=t.bg)
        self._stats_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Notebook: Queue / Missing / Upcoming
        nb_style = ttk.Style()
        nb_style.configure("Arr.TNotebook",        background=t.bg, borderwidth=0)
        nb_style.configure("Arr.TNotebook.Tab",    background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("Arr.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="Arr.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._queue_frame   = tk.Frame(self._nb, bg=t.bg)
        self._missing_frame = tk.Frame(self._nb, bg=t.bg)
        self._upcoming_frame= tk.Frame(self._nb, bg=t.bg)

        self._nb.add(self._queue_frame,    text="  Queue  ")
        self._nb.add(self._missing_frame,  text="  Missing  ")
        self._nb.add(self._upcoming_frame, text="  Upcoming  ")

        # Count labels shown above each tree (updated in _populate)
        self._queue_count_lbl    = tk.Label(self._queue_frame,    text="",
            bg=t.bg, fg=t.text_muted, font=t.font_small, anchor="w")
        self._queue_count_lbl.pack(fill="x", padx=8, pady=(4, 0))
        self._missing_count_lbl  = tk.Label(self._missing_frame,  text="",
            bg=t.bg, fg=t.text_muted, font=t.font_small, anchor="w")
        self._missing_count_lbl.pack(fill="x", padx=8, pady=(4, 0))
        self._upcoming_count_lbl = tk.Label(self._upcoming_frame, text="",
            bg=t.bg, fg=t.text_muted, font=t.font_small, anchor="w")
        self._upcoming_count_lbl.pack(fill="x", padx=8, pady=(4, 0))

        self._build_queue_tree()
        self._build_missing_tree()
        self._build_upcoming_tree()
        self._build_missing_toolbar()
        self._build_upcoming_toolbar()

        # Status bar
        self._status_lbl = tk.Label(self, text="Configure API keys in the Config tab",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # TREEVIEWS
    # =========================================================
    def _make_tree(self, parent, cols, headings):
        t = self.theme
        style = ttk.Style()
        sid = "Arr{}.Treeview".format(id(parent))
        style.configure(sid, background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure(sid + ".Heading", background=t.surface_dark,
                        foreground=t.text_muted, font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map(sid, background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=sid, selectmode="browse")
        for col, text, width, anchor in headings:
            tree.heading(col, text=text, anchor=anchor)
            tree.column(col, width=width, minwidth=40,
                        anchor=anchor, stretch=(width > 150))
        tree.tag_configure("odd",       background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",      background=t.card_bg,      foreground=t.text)
        tree.tag_configure("sonarr",    foreground=t.cyan)
        tree.tag_configure("radarr",    foreground=t.purple)
        tree.tag_configure("warning",   foreground=t.yellow)
        tree.tag_configure("error",     foreground=t.status_stopped)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _build_queue_tree(self):
        cols = ("app", "title", "status", "progress", "size", "protocol", "client")
        hdgs = [
            ("app",      "App",      60,  "center"),
            ("title",    "Title",    300, "w"),
            ("status",   "Status",   100, "w"),
            ("progress", "Progress", 70,  "e"),
            ("size",     "Size",     80,  "e"),
            ("protocol", "Protocol", 80,  "center"),
            ("client",   "Client",   120, "w"),
        ]
        self._queue_tree = self._make_tree(self._queue_frame, cols, hdgs)

    def _build_missing_tree(self):
        cols = ("app", "title", "monitored", "airdate", "quality")
        hdgs = [
            ("app",       "App",       60,  "center"),
            ("title",     "Title",     340, "w"),
            ("monitored", "Monitored", 90,  "center"),
            ("airdate",   "Air Date",  110, "w"),
            ("quality",   "Quality",   100, "w"),
        ]
        self._missing_tree = self._make_tree(self._missing_frame, cols, hdgs)

    def _build_missing_toolbar(self):
        """Search Now button + hint above the missing treeview."""
        t = self.theme
        bar = tk.Frame(self._missing_frame, bg=t.bg)
        bar.pack(fill="x", pady=(4, 0), before=self._missing_tree)

        self._search_btn = tk.Button(
            bar, text="Search Selected",
            command=self._search_selected_missing,
            bg=t.surface_light, fg=t.blue,
            bd=0, relief="flat", font=t.font_small, padx=10, pady=3, cursor="hand2",
        )
        self._search_btn.pack(side="left")
        self._search_btn.bind("<Enter>", lambda e: self._search_btn.configure(fg=t.blue_bright))
        self._search_btn.bind("<Leave>", lambda e: self._search_btn.configure(fg=t.blue))

        tk.Label(bar, text="  Double-click a row to search immediately",
                 bg=t.bg, fg=t.text_dim, font=t.font_small).pack(side="left", padx=4)

        self._search_status = tk.Label(bar, text="", bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._search_status.pack(side="right", padx=8)

        self._missing_tree.bind("<Double-1>", lambda e: self._search_selected_missing())

    def _search_selected_missing(self):
        """Trigger an immediate search for the selected missing item(s)."""
        selected = self._missing_tree.selection()
        if not selected:
            self._search_status.config(text="Select a row first", fg=self.theme.yellow)
            self.after(3000, lambda: self._search_status.config(text=""))
            return

        srv = getattr(self, "_active_srv", {})
        ok = err = 0

        def worker():
            nonlocal ok, err
            for iid in selected:
                if iid not in self._missing_ids:
                    continue
                app, item_id = self._missing_ids[iid]
                host   = (srv.get("sonarr_host", "localhost") if app == "sonarr"
                          else srv.get("radarr_host", "localhost"))
                port   = (srv.get("sonarr_port", "8989") if app == "sonarr"
                          else srv.get("radarr_port", "7878"))
                apikey = (srv.get("sonarr_apikey", "") if app == "sonarr"
                          else srv.get("radarr_apikey", ""))
                if app == "sonarr":
                    body = {"name": "EpisodeSearch", "episodeIds": [item_id]}
                else:
                    body = {"name": "MoviesSearch",  "movieIds":   [item_id]}
                try:
                    _api_post(host, port, apikey, "command", body)
                    ok += 1
                except Exception:
                    err += 1
            def _done():
                msg = "Search triggered for {} item(s)".format(ok)
                if err:
                    msg += " ({} failed)".format(err)
                color = self.theme.status_running if not err else self.theme.yellow
                self._search_status.config(text=msg, fg=color)
                self.after(4000, lambda: self._search_status.config(text=""))
            self.after(0, _done)

        import threading
        threading.Thread(target=worker, daemon=True).start()
        self._search_status.config(text="Searching…", fg=self.theme.text_muted)

    def _build_upcoming_toolbar(self):
        t = self.theme
        bar = tk.Frame(self._upcoming_frame, bg=t.bg)
        bar.pack(fill="x", pady=(4, 0), before=self._upcoming_tree)

        tk.Label(bar, text="Look ahead:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(8, 4))

        om = tk.OptionMenu(bar, self._cal_days, 30, 60, 90, 120,
                           command=lambda _: self._refresh())
        om.config(bg=t.surface_light, fg=t.text, activebackground=t.surface,
                  activeforeground=t.text, relief="flat", bd=0,
                  font=t.font_small, highlightthickness=0)
        om["menu"].config(bg=t.surface_light, fg=t.text,
                          activebackground=t.blue, activeforeground=t.text,
                          font=t.font_small)
        om.pack(side="left")

        tk.Label(bar, text="days", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(2, 0))

    def _build_upcoming_tree(self):
        cols = ("app", "title", "airdate", "network", "quality")
        hdgs = [
            ("app",     "App",     60,  "center"),
            ("title",   "Title",   340, "w"),
            ("airdate", "Air Date",120, "w"),
            ("network", "Network", 140, "w"),
            ("quality", "Quality", 100, "w"),
        ]
        self._upcoming_tree = self._make_tree(self._upcoming_frame, cols, hdgs)

    # =========================================================
    # REFRESH
    # =========================================================
    def _refresh(self):
        if getattr(self, "_fetching", False): return
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._set_status("Fetching data…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            cfg = self.controller.config_manager
            srv = (cfg.get_active_server() or {}).get("settings", {})
            self._active_srv = srv
            results = {"sonarr": {}, "radarr": {}, "errors": []}

            for app, host, port, apikey in [
                ("sonarr", srv.get("sonarr_host", "localhost"),
                 srv.get("sonarr_port", "8989"), srv.get("sonarr_apikey", "")),
                ("radarr", srv.get("radarr_host", "localhost"),
                 srv.get("radarr_port", "7878"), srv.get("radarr_apikey", "")),
            ]:
                if not apikey:
                    results["errors"].append("{}: no API key configured".format(app))
                    continue
                try:
                    results[app]["queue"]    = _api_get(host, port, apikey, "queue?pageSize=50")
                    results[app]["missing"]  = _api_get(host, port, apikey,
                        "wanted/missing?pageSize=30&sortKey=airDateUtc&sortDir=desc")
                    today = time.strftime("%Y-%m-%d")
                    days  = self._cal_days.get()
                    end   = time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 86400))
                    results[app]["calendar"] = _api_get(host, port, apikey,
                        f"calendar?unmonitored=false&start={today}&end={end}")
                    # Pre-fetch series list for Sonarr so we can resolve titles by ID.
                    # The wanted/missing and calendar endpoints don't always embed the
                    # full series object, leaving series.title empty.
                    if app == "sonarr":
                        series_list = _api_get(host, port, apikey, "series")
                        results[app]["series_map"] = {
                            s["id"]: s["title"] for s in series_list
                            if isinstance(s, dict) and "id" in s and "title" in s
                        }
                except Exception as e:
                    results["errors"].append("{}: {}".format(app, str(e)))

            self.after(0, lambda r=results: self._populate(r))
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, results):
        t = self.theme
        self._queue_tree.delete(*self._queue_tree.get_children())
        self._missing_tree.delete(*self._missing_tree.get_children())
        self._upcoming_tree.delete(*self._upcoming_tree.get_children())

        q_count = m_count = u_count = 0
        row_idx = 0
        self._missing_ids.clear()

        for app in ("sonarr", "radarr"):
            data      = results.get(app, {})
            app_tag   = app
            # ID→title map fetched from /api/v3/series (Sonarr only)
            series_map = data.get("series_map", {})

            # --- Queue ---
            queue_data = data.get("queue", {})
            records = queue_data.get("records", [])
            for item in records:
                if app == "sonarr":
                    # Queue items: build "Show S01E01" from the embedded episode/series
                    series_id    = item.get("seriesId")
                    series_title = (
                        series_map.get(series_id)
                        or item.get("series", {}).get("title")
                        or item.get("seriesTitle")
                    )
                    ep  = item.get("episode", {})
                    sea = ep.get("seasonNumber") or item.get("seasonNumber")
                    epn = ep.get("episodeNumber") or item.get("episodeNumber")
                    if series_title and sea is not None and epn is not None:
                        title = "{} S{:02d}E{:02d}".format(
                            series_title, int(sea), int(epn))
                    else:
                        title = series_title or item.get("title", "?")
                else:
                    title = item.get("title", "?")
                status   = item.get("status", "--")
                size_mb  = item.get("size", 0) / (1024**2) if item.get("size") else 0
                size_rem = item.get("sizeleft", 0) / (1024**2) if item.get("sizeleft") else 0
                done_mb  = size_mb - size_rem
                pct      = _fmt_pct(done_mb, size_mb) if size_mb else "--"
                protocol = item.get("protocol", "--")
                client   = item.get("downloadClient", "--")
                status_tag = "error" if "error" in status.lower() else ""
                tag = ("even" if row_idx % 2 == 0 else "odd", app_tag)
                if status_tag:
                    tag = tag + (status_tag,)
                self._queue_tree.insert("", "end",
                    values=(app.capitalize(), title, status,
                            pct, _fmt_size(size_mb), protocol, client),
                    tags=tag)
                row_idx += 1
                q_count += 1

            # --- Missing ---
            row_idx = 0
            missing_data = data.get("missing", {})
            for item in missing_data.get("records", []):
                if app == "sonarr":
                    ep  = item.get("episodeNumber", "?")
                    sea = item.get("seasonNumber", "?")
                    series_id    = item.get("seriesId")
                    series_title = (
                        series_map.get(series_id)
                        or item.get("series", {}).get("title")
                        or item.get("seriesTitle", "?")
                    )
                    title = "{} S{:02d}E{:02d}".format(
                        series_title, int(sea), int(ep))
                    airdate = item.get("airDateUtc", "--")[:10]
                else:
                    title   = item.get("title", "?")
                    airdate = item.get("digitalRelease") or item.get("physicalRelease") or "--"
                    if airdate != "--":
                        airdate = airdate[:10]
                monitored = "Yes" if item.get("monitored", True) else "No"
                quality   = (item.get("qualityProfileId") or
                             item.get("quality", {}).get("quality", {}).get("name", "--"))
                iid = self._missing_tree.insert("", "end",
                    values=(app.capitalize(), title, monitored, airdate, str(quality)),
                    tags=("even" if row_idx % 2 == 0 else "odd", app_tag))
                self._missing_ids[iid] = (app, item.get("id"))
                row_idx += 1
                m_count += 1

            # --- Upcoming / Calendar ---
            row_idx = 0
            cal_items = data.get("calendar", [])
            if not isinstance(cal_items, list):
                cal_items = cal_items.get("records", [])
            for item in cal_items:
                if app == "sonarr":
                    series_id    = item.get("seriesId")
                    series_title = (
                        series_map.get(series_id)
                        or item.get("series", {}).get("title")
                        or item.get("seriesTitle", "?")
                    )
                    ep  = item.get("episodeNumber", "?")
                    sea = item.get("seasonNumber",  "?")
                    title   = "{} S{:02d}E{:02d}".format(series_title, int(sea), int(ep))
                    network = item.get("series", {}).get("network", "--")
                    quality = item.get("series", {}).get("qualityProfileId", "--")
                else:
                    title   = item.get("title", "?")
                    network = item.get("studio", "--")
                    quality = "--"
                airdate = (item.get("airDateUtc") or item.get("airDate") or
                           item.get("digitalRelease") or "--")
                if airdate != "--":
                    airdate = airdate[:10]
                tag = ("even" if row_idx % 2 == 0 else "odd", app_tag)
                self._upcoming_tree.insert("", "end",
                    values=(app.capitalize(), title, airdate, network, quality),
                    tags=tag)
                row_idx += 1
                u_count += 1

        # Update counts + badge
        self._queue_count_lbl.config(
            text="{} in queue".format(q_count) if q_count else "Queue empty")
        self._missing_count_lbl.config(
            text="{} missing".format(m_count) if m_count else "Nothing missing")
        self._upcoming_count_lbl.config(
            text="{} upcoming".format(u_count) if u_count else "Nothing upcoming")

        self.controller.set_arr_badge(m_count if m_count else 0)

        errs = results.get("errors", [])
        if errs:
            self._set_status("Errors: " + "; ".join(errs))
        else:
            import time
            self._set_status("Updated " + time.strftime("%H:%M:%S"))
        self._refresh_btn.config(state="normal", text="⟳ Refresh")

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, msg):
        t = self.theme
        if msg.endswith("…") or msg.endswith("..."):
            self._status_lbl.config(text=msg, bg=t.blue, fg="#ffffff")
        else:
            self._status_lbl.config(text=msg, bg=t.surface_dark, fg=t.text_muted)
