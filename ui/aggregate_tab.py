# ui/aggregate_tab.py
"""
Multi-Server Aggregate Dashboard
---------------------------------
Shows one card per server profile with on-demand polling.
Each card displays: connection status, CPU / RAM / Disk mini bars,
active media-session count (Emby/Plex/Jellyfin where configured),
last uptime string, and last-polled timestamp.

Clicking a card's "Switch" button calls controller.switch_server() to
make that profile the active connection.
"""

import threading
import time
import tkinter as tk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar_color(pct: float) -> str:
    """Return a hex color based on percentage."""
    if pct < 70:
        return "#4caf50"   # green
    if pct < 85:
        return "#f5a623"   # amber
    return "#e53935"       # red


def _poll_server(profile: dict, timeout: int = 8) -> dict:
    """
    Open a temporary SSH connection to *profile*, run a handful of quick
    commands, return a result dict.  Runs in a background thread.

    Result keys:
        ok        bool    — connection succeeded
        error     str     — error message if not ok
        cpu       float   — CPU % (0-100)
        ram       float   — RAM % (0-100)
        disk      float   — primary disk % (0-100)
        uptime    str     — human-readable uptime
        sessions  int     — active media sessions (-1 unknown)
        polled_at float   — time.time() when poll completed
    """
    result = {
        "ok": False, "error": "", "cpu": 0.0, "ram": 0.0,
        "disk": 0.0, "uptime": "--", "sessions": -1,
        "polled_at": time.time(),
    }
    try:
        import paramiko
        from core.ssh_manager import configure_host_key_verification, persist_host_keys
        client = paramiko.SSHClient()
        configure_host_key_verification(client)

        host     = profile.get("host", "")
        port     = int(profile.get("port", 22) or 22)
        username = profile.get("username", "")
        password = profile.get("password", "")
        key_path = profile.get("key_path", "")

        connect_kwargs = dict(
            hostname=host, port=port, username=username,
            timeout=timeout,
        )
        if password:
            # Password takes priority — key_path may be a leftover default
            connect_kwargs["password"]      = password
            connect_kwargs["allow_agent"]   = False
            connect_kwargs["look_for_keys"] = False
        elif key_path:
            # Explicit key file with no password stored
            connect_kwargs["key_filename"]  = key_path
            connect_kwargs["allow_agent"]   = False
            connect_kwargs["look_for_keys"] = False
        else:
            # No credentials stored — fall back to SSH agent and ~/.ssh/ keys
            connect_kwargs["allow_agent"]   = True
            connect_kwargs["look_for_keys"] = True

        client.connect(**connect_kwargs)
        persist_host_keys(client)

        def _run(cmd):
            try:
                _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
                return stdout.read().decode(errors="replace").strip()
            except Exception:
                return ""

        # CPU % via load average
        out = _run("nproc && cat /proc/loadavg")
        lines = out.splitlines()
        try:
            cores = int(lines[0])
            load1 = float(lines[1].split()[0])
            result["cpu"] = min(round(load1 / cores * 100, 1), 100)
        except Exception:
            pass

        # RAM %
        out = _run("free -m | awk 'NR==2{printf \"%s %s\", $3, $2}'")
        try:
            used, total = map(int, out.split())
            result["ram"] = round(used / total * 100, 1) if total else 0.0
        except Exception:
            pass

        # Disk % (root)
        out = _run("df / | awk 'NR==2{print $5}'")
        try:
            result["disk"] = float(out.strip().rstrip("%"))
        except Exception:
            pass

        # Uptime
        out = _run("uptime -p 2>/dev/null || uptime")
        result["uptime"] = out.splitlines()[0][:40] if out else "--"

        client.close()
        result["ok"] = True

    except paramiko.BadHostKeyException:
        result["error"] = "Host key mismatch — possible MITM, refusing to connect"
    except Exception as exc:
        result["error"] = str(exc)[:80]

    result["polled_at"] = time.time()
    return result


# ---------------------------------------------------------------------------
# Mini progress bar widget
# ---------------------------------------------------------------------------

