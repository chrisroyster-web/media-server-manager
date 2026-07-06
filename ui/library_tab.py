# ui/library_tab.py
"""
Unified Media Library Browser.
Supports Emby, Jellyfin, and Plex from a single tab.
Features: server/library picker, type filter, full-text search,
sortable treeview, and an expandable item detail panel.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.parse
import json

# Server type constants
_EMBY     = "Emby"
_JELLYFIN = "Jellyfin"
_PLEX     = "Plex"

LOAD_LIMIT = 300


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_ticks(ticks):
    """100-ns ticks (Emby/Jellyfin) → H:MM:SS."""
    if not ticks:
        return ""
    s = int(ticks) // 10_000_000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, sec)
    return "{:02d}:{:02d}".format(m, sec)


def _fmt_ms(ms):
    """Milliseconds (Plex) → H:MM:SS."""
    if not ms:
        return ""
    s = int(ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, sec)
    return "{:02d}:{:02d}".format(m, sec)


def _fmt_rating(r):
    if not r:
        return ""
    try:
        return "★ {:.1f}".format(float(r))
    except Exception:
        return str(r)


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def _jf_get(host, port, apikey, path):
    url = "http://{}:{}{}".format(host, port, path)
    req = urllib.request.Request(url, headers={
        "X-Emby-Token": apikey, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())


def _plex_get(host, port, token, path):
    sep = "&" if "?" in path else "?"
    url = "http://{}:{}{}{}X-Plex-Token={}".format(host, port, path, sep, token)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Type-filter maps
# ---------------------------------------------------------------------------

# Display label → (jf/emby IncludeItemTypes value, plex type number)
_TYPE_MAP = {
    "All":      (None,    None),
    "Movies":   ("Movie", "1"),
    "TV Shows": ("Series","2"),
    "Episodes": ("Episode","4"),
    "Music":    ("Audio", "10"),
}
_TYPE_LABELS = list(_TYPE_MAP.keys())


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class LibraryTab(tk.Frame):
    """Browse Emby, Jellyfin, or Plex media library from a single unified view."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller   = controller
        self.theme        = controller.theme
        self._items       = []       # currently displayed items (normalised dicts)
        self._total       = 0        # total count reported by API
        self._start       = 0        # pagination offset
        self._libraries   = []       # [{id, title}]
        self._loading     = False
        self._sort_col    = "title"
        self._sort_asc    = True
        self._build_ui()

    # ------------------------------------------------------------------
    # UI BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # ── Header ────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        tk.Frame(hdr, bg=t.blue, width=4).pack(side="left", fill="y", padx=(0, 10))
        tk.Label(hdr, text="MEDIA LIBRARY BROWSER",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._on_refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))

        # ── Controls row ──────────────────────────────────────────────
        ctrl = tk.Frame(self, bg=t.surface_dark)
        ctrl.pack(fill="x", padx=16, pady=(0, 4))

        # Server picker
        tk.Label(ctrl, text="Server:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(12, 4), pady=8)
        self._server_var = tk.StringVar(value="")
        self._server_menu = ttk.Combobox(ctrl, textvariable=self._server_var,
                                          state="readonly", width=10,
                                          font=t.font_small)
        self._server_menu.pack(side="left", padx=(0, 12), pady=6)
        self._server_var.trace_add("write", self._on_server_change)

        # Library picker
        tk.Label(ctrl, text="Library:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 4))
        self._lib_var = tk.StringVar(value="")
        self._lib_menu = ttk.Combobox(ctrl, textvariable=self._lib_var,
                                       state="readonly", width=16,
                                       font=t.font_small)
        self._lib_menu.pack(side="left", padx=(0, 12), pady=6)
        self._lib_var.trace_add("write", self._on_library_change)

        # Type filter
        tk.Label(ctrl, text="Type:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 4))
        self._type_var = tk.StringVar(value="All")
        ttk.Combobox(ctrl, textvariable=self._type_var,
                     values=_TYPE_LABELS, state="readonly", width=10,
                     font=t.font_small).pack(side="left", padx=(0, 12), pady=6)

        # Search
        self._search_var = tk.StringVar()
        search_entry = tk.Entry(ctrl, textvariable=self._search_var, width=22,
                                bg=t.surface_light, fg=t.text, relief="flat",
                                insertbackground=t.blue, font=t.font_small)
        search_entry.pack(side="left", padx=(0, 4), ipady=4)
        search_entry.bind("<Return>", lambda e: self._on_search())

        search_btn = tk.Button(ctrl, text="🔍", command=self._on_search,
                                bg=t.blue, fg="#fff", bd=0, relief="flat",
                                font=t.font_small, padx=8, pady=4, cursor="hand2")
        search_btn.pack(side="left", padx=(0, 4))

        clear_btn = tk.Button(ctrl, text="Clear", command=self._on_clear,
                               bg=t.surface_light, fg=t.text_muted,
                               bd=0, relief="flat", font=t.font_small,
                               padx=8, pady=4, cursor="hand2")
        clear_btn.pack(side="left")

        # ── Status bar ────────────────────────────────────────────────
        self._status_lbl = tk.Label(self, text="Select a server to begin.",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w", padx=12)
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 4))

        # ── Treeview ─────────────────────────────────────────────────
        tree_outer = tk.Frame(self, bg=t.bg)
        tree_outer.pack(fill="both", expand=True, padx=16)

        cols = ("title", "year", "type", "runtime", "rating")
        style = ttk.Style()
        style.configure("Library.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, rowheight=26,
                        font=("Segoe UI", 10))
        style.configure("Library.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=("Segoe UI", 9, "bold"))
        style.map("Library.Treeview",
                  background=[("selected", t.blue)],
                  foreground=[("selected", "#fff")])

        self._tree = ttk.Treeview(tree_outer, columns=cols, show="headings",
                                   style="Library.Treeview", selectmode="browse")
        sb_v = ttk.Scrollbar(tree_outer, orient="vertical",   command=self._tree.yview)
        sb_h = ttk.Scrollbar(tree_outer, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        sb_v.pack(side="right", fill="y")
        sb_h.pack(side="bottom", fill="x")
        self._tree.pack(side="left", fill="both", expand=True)

        col_cfg = [
            ("title",   "Title",          340, "w"),
            ("year",    "Year",            55, "center"),
            ("type",    "Type",            80, "center"),
            ("runtime", "Runtime",         75, "center"),
            ("rating",  "Rating",          70, "center"),
        ]
        for col, heading, width, anchor in col_cfg:
            self._tree.heading(col, text=heading,
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=width, anchor=anchor, minwidth=40)

        self._tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # ── Load More row ─────────────────────────────────────────────
        self._more_frame = tk.Frame(self, bg=t.bg)
        self._more_frame.pack(fill="x", padx=16)
        self._more_btn = tk.Button(self._more_frame, text="Load More…",
                                    command=self._load_more,
                                    bg=t.surface_light, fg=t.blue_bright,
                                    bd=0, relief="flat", font=t.font_small,
                                    padx=14, pady=4, cursor="hand2")

        # ── Detail panel ─────────────────────────────────────────────
        self._detail_frame = tk.Frame(self, bg=t.surface_dark,
                                       highlightbackground=t.card_border,
                                       highlightthickness=1)
        # Packed on demand when a row is selected

        top_row = tk.Frame(self._detail_frame, bg=t.surface_dark)
        top_row.pack(fill="x", padx=14, pady=(10, 4))

        self._detail_title = tk.Label(top_row, text="",
                                       bg=t.surface_dark, fg=t.text,
                                       font=("Segoe UI Semibold", 12),
                                       anchor="w")
        self._detail_title.pack(side="left", fill="x", expand=True)

        close_btn = tk.Button(top_row, text="✕", command=self._close_detail,
                               bg=t.surface_dark, fg=t.text_muted,
                               bd=0, relief="flat", font=("Segoe UI", 12),
                               cursor="hand2")
        close_btn.pack(side="right")

        self._detail_meta = tk.Label(self._detail_frame, text="",
                                      bg=t.surface_dark, fg=t.text_muted,
                                      font=t.font_small, anchor="w")
        self._detail_meta.pack(fill="x", padx=14, pady=(0, 4))

        self._detail_overview = tk.Text(
            self._detail_frame, height=4,
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, relief="flat", wrap="word",
            state="disabled", cursor="arrow")
        self._detail_overview.pack(fill="x", padx=14, pady=(0, 10))

        # Populate server dropdown on start
        self._populate_server_menu()

    # ------------------------------------------------------------------
    # SERVER MENU
    # ------------------------------------------------------------------
    def _populate_server_menu(self):
        servers = self._available_servers()
        self._server_menu["values"] = servers
        if servers:
            self._server_var.set(servers[0])
        else:
            self._server_var.set("")
            self._status("No media servers configured — add API keys in Config.")

    def _available_servers(self):
        cfg = self.controller.config_manager
        out = []
        if cfg.emby_apikey:     out.append(_EMBY)
        if cfg.jellyfin_apikey: out.append(_JELLYFIN)
        if cfg.plex_token:      out.append(_PLEX)
        return out

    # ------------------------------------------------------------------
    # CONTROL CALLBACKS
    # ------------------------------------------------------------------
    def _on_server_change(self, *_):
        server = self._server_var.get()
        if not server:
            return
        self._lib_menu["values"] = []
        self._lib_var.set("")
        self._tree.delete(*self._tree.get_children())
        self._items = []
        self._close_detail()
        self._status("Loading libraries…")
        threading.Thread(target=self._do_fetch_libraries,
                         args=(server,), daemon=True).start()

    def _on_library_change(self, *_):
        lib_title = self._lib_var.get()
        if not lib_title or not self._libraries:
            return
        self._start = 0
        self._items = []
        self._close_detail()
        self._fetch_items(reset=True)

    def _on_search(self):
        self._start = 0
        self._items = []
        self._close_detail()
        self._fetch_items(reset=True)

    def _on_clear(self):
        self._search_var.set("")
        self._type_var.set("All")
        self._on_search()

    def _on_refresh(self):
        self._populate_server_menu()
        self._on_search()

    def _load_more(self):
        self._fetch_items(reset=False)

    # ------------------------------------------------------------------
    # FETCH LIBRARIES
    # ------------------------------------------------------------------
    def _do_fetch_libraries(self, server):
        cfg = self.controller.config_manager
        try:
            if server == _EMBY:
                data  = _jf_get(cfg.emby_host, cfg.emby_port, cfg.emby_apikey,
                                "/emby/Library/VirtualFolders")
                libs  = [{"id": d.get("ItemId") or d.get("Id", ""),
                          "title": d.get("Name", "?")}
                         for d in (data if isinstance(data, list) else [])]
            elif server == _JELLYFIN:
                data  = _jf_get(cfg.jellyfin_host, cfg.jellyfin_port, cfg.jellyfin_apikey,
                                "/Library/VirtualFolders")
                libs  = [{"id": d.get("ItemId") or d.get("Id", ""),
                          "title": d.get("Name", "?")}
                         for d in (data if isinstance(data, list) else [])]
            elif server == _PLEX:
                data  = _plex_get(cfg.plex_host, cfg.plex_port, cfg.plex_token,
                                  "/library/sections")
                dirs  = data.get("MediaContainer", {}).get("Directory", []) or []
                if not isinstance(dirs, list):
                    dirs = [dirs]
                libs  = [{"id": d.get("key", ""),
                          "title": d.get("title", "?"),
                          "plex_type": d.get("type", "")}
                         for d in dirs]
            else:
                libs = []

            self._libraries = libs
            titles = [l["title"] for l in libs]
            def _update():
                self._lib_menu["values"] = titles
                if titles:
                    self._lib_var.set(titles[0])
                else:
                    self._status("No libraries found.")
            self.after(0, _update)
        except Exception as e:
            self.after(0, lambda err=str(e): self._status(
                "Failed to load libraries: " + err[:80], error=True))

    # ------------------------------------------------------------------
    # FETCH ITEMS
    # ------------------------------------------------------------------
    def _fetch_items(self, reset=True):
        if self._loading:
            return
        self._loading = True
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._more_btn.pack_forget()

        server    = self._server_var.get()
        lib_title = self._lib_var.get()
        lib       = next((l for l in self._libraries if l["title"] == lib_title), None)
        search    = self._search_var.get().strip()
        type_key  = self._type_var.get()

        threading.Thread(
            target=self._do_fetch_items,
            args=(server, lib, search, type_key, self._start, reset),
            daemon=True).start()

    def _do_fetch_items(self, server, lib, search, type_key, start, reset):
        cfg     = self.controller.config_manager
        jf_type, plex_type = _TYPE_MAP.get(type_key, (None, None))
        items   = []
        total   = 0

        try:
            if server in (_EMBY, _JELLYFIN):
                host   = cfg.emby_host   if server == _EMBY else cfg.jellyfin_host
                port   = cfg.emby_port   if server == _EMBY else cfg.jellyfin_port
                apikey = cfg.emby_apikey if server == _EMBY else cfg.jellyfin_apikey
                prefix = "/emby" if server == _EMBY else ""

                params = {
                    "Recursive": "true",
                    "SortBy": "SortName",
                    "SortOrder": "Ascending",
                    "Limit": str(LOAD_LIMIT),
                    "StartIndex": str(start),
                    "Fields": "Overview,Genres,RunTimeTicks,CommunityRating,ProductionYear",
                }
                if lib and lib.get("id"):
                    params["ParentId"] = lib["id"]
                if search:
                    params["SearchTerm"] = search
                if jf_type:
                    params["IncludeItemTypes"] = jf_type
                else:
                    params["IncludeItemTypes"] = "Movie,Series,Episode,Audio"

                path  = "{}/Items?{}".format(prefix, urllib.parse.urlencode(params))
                data  = _jf_get(host, port, apikey, path)
                total = data.get("TotalRecordCount", 0)
                raw   = data.get("Items", []) or []
                items = [self._norm_jf(i) for i in raw]

            elif server == _PLEX:
                token = cfg.plex_token
                host  = cfg.plex_host
                port  = cfg.plex_port

                if search:
                    # Global search across all
                    path  = "/search?query={}".format(urllib.parse.quote(search))
                    data  = _plex_get(host, port, token, path)
                    raw   = data.get("MediaContainer", {}).get("Metadata", []) or []
                    if not isinstance(raw, list):
                        raw = [raw]
                    if plex_type:
                        raw = [m for m in raw if str(m.get("type","")) == _plex_type_name(plex_type)]
                    items = [self._norm_plex(m) for m in raw]
                    total = len(items)
                elif lib:
                    key    = lib["id"]
                    qparams = {}
                    if plex_type:
                        qparams["type"] = plex_type
                    path   = "/library/sections/{}/all".format(key)
                    if qparams:
                        path += "?" + urllib.parse.urlencode(qparams)
                    data  = _plex_get(host, port, token, path)
                    mc    = data.get("MediaContainer", {})
                    total = int(mc.get("totalSize", mc.get("size", 0)) or 0)
                    raw   = mc.get("Metadata", []) or []
                    if not isinstance(raw, list):
                        raw = [raw]
                    items = [self._norm_plex(m) for m in raw]
                else:
                    items = []
                    total = 0

        except Exception as e:
            self.after(0, lambda err=str(e): self._status(
                "Fetch error: " + err[:80], error=True))
            self.after(0, self._reset_refresh_btn)
            self._loading = False
            return

        self._loading = False
        self.after(0, lambda i=items, t=total, r=reset:
                   self._populate_tree(i, t, r))

    # ------------------------------------------------------------------
    # NORMALISE ITEMS
    # ------------------------------------------------------------------
    def _norm_jf(self, d):
        genres = ", ".join((d.get("Genres") or [])[:3])
        return {
            "id":       d.get("Id", ""),
            "title":    d.get("Name", ""),
            "year":     str(d.get("ProductionYear", "")) if d.get("ProductionYear") else "",
            "type":     d.get("Type", ""),
            "runtime":  _fmt_ticks(d.get("RunTimeTicks")),
            "rating":   _fmt_rating(d.get("CommunityRating")),
            "overview": d.get("Overview", ""),
            "genres":   genres,
        }

    def _norm_plex(self, d):
        genres_raw = d.get("Genre", []) or []
        if isinstance(genres_raw, dict):
            genres_raw = [genres_raw]
        genres = ", ".join(g.get("tag", "") for g in genres_raw[:3])
        ptype  = d.get("type", "")
        type_label = {"movie": "Movie", "show": "TV Show",
                      "season": "Season", "episode": "Episode",
                      "track": "Track"}.get(ptype, ptype.title())
        return {
            "id":       d.get("ratingKey", ""),
            "title":    d.get("title", ""),
            "year":     str(d.get("year", "")) if d.get("year") else "",
            "type":     type_label,
            "runtime":  _fmt_ms(d.get("duration")),
            "rating":   _fmt_rating(d.get("rating") or d.get("audienceRating")),
            "overview": d.get("summary", ""),
            "genres":   genres,
        }

    # ------------------------------------------------------------------
    # POPULATE TREE
    # ------------------------------------------------------------------
    def _populate_tree(self, new_items, total, reset):
        if reset:
            self._tree.delete(*self._tree.get_children())
            self._items = []
            self._start = 0

        self._items.extend(new_items)
        self._start += len(new_items)
        self._total  = total

        for item in new_items:
            iid = "{}_{}".format(item["id"], len(self._tree.get_children()))
            self._tree.insert("", "end", iid=iid, tags=(item["id"],),
                              values=(item["title"], item["year"],
                                      item["type"], item["runtime"],
                                      item["rating"]))

        shown = len(self._items)
        status = "Showing {} of {} item{}".format(
            shown, total if total else shown, "s" if shown != 1 else "")
        if self._search_var.get().strip():
            status += "  ·  \"{}\"".format(self._search_var.get().strip())
        self._status(status)

        # Show/hide Load More button
        if total and self._start < total:
            self._more_btn.config(
                text="Load More…  ({} remaining)".format(total - self._start))
            self._more_btn.pack(side="left", pady=(4, 8))
        else:
            self._more_btn.pack_forget()

        self._reset_refresh_btn()

    # ------------------------------------------------------------------
    # DETAIL PANEL
    # ------------------------------------------------------------------
    def _on_row_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        # The tag on each row holds the item id
        tags = self._tree.item(sel[0], "tags")
        if not tags:
            return
        item_id = tags[0]
        item = next((i for i in self._items if str(i["id"]) == str(item_id)), None)
        if not item:
            return
        self._show_detail(item)

    def _show_detail(self, item):
        title_year = item["title"]
        if item.get("year"):
            title_year += "  ({})".format(item["year"])
        self._detail_title.config(text=title_year)

        meta_parts = []
        if item.get("type"):
            meta_parts.append(item["type"])
        if item.get("runtime"):
            meta_parts.append(item["runtime"])
        if item.get("rating"):
            meta_parts.append(item["rating"])
        if item.get("genres"):
            meta_parts.append(item["genres"])
        self._detail_meta.config(text="   ·   ".join(meta_parts))

        overview = item.get("overview", "").strip() or "(No description available)"
        self._detail_overview.config(state="normal")
        self._detail_overview.delete("1.0", "end")
        self._detail_overview.insert("end", overview)
        self._detail_overview.config(state="disabled")

        if not self._detail_frame.winfo_ismapped():
            self._detail_frame.pack(fill="x", padx=16, pady=(4, 8))

    def _close_detail(self):
        if self._detail_frame.winfo_ismapped():
            self._detail_frame.pack_forget()
        self._tree.selection_remove(*self._tree.selection())

    # ------------------------------------------------------------------
    # SORTING
    # ------------------------------------------------------------------
    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        reverse = not self._sort_asc
        data = [(self._tree.set(k, col), k) for k in self._tree.get_children()]
        data.sort(key=lambda x: x[0].lower() if x[0] else "", reverse=reverse)
        for i, (_, k) in enumerate(data):
            self._tree.move(k, "", i)

        # Update heading arrow indicators
        for c in ("title", "year", "type", "runtime", "rating"):
            label = {
                "title": "Title", "year": "Year", "type": "Type",
                "runtime": "Runtime", "rating": "Rating"
            }[c]
            arrow = (" ▲" if self._sort_asc else " ▼") if c == col else ""
            self._tree.heading(c, text=label + arrow)

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _status(self, msg, error=False):
        t = self.theme
        color = t.status_stopped if error else t.text_muted
        self._status_lbl.config(text=msg, fg=color)

    def _reset_refresh_btn(self):
        self._refresh_btn.config(state="normal", text="⟳ Refresh")

    def on_show(self):
        """Called by main when this tab is switched to."""
        self._populate_server_menu()


# ---------------------------------------------------------------------------
# Plex helpers
# ---------------------------------------------------------------------------

def _plex_type_name(plex_type_num):
    """Map Plex type number back to its string name for client-side filtering."""
    return {"1": "movie", "2": "show", "4": "episode", "10": "track"}.get(
        str(plex_type_num), "")
