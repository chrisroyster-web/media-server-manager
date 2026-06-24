# ui/plex_tab.py
"""
Plex Now Playing tab.
Uses the Plex Media Server HTTP API with X-Plex-Token authentication.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import json
import time


def _fmt_ms(ms):
    """Format milliseconds as H:MM:SS or MM:SS."""
    try:
        s   = int(ms) // 1000
        h   = s // 3600
        m   = (s % 3600) // 60
        sec = s % 60
        if h:
            return "{}:{:02d}:{:02d}".format(h, m, sec)
        return "{:02d}:{:02d}".format(m, sec)
    except Exception:
        return "--:--"


def _fmt_bitrate(bps):
    if not bps:
        return "--"
    try:
        kbps = int(bps) // 1000
        if kbps >= 1000:
            return "{:.1f} Mbps".format(kbps / 1000)
        return "{} kbps".format(kbps)
    except Exception:
        return "--"


class PlexTab(tk.Frame):
    """Plex Now Playing — active sessions with progress and kick support."""

    PLAYER_COLOR = "#e5a00d"   # Plex gold
    REFRESH_MS   = 15_000

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller      = controller
        self.theme           = controller.theme
        self._refresh_job    = None
        self._active_sessions = []
        self._build_ui()

    # ---------------------------------------------------------
    # BUILD
    # ---------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))

        # Plex gold accent bar
        tk.Frame(hdr, bg=self.PLAYER_COLOR, width=4).pack(side="left", fill="y", padx=(0, 10))
        tk.Label(hdr, text="PLEX  —  NOW PLAYING",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._fetch)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")

        # Summary cards
        cards_row = tk.Frame(self, bg=t.bg)
        cards_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_streams  = self._stat_card(cards_row, "Active Streams", "0")
        self._card_transcode = self._stat_card(cards_row, "Transcoding",   "0")
        self._card_direct   = self._stat_card(cards_row, "Direct Play",    "0")

        # Status label
        self._status_lbl = tk.Label(self, text="",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w", padx=8)
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 4))

        # Scrollable session list
        canvas = tk.Canvas(self, bg=t.bg, highlightthickness=0)
        sb = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))

        self._session_frame = tk.Frame(canvas, bg=t.bg)
        canvas.create_window((0, 0), window=self._session_frame, anchor="nw")
        self._session_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _mw)
        self._session_frame.bind("<MouseWheel>", _mw)

        self._canvas = canvas
        self._fetch()

    def _stat_card(self, parent, label, value):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=t.text,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    # ---------------------------------------------------------
    # FETCH
    # ---------------------------------------------------------
    def _fetch(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._refresh_btn.config(state="disabled", text="Loading…")
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        cfg   = self.controller.config_manager
        host  = cfg.plex_host
        port  = cfg.plex_port
        token = cfg.plex_token
        if not token:
            self.after(0, lambda: self._show_error("No Plex token configured — add it in Config."))
            return
        try:
            url = "http://{}:{}/status/sessions".format(host, port)
            req = urllib.request.Request(url, headers={
                "X-Plex-Token": token,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            sessions = data.get("MediaContainer", {}).get("Metadata") or []
            if not isinstance(sessions, list):
                sessions = [sessions]
            self.after(0, lambda s=sessions: self._update_ui(s))
        except Exception as e:
            self.after(0, lambda err=str(e): self._show_error("Fetch failed: " + err[:80]))
        finally:
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳ Refresh"))
            self._refresh_job = self.after(self.REFRESH_MS, self._fetch)

    # ---------------------------------------------------------
    # UI UPDATE
    # ---------------------------------------------------------
    def _update_ui(self, sessions):
        for w in self._session_frame.winfo_children():
            w.destroy()

        self._active_sessions = sessions
        total    = len(sessions)
        transcode = sum(1 for s in sessions if s.get("TranscodeSession"))
        direct   = total - transcode

        self._card_streams.config(text=str(total))
        self._card_transcode.config(text=str(transcode))
        self._card_direct.config(text=str(direct))

        if not sessions:
            tk.Label(self._session_frame, text="No active streams",
                     bg=self.theme.bg, fg=self.theme.text_muted,
                     font=("Segoe UI", 13)).pack(pady=40)
            self._show_status("No active sessions  ·  " + time.strftime("%H:%M:%S"))
            return

        for s in sessions:
            self._build_session_card(s)

        self._show_status("{} stream{} active  ·  {}".format(
            total, "s" if total != 1 else "", time.strftime("%H:%M:%S")))

    def _build_session_card(self, s):
        t  = self.theme
        ts = s.get("TranscodeSession", {}) or {}

        user    = (s.get("User") or {}).get("title", "Unknown")
        player  = (s.get("Player") or {}).get("title", "Unknown")
        state   = (s.get("Player") or {}).get("state", "unknown")
        ip_addr = (s.get("Player") or {}).get("address", "--")

        media_type = s.get("type", "unknown")
        if media_type == "episode":
            title = "{} — {}".format(s.get("grandparentTitle", "?"), s.get("title", "?"))
        else:
            title = s.get("title", "Unknown")

        duration   = s.get("duration",   0) or 0
        view_offset = s.get("viewOffset", 0) or 0
        pct = (view_offset / duration * 100) if duration else 0

        # Transcode info
        if ts:
            video_dec = ts.get("videoDecision", "copy")
            audio_dec = ts.get("audioDecision", "copy")
            stream_type = "Transcode"
            speed = ts.get("speed", 0)
            stream_detail = "Video: {}  Audio: {}  Speed: {}x".format(
                video_dec.title(), audio_dec.title(), speed)
        else:
            stream_type   = "Direct Play"
            stream_detail = "No transcode"

        # Media info
        media = (s.get("Media") or [{}])[0]
        video_codec = media.get("videoCodec", "--").upper()
        audio_codec = media.get("audioCodec", "--").upper()
        bitrate     = _fmt_bitrate(media.get("bitrate", 0) * 1000 if media.get("bitrate") else 0)
        resolution  = "{}x{}".format(media.get("width", "?"), media.get("height", "?")) \
                      if media.get("width") else "--"

        session_key = s.get("sessionKey", "")
        session_id  = (s.get("Session") or {}).get("id", session_key)

        # Card
        card = tk.Frame(self._session_frame, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", pady=6, padx=4)

        # Colored top bar
        tk.Frame(card, bg=self.PLAYER_COLOR, height=3).pack(fill="x")

        # Header row
        head = tk.Frame(card, bg=t.card_bg)
        head.pack(fill="x", padx=12, pady=(8, 2))

        # State dot
        dot_color = (t.status_running if state == "playing" else
                     t.yellow         if state == "paused"  else t.text_dim)
        dot = tk.Canvas(head, width=10, height=10, bg=t.card_bg, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=dot_color, outline=dot_color)
        dot.pack(side="left", padx=(0, 6))

        tk.Label(head, text=title, bg=t.card_bg, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", fill="x", expand=True)

        # Stream type badge
        badge_color = t.status_stopped if stream_type == "Transcode" else t.status_running
        tk.Label(head, text="  {}  ".format(stream_type),
                 bg=badge_color, fg="#fff", font=t.font_small).pack(side="right", padx=(4, 0))

        # User / player row
        info = tk.Frame(card, bg=t.card_bg)
        info.pack(fill="x", padx=12, pady=2)
        tk.Label(info, text="\U0001f464 {}".format(user),
                 bg=t.card_bg, fg=t.blue, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text="\U0001f4bb {}".format(player),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text=state.title(),
                 bg=t.card_bg, fg=dot_color, font=t.font_small).pack(side="left")

        # Progress bar
        bar_bg  = t.surface_dark
        bar_fg  = self.PLAYER_COLOR
        bar_frm = tk.Frame(card, bg=bar_bg, height=4)
        bar_frm.pack(fill="x", padx=12, pady=(6, 0))
        bar_frm.pack_propagate(False)
        bar_fill = tk.Frame(bar_frm, bg=bar_fg, height=4)
        bar_fill.place(relwidth=min(pct / 100, 1.0), relheight=1.0)

        time_row = tk.Frame(card, bg=t.card_bg)
        time_row.pack(fill="x", padx=12, pady=(2, 4))
        tk.Label(time_row, text=_fmt_ms(view_offset),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left")
        tk.Label(time_row, text=_fmt_ms(duration),
                 bg=t.card_bg, fg=t.text_dim, font=t.font_small).pack(side="right")

        # Stream details
        detail_row = tk.Frame(card, bg=t.card_bg)
        detail_row.pack(fill="x", padx=12, pady=(0, 4))
        bits = [stream_detail, "{}  {}  {}".format(video_codec, audio_codec, bitrate),
                resolution, "IP: {}".format(ip_addr)]
        tk.Label(detail_row, text="   ·   ".join(b for b in bits if b and b != "--"),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left")

        # Kick button
        btn_row = tk.Frame(card, bg=t.card_bg)
        btn_row.pack(fill="x", padx=12, pady=(2, 8))
        kick_btn = tk.Button(btn_row, text="Kick",
                             command=lambda sid=session_id, u=user: self._kick_session(sid, u),
                             bg=t.status_stopped, fg="#fff",
                             bd=0, relief="flat", font=t.font_small,
                             padx=10, pady=2, cursor="hand2")
        kick_btn.pack(side="left")

    # ---------------------------------------------------------
    # KICK
    # ---------------------------------------------------------
    def _kick_session(self, session_id, username):
        def worker():
            try:
                cfg   = self.controller.config_manager
                host  = cfg.plex_host
                port  = cfg.plex_port
                token = cfg.plex_token
                url = ("http://{}:{}/status/sessions/terminate"
                       "?sessionId={}&reason=Removed by administrator".format(
                           host, port, session_id))
                req = urllib.request.Request(url, headers={"X-Plex-Token": token})
                req.get_method = lambda: "DELETE"
                urllib.request.urlopen(req, timeout=8)
                self.after(0, lambda: self._show_status(
                    "Kicked {} successfully.".format(username)))
                self.after(2000, self._fetch)
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Kick failed: " + err[:60]))
        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def _show_status(self, msg, color=None):
        self._status_lbl.config(text=msg, fg=color or self.theme.text_muted)

    def _show_error(self, msg):
        self._show_status(msg, self.theme.status_stopped)
        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        for w in self._session_frame.winfo_children():
            w.destroy()
        tk.Label(self._session_frame, text=msg,
                 bg=self.theme.bg, fg=self.theme.status_stopped,
                 font=self.theme.font_small, wraplength=500).pack(pady=30)