class _MiniBar(tk.Frame):
    """A simple horizontal progress bar rendered on a Canvas."""

    HEIGHT = 8

    def __init__(self, parent, bg_color: str, **kwargs):
        super().__init__(parent, bg=bg_color, **kwargs)
        self._bg = bg_color
        self._canvas = tk.Canvas(self, bg=bg_color, height=self.HEIGHT,
                                 highlightthickness=0, bd=0)
        self._canvas.pack(fill="x", expand=True)
        self._canvas.bind("<Configure>", self._draw)
        self._pct = 0.0
        self._bar_color = "#4caf50"

    def set(self, pct: float):
        self._pct = max(0.0, min(float(pct), 100.0))
        self._bar_color = _bar_color(self._pct)
        self._draw()

    def _draw(self, _event=None):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        h = self.HEIGHT
        if w < 2:
            return
        # Track
        c.create_rectangle(0, 0, w, h, fill=self._bg, outline="")
        # Filled portion
        fill_w = int(w * self._pct / 100)
        if fill_w > 0:
            c.create_rectangle(0, 0, fill_w, h,
                                fill=self._bar_color, outline="")


# ---------------------------------------------------------------------------
# Single server card
# ---------------------------------------------------------------------------

class _ServerCard(tk.Frame):
    """Card widget representing one server profile."""

    STATUS_COLORS = {
        "online":      "#4caf50",
        "offline":     "#e53935",
        "connecting":  "#f5a623",
        "unknown":     "#607d8b",
    }

    def __init__(self, parent, controller, profile: dict, **kwargs):
        t = controller.theme
        super().__init__(parent, bg=t.card_bg,
                         highlightbackground=t.card_border,
                         highlightthickness=1, **kwargs)
        self.controller = controller
        self.profile    = profile
        self.theme      = t
        self._status    = "unknown"
        self._build()

    def _build(self):
        t    = self.theme
        name = self.profile.get("name") or self.profile.get("host", "?")
        host = self.profile.get("host", "")

        # ---- Top row: status dot + name + switch button ----
        top = tk.Frame(self, bg=t.card_bg, pady=10, padx=14)
        top.pack(fill="x")

        self._dot = tk.Label(top, text="●", bg=t.card_bg,
                             fg=self.STATUS_COLORS["unknown"],
                             font=("Segoe UI", 14))
        self._dot.pack(side="left")

        name_frame = tk.Frame(top, bg=t.card_bg)
        name_frame.pack(side="left", padx=(8, 0), fill="x", expand=True)
        tk.Label(name_frame, text=name, bg=t.card_bg, fg=t.text,
                 font=("Segoe UI Semibold", 11), anchor="w").pack(anchor="w")
        self._host_lbl = tk.Label(name_frame, text=host, bg=t.card_bg,
                                  fg=t.text_muted, font=t.font_small, anchor="w")
        self._host_lbl.pack(anchor="w")

        switch_btn = tk.Button(top, text="Switch →",
                               command=self._on_switch,
                               bg=t.blue, fg="#ffffff",
                               font=t.font_small, relief="flat",
                               cursor="hand2", padx=10, pady=4,
                               activebackground=t.text, activeforeground="#ffffff")
        switch_btn.pack(side="right")

        # ---- Metric bars ----
        bars = tk.Frame(self, bg=t.card_bg, padx=14, pady=4)
        bars.pack(fill="x")
        bars.columnconfigure(1, weight=1)

        self._bars  = {}
        self._pct_labels = {}

        for row_i, (key, label) in enumerate([
            ("cpu",  "CPU"),
            ("ram",  "RAM"),
            ("disk", "Disk"),
        ]):
            tk.Label(bars, text=label, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small, width=4, anchor="e").grid(
                row=row_i, column=0, padx=(0, 8), pady=3, sticky="e")

            bar = _MiniBar(bars, bg_color=t.card_bg)
            bar.grid(row=row_i, column=1, sticky="ew", pady=3)
            self._bars[key] = bar

            lbl = tk.Label(bars, text="--", bg=t.card_bg, fg=t.text_muted,
                           font=t.font_small, width=6, anchor="w")
            lbl.grid(row=row_i, column=2, padx=(8, 0), pady=3, sticky="w")
            self._pct_labels[key] = lbl

        # ---- Footer: uptime + last polled ----
        foot = tk.Frame(self, bg=t.card_bg, padx=14, pady=8)
        foot.pack(fill="x")

        self._uptime_lbl = tk.Label(foot, text="Uptime: --", bg=t.card_bg,
                                    fg=t.text_muted, font=t.font_small, anchor="w")
        self._uptime_lbl.pack(side="left")

        self._polled_lbl = tk.Label(foot, text="Never polled",
                                    bg=t.card_bg, fg=t.text_dim,
                                    font=t.font_small, anchor="e")
        self._polled_lbl.pack(side="right")

        # ---- Error label (hidden when ok) ----
        self._error_lbl = tk.Label(self, text="", bg=t.card_bg,
                                   fg=t.status_stopped_text, font=t.font_small,
                                   wraplength=300, anchor="w", padx=14)
        self._error_lbl.pack(fill="x", pady=(0, 8))

        # ---- "Last known" note from SQLite ----
        self._show_last_known()

    def _show_last_known(self):
        """Pre-populate bars from the most-recent SQLite row, if any."""
        try:
            name = self.profile.get("name") or self.profile.get("host", "default")
            row  = self.controller.metrics_store.get_last_metric(name)
            if row:
                self._apply_result({
                    "ok": True, "cpu": row["cpu"], "ram": row["ram"],
                    "disk": row["disk"], "uptime": "--",
                    "polled_at": row["ts"], "error": "", "sessions": -1,
                })
                # Override status to "unknown" since we don't know if still up
                self._set_status("unknown")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_connecting(self):
        self._set_status("connecting")
        self._error_lbl.config(text="")
        self._polled_lbl.config(text="Polling…")

    def apply_result(self, result: dict):
        self._apply_result(result)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _apply_result(self, result: dict):
        if result.get("ok"):
            self._set_status("online")
            for key in ("cpu", "ram", "disk"):
                pct = result.get(key, 0)
                self._bars[key].set(pct)
                self._pct_labels[key].config(
                    text="{:.0f}%".format(pct),
                    fg=_bar_color(pct))
            self._uptime_lbl.config(
                text="Uptime: {}".format(result.get("uptime", "--")))
            self._error_lbl.config(text="")
        else:
            self._set_status("offline")
            self._error_lbl.config(text=result.get("error", "Unreachable"))

        ts = result.get("polled_at", 0)
        if ts:
            self._polled_lbl.config(
                text="Polled {}".format(
                    time.strftime("%H:%M:%S", time.localtime(ts))))

    def _set_status(self, status: str):
        self._status = status
        color = self.STATUS_COLORS.get(status, self.STATUS_COLORS["unknown"])
        self._dot.config(fg=color)

    def _on_switch(self):
        self.controller.switch_server(self.profile)


