# ui/play_history_tab.py
"""
Unified play history tab — pulls from Plex, Emby, and/or Jellyfin
(whichever are configured) and merges into a single newest-first list.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fmt_ms(ms):
    """Milliseconds → '1h 23m'."""
    try:
        s = int(ms) // 1000
        h, r = divmod(s, 3600)
        m = r // 60
        return ("{}h {}m".format(h, m) if h else "{}m".format(m))
    except Exception:
        return "--"


def _fmt_ticks(ticks):
    """Emby/Jellyfin 100-ns ticks → '1h 23m'."""
    try:
        return _fmt_ms(int(ticks) / 10_000)
    except Exception:
        return "--"


_UTC = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)


def _parse_iso(s):
    """ISO-8601 string → timezone-aware datetime (UTC). Tolerates fractional seconds."""
    if not s:
        return _EPOCH
    # Strip trailing Z, drop fractional seconds
    s2 = s.rstrip("Z").split(".")[0].strip()
    for fmt, length in (
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d",          10),
    ):
        try:
            return datetime.strptime(s2[:length], fmt).replace(tzinfo=_UTC)
        except Exception:
            pass
    return _EPOCH


def _ep_label(title, series="", season=None, episode=None):
    if series:
        return "{} S{:0>2}E{:0>2} – {}".format(
            series, season or "?", episode or "?", title)
    return title


class PlayHistoryTab(tk.Frame):
    LIMIT = 50   # entries per source

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller  = controller
        self.theme       = controller.theme
        self._entries    = []
        self._loading    = False
        self._source_var = tk.StringVar(value="All")
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # ── Header ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="PLAY HISTORY",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        ctrl = tk.Frame(hdr, bg=t.bg)
        ctrl.pack(side="right")

        # Source filter
        tk.Label(ctrl, text="Source:", bg=t.bg,
                 fg=t.text_muted, font=t.font_small).pack(side="left")
        src_menu = tk.OptionMenu(ctrl, self._source_var,
                                 "All", "Plex", "Emby", "Jellyfin",
                                 command=lambda _: self._render())
        src_menu.configure(
            bg=t.surface, fg=t.text, relief="flat",
            font=t.font_small, highlightthickness=0,
            activebackground=t.surface_light, activeforeground=t.text,
        )
        src_menu["menu"].configure(bg=t.surface, fg=t.text)
        src_menu.pack(side="left", padx=(4, 12))

        self._count_lbl = tk.Label(ctrl, text="",
                                    bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._count_lbl.pack(side="left", padx=(0, 12))

        self._refresh_btn = tk.Button(ctrl, text="⟳ Refresh",
                                       command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="left")

        # ── Treeview ─────────────────────────────────────────
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("History.Treeview",
                        background=t.card_bg,
                        foreground=t.text,
                        fieldbackground=t.card_bg,
                        borderwidth=0,
                        rowheight=28,
                        font=t.font_regular)
        style.configure("History.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map("History.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("date", "title", "type", "user", "duration", "source")
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                  show="headings",
                                  style="History.Treeview",
                                  selectmode="browse")

        headings = [
            ("date",     "Date / Time",  150, "w"),
            ("title",    "Title",        360, "w"),
            ("type",     "Type",          70, "center"),
            ("user",     "User",         110, "w"),
            ("duration", "Duration",      80, "e"),
            ("source",   "Source",        90, "center"),
        ]
        for col, text, width, anchor in headings:
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=40,
                             anchor=anchor, stretch=(col == "title"))

        self.tree.tag_configure("odd",      background=t.surface_dark, foreground=t.text)
        self.tree.tag_configure("even",     background=t.card_bg,      foreground=t.text)
        self.tree.tag_configure("plex",     foreground="#e5a00d")
        self.tree.tag_configure("emby",     foreground="#52b54b")
        self.tree.tag_configure("jellyfin", foreground="#aa5cc3")

        vsb = tk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # ── Status bar ───────────────────────────────────────
        self._status = tk.Label(
            self,
            text="Click  ⟳ Refresh  to load history from configured media servers",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # PUBLIC
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        if self._loading:
            return
        self._loading = True
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._set_status("Fetching play history…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    # =========================================================
    # FETCH  (background thread)
    # =========================================================
    def _http(self, url, headers=None):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read(), None
        except Exception as e:
            return None, str(e)

    def _fetch(self):
        try:
            cfg     = self.controller.config_manager
            entries = []
            errors  = []

            if cfg.plex_token:
                try:
                    entries += self._fetch_plex(cfg)
                except Exception as e:
                    errors.append("Plex: {}".format(e))

            if cfg.emby_apikey:
                try:
                    entries += self._fetch_server("Emby",
                                                  cfg.emby_host, cfg.emby_port,
                                                  cfg.emby_apikey)
                except Exception as e:
                    errors.append("Emby: {}".format(e))

            if cfg.jellyfin_apikey:
                try:
                    entries += self._fetch_server("Jellyfin",
                                                  cfg.jellyfin_host, cfg.jellyfin_port,
                                                  cfg.jellyfin_apikey)
                except Exception as e:
                    errors.append("Jellyfin: {}".format(e))

            # Sort newest first across all sources
            entries.sort(key=lambda e: e["ts"], reverse=True)

            status = "Loaded {} entr{}".format(
                len(entries), "y" if len(entries) == 1 else "ies")
            if errors:
                status += "   ⚠ " + "  |  ".join(errors)

            self.after(0, lambda: self._done(entries, status,
                                              level="ok" if entries else "info"))
        finally:
            self._fetching = False

    # ── Plex ──────────────────────────────────────────────────
    def _fetch_plex(self, cfg):
        base = "http://{}:{}".format(cfg.plex_host, cfg.plex_port)
        url  = ("{}/status/sessions/history/all"
                "?sort=viewedAt:desc"
                "&X-Plex-Token={}").format(base, cfg.plex_token)

        data, err = self._http(url)
        if err or not data:
            raise RuntimeError(err or "no response")

        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            raise RuntimeError("XML: {}".format(e))

        entries = []
        for el in root:
            viewed = el.get("viewedAt") or el.get("lastViewedAt")
            if not viewed:
                continue
            try:
                ts = datetime.fromtimestamp(int(viewed), tz=_UTC)
            except Exception:
                ts = _EPOCH

            mtype  = el.get("type", "unknown")
            title  = el.get("title", "?")
            if mtype == "episode":
                title = _ep_label(title,
                                  el.get("grandparentTitle", ""),
                                  el.get("parentIndex"),
                                  el.get("index"))

            user_el = el.find("User")
            user = user_el.get("title", "Unknown") if user_el is not None else "Unknown"

            entries.append({
                "source":   "Plex",
                "title":    title,
                "type":     mtype.capitalize(),
                "user":     user,
                "duration": _fmt_ms(el.get("duration")),
                "ts":       ts,
                "date_str": ts.strftime("%Y-%m-%d  %H:%M"),
            })
            if len(entries) >= self.LIMIT:
                break
        return entries

    # ── Emby / Jellyfin ───────────────────────────────────────
    def _fetch_server(self, source, host, port, apikey):
        """
        Pulls play history from the Activity Log endpoint, which has real
        timestamps for every play event across all users.  Falls back to
        the Items API if the log returns nothing useful.
        """
        base    = "http://{}:{}".format(host, port)
        headers = {"X-Emby-Token": apikey}

        # Activity log — fetch a larger window so we have enough after filtering
        url  = ("{}/System/ActivityLog/Entries"
                "?startIndex=0&limit={}").format(base, self.LIMIT * 4)
        data, err = self._http(url, headers)
        if err or not data:
            raise RuntimeError(err or "no response from /System/ActivityLog/Entries")

        obj   = json.loads(data)
        items = obj.get("Items", [])

        _STOP_TYPES  = {"playback.stop",  "videoplaybackstopped"}
        _START_TYPES = {"playback.start", "videoplaybackstarted"}

        def _parse_entry(item):
            """Return (user, title, ts) parsed from the Name sentence."""
            raw  = item.get("Name", "")
            user = item.get("UserName") or ""
            title = raw
            if " playing " in raw:
                after = raw.split(" playing ", 1)[1]
                title = after.rsplit(" on ", 1)[0] if " on " in after else after
                if not user:
                    if " has finished" in raw:
                        user = raw.split(" has finished", 1)[0]
                    elif " is playing" in raw:
                        user = raw.split(" is playing", 1)[0]
            if not user:
                user = str(item.get("UserId", "Unknown"))
            ts = _parse_iso(item.get("Date", ""))
            return user, title, ts

        # First pass: index all start events by (user, title_key) → [ts, ...]
        # items are newest-first, so starts for a given play sit after its stop
        start_lookup = {}
        for item in items:
            if item.get("Type", "").lower() not in _START_TYPES:
                continue
            user, title, ts = _parse_entry(item)
            key = (user.lower(), title.lower()[:60])
            start_lookup.setdefault(key, []).append(ts)

        # Second pass: emit stop events with computed duration
        entries = []
        for item in items:
            if item.get("Type", "").lower() not in _STOP_TYPES:
                continue

            user, title, stop_ts = _parse_entry(item)
            date_s = stop_ts.strftime("%Y-%m-%d  %H:%M") if stop_ts != _EPOCH else "—"

            # Match to most-recent start that occurred before this stop
            dur_str = "—"
            key = (user.lower(), title.lower()[:60])
            candidates = [t for t in start_lookup.get(key, []) if t <= stop_ts]
            if candidates:
                start_ts  = max(candidates)
                delta_s   = int((stop_ts - start_ts).total_seconds())
                if 0 < delta_s < 86400:   # sanity: must be < 24 h
                    dur_str = _fmt_ms(delta_s * 1000)

            entries.append({
                "source":   source,
                "title":    title,
                "type":     "Video",
                "user":     user,
                "duration": dur_str,
                "ts":       stop_ts,
                "date_str": date_s,
            })
            if len(entries) >= self.LIMIT:
                break

        return entries

    # =========================================================
    # DONE / RENDER  (main thread)
    # =========================================================
    def _done(self, entries, status, level="info"):
        self._entries = entries
        self._loading = False
        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._set_status(status, level)
        self._render()

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        src = self._source_var.get()
        shown = [e for e in self._entries
                 if src == "All" or e["source"] == src]

        count = len(shown)
        self._count_lbl.config(
            text="{} entr{}".format(count, "y" if count == 1 else "ies"))

        for i, e in enumerate(shown):
            src_tag = e["source"].lower()   # "plex" / "emby" / "jellyfin"
            row_tag = "odd" if i % 2 else "even"
            self.tree.insert("", "end",
                             values=(e["date_str"], e["title"], e["type"],
                                     e["user"], e["duration"], e["source"]),
                             tags=(row_tag, src_tag))

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "ok": t.status_running, "error": t.status_stopped}
        self._status.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
