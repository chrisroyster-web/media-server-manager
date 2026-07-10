# ui/bazarr_tab.py
"""
Bazarr subtitle management tab.

Lists everything Bazarr considers "wanted" — episodes/movies missing one
or more subtitle languages — across both its Sonarr and Radarr libraries,
and lets you trigger a search: either for the selected rows (each missing
language, specifically) or Bazarr's own two background jobs that search
the whole library ("Search for Missing Series/Movies Subtitles").
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import urllib.request
import json

from ui.refresh_control import RefreshControl
from ui.empty_state import EmptyState

# Bazarr scheduler job ids (bazarr/app/scheduler.py) for the two built-in
# "search everything missing" jobs — triggering these is far cheaper than
# reimplementing per-item search across a whole library from this tab.
_SERIES_TASK = "wanted_search_missing_subtitles_series"
_MOVIES_TASK = "wanted_search_missing_subtitles_movies"


def _api_get(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url  = "http://{}:{}/api/{}".format(host, port, path)
    req  = urllib.request.Request(
        url, headers={"X-API-KEY": apikey, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _api_patch(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url  = "http://{}:{}/api/{}".format(host, port, path)
    req  = urllib.request.Request(url, headers={"X-API-KEY": apikey}, method="PATCH")
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def _api_post(host, port, apikey, path):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url  = "http://{}:{}/api/{}".format(host, port, path)
    req  = urllib.request.Request(url, headers={"X-API-KEY": apikey}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


class BazarrTab(tk.Frame):
    """Missing-subtitle overview for Bazarr, plus search triggers."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._rows      = {}   # tree iid -> row dict
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="BAZARR  —  SUBTITLES",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "bazarr",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Toolbar
        bar = tk.Frame(self, bg=t.surface_dark)
        bar.pack(fill="x", padx=16, pady=(0, 8))
        self._count_lbl = tk.Label(bar, text="", bg=t.surface_dark, fg=t.text_muted,
                                    font=t.font_small)
        self._count_lbl.pack(side="left", padx=(12, 6), pady=8)

        self._search_all_btn = tk.Button(bar, text="Search All Wanted",
                                          command=self._search_all_wanted)
        t.style_button(self._search_all_btn)
        self._search_all_btn.pack(side="right", padx=(0, 12), pady=6)
        self._search_sel_btn = tk.Button(bar, text="Search Selected",
                                          command=self._search_selected)
        t.style_button(self._search_sel_btn)
        self._search_sel_btn.pack(side="right", padx=(0, 6), pady=6)

        # Treeview
        tv_frame = tk.Frame(self, bg=t.bg)
        tv_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Bazarr.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("Bazarr.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("Bazarr.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("type", "title", "missing", "tags")
        self._tree = ttk.Treeview(tv_frame, columns=cols, show="headings",
                                   style="Bazarr.Treeview", selectmode="extended")
        for col, w, lbl, anch in [
            ("type",    70,  "Type",    "center"),
            ("title",   360, "Title",   "w"),
            ("missing", 220, "Missing", "w"),
            ("tags",    140, "Tags",    "w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anch)
            self._tree.column(col, width=w, minwidth=40,
                              anchor=anch, stretch=(col == "title"))

        self._tree.tag_configure("odd",    background=t.surface_dark, foreground=t.text)
        self._tree.tag_configure("even",   background=t.card_bg,      foreground=t.text)
        self._tree.tag_configure("series", foreground=t.cyan)
        self._tree.tag_configure("movie",  foreground=t.purple)

        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", lambda e: self._search_selected())

        self._status = tk.Label(self, text="Add a Bazarr API key in Settings to manage subtitles.",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        # Empty state overlay — shown when no API key is configured
        self._empty = EmptyState(
            self, t,
            icon="💬",
            title="Bazarr not configured",
            subtitle="Add a Bazarr API key in Settings to manage subtitles.",
            action_text="⚙ Open Settings",
            action_cmd=lambda: self.controller.tabs.select(8),
        )
        self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._empty.place_forget()

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def on_show(self):
        self.refresh()

    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.bazarr_apikey:
            self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._empty.lift()
            return
        self._empty.place_forget()
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        cfg  = self.controller.config_manager
        host, port, key = cfg.bazarr_host, cfg.bazarr_port, cfg.bazarr_apikey
        rows, errors = [], []
        try:
            try:
                data = _api_get(host, port, key, "episodes/wanted?start=0&length=-1")
                for item in data.get("data", []) or []:
                    title = item.get("seriesTitle", "?")
                    ep    = item.get("episode_number")
                    if ep:
                        title = "{}  —  {}".format(title, ep)
                    rows.append({
                        "type":       "series",
                        "title":      title,
                        "missing":    item.get("missing_subtitles", []) or [],
                        "tags":       item.get("tags", []) or [],
                        "series_id":  item.get("sonarrSeriesId"),
                        "episode_id": item.get("sonarrEpisodeId"),
                    })
            except Exception as e:
                errors.append("Series wanted list: {}".format(e))

            try:
                data = _api_get(host, port, key, "movies/wanted?start=0&length=-1")
                for item in data.get("data", []) or []:
                    rows.append({
                        "type":      "movie",
                        "title":     item.get("title", "?"),
                        "missing":   item.get("missing_subtitles", []) or [],
                        "tags":      item.get("tags", []) or [],
                        "radarr_id": item.get("radarrId"),
                    })
            except Exception as e:
                errors.append("Movies wanted list: {}".format(e))

            self.after(0, lambda r=rows, e=errors: self._populate(r, e))
        finally:
            self._fetching = False
            self.after(0, self._rc.schedule)

    # ------------------------------------------------------------------
    # POPULATE
    # ------------------------------------------------------------------
    def _populate(self, rows, errors):
        self._tree.delete(*self._tree.get_children())
        self._rows.clear()

        for i, row in enumerate(rows):
            langs = ", ".join(m.get("name") or m.get("code2", "?") for m in row["missing"])
            tags  = ", ".join(row["tags"])
            tag   = ("even" if i % 2 == 0 else "odd", row["type"])
            iid   = self._tree.insert("", "end",
                        values=(row["type"].capitalize(), row["title"], langs, tags),
                        tags=tag)
            self._rows[iid] = row

        self._count_lbl.config(text="{} item(s) missing subtitles".format(len(rows)))

        if errors:
            self._status.config(text="; ".join(errors),
                                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)
        elif not rows:
            self._status.config(text="Nothing missing — all subtitles present.",
                                bg=self.theme.surface_dark, fg=self.theme.status_running)
        else:
            self._status.config(
                text="Updated {}".format(time.strftime("%H:%M:%S")),
                bg=self.theme.surface_dark, fg=self.theme.text_muted)
        self._last_lbl.config(text=time.strftime("%H:%M"))

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _search_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        cfg  = self.controller.config_manager
        host, port, key = cfg.bazarr_host, cfg.bazarr_port, cfg.bazarr_apikey
        items = [self._rows[iid] for iid in sel if iid in self._rows]
        if not items:
            return

        self._search_sel_btn.config(state="disabled", text="Searching…")

        def worker():
            ok = err = 0
            for row in items:
                for m in row["missing"]:
                    lang = m.get("code2")
                    if not lang:
                        continue
                    forced = "true" if m.get("forced") else "false"
                    hi     = "true" if m.get("hi") else "false"
                    try:
                        if row["type"] == "series":
                            path = ("episodes/subtitles?seriesid={}&episodeid={}"
                                    "&language={}&forced={}&hi={}").format(
                                        row["series_id"], row["episode_id"], lang, forced, hi)
                        else:
                            path = "movies/subtitles?radarrid={}&language={}&forced={}&hi={}".format(
                                row["radarr_id"], lang, forced, hi)
                        _api_patch(host, port, key, path)
                        ok += 1
                    except Exception:
                        err += 1

            def _done():
                msg = "Searched {} subtitle(s)".format(ok)
                if err:
                    msg += ", {} failed".format(err)
                self._status.config(text=msg, bg=self.theme.surface_dark,
                                    fg=self.theme.status_running if not err else self.theme.yellow)
                self._search_sel_btn.config(state="normal", text="Search Selected")
                self.refresh()
            self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _search_all_wanted(self):
        cfg  = self.controller.config_manager
        host, port, key = cfg.bazarr_host, cfg.bazarr_port, cfg.bazarr_apikey
        if not key:
            return
        if not messagebox.askyesno(
                "Search All Wanted",
                "Trigger Bazarr's background search for every missing subtitle "
                "across all series and movies? This can take a while on a large library.",
                parent=self):
            return

        self._search_all_btn.config(state="disabled", text="Triggering…")

        def worker():
            failed = []
            for task in (_SERIES_TASK, _MOVIES_TASK):
                try:
                    _api_post(host, port, key, "system/tasks?taskid={}".format(task))
                except Exception as e:
                    failed.append(str(e))

            def _done():
                if failed:
                    self._status.config(text="Failed to trigger: " + "; ".join(failed),
                                        bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)
                else:
                    self._status.config(
                        text="Search triggered — running in the background on Bazarr.",
                        bg=self.theme.surface_dark, fg=self.theme.status_running)
                self._search_all_btn.config(state="normal", text="Search All Wanted")
            self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()
