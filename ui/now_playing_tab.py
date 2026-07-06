# ui/now_playing_tab.py
"""
Unified Now Playing tab.
Fetches active streaming sessions from all configured media servers
(Plex, Emby, Jellyfin) in parallel and shows them in a single view.
Each card carries a server badge and routes kick/message to the correct API.
"""

import tkinter as tk
from tkinter import messagebox
import threading
import urllib.request
import json
import time

from ui.refresh_control import RefreshControl


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_ms(ms):
    if not ms:
        return "--:--"
    s = int(ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return "{}:{:02d}:{:02d}".format(h, m, sec) if h else "{:02d}:{:02d}".format(m, sec)


def _fmt_ticks(ticks):
    if not ticks:
        return "--:--"
    return _fmt_ms(int(ticks) // 10_000)


def _fmt_bitrate(bps):
    if not bps:
        return "--"
    if bps >= 1_000_000:
        return "{:.1f} Mbps".format(bps / 1_000_000)
    return "{} kbps".format(bps // 1000)


# ---------------------------------------------------------------------------
# Session normalizers — each returns a common dict
# ---------------------------------------------------------------------------

def _norm_plex(s):
    ts     = s.get("TranscodeSession", {}) or {}
    player = s.get("Player", {}) or {}
    user   = (s.get("User", {}) or {}).get("title", "Unknown")
    state  = player.get("state", "unknown")

    mtype = s.get("type", "")
    title = ("{} — {}".format(s.get("grandparentTitle", "?"), s.get("title", "?"))
             if mtype == "episode" else s.get("title", "Unknown"))

    duration = s.get("duration", 0) or 0
    pos      = s.get("viewOffset", 0) or 0
    pct      = (pos / duration * 100) if duration else 0

    if ts:
        stream_type   = "Transcode"
        stream_detail = "Video: {}  Audio: {}  Speed: {}x".format(
            ts.get("videoDecision", "?").title(),
            ts.get("audioDecision", "?").title(),
            ts.get("speed", 0))
    else:
        stream_type   = "Direct Play"
        stream_detail = ""

    media   = (s.get("Media") or [{}])[0]
    v_codec = media.get("videoCodec", "--").upper()
    a_codec = media.get("audioCodec", "--").upper()
    bitrate = _fmt_bitrate(media.get("bitrate", 0) * 1000 if media.get("bitrate") else 0)
    res     = ("{}x{}".format(media.get("width", "?"), media.get("height", "?"))
               if media.get("width") else "--")

    session_id = (s.get("Session", {}) or {}).get("id", s.get("sessionKey", ""))

    return {
        "server": "Plex", "server_color": "#e5a00d",
        "session_id": session_id, "user": user,
        "device": player.get("title", "?"), "ip": player.get("address", "--"),
        "title": title, "state": state,
        "stream_type": stream_type, "stream_detail": stream_detail,
        "v_codec": v_codec, "a_codec": a_codec, "res": res, "bitrate": bitrate,
        "position_str": _fmt_ms(pos), "duration_str": _fmt_ms(duration),
        "progress_pct": pct, "can_message": False,
    }


def _norm_jf(s, server="Jellyfin"):
    item  = s.get("NowPlayingItem", {}) or {}
    ti    = s.get("TranscodingInfo", {}) or {}
    ps    = s.get("PlayState", {}) or {}

    mtype = item.get("Type", "")
    title = ("{} — {}".format(item.get("SeriesName", "?"), item.get("Name", "?"))
             if mtype == "Episode" else item.get("Name", "Unknown"))

    is_paused     = ps.get("IsPaused", False)
    state         = "paused" if is_paused else "playing"
    pos_ticks     = ps.get("PositionTicks", 0) or 0
    dur_ticks     = item.get("RunTimeTicks", 0) or 0
    pct           = (pos_ticks / dur_ticks * 100) if dur_ticks else 0

    vid_direct = ti.get("IsVideoDirect", True)
    aud_direct = ti.get("IsAudioDirect", True)
    if not vid_direct:
        stream_type   = "Transcoding"
        stream_detail = "→ {}/{}".format(
            (ti.get("VideoCodec") or "").upper(),
            (ti.get("AudioCodec") or "").upper())
    elif not aud_direct:
        stream_type   = "Video Direct / Audio Transcode"
        stream_detail = "Audio transcode"
    else:
        stream_type   = "Direct Play"
        stream_detail = ""

    vs = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Video"]
    as_ = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Audio"]
    v_codec = vs[0].get("Codec", "--").upper() if vs else "--"
    a_codec = as_[0].get("Codec", "--").upper() if as_ else "--"
    res     = ("{}x{}".format(vs[0].get("Width", "?"), vs[0].get("Height", "?"))
               if vs else "--")
    bitrate = _fmt_bitrate(ti.get("Bitrate") or 0)

    color = "#00a4dc" if server == "Jellyfin" else "#52b54b"

    return {
        "server": server, "server_color": color,
        "session_id": s.get("Id", ""), "user": s.get("UserName", "Unknown"),
        "device": s.get("DeviceName", "?"), "ip": s.get("RemoteEndPoint", "--"),
        "title": title, "state": state,
        "stream_type": stream_type, "stream_detail": stream_detail,
        "v_codec": v_codec, "a_codec": a_codec, "res": res, "bitrate": bitrate,
        "position_str": _fmt_ticks(pos_ticks), "duration_str": _fmt_ticks(dur_ticks),
        "progress_pct": pct, "can_message": True,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _http_post(url, headers, body=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else b""
    req  = urllib.request.Request(url, data=data, method=method, headers={
        **headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.status


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class NowPlayingTab(tk.Frame):
    """Unified Now Playing — all configured media servers in one view."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller      = controller
        self.theme           = controller.theme
        self._sessions       = []   # normalised session dicts
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="NOW PLAYING",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "now_playing",
                                  default=15, on_refresh=self._fetch)
        self._rc.pack(side="right")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._fetch)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))

        self._scan_btn = tk.Button(hdr, text="⟳ Scan Libraries",
                                   command=self._scan_all_libraries)
        t.style_button(self._scan_btn)
        self._scan_btn.pack(side="right", padx=(0, 8))

        # Summary cards
        cards_row = tk.Frame(self, bg=t.bg)
        cards_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_streams   = self._stat_card(cards_row, "Active Streams", "0")
        self._card_transcode = self._stat_card(cards_row, "Transcoding",    "0")
        self._card_direct    = self._stat_card(cards_row, "Direct Play",    "0")
        self._card_servers   = self._stat_card(cards_row, "Servers",        "0")

        # Status bar
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
        self._session_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._session_frame.bind("<MouseWheel>",
                                  lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

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

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------
    def _fetch(self):
        self._rc.cancel()
        self._refresh_btn.config(state="disabled", text="Loading…")
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        cfg = self.controller.config_manager
        # Read ONLY from the active server profile's settings — no global fallback.
        # This prevents one server's media credentials leaking into another profile.
        srv = (cfg.get_active_server() or {}).get("settings", {})
        self._active_srv = srv  # cached for kick / message / scan actions

        plex_token = srv.get("plex_token", "")
        plex_host  = srv.get("plex_host", "localhost")
        plex_port  = srv.get("plex_port", "32400")
        jf_key     = srv.get("jellyfin_apikey", "")
        jf_host    = srv.get("jellyfin_host", "localhost")
        jf_port    = srv.get("jellyfin_port", "8096")
        emby_key   = srv.get("emby_apikey", "")
        emby_host  = srv.get("emby_host", "localhost")
        emby_port  = srv.get("emby_port", "8096")

        results = []
        errors  = []
        lock    = threading.Lock()
        threads = []

        def fetch_plex():
            if not plex_token:
                return
            try:
                url  = "http://{}:{}/status/sessions".format(plex_host, plex_port)
                data = _http_get(url, {"X-Plex-Token": plex_token,
                                       "Accept": "application/json"})
                raw  = data.get("MediaContainer", {}).get("Metadata") or []
                if not isinstance(raw, list):
                    raw = [raw]
                with lock:
                    results.extend([_norm_plex(s) for s in raw])
            except Exception as e:
                with lock:
                    errors.append("Plex: {}".format(str(e)[:50]))

        def fetch_jellyfin():
            if not jf_key:
                return
            try:
                url  = "http://{}:{}/Sessions?activeWithinSeconds=30".format(jf_host, jf_port)
                data = _http_get(url, {"X-Emby-Token": jf_key,
                                       "Accept": "application/json"})
                raw  = [s for s in (data if isinstance(data, list) else [])
                        if s.get("NowPlayingItem")]
                with lock:
                    results.extend([_norm_jf(s, "Jellyfin") for s in raw])
            except Exception as e:
                with lock:
                    errors.append("Jellyfin: {}".format(str(e)[:50]))

        def fetch_emby():
            if not emby_key:
                return
            try:
                host = emby_host.removeprefix("https://").removeprefix("http://").strip("/")
                url  = "http://{}:{}/emby/Sessions?ControllableByUserId=&ActiveWithinSeconds=60".format(
                    host, emby_port)
                data = _http_get(url, {"X-Emby-Token": emby_key,
                                       "Accept": "application/json"})
                raw  = [s for s in (data if isinstance(data, list) else [])
                        if s.get("NowPlayingItem")]
                with lock:
                    results.extend([_norm_jf(s, "Emby") for s in raw])
            except Exception as e:
                with lock:
                    errors.append("Emby: {}".format(str(e)[:50]))

        if not any([plex_token, jf_key, emby_key]):
            self.after(0, lambda: self._update_ui(
                [], ["No media servers configured for this server profile.  →  Add API keys in Config."]))
            return

        for fn in (fetch_plex, fetch_jellyfin, fetch_emby):
            t = threading.Thread(target=fn, daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        self.after(0, lambda r=list(results), e=list(errors):
                   self._update_ui(r, e))

    # ------------------------------------------------------------------
    # UI UPDATE
    # ------------------------------------------------------------------
    def _update_ui(self, sessions, errors):
        self._sessions = sessions
        for w in self._session_frame.winfo_children():
            w.destroy()

        total     = len(sessions)
        transcode = sum(1 for s in sessions
                        if "transcode" in s["stream_type"].lower())
        direct    = total - transcode
        servers   = len({s["server"] for s in sessions})

        self._card_streams.config(text=str(total))
        self._card_transcode.config(text=str(transcode))
        self._card_direct.config(text=str(direct))
        self._card_servers.config(text=str(servers))

        if not sessions and not errors:
            tk.Label(self._session_frame, text="No active streams",
                     bg=self.theme.bg, fg=self.theme.text_muted,
                     font=("Segoe UI", 13)).pack(pady=40)
        elif not sessions and errors:
            tk.Label(self._session_frame,
                     text="\n".join(errors),
                     bg=self.theme.bg, fg=self.theme.status_stopped_text,
                     font=self.theme.font_small).pack(pady=20)
        else:
            for s in sorted(sessions, key=lambda x: (x["server"], x["user"])):
                self._build_card(s)

        status = "{} stream{} active".format(total, "s" if total != 1 else "")
        if errors:
            status += "  ·  ⚠ " + "; ".join(errors)
        status += "  ·  " + time.strftime("%H:%M:%S")
        self._status_lbl.config(text=status,
                                 fg=self.theme.yellow if errors else self.theme.text_muted)

        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._rc.schedule()

    # ------------------------------------------------------------------
    # SESSION CARD
    # ------------------------------------------------------------------
    def _build_card(self, s):
        t   = self.theme
        col = s["server_color"]

        card = tk.Frame(self._session_frame, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", pady=6, padx=4)

        # Coloured top accent
        tk.Frame(card, bg=col, height=3).pack(fill="x")

        # Title row
        head = tk.Frame(card, bg=t.card_bg)
        head.pack(fill="x", padx=12, pady=(8, 2))

        # State dot
        state     = s["state"]
        dot_color = (t.status_running if state == "playing" else
                     t.yellow         if state == "paused"  else t.text_dim)
        dot = tk.Canvas(head, width=10, height=10, bg=t.card_bg, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=dot_color, outline=dot_color)
        dot.pack(side="left", padx=(0, 6))

        tk.Label(head, text=s["title"], bg=t.card_bg, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", fill="x", expand=True)

        # Server badge
        tk.Label(head, text="  {}  ".format(s["server"]),
                 bg=col, fg="#fff", font=t.font_small).pack(side="right", padx=(8, 0))

        # Stream type badge
        is_transcode = "transcode" in s["stream_type"].lower()
        badge_col    = t.status_stopped if is_transcode else t.status_running
        tk.Label(head, text="  {}  ".format(s["stream_type"]),
                 bg=badge_col, fg="#fff", font=t.font_small).pack(side="right", padx=(4, 0))

        # User / device row
        info = tk.Frame(card, bg=t.card_bg)
        info.pack(fill="x", padx=12, pady=2)
        tk.Label(info, text="\U0001f464 {}".format(s["user"]),
                 bg=t.card_bg, fg=t.blue_bright, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text="\U0001f4bb {}".format(s["device"]),
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left", padx=(0, 16))
        tk.Label(info, text=state.title(),
                 bg=t.card_bg, fg=dot_color, font=t.font_small).pack(side="left")

        # Progress bar
        pct     = min(s["progress_pct"] / 100, 1.0)
        bar_frm = tk.Frame(card, bg=t.surface_dark, height=4)
        bar_frm.pack(fill="x", padx=12, pady=(6, 0))
        bar_frm.pack_propagate(False)
        tk.Frame(bar_frm, bg=col, height=4).place(relwidth=pct, relheight=1.0)

        time_row = tk.Frame(card, bg=t.card_bg)
        time_row.pack(fill="x", padx=12, pady=(2, 4))
        tk.Label(time_row, text=s["position_str"],
                 bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack(side="left")
        tk.Label(time_row, text=s["duration_str"],
                 bg=t.card_bg, fg=t.text_dim, font=t.font_small).pack(side="right")

        # Stream detail row
        detail_parts = [p for p in [
            s.get("stream_detail", ""),
            "{} / {}".format(s["v_codec"], s["a_codec"])
                if s["v_codec"] != "--" else "",
            s["res"] if s["res"] != "--" else "",
            s["bitrate"] if s["bitrate"] != "--" else "",
        ] if p]
        if detail_parts:
            tk.Label(card, text="   ·   ".join(detail_parts),
                     bg=t.card_bg, fg=t.text_muted, font=t.font_small,
                     anchor="w").pack(fill="x", padx=12, pady=(0, 4))

        # Action buttons
        btn_row = tk.Frame(card, bg=t.card_bg)
        btn_row.pack(fill="x", padx=12, pady=(2, 8))

        kick_btn = tk.Button(btn_row, text="Kick",
                             command=lambda ss=s: self._kick(ss),
                             bg=t.status_stopped, fg="#fff",
                             bd=0, relief="flat", font=t.font_small,
                             padx=10, pady=2, cursor="hand2")
        kick_btn.pack(side="left", padx=(0, 6))

        if s.get("can_message"):
            msg_btn = tk.Button(btn_row, text="Message",
                                command=lambda ss=s: self._message_dialog(ss),
                                bg=t.surface_light, fg=t.blue_bright,
                                bd=0, relief="flat", font=t.font_small,
                                padx=10, pady=2, cursor="hand2")
            msg_btn.pack(side="left")

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _kick(self, s):
        if not messagebox.askyesno(
                "Kick User", "Stop playback for {} ({})?".format(s["user"], s["server"]),
                parent=self):
            return
        def worker():
            try:
                srv    = getattr(self, "_active_srv", {})
                server = s["server"]
                sid    = s["session_id"]

                if server == "Plex":
                    url = ("http://{}:{}/status/sessions/terminate"
                           "?sessionId={}&reason=Removed by administrator".format(
                               srv.get("plex_host", "localhost"),
                               srv.get("plex_port", "32400"), sid))
                    req = urllib.request.Request(url,
                                                  headers={"X-Plex-Token": srv.get("plex_token", "")})
                    req.get_method = lambda: "DELETE"
                    urllib.request.urlopen(req, timeout=8).close()
                elif server == "Jellyfin":
                    _http_post(
                        "http://{}:{}/Sessions/{}/Playing/Stop".format(
                            srv.get("jellyfin_host", "localhost"),
                            srv.get("jellyfin_port", "8096"), sid),
                        {"X-Emby-Token": srv.get("jellyfin_apikey", "")})
                elif server == "Emby":
                    host = srv.get("emby_host", "localhost").removeprefix("https://").removeprefix("http://").strip("/")
                    _http_post(
                        "http://{}:{}/emby/Sessions/{}/Playing/Stop".format(
                            host, srv.get("emby_port", "8096"), sid),
                        {"X-Emby-Token": srv.get("emby_apikey", "")})

                self.after(0, lambda: self._status_lbl.config(
                    text="Kicked {} ({}).".format(s["user"], server),
                    fg=self.theme.status_running))
                self.after(2000, self._fetch)
            except Exception as e:
                self.after(0, lambda err=str(e): self._status_lbl.config(
                    text="Kick failed: " + err[:60], fg=self.theme.status_stopped_text))
        threading.Thread(target=worker, daemon=True).start()

    def _message_dialog(self, s):
        t   = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("Send Message")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)

        tk.Label(dlg, text="Message to {} ({})".format(s["user"], s["server"]),
                 bg=t.bg, fg=t.text, font=("Segoe UI Semibold", 11),
                 padx=20, pady=12).pack()

        msg_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=msg_var, width=40,
                         bg=t.surface_dark, fg=t.text, relief="flat",
                         insertbackground=t.blue, font=t.font_regular)
        entry.pack(padx=20, pady=(0, 12))
        entry.focus_set()

        def _send():
            msg = msg_var.get().strip()
            if not msg:
                return
            def worker():
                try:
                    srv    = getattr(self, "_active_srv", {})
                    server = s["server"]
                    sid    = s["session_id"]
                    body   = {"Header": "Admin", "Text": msg, "TimeoutMs": 8000}
                    if server == "Jellyfin":
                        _http_post(
                            "http://{}:{}/Sessions/{}/Message".format(
                                srv.get("jellyfin_host", "localhost"),
                                srv.get("jellyfin_port", "8096"), sid),
                            {"X-Emby-Token": srv.get("jellyfin_apikey", "")}, body)
                    elif server == "Emby":
                        host = srv.get("emby_host", "localhost").removeprefix("https://").removeprefix("http://").strip("/")
                        _http_post(
                            "http://{}:{}/emby/Sessions/{}/Message".format(
                                host, srv.get("emby_port", "8096"), sid),
                            {"X-Emby-Token": srv.get("emby_apikey", "")}, body)
                except Exception:
                    pass
            threading.Thread(target=worker, daemon=True).start()
            dlg.destroy()

        entry.bind("<Return>", lambda e: _send())
        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=(0, 12))
        send_btn = tk.Button(btn_row, text="Send", command=_send)
        t.style_button(send_btn)
        send_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat", bd=0).pack(side="left")

    # ------------------------------------------------------------------
    # SCAN LIBRARIES (all configured servers)
    # ------------------------------------------------------------------
    def _scan_all_libraries(self):
        self._scan_btn.config(state="disabled", text="Scanning…")

        def worker():
            srv  = getattr(self, "_active_srv", {})
            done = []
            plex_token = srv.get("plex_token", "")
            if plex_token:
                try:
                    plex_host = srv.get("plex_host", "localhost")
                    plex_port = srv.get("plex_port", "32400")
                    url  = "http://{}:{}/library/sections".format(plex_host, plex_port)
                    data = _http_get(url, {"X-Plex-Token": plex_token,
                                           "Accept": "application/json"})
                    dirs = data.get("MediaContainer", {}).get("Directory", []) or []
                    if not isinstance(dirs, list):
                        dirs = [dirs]
                    for d in dirs:
                        key = d.get("key", "")
                        req = urllib.request.Request(
                            "http://{}:{}/library/sections/{}/refresh".format(
                                plex_host, plex_port, key),
                            headers={"X-Plex-Token": plex_token})
                        urllib.request.urlopen(req, timeout=8).close()
                    done.append("Plex")
                except Exception:
                    pass
            for label, host, port, apikey, prefix in [
                ("Jellyfin", srv.get("jellyfin_host", "localhost"),
                 srv.get("jellyfin_port", "8096"), srv.get("jellyfin_apikey", ""), ""),
                ("Emby", srv.get("emby_host", "localhost"),
                 srv.get("emby_port", "8096"), srv.get("emby_apikey", ""), "/emby"),
            ]:
                if not apikey:
                    continue
                try:
                    h = host.removeprefix("https://").removeprefix("http://").strip("/")
                    _http_post(
                        "http://{}:{}{}/Library/Refresh".format(h, port, prefix),
                        {"X-Emby-Token": apikey})
                    done.append(label)
                except Exception:
                    pass

            msg = ("Scan queued: {}".format(", ".join(done))
                   if done else "No servers responded to scan.")
            self.after(0, lambda m=msg: self._status_lbl.config(
                text=m, fg=self.theme.status_running))
            self.after(0, lambda: self._scan_btn.config(
                state="normal", text="⟳ Scan Libraries"))

        threading.Thread(target=worker, daemon=True).start()