# ---------------------------------------------------------------------------
# Aggregate Tab
# ---------------------------------------------------------------------------

class AggregateTab(tk.Frame):
    """
    Multi-server overview.  One _ServerCard per profile in the server list.
    Refresh button polls all servers in parallel threads.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._cards: dict[str, _ServerCard] = {}   # name → card
        self._polling   = False
        self._build_ui()
        # Refresh cards when server list changes
        self.bind("<Visibility>", lambda _e: self._sync_cards())

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="ALL SERVERS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")

        ctrl = tk.Frame(hdr, bg=t.bg)
        ctrl.pack(side="right")

        self._status_lbl = tk.Label(ctrl, text="", bg=t.bg, fg=t.text_muted,
                                    font=t.font_small)
        self._status_lbl.pack(side="left", padx=(0, 12))

        self._refresh_btn = tk.Button(
            ctrl, text="⟳  Refresh All",
            command=self.refresh,
            font=t.font_small, relief="flat", cursor="hand2",
            bg=t.blue, fg="#ffffff", padx=12, pady=5,
            activebackground=t.text, activeforeground="#ffffff")
        self._refresh_btn.pack(side="right", padx=(8, 0))

        add_btn = tk.Button(
            ctrl, text="+ Add Server",
            command=self._open_server_manager,
            font=t.font_small, relief="flat", cursor="hand2",
            bg=t.surface, fg=t.text, padx=12, pady=5,
            activebackground=t.card_border, activeforeground=t.text)
        add_btn.pack(side="right")

        # Separator
        tk.Frame(self, bg=t.card_border, height=1).pack(
            fill="x", padx=16, pady=(0, 12))

        # Scrollable card area
        outer = tk.Frame(self, bg=t.bg)
        outer.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self._canvas = tk.Canvas(outer, bg=t.bg, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._card_frame = tk.Frame(self._canvas, bg=t.bg)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._card_frame, anchor="nw")

        self._card_frame.bind("<Configure>", self._on_frame_resize)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        def _mw(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._canvas.bind("<MouseWheel>", _mw)

        self._sync_cards()

    def _on_frame_resize(self, _e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self._canvas.itemconfig(self._canvas_win, width=e.width)

    def _open_server_manager(self):
        """Jump to the Server Manager tab (index 20) to add/edit profiles."""
        try:
            self.controller.tabs.select(20)
            self.controller.server_tab._add()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Card management
    # ------------------------------------------------------------------
    def _sync_cards(self):
        """Create / remove cards to match the current server profile list."""
        profiles = self.controller.config_manager.get_servers()
        existing_names = set(self._cards.keys())
        current_names  = {
            (p.get("name") or p.get("host", "?")) for p in profiles}

        # Remove stale
        for name in existing_names - current_names:
            self._cards[name].destroy()
            del self._cards[name]

        # Add new
        for profile in profiles:
            name = profile.get("name") or profile.get("host", "?")
            if name not in self._cards:
                card = _ServerCard(self._card_frame, self.controller, profile)
                card.pack(fill="x", pady=6, padx=2)
                self._cards[name] = card

        if not profiles:
            tk.Label(self._card_frame,
                     text="No server profiles configured.\n"
                          "Add servers in the Server Manager tab.",
                     bg=self.theme.bg, fg=self.theme.text_muted,
                     font=("Segoe UI", 12), justify="center").pack(pady=40)

    # ------------------------------------------------------------------
    # Refresh (on-demand polling)
    # ------------------------------------------------------------------
    def refresh(self):
        if self._polling:
            return
        self._polling = True
        self._refresh_btn.config(state="disabled", text="Polling…")
        self._status_lbl.config(text="")

        profiles = self.controller.config_manager.get_servers()
        if not profiles:
            self._polling = False
            self._refresh_btn.config(state="normal", text="⟳  Refresh All")
            return

        self._sync_cards()
        for profile in profiles:
            name = profile.get("name") or profile.get("host", "?")
            if name in self._cards:
                self._cards[name].set_connecting()

        total    = len(profiles)
        done     = [0]
        lock     = threading.Lock()

        def _worker(prof):
            result = _poll_server(prof)
            # Persist to metrics store
            try:
                server_id = prof.get("name") or prof.get("host", "default")
                if result.get("ok"):
                    self.controller.metrics_store.insert_metric(
                        server_id=server_id,
                        cpu=result["cpu"],
                        ram=result["ram"],
                        disk=result["disk"],
                    )
            except Exception:
                pass

            n = prof.get("name") or prof.get("host", "?")
            self.after(0, lambda r=result, nm=n: self._apply(nm, r))

            with lock:
                done[0] += 1
                if done[0] == total:
                    self.after(0, self._poll_done)

        for profile in profiles:
            threading.Thread(target=_worker, args=(profile,), daemon=True).start()

    def _apply(self, name: str, result: dict):
        if name in self._cards:
            self._cards[name].apply_result(result)

    def _poll_done(self):
        self._polling = False
        self._refresh_btn.config(state="normal", text="⟳  Refresh All")
        online  = sum(1 for c in self._cards.values() if c._status == "online")
        offline = sum(1 for c in self._cards.values() if c._status == "offline")
        self._status_lbl.config(
            text="{} online  ·  {} offline".format(online, offline))
