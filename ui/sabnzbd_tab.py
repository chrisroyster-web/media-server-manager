# ui/sabnzbd_tab.py

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import urllib.request
import json


class SABnzbdTab(tk.Frame):
    """
    SABnzbd queue viewer.
    - Connects to the local SABnzbd HTTP API (no SSH required)
    - Shows queue slots with progress bars, size, ETA
    - Pause / Resume / Clear queue controls
    - Per-slot delete
    - Auto-refresh every 10 s
    """

    REFRESH_INTERVAL = 10_000  # ms

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller     = controller
        self.theme          = controller.theme
        self._refresh_job   = None
        self._slot_widgets  = []
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        # ---- Header ----
        hdr = tk.Frame(self, bg=self.theme.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text="SABNZBD QUEUE", bg=self.theme.bg, fg=self.theme.text,
                 font=self.theme.font_title).pack(side="left")

        # ---- Connection info (read-only — edit in Config → SABnzbd) ----
        info = tk.Frame(self, bg=self.theme.surface, padx=12, pady=8)
        info.pack(fill="x", padx=16, pady=(0, 8))
        self._conn_lbl = tk.Label(info, text="--", bg=self.theme.surface,
                                  fg=self.theme.text_muted, font=self.theme.font_small)
        self._conn_lbl.pack(side="left")
        self._update_conn_label()

        # ---- Status strip ----
        strip = tk.Frame(self, bg=self.theme.card_bg,
                          highlightbackground=self.theme.card_border, highlightthickness=1)
        strip.pack(fill="x", padx=16, pady=(0, 8))

        self._status_lbl = tk.Label(strip, text="--", bg=self.theme.card_bg,
                                     fg=self.theme.text_muted, font=self.theme.font_small)
        self._status_lbl.pack(side="left", padx=12, pady=8)

        self._speed_lbl = tk.Label(strip, text="Speed: --", bg=self.theme.card_bg,
                                    fg=self.theme.cyan, font=self.theme.font_small)
        self._speed_lbl.pack(side="left", padx=12)

        self._size_lbl = tk.Label(strip, text="Queue: --", bg=self.theme.card_bg,
                                   fg=self.theme.text_muted, font=self.theme.font_small)
        self._size_lbl.pack(side="left", padx=12)

        self._eta_lbl = tk.Label(strip, text="ETA: --", bg=self.theme.card_bg,
                                  fg=self.theme.text_muted, font=self.theme.font_small)
        self._eta_lbl.pack(side="left", padx=12)

        # ---- Action buttons ----
        btns = tk.Frame(self, bg=self.theme.bg)
        btns.pack(fill="x", padx=16, pady=(0, 8))

        for label, cmd in [
            ("Refresh",     self.refresh),
            ("Pause All",   lambda: self._api_action("pause")),
            ("Resume All",  lambda: self._api_action("resume")),
            ("Clear Queue", self._confirm_clear),
        ]:
            b = tk.Button(btns, text=label, command=cmd)
            self.theme.style_button(b)
            b.pack(side="left", padx=(0, 8))

        # ---- Scrollable queue list ----
        canvas = tk.Canvas(self, bg=self.theme.bg, highlightthickness=0)
        vsb    = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self._queue_frame = tk.Frame(canvas, bg=self.theme.bg)
        self._canvas_win  = canvas.create_window((0, 0), window=self._queue_frame, anchor="nw")

        self._queue_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(self._canvas_win, width=e.width))

        def _on_wheel(e):
            # A fast physical scroll delivers many wheel events in one burst,
            # faster than Tk can settle canvas geometry between them.
            # Calling yview_scroll() once per event let repeated rapid calls
            # desync the embedded queue_frame window's actual on-screen
            # position from what yview()/bbox() reported. Coalescing the
            # whole burst into a single net delta, applied once after it
            # settles, avoids that. Same fix as ui/sidebar.py's nav scroll.
            delta = 120 if e.num == 4 else -120 if e.num == 5 else e.delta
            self._wheel_delta_pending = getattr(self, "_wheel_delta_pending", 0) + delta
            if not getattr(self, "_wheel_scroll_scheduled", False):
                self._wheel_scroll_scheduled = True
                self.after_idle(_apply_pending_wheel_scroll)
            # Scrollbar has a built-in Tk class-level <MouseWheel> binding
            # (tk::ScrollByUnits) that calls canvas.yview directly, bypassing
            # this handler's guard entirely. Binding this same handler onto
            # vsb too (below) and returning "break" here stops that default.
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
        canvas.bind("<Button-4>",   _on_wheel)
        canvas.bind("<Button-5>",   _on_wheel)
        vsb.bind("<MouseWheel>", _on_wheel)

        self._canvas = canvas

        self._empty_lbl = tk.Label(self._queue_frame, text="No items in queue.",
                                    bg=self.theme.bg, fg=self.theme.text_muted,
                                    font=self.theme.font_regular)
        self._empty_lbl.pack(pady=40)

    # =========================================================
    # CONFIG
    # =========================================================
    def _update_conn_label(self):
        cfg = self.controller.config_manager
        host, port = cfg.sabnzbd_host, cfg.sabnzbd_port
        if not host:
            self._conn_lbl.config(
                text="No host configured — add it in Config → SABnzbd",
                fg=self.theme.yellow)
        else:
            self._conn_lbl.config(
                text="Connected to {}:{}  ·  edit in Config → SABnzbd".format(host, port),
                fg=self.theme.text_muted)

    # =========================================================
    # API
    # =========================================================
    def _build_url(self, mode, extra=""):
        cfg    = self.controller.config_manager
        host   = cfg.sabnzbd_host
        port   = cfg.sabnzbd_port
        apikey = cfg.sabnzbd_apikey
        url = ("http://{0}:{1}/sabnzbd/api"
               "?output=json&apikey={2}&mode={3}").format(host, port, apikey, mode)
        if extra:
            url += "&" + extra
        return url

    def _api_call(self, mode, extra=""):
        try:
            url = self._build_url(mode, extra)
            req = urllib.request.Request(url, headers={"User-Agent": "MediaServerManager/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"error": str(e)}

    def _api_action(self, mode):
        def worker():
            self._api_call(mode)
            self.after(500, self.refresh)
        threading.Thread(target=worker, daemon=True).start()

    def _confirm_clear(self):
        if messagebox.askyesno("Clear Queue", "Delete all items in the SABnzbd queue?"):
            self._api_action("delete&name=queue&del_files=1")

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        self._update_conn_label()
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        data = self._api_call("queue")
        self.after(0, lambda d=data: self._update_ui(d))
        self._schedule_refresh()

    def _update_ui(self, data):
        if "error" in data:
            self._status_lbl.config(
                text="Error: " + data["error"], fg=self.theme.console_error)
            self._speed_lbl.config(text="Speed: --")
            self._size_lbl.config(text="Queue: --")
            self._eta_lbl.config(text="ETA: --")
            self._rebuild_slots([])
            return

        q        = data.get("queue", {})
        status   = q.get("status",   "Unknown")
        speed    = q.get("speed",    "--")
        size     = q.get("size",     "--")
        timeleft = q.get("timeleft", "--")

        color = (self.theme.status_running if status == "Downloading" else
                 self.theme.yellow         if status == "Paused"      else
                 self.theme.text_muted)
        self._status_lbl.config(text=status, fg=color)
        self._speed_lbl.config(text="Speed: " + speed)
        self._size_lbl.config(text="Queue: " + size)
        self._eta_lbl.config(text="ETA: " + timeleft)

        self._rebuild_slots(q.get("slots", []))

    def _rebuild_slots(self, slots):
        for w in self._slot_widgets:
            w.destroy()
        self._slot_widgets = []
        # Rebuilding can shrink the queue (fewer downloads than before); the
        # canvas keeps its old scroll fraction otherwise, which now points
        # past the shorter content and shows as blank space above the cards.
        # Pin back to the top on every rebuild.
        self._canvas.yview_moveto(0)

        if not slots:
            self._empty_lbl.pack(pady=40)
        else:
            self._empty_lbl.pack_forget()
            self._rebuild_slot_cards(slots)

        # The scrollregion is normally kept in sync by the <Configure>
        # binding on _queue_frame, but that fires on Tk's own schedule --
        # relying on it left stale (too-tall) scrollregions in place after a
        # rebuild, so a short queue could still be scrolled down into blank
        # space even though yview_moveto(0) above put it back at the top.
        # Force the geometry pass now and recompute directly so the region
        # always matches what was actually just built.
        self._queue_frame.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.yview_moveto(0)

    def _rebuild_slot_cards(self, slots):
        for slot in slots:
            nzo_id   = slot.get("nzo_id",     "")
            filename = slot.get("filename",    "Unknown")
            status   = slot.get("status",      "--")
            pct      = slot.get("percentage",  "0")
            size     = slot.get("size",        "--")
            sizeleft = slot.get("sizeleft",    "--")
            eta      = slot.get("timeleft",    "--")

            card = tk.Frame(self._queue_frame, bg=self.theme.card_bg,
                            highlightbackground=self.theme.card_border, highlightthickness=1)
            card.pack(fill="x", pady=4)
            self._slot_widgets.append(card)

            # Top row: filename + status + delete
            top = tk.Frame(card, bg=self.theme.card_bg)
            top.pack(fill="x", padx=10, pady=(8, 4))

            tk.Label(top, text=filename, bg=self.theme.card_bg, fg=self.theme.text,
                     font=self.theme.font_small, anchor="w", wraplength=550,
                     ).pack(side="left", fill="x", expand=True)

            s_color = (self.theme.status_running if status == "Downloading" else
                       self.theme.yellow         if status == "Paused"      else
                       self.theme.text_muted)
            tk.Label(top, text=status, bg=self.theme.card_bg, fg=s_color,
                     font=self.theme.font_small).pack(side="right", padx=(8, 0))

            del_btn = tk.Button(top, text="Remove",
                                command=lambda nid=nzo_id: self._delete_slot(nid))
            self.theme.style_button(del_btn)
            del_btn.pack(side="right", padx=(0, 8))

            # Progress bar
            pb_row = tk.Frame(card, bg=self.theme.card_bg)
            pb_row.pack(fill="x", padx=10, pady=(0, 4))

            try:
                pct_val = int(float(pct))
            except Exception:
                pct_val = 0

            pb = ttk.Progressbar(pb_row, value=pct_val, maximum=100)
            pb.pack(side="left", fill="x", expand=True, padx=(0, 8))

            tk.Label(pb_row, text=str(pct_val) + "%", bg=self.theme.card_bg,
                     fg=self.theme.text_muted, font=self.theme.font_small,
                     width=5).pack(side="left")

            # Bottom row: sizes + ETA
            bot = tk.Frame(card, bg=self.theme.card_bg)
            bot.pack(fill="x", padx=10, pady=(0, 8))
            tk.Label(bot, text=sizeleft + " remaining of " + size,
                     bg=self.theme.card_bg, fg=self.theme.text_muted,
                     font=self.theme.font_small).pack(side="left")
            tk.Label(bot, text="ETA: " + eta,
                     bg=self.theme.card_bg, fg=self.theme.cyan,
                     font=self.theme.font_small).pack(side="right")

    def _delete_slot(self, nzo_id):
        if messagebox.askyesno("Remove Item", "Remove this item from the queue?"):
            def worker():
                self._api_call("delete", "name=" + nzo_id + "&del_files=1")
                self.after(500, self.refresh)
            threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # AUTO-REFRESH
    # =========================================================
    def _schedule_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(self.REFRESH_INTERVAL, self.refresh)
