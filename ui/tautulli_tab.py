# ui/tautulli_tab.py
"""
Tautulli statistics and monitoring tab.
Shows active streams, play history, and library stats.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import urllib.parse
import json
import time

from ui.refresh_control import RefreshControl


def _api(host, port, apikey, cmd, extra=""):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v2?apikey={}&cmd={}{}".format(
        host, port, urllib.parse.quote(apikey), cmd, extra)
    with urllib.request.urlopen(url, timeout=8) as r:
        data = json.loads(r.read().decode())
    resp = data.get("response", {})
    if resp.get("result") != "success":
        raise RuntimeError(resp.get("message", "API error"))
    return resp.get("data", {})


def _fmt_duration(seconds):
    """Convert seconds to h:mm:ss or m:ss string."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "--"
    if s >= 3600:
        return "{:d}h {:02d}m".format(s // 3600, (s % 3600) // 60)
    return "{:d}m {:02d}s".format(s // 60, s % 60)


class TautulliTab(tk.Frame):

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
        tk.Label(hdr, text="TAUTULLI", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "tautulli",
                                  default=30, on_refresh=self.refresh)
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
        self._card_streams    = self._stat_card(cards, "Active",       "--", t.cyan)
        self._card_transcode  = self._stat_card(cards, "Transcoding",  "--", t.yellow)
        self._card_direct     = self._stat_card(cards, "Direct Play",  "--", t.status_running)
        self._card_bandwidth  = self._stat_card(cards, "Bandwidth",    "--", t.purple)

        # Notebook
        nb_style = ttk.Style()
        nb_style.configure("TT.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("TT.TNotebook.Tab",
                           background=t.surface, foreground=t.text_muted,
                           padding=[12, 6], font=t.font_small)
        nb_style.map("TT.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="TT.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._streams_frame  = tk.Frame(self._nb, bg=t.bg)
        self._history_frame  = tk.Frame(self._nb, bg=t.bg)
        self._libs_frame     = tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._streams_frame, text="  Active Streams  ")
        self._nb.add(self._history_frame, text="  History  ")
        self._nb.add(self._libs_frame,    text="  Libraries  ")

        self._build_streams_tab()
        self._build_history_tab()
        self._build_libraries_tab()

        self._status = tk.Label(
            self, text="Configure Tautulli in Settings to get started",
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

    def _build_streams_tab(self):
        t = self.theme
        style = ttk.Style()
        style.configure("TT.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("TT.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("TT.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("user", "title", "type", "progress", "decision", "quality", "player")
        self._stream_tree = ttk.Treeview(self._streams_frame, columns=cols,
                                          show="headings", style="TT.Treeview")
        for col, w, lbl, anch in [
            ("user",      120, "User",       "w"),
            ("title",     240, "Title",      "w"),
            ("type",       70, "Type",       "w"),
            ("progress",   80, "Progress",   "center"),
            ("decision",   90, "Decision",   "w"),
            ("quality",   100, "Quality",    "w"),
            ("player",    130, "Player",     "w"),
        ]:
            self._stream_tree.heading(col, text=lbl, anchor=anch)
            self._stream_tree.column(col, width=w, minwidth=40,
                                     anchor=anch, stretch=(col == "title"))

        self._stream_tree.tag_configure("transcode",    foreground=t.yellow)
        self._stream_tree.tag_configure("direct_play",  foreground=t.status_running)
        self._stream_tree.tag_configure("direct_stream",foreground=t.cyan)

        vsb = ttk.Scrollbar(self._streams_frame, orient="vertical",
                            command=self._stream_tree.yview)
        self._stream_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._stream_tree.pack(fill="both", expand=True)

        self._no_streams = tk.Label(self._streams_frame,
                                     text="No active streams",
                                     bg=t.bg, fg=t.text_muted,
                                     font=t.font_small)

    def _build_history_tab(self):
        t = self.theme
        cols = ("date", "user", "title", "type", "duration", "decision")
        self._hist_tree = ttk.Treeview(self._history_frame, columns=cols,
                                        show="headings", style="TT.Treeview")
        for col, w, lbl, anch in [
            ("date",      130, "Date",     "w"),
            ("user",      120, "User",     "w"),
            ("title",     280, "Title",    "w"),
            ("type",       70, "Type",     "w"),
            ("duration",   80, "Duration", "e"),
            ("decision",   90, "Decision", "w"),
        ]:
            self._hist_tree.heading(col, text=lbl, anchor=anch)
            self._hist_tree.column(col, width=w, minwidth=40,
                                   anchor=anch, stretch=(col == "title"))
        vsb2 = ttk.Scrollbar(self._history_frame, orient="vertical",
                             command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self._hist_tree.pack(fill="both", expand=True)

    def _build_libraries_tab(self):
        t = self.theme
        cols = ("name", "type", "count", "plays")
        self._lib_tree = ttk.Treeview(self._libs_frame, columns=cols,
                                       show="headings", style="TT.Treeview")
        for col, w, lbl, anch in [
            ("name",   220, "Library", "w"),
            ("type",    90, "Type",    "w"),
            ("count",   80, "Items",   "e"),
            ("plays",   80, "Plays",   "e"),
        ]:
            self._lib_tree.heading(col, text=lbl, anchor=anch)
            self._lib_tree.column(col, width=w, minwidth=40,
                                  anchor=anch, stretch=(col == "name"))
        vsb3 = ttk.Scrollbar(self._libs_frame, orient="vertical",
                             command=self._lib_tree.yview)
        self._lib_tree.configure(yscrollcommand=vsb3.set)
        vsb3.pack(side="right", fill="y")
        self._lib_tree.pack(fill="both", expand=True)

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.tautulli_apikey:
            self._status.config(
                text="No API key — add it in Settings > Tautulli",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            cfg  = self.controller.config_manager
            host = cfg.tautulli_host
            port = cfg.tautulli_port
            key  = cfg.tautulli_apikey

            try:
                activity = _api(host, port, key, "get_activity")
            except Exception as e:
                self.after(0, lambda: self._status.config(
                    text="Cannot reach Tautulli: {}".format(e),
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped))
                return

            try:
                history_data = _api(host, port, key, "get_history", "&length=50")
                history = history_data.get("data", [])
            except Exception:
                history = []

            try:
                libs = _api(host, port, key, "get_libraries")
            except Exception:
                libs = []

            self.after(0, lambda: self._populate(activity, history, libs))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, activity, history, libs):
        t = self.theme

        sessions   = activity.get("sessions", [])
        n_streams  = int(activity.get("stream_count", 0))
        n_transcode= int(activity.get("stream_count_transcode", 0))
        n_direct   = int(activity.get("stream_count_direct_play", 0))
        bw_total   = int(activity.get("total_bandwidth", 0))

        if bw_total >= 1024:
            bw_str = "{:.1f} Mbps".format(bw_total / 1024)
        else:
            bw_str = "{} kbps".format(bw_total)

        self._card_streams.config(
            text=str(n_streams),
            fg=t.cyan if n_streams else t.text_muted)
        self._card_transcode.config(
            text=str(n_transcode),
            fg=t.yellow if n_transcode else t.text_muted)
        self._card_direct.config(text=str(n_direct))
        self._card_bandwidth.config(text=bw_str)

        # Active streams
        self._stream_tree.delete(*self._stream_tree.get_children())
        if sessions:
            self._no_streams.place_forget()
            for sess in sessions:
                decision = sess.get("transcode_decision", "direct play")
                tag = {"transcode": "transcode",
                       "direct play": "direct_play",
                       "direct stream": "direct_stream"}.get(decision, "")

                # Progress
                dur = int(sess.get("duration", 0) or 0)
                prog = int(sess.get("view_offset", 0) or 0)
                if dur > 0:
                    pct = "{:.0f}%".format(100 * prog / dur)
                else:
                    pct = "--"

                media_type = sess.get("media_type", "")
                if media_type == "episode":
                    title = "{} S{:02d}E{:02d}".format(
                        sess.get("grandparent_title", ""),
                        int(sess.get("parent_media_index", 0) or 0),
                        int(sess.get("media_index", 0) or 0))
                else:
                    title = sess.get("title", "--")

                quality = sess.get("stream_video_resolution", "") or \
                          sess.get("video_resolution", "--")

                self._stream_tree.insert("", "end", tags=(tag,), values=(
                    sess.get("friendly_name", "--"),
                    title,
                    media_type.capitalize() or "--",
                    pct,
                    decision.replace("_", " ").title(),
                    quality,
                    sess.get("player", "--"),
                ))
        else:
            self._no_streams.place(relx=0.5, rely=0.4, anchor="center")

        # History
        self._hist_tree.delete(*self._hist_tree.get_children())
        for rec in history:
            ts = rec.get("date", 0)
            try:
                date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
            except Exception:
                date_str = str(ts)

            media_type = rec.get("media_type", "")
            if media_type == "episode":
                title = "{} S{:02d}E{:02d}".format(
                    rec.get("grandparent_title", ""),
                    int(rec.get("parent_media_index", 0) or 0),
                    int(rec.get("media_index", 0) or 0))
            else:
                title = rec.get("title", "--")

            dur = _fmt_duration(rec.get("play_duration", 0))
            decision = (rec.get("transcode_decision") or "direct play").replace("_", " ").title()

            self._hist_tree.insert("", "end", values=(
                date_str,
                rec.get("friendly_name", "--"),
                title,
                media_type.capitalize() or "--",
                dur,
                decision,
            ))

        # Libraries
        self._lib_tree.delete(*self._lib_tree.get_children())
        for lib in libs:
            count = lib.get("count", lib.get("parent_count", "--"))
            self._lib_tree.insert("", "end", values=(
                lib.get("section_name", "--"),
                lib.get("section_type", "--").capitalize(),
                count,
                lib.get("plays", "--"),
            ))

        stream_txt = "{} stream{}".format(n_streams, "s" if n_streams != 1 else "")
        self._status.config(
            text="{} active | {} transcoding | {} direct play | {}".format(
                stream_txt, n_transcode, n_direct, bw_str),
            bg=t.surface_dark, fg=t.status_running if n_streams else t.text_muted)
