# ui/jellyfin_tab.py
"""
Jellyfin Now Playing tab.
Jellyfin is an Emby fork — the Sessions API is nearly identical.
Uses X-Emby-Token header (same key name as Emby).
"""

import tkinter as tk
import threading
import urllib.request
import json
import time

from ui.refresh_control import RefreshControl


def _fmt_ticks(ticks):
    """Format Jellyfin ticks (10,000,000 per second) as H:MM:SS."""
    try:
        s   = int(ticks) // 10_000_000
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
        if bps >= 1_000_000:
            return "{:.1f} Mbps".format(bps / 1_000_000)
        return "{} kbps".format(bps // 1000)
    except Exception:
        return "--"


class JellyfinTab(tk.Frame):
    """Jellyfin Now Playing — active sessions with progress, kick, and message support."""

    PLAYER_COLOR = "#00a4dc"   # Jellyfin blue

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller       = controller
        self.theme            = controller.theme
        self._active_sessions = []
        self._build_ui()

    # ---------------------------------------------------------
    # BUILD
    # ---------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))

        tk.Frame(hdr, bg=self.PLAYER_COLOR, width=4).pack(side="left", fill="y", padx=(0, 10))
        tk.Label(hdr, text="JELLYFIN  —  NOW PLAYING",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "jellyfin",
                                  default=15, on_refresh=self._fetch)
        self._rc.pack(side="right")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._fetch)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))

        msg_btn = tk.Button(hdr, text="Message All", command=self._message_all)
        t.style_button(msg_btn)
        msg_btn.pack(side="right", padx=(0, 8))

        scan_btn = tk.Button(hdr, text="⟳ Scan Libraries", command=self._scan_libraries)
        t.style_button(scan_btn)
        scan_btn.pack(side="right", padx=(0, 8))

        cards_row = tk.Frame(self, bg=t.bg)
        cards_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_streams   = self._stat_card(cards_row, "Active Streams", "0")
        self._card_transcode = self._stat_card(cards_row, "Transcoding",    "0")
        self._card_direct    = self._stat_card(cards_row, "Direct Play",    "0")

        self._status_lbl = tk.Label(self, text="",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w", padx=8)
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 4))

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
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._fetching = True
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        cfg    = self.controller.config_manager
        host   = cfg.jellyfin_host
        port   = cfg.jellyfin_port
        apikey = cfg.jellyfin_apikey
        if not apikey:
            self.after(0, lambda: self._show_error(
                "No Jellyfin API key configured — add it in Config."))
            return
        try:
            url = "http://{}:{}/Sessions?activeWithinSeconds=30".format(host, port)
            req = urllib.request.Request(url, headers={
                "X-Emby-Token": apikey,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                sessions = json.loads(r.read())
            if not isinstance(sessions, list):
                sessions = []
            # Only sessions with NowPlayingItem
            sessions = [s for s in sessions if s.get("NowPlayingItem")]
            self.after(0, lambda s=sessions: self._update_ui(s))
        except Exception as e:
            self.after(0, lambda err=str(e): self._show_error("Fetch failed: " + err[:80]))
        finally:
            self._fetching = False
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳ Refresh"))
            self.after(0, self._rc.schedule)

    # ---------------------------------------------------------
    # UI UPDATE
    # ---------------------------------------------------------
    def _update_ui(self, sessions):
        for w in self._session_frame.winfo_children():
            w.destroy()

        self._active_sessions = sessions
        total     = len(sessions)
        transcode = sum(1 for s in sessions
                        if (s.get("TranscodingInfo") or {}).get("IsVideoDirect") is False)
        direct    = total - transcode

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
        t     = self.theme
        item  = s.get("NowPlayingItem", {})
        ti    = s.get("TranscodingInfo", {}) or {}

        session_id = s.get("Id", "")
        username   = s.get("UserName", "Unknown")
        client     = s.get("Client", "Unknown")
        device     = s.get("DeviceName", "Unknown")
        state_info = s.get("PlayState", {}) or {}
        is_paused  = state_info.get("IsPaused", False)
        state      = "Paused" if is_paused else "Playing"

        media_type = item.get("Type", "")
        if media_type == "Episode":
            title = "{} — {}".format(item.get("SeriesName", "?"), item.get("Name", "?"))
        else:
            title = item.get("Name", "Unknown")

        pos_ticks  = state_info.get("PositionTicks", 0) or 0
        dur_ticks  = item.get("RunTimeTicks", 0) or 0
        pct        = (pos_ticks / dur_ticks * 100) if dur_ticks else 0

        # Stream type
        is_video_direct = ti.get("IsVideoDirect", True)
        is_audio_direct = ti.get("IsAudioDirect", True)
        if not is_video_direct:
            stream_type = "Transcoding"
        elif not is_audio_direct:
            stream_type = "Video Direct / Audio Transcode"
        else:
            stream_type = "Direct Play"

        # Video stream info
        video_streams = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Video"]
        audio_streams = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Audio"]
        v_codec = video_streams[0].get("Codec", "--").upper() if video_streams else "--"
        a_codec = audio_streams[0].get("Codec", "--").upper() if audio_streams else "--"
        resolution = ("{}x{}".format(video_streams[0].get("Width", "?"),
                                     video_streams[0].get("Height", "?"))
                      if video_streams else "--")
        bitrate = _fmt_bitrate(ti.get("Bitrate") or s.get("TranscodingInfo", {}).get("Bitrate"))

        # Card
        card = tk.Frame(self._session_frame, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", pady=6, padx=4)

        tk.Frame(card, bg=self.PLAYER_COLOR, height=3).pack(fill="x")

        head = tk.Frame(card, bg=t.card_bg)
        head.pack(fill="x", padx=12, pady=(8, 2))

        dot_color = t.yellow if is_paused else t.status_running
        dot = tk.Canvas(head, width=10, height=10, bg=t.card_bg, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=dot_color, outline=dot_color)
        dot.pack(side="left", padx=(0, 6))

        tk.Label(head, text=title, bg=t.card_bg, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", fill="x", expand=True)

        badge_color = t.status_stopped if "Transcode" in stream_type else t.status_running
        tk.Label(head, text="  {}  ".format(stream_type),
                 bg=badge_color, fg="#fff", font=t.font_small).pack(side="right", padx=(4, 0))

        info = tk.Frame(card, bg=t.card_bg)
        info.pack(fill="x", padx=12, pady=2)
        tk.Label(info, text="\U0001f464 {}".format(username),
                 bg=t.card_bg, fg=t.blue, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text="\U0001f4bb {}".format(device),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text=client,
                 bg=t.card_bg, fg=t.text_dim, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text=state,
                 bg=t.card_bg, fg=dot_color, font=t.font_small).pack(side="left")

        # Progress bar
        bar_frm = tk.Frame(card, bg=t.surface_dark, height=4)
        bar_frm.pack(fill="x", padx=12, pady=(6, 0))
        bar_frm.pack_propagate(False)
        tk.Frame(bar_frm, bg=self.PLAYER_COLOR, height=4).place(
            relwidth=min(pct / 100, 1.0), relheight=1.0)

        time_row = tk.Frame(card, bg=t.card_bg)
        time_row.pack(fill="x", padx=12, pady=(2, 4))
        tk.Label(time_row, text=_fmt_ticks(pos_ticks),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left")
        tk.Label(time_row, text=_fmt_ticks(dur_ticks),
                 bg=t.card_bg, fg=t.text_dim, font=t.font_small).pack(side="right")

        detail_row = tk.Frame(card, bg=t.card_bg)
        detail_row.pack(fill="x", padx=12, pady=(0, 4))
        bits = ["{} / {}".format(v_codec, a_codec), resolution, bitrate]
        tk.Label(detail_row, text="   ·   ".join(b for b in bits if b and b != "--"),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left")

        btn_row = tk.Frame(card, bg=t.card_bg)
        btn_row.pack(fill="x", padx=12, pady=(2, 8))

        kick_btn = tk.Button(btn_row, text="Kick",
                             command=lambda sid=session_id, u=username: self._kick_session(sid, u),
                             bg=t.status_stopped, fg="#fff",
                             bd=0, relief="flat", font=t.font_small,
                             padx=10, pady=2, cursor="hand2")
        kick_btn.pack(side="left", padx=(0, 6))

        msg_btn = tk.Button(btn_row, text="Message",
                            command=lambda sid=session_id: self._message_session(sid),
                            bg=t.surface_light, fg=t.blue,
                            bd=0, relief="flat", font=t.font_small,
                            padx=10, pady=2, cursor="hand2")
        msg_btn.pack(side="left")

    # ---------------------------------------------------------
    # ACTIONS
    # ---------------------------------------------------------
    def _kick_session(self, session_id, username):
        def worker():
            try:
                self._jf_post("/Sessions/{}/Playing/Stop".format(session_id), {})
                self.after(0, lambda: self._show_status(
                    "Kicked {} successfully.".format(username)))
                self.after(2000, self._fetch)
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Kick failed: " + err[:60]))
        threading.Thread(target=worker, daemon=True).start()

    def _message_session(self, session_id):
        t = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("Send Message")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Message:", bg=t.bg, fg=t.text,
                 font=t.font_regular, padx=16, pady=8).pack(anchor="w")
        msg_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=msg_var, width=40,
                         bg=t.surface_dark, fg=t.text, relief="flat",
                         insertbackground=t.blue, font=t.font_regular)
        entry.pack(padx=16, pady=(0, 12))
        entry.focus_set()

        def _send():
            msg = msg_var.get().strip()
            if not msg:
                return
            try:
                self._jf_post("/Sessions/{}/Message".format(session_id),
                              {"Header": "Admin", "Text": msg, "TimeoutMs": 8000})
            except Exception:
                pass
            dlg.destroy()

        entry.bind("<Return>", lambda e: _send())
        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=(0, 12))
        send_btn = tk.Button(btn_row, text="Send", command=_send)
        t.style_button(send_btn)
        send_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat", bd=0).pack(side="left")

    def _message_all(self):
        if not self._active_sessions:
            return
        t = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("Message All")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Send to all {} session(s)".format(len(self._active_sessions)),
                 bg=t.bg, fg=t.text, font=("Segoe UI Semibold", 11),
                 padx=16, pady=10).pack()

        frm = tk.Frame(dlg, bg=t.bg, padx=16)
        frm.pack(fill="x")
        tk.Label(frm, text="Header:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=0, column=0, sticky="w", pady=4)
        hdr_var = tk.StringVar(value="Notice from Admin")
        tk.Entry(frm, textvariable=hdr_var, width=38,
                 bg=t.surface_dark, fg=t.text, relief="flat",
                 insertbackground=t.blue).grid(row=0, column=1, padx=8)
        tk.Label(frm, text="Message:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=1, column=0, sticky="nw", pady=4)
        msg_box = tk.Text(frm, width=38, height=3, bg=t.surface_dark, fg=t.text,
                          relief="flat", insertbackground=t.blue, wrap="word")
        msg_box.grid(row=1, column=1, padx=8)

        st_lbl = tk.Label(dlg, text="", bg=t.bg, fg=t.text_muted, font=t.font_small)
        st_lbl.pack(pady=4)

        def _send_all():
            hdr = hdr_var.get().strip() or "Notice"
            msg = msg_box.get("1.0", "end").strip()
            if not msg:
                return
            ok = err = 0
            for s in self._active_sessions:
                try:
                    self._jf_post("/Sessions/{}/Message".format(s.get("Id", "")),
                                  {"Header": hdr, "Text": msg, "TimeoutMs": 8000})
                    ok += 1
                except Exception:
                    err += 1
            st_lbl.config(
                text="Sent to {} session(s){}.".format(
                    ok, " ({} failed)".format(err) if err else ""),
                fg=t.status_running if not err else t.yellow)
            dlg.after(2000, dlg.destroy)

        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=10)
        send_btn = tk.Button(btn_row, text="Send All", command=_send_all)
        t.style_button(send_btn)
        send_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat", bd=0).pack(side="left")

    # ---------------------------------------------------------
    # LIBRARY SCAN
    # ---------------------------------------------------------
    def _scan_libraries(self):
        def worker():
            try:
                self._jf_post("/Library/Refresh", {})
                self.after(0, lambda: self._show_status(
                    "Library scan queued — Jellyfin is scanning now."))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Scan failed: " + err[:60], self.theme.status_stopped))
        import threading as _t
        _t.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # API HELPER
    # ---------------------------------------------------------
    def _jf_post(self, endpoint, payload):
        cfg    = self.controller.config_manager
        host   = cfg.jellyfin_host
        port   = cfg.jellyfin_port
        apikey = cfg.jellyfin_apikey
        url    = "http://{}:{}{}".format(host, port, endpoint)
        body   = json.dumps(payload).encode()
        req    = urllib.request.Request(url, data=body, method="POST",
                                         headers={"X-Emby-Token": apikey,
                                                  "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read()

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def _show_status(self, msg, color=None):
        t = self.theme
        if msg.endswith("…") or msg.endswith("..."):
            self._status_lbl.config(text=msg, bg=t.blue, fg="#ffffff")
            return
        self._status_lbl.config(text=msg, bg=t.surface_dark, fg=color or t.text_muted)
        if color:
            self.after(6000, lambda: self._status_lbl.config(text="", bg=t.surface_dark, fg=t.text_muted))

    def _show_error(self, msg):
        self._show_status(msg, self.theme.status_stopped)
        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        for w in self._session_frame.winfo_children():
            w.destroy()
        tk.Label(self._session_frame, text=msg,
                 bg=self.theme.bg, fg=self.theme.status_stopped,
                 font=self.theme.font_regular).pack(pady=40)
