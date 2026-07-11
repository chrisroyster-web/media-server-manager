# ui/emby_tab.py
"""
Emby Now Playing tab.
Shows active streaming sessions via the Emby HTTP API.
Polls every 15 seconds automatically.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import json
import time

from ui.refresh_control import RefreshControl


def _emby_get(host, port, apikey, path):
    """GET /emby/<path> and return parsed JSON."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/emby/{}".format(host, port, path)
    req = urllib.request.Request(
        url,
        headers={"X-Emby-Token": apikey, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _emby_post(host, port, apikey, path, body=None):
    """POST /emby/<path> with optional JSON body."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/emby/{}".format(host, port, path)
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "X-Emby-Token": apikey,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.status


def _fmt_ticks(ticks):
    """Convert Emby ticks (100-ns units) to HH:MM:SS string."""
    if not ticks:
        return "0:00:00"
    secs = int(ticks / 10_000_000)
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return "{:d}:{:02d}:{:02d}".format(h, m, s)


def _progress_pct(pos, runtime):
    if not runtime:
        return 0
    return min(int(pos * 100 / runtime), 100)


def _fmt_bitrate(bps):
    if not bps:
        return "--"
    if bps >= 1_000_000:
        return "{:.1f} Mbps".format(bps / 1_000_000)
    return "{:.0f} Kbps".format(bps / 1_000)


class EmbyTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller      = controller
        self.theme           = t
        self._session_frames = []
        self._active_sessions = []   # raw session dicts for Message All

        self._build_ui()
        self.after(500, self._fetch)

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header bar
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x", padx=0, pady=0)

        tk.Label(
            hdr, text="Now Playing",
            bg=t.surface_dark, fg=t.text,
            font=t.font_title, anchor="w",
        ).pack(side="left", padx=18, pady=14)

        self._status_lbl = tk.Label(
            hdr, text="",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small,
        )
        self._status_lbl.pack(side="right", padx=18)

        self._rc = RefreshControl(hdr, self.controller, "emby",
                                  default=15, on_refresh=self._fetch)
        self._rc.pack(side="right", padx=(0, 10))

        tk.Button(
            hdr, text="Refresh",
            command=self._fetch,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat",
            font=t.font_small, padx=12, pady=4,
        ).pack(side="right", padx=(0, 10), pady=10)

        # Message All button
        self._msg_btn = tk.Button(
            hdr, text="Message All",
            command=self._message_all,
            bg=t.surface_light, fg=t.text,
            bd=0, relief="flat",
            font=t.font_small, padx=12, pady=4,
            cursor="hand2",
        )
        self._msg_btn.pack(side="right", padx=(0, 6), pady=10)
        self._msg_btn.bind("<Enter>", lambda e: self._msg_btn.configure(bg=t.card_border))
        self._msg_btn.bind("<Leave>", lambda e: self._msg_btn.configure(bg=t.surface_light))

        # Scan Libraries button
        self._scan_btn = tk.Button(
            hdr, text="⟳ Scan Libraries",
            command=self._scan_libraries,
            bg=t.surface_light, fg=t.text,
            bd=0, relief="flat",
            font=t.font_small, padx=12, pady=4,
            cursor="hand2",
        )
        self._scan_btn.pack(side="right", padx=(0, 6), pady=10)
        self._scan_btn.bind("<Enter>", lambda e: self._scan_btn.configure(bg=t.card_border))
        self._scan_btn.bind("<Leave>", lambda e: self._scan_btn.configure(bg=t.surface_light))

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Summary cards row
        self._summary_row = tk.Frame(self, bg=t.bg)
        self._summary_row.pack(fill="x", padx=16, pady=12)

        self._card_streams   = self._summary_card("Active Streams", "--")
        self._card_transcode = self._summary_card("Transcoding",    "--")
        self._card_direct    = self._summary_card("Direct Play",    "--")
        self._card_users     = self._summary_card("Users",          "--")

        # Scrollable session area
        outer = tk.Frame(self, bg=t.bg)
        outer.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        canvas = tk.Canvas(outer, bg=t.bg, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._session_area = tk.Frame(canvas, bg=t.bg)
        self._canvas_win = canvas.create_window((0, 0), window=self._session_area, anchor="nw")

        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._canvas_win, width=e.width))
        self._session_area.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_wheel(e):
            # A fast physical scroll delivers many wheel events in one burst,
            # faster than Tk can settle canvas geometry between them.
            # Calling yview_scroll() once per event let repeated rapid calls
            # desync the embedded session_area window's actual on-screen
            # position from what yview()/bbox() reported. Coalescing the
            # whole burst into a single net delta, applied once after it
            # settles, avoids that. Same fix as ui/sidebar.py's nav scroll.
            self._wheel_delta_pending = getattr(self, "_wheel_delta_pending", 0) + e.delta
            if not getattr(self, "_wheel_scroll_scheduled", False):
                self._wheel_scroll_scheduled = True
                self.after_idle(_apply_pending_wheel_scroll)
            # Scrollbar has a built-in Tk class-level <MouseWheel> binding
            # (tk::ScrollByUnits) that calls canvas.yview directly, bypassing
            # this handler's guard entirely. Binding this same handler onto
            # sb too (below) and returning "break" here stops that default.
            return "break"

        def _apply_pending_wheel_scroll():
            delta = self._wheel_delta_pending
            self._wheel_delta_pending = 0
            self._wheel_scroll_scheduled = False
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)
                if (bbox[3] - bbox[1]) <= canvas.winfo_height():
                    canvas.yview_moveto(0.0)
                    return
            canvas.yview_scroll(int(-1 * (delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_wheel)
        sb.bind("<MouseWheel>", _on_wheel)

        self._canvas = canvas

        # Placeholder when idle
        self._idle_lbl = tk.Label(
            self._session_area,
            text="No active streams",
            bg=t.bg, fg=t.text_muted,
            font=t.font_regular,
        )

    def _summary_card(self, label, value):
        t = self.theme
        card = tk.Frame(self._summary_row, bg=t.surface, padx=16, pady=10)
        card.pack(side="left", padx=(0, 10))
        tk.Label(card, text=label, bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        val_lbl = tk.Label(card, text=value, bg=t.surface, fg=t.text,
                           font=("Segoe UI", 18, "bold"))
        val_lbl.pack(anchor="w")
        return val_lbl

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------
    def _fetch(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        self._status_lbl.config(text="Refreshing…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        try:
            cfg    = self.controller.config_manager
            host   = cfg.emby_host
            port   = cfg.emby_port
            apikey = cfg.emby_apikey

            if not apikey:
                self.after(0, lambda: self._show_error("No Emby API key configured.\nGo to Config > Emby."))
                return

            data     = _emby_get(host, port, apikey,
                                 "Sessions?ControllableByUserId=&ActiveWithinSeconds=60")
            sessions = [s for s in data if s.get("NowPlayingItem")]
            self.after(0, lambda s=sessions: self._update_ui(s))
        except urllib.error.URLError as e:
            self.after(0, lambda err=str(e): self._show_error("Connection error:\n{}".format(err)))
        except Exception as e:
            self.after(0, lambda err=str(e): self._show_error("Error: {}".format(err)))
        finally:
            self._fetching = False

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def _update_ui(self, sessions):
        self._rc.schedule()
        self._active_sessions = sessions

        for child in list(self._session_area.winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass
        self._session_frames.clear()
        # Rebuilding can shrink the list (fewer active streams than before);
        # the canvas keeps its old scroll fraction otherwise, which now
        # points past the shorter content and shows as blank space above
        # the cards. Pin back to the top on every rebuild.
        self._canvas.yview_moveto(0)

        self._idle_lbl = tk.Label(
            self._session_area,
            text="No active streams",
            bg=self.theme.bg, fg=self.theme.text_muted,
            font=self.theme.font_regular,
        )

        total     = len(sessions)
        transcode = sum(1 for s in sessions
                        if s.get("PlayState", {}).get("PlayMethod") == "Transcode")
        direct    = total - transcode
        users     = len({s.get("UserName", "") for s in sessions})

        self._card_streams.config(text=str(total))
        self._card_transcode.config(text=str(transcode))
        self._card_direct.config(text=str(direct))
        self._card_users.config(text=str(users))
        self._status_lbl.config(text="Updated {}".format(time.strftime("%H:%M:%S")),
                               bg=self.theme.surface_dark, fg=self.theme.text_muted)

        if not sessions:
            self._idle_lbl.pack(pady=40)
        else:
            for s in sessions:
                self._session_frames.append(self._build_session_card(s))

        # The scrollregion is normally kept in sync by the <Configure>
        # binding on _session_area, but that fires on Tk's own schedule --
        # relying on it left stale (too-tall) scrollregions in place after a
        # rebuild, so a short list could still be scrolled down into blank
        # space even though yview_moveto(0) above put it back at the top.
        # Force the geometry pass now and recompute directly so the region
        # always matches what was actually just built.
        self._session_area.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.yview_moveto(0)

    def _build_session_card(self, s):
        t = self.theme

        card = tk.Frame(self._session_area, bg=t.surface,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))

        # Top row: user + device + badges
        top = tk.Frame(card, bg=t.surface, padx=14, pady=10)
        top.pack(fill="x")

        user       = s.get("UserName", "Unknown")
        device     = s.get("DeviceName", "")
        client     = s.get("Client", "")
        session_id = s.get("Id", "")

        tk.Label(top, text="  {}".format(user),
                 bg=t.surface, fg=t.text,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        tk.Label(top, text="  {}  .  {}".format(device, client),
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(side="left")

        # Kick button
        kick_btn = tk.Button(
            top, text="Kick",
            command=lambda sid=session_id, u=user: self._kick_session(sid, u),
        )
        t.style_button(kick_btn, "danger")
        kick_btn.pack(side="right", padx=(4, 0))

        # Expand/collapse detail button
        expand_btn = tk.Button(
            top, text="Details",
            bg=t.surface_light, fg=t.text_muted,
            bd=0, relief="flat", font=t.font_small, padx=8, pady=3, cursor="hand2",
        )
        expand_btn.pack(side="right", padx=(0, 6))

        # Play method badge
        play_method = s.get("PlayState", {}).get("PlayMethod", "")
        ti = s.get("TranscodingInfo", {})
        if play_method == "Transcode":
            badge_txt = "Transcoding"
            badge_col = t.yellow
            badge_fg  = "#000000"
        elif play_method == "DirectStream":
            badge_txt = "Direct Stream"
            badge_col = t.blue
            badge_fg  = "#ffffff"
        else:
            badge_txt = "Direct Play"
            badge_col = t.status_running
            badge_fg  = "#ffffff"
        tk.Label(top, text=badge_txt,
                 bg=badge_col, fg=badge_fg,
                 font=t.font_small, padx=8, pady=2).pack(side="right", padx=4)

        # Media title
        item      = s.get("NowPlayingItem", {})
        media_name = item.get("Name", "Unknown")
        item_type  = item.get("Type", "")
        series     = item.get("SeriesName", "")
        season     = item.get("ParentIndexNumber", "")
        episode    = item.get("IndexNumber", "")

        if item_type == "Episode" and series:
            title = "{}  S{:02d}E{:02d}  -  {}".format(
                series, season or 0, episode or 0, media_name)
        else:
            year = item.get("ProductionYear", "")
            title = "{}{}".format(media_name, "  ({})".format(year) if year else "")

        mid = tk.Frame(card, bg=t.surface)
        mid.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(mid, text="{}".format(title),
                 bg=t.surface, fg=t.text,
                 font=t.font_regular).pack(side="left")

        # Progress bar
        pos     = s.get("PlayState", {}).get("PositionTicks", 0)
        runtime = item.get("RunTimeTicks", 0)
        pct     = _progress_pct(pos, runtime)

        prog_frame = tk.Frame(card, bg=t.surface)
        prog_frame.pack(fill="x", padx=14, pady=(0, 4))

        bar_bg = tk.Frame(prog_frame, bg=t.surface_light, height=6)
        bar_bg.pack(fill="x", side="left", expand=True)

        def _draw_bar(bg=bar_bg, p=pct):
            bg.update_idletasks()
            w = bg.winfo_width()
            fill_w = max(4, int(w * p / 100))
            tk.Frame(bg, bg=t.blue, height=6, width=fill_w).place(x=0, y=0)
        bar_bg.after(50, _draw_bar)

        tk.Label(prog_frame,
                 text="  {} / {}  ({}%)".format(_fmt_ticks(pos), _fmt_ticks(runtime), pct),
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(8, 0))

        # Stream details bar
        details_bar = tk.Frame(card, bg=t.surface_dark, padx=14, pady=6)
        details_bar.pack(fill="x")

        video_streams = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Video"]
        audio_streams = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Audio"
                         and m.get("IsDefault")]
        if not audio_streams:
            audio_streams = [m for m in item.get("MediaStreams", []) if m.get("Type") == "Audio"]

        bits = []
        if video_streams:
            v     = video_streams[0]
            codec = v.get("Codec", "").upper()
            w2    = v.get("Width", "")
            h2    = v.get("Height", "")
            res   = "{}x{}".format(w2, h2) if w2 and h2 else ""
            bits.append("Video: {} {}".format(codec, res).strip())
        if audio_streams:
            a      = audio_streams[0]
            acodec = a.get("Codec", "").upper()
            ach    = a.get("Channels", "")
            bits.append("Audio: {}{}".format(acodec, " {}ch".format(ach) if ach else ""))
        if play_method == "Transcode" and ti:
            reasons = ti.get("TranscodeReasons", [])
            bits.append("-> {}/{}".format(ti.get("VideoCodec",""), ti.get("AudioCodec","")))
            if reasons:
                bits.append("Reason: {}".format(", ".join(reasons[:2])))
        br = ti.get("Bitrate") or s.get("TranscodingInfo", {}).get("Bitrate")
        bits.append("Bitrate: {}".format(_fmt_bitrate(br)))

        tk.Label(details_bar, text="   .   ".join(bits),
                 bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left")

        # Expandable detail panel (hidden by default)
        detail_panel = tk.Frame(card, bg=t.surface_dark, padx=14, pady=8)
        # NOT packed yet — toggled by expand_btn

        # Populate detail panel
        remote_end = s.get("RemoteEndPoint", "Unknown IP")
        container  = next((m.get("Container") for m in item.get("MediaSources", []) if m.get("Container")), "--")
        app_ver    = s.get("ApplicationVersion", "--")

        detail_cols = [
            ("Client IP",    remote_end),
            ("App Version",  app_ver),
            ("Container",    container or "--"),
            ("Session ID",   session_id[:16] + "..." if len(session_id) > 16 else session_id),
        ]
        if video_streams:
            v = video_streams[0]
            detail_cols += [
                ("Resolution", "{}x{}".format(v.get("Width","?"), v.get("Height","?"))),
                ("Profile",    v.get("Profile", "--")),
                ("Level",      str(v.get("Level", "--"))),
            ]
        if audio_streams:
            a = audio_streams[0]
            detail_cols += [
                ("Audio Lang",    a.get("Language", "--")),
                ("Audio Channels", str(a.get("Channels", "--"))),
            ]

        for i, (lbl_text, val_text) in enumerate(detail_cols):
            col = i % 4
            row = i // 4
            grp = tk.Frame(detail_panel, bg=t.surface_dark)
            grp.grid(row=row, column=col, sticky="w", padx=12, pady=2)
            tk.Label(grp, text=lbl_text + ":",
                     bg=t.surface_dark, fg=t.text_dim,
                     font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(grp, text=val_text,
                     bg=t.surface_dark, fg=t.text,
                     font=("Segoe UI", 9, "bold")).pack(anchor="w")

        for c in range(4):
            detail_panel.columnconfigure(c, weight=1, minsize=140)

        def _toggle_detail():
            if detail_panel.winfo_ismapped():
                detail_panel.pack_forget()
                expand_btn.configure(text="Details \u25b8")
            else:
                detail_panel.pack(fill="x", padx=10, pady=(0, 6))
                expand_btn.configure(text="Details \u25be")

        expand_btn.configure(command=_toggle_detail)
        return card

    def _message_all(self):
        if not self._active_sessions:
            return
        t = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("Message All Viewers")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)

        tk.Label(dlg, text="Send a message to all {} active session(s)".format(
                 len(self._active_sessions)),
                 bg=t.bg, fg=t.text, font=("Segoe UI Semibold", 11),
                 padx=20, pady=12).pack()

        frm = tk.Frame(dlg, bg=t.bg, padx=20)
        frm.pack(fill="x")
        tk.Label(frm, text="Header:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=0, column=0, sticky="w", pady=4)
        header_var = tk.StringVar(value="Notice from Admin")
        tk.Entry(frm, textvariable=header_var, width=40,
                 bg=t.surface_dark, fg=t.text, relief="flat",
                 insertbackground=t.blue).grid(row=0, column=1, padx=8)

        tk.Label(frm, text="Message:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=1, column=0, sticky="nw", pady=4)
        msg_box = tk.Text(frm, width=40, height=4,
                          bg=t.surface_dark, fg=t.text, relief="flat",
                          insertbackground=t.blue, wrap="word")
        msg_box.grid(row=1, column=1, padx=8)

        status_lbl = tk.Label(dlg, text="", bg=t.bg, fg=t.text_muted,
                              font=t.font_small)
        status_lbl.pack(pady=4)

        def _send():
            hdr = header_var.get().strip() or "Notice"
            msg = msg_box.get("1.0", "end").strip()
            if not msg:
                status_lbl.config(text="Please enter a message.", fg=t.yellow)
                return
            ok = err = 0
            for s in self._active_sessions:
                sid = s.get("Id", "")
                payload = {"Header": hdr, "Text": msg, "TimeoutMs": 8000}
                try:
                    self._emby_post("/Sessions/{}/Message".format(sid), payload)
                    ok += 1
                except Exception:
                    err += 1
            status_lbl.config(
                text="Sent to {} session(s){}.".format(
                    ok, " ({} failed)".format(err) if err else ""),
                fg=t.status_running if not err else t.yellow)
            dlg.after(2000, dlg.destroy)

        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=12)
        send_btn = tk.Button(btn_row, text="Send", command=_send)
        self.theme.style_button(send_btn)
        send_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat",
                  bd=0, cursor="hand2").pack(side="left", padx=6)

    def _scan_libraries(self):
        self._scan_btn.config(state="disabled", text="Scanning…")
        def worker():
            try:
                cfg    = self.controller.config_manager
                host   = cfg.emby_host
                port   = cfg.emby_port
                apikey = cfg.emby_apikey
                _emby_post(host, port, apikey, "Library/Refresh")
                self.after(0, lambda: self._show_status(
                    "Library scan queued — Emby is scanning now.", self.theme.status_running))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Scan failed: " + err[:60], self.theme.status_stopped))
            finally:
                self.after(0, lambda: self._scan_btn.config(state="normal", text="⟳ Scan Libraries"))
        import threading as _t
        _t.Thread(target=worker, daemon=True).start()

    def _kick_session(self, session_id, username):
        def worker():
            try:
                self._emby_post("/Sessions/{}/Playing/Stop".format(session_id), {})
                self.after(0, lambda: self._show_status(
                    "Kicked {} successfully.".format(username),
                    self.theme.status_running))
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Kick failed: {}".format(err[:60]),
                    self.theme.status_stopped))
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _emby_post(self, endpoint, payload):
        import urllib.request, json as _json
        cfg  = self.controller.config_manager
        host = cfg.last_host or "localhost"
        port = getattr(cfg, "emby_port", "8096")
        key  = getattr(cfg, "emby_apikey", "")
        url  = "http://{}:{}{}".format(host, port, endpoint)
        body = _json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=body, method="POST",
                                       headers={"X-Emby-Token": key,
                                                "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read()

    def _show_status(self, msg, color=None):
        t = self.theme
        if msg.endswith("…") or msg.endswith("..."):
            self._status_lbl.config(text=msg, bg=t.blue, fg="#ffffff")
            return
        self._status_lbl.config(text=msg, bg=t.surface_dark, fg=color or t.text_muted)
        self.after(5000, lambda: self._status_lbl.config(text="", bg=t.surface_dark))

    def _show_error(self, msg):
        self._show_status(msg, self.theme.status_stopped)
