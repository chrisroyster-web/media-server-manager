import os
import threading
import tkinter as tk
from tkinter import ttk

from core.config_manager import ConfigManager
from core.notification_manager import NotificationManager
from core.ssh_manager import SSHManager
from core.service_manager import ServiceManager
from core.docker_manager import DockerManager
from core.tray_manager import TrayManager

from ui.sidebar import Sidebar
from ui.connection_panel import ConnectionPanel
from ui.quick_commands import QuickCommandsPanel
from ui.dashboard_tab import DashboardTab
from ui.services_tab import ServicesTab
from ui.docker_tab import DockerTab
from ui.custom_commands_tab import CustomCommandsTab
from ui.log_viewer_tab import LogViewerTab
from ui.sabnzbd_tab import SABnzbdTab
from ui.config_tab import ConfigTab
from ui.sftp_tab import SFTPTab
from ui.smart_tab import SmartTab
from ui.arr_tab import ArrTab
from ui.updates_tab import UpdatesTab
from ui.sessions_tab import SessionsTab
from ui.emby_tab import EmbyTab
from ui.plex_tab import PlexTab
from ui.jellyfin_tab import JellyfinTab
from ui.compose_tab import ComposeTab
from ui.cron_tab import CronTab
from ui.notification_history_tab import NotificationHistoryTab
from ui.server_manager_tab import ServerManagerTab
from ui.play_history_tab import PlayHistoryTab
from ui.vpn_tab import VPNTab
from ui.reverse_proxy_tab import ReverseProxyTab
from ui.speedtest_tab import SpeedtestTab
from ui.storage_health_tab import StorageHealthTab
from ui.ssl_tab import SSLTab
from ui.tailscale_tab import TailscaleTab
from ui.bandwidth_tab import BandwidthTab
from ui.backup_tab import BackupTab
from ui.prowlarr_tab import ProwlarrTab

from ui.theme import Theme


class MediaServerManager(tk.Tk):
    """
    Main application window.
    """

    def __init__(self):
        super().__init__()
        self.withdraw()   # hidden until splash finishes

        self.title("Media Server Manager")
        self.geometry("1500x1000")
        self.minsize(1200, 850)

        # Core components — theme_mode read before Theme() so colors are right
        self.config_manager = ConfigManager()
        self.theme = Theme(mode=self.config_manager.theme_mode)
        self.theme.apply_ttk_styles(self)   # global ttk contrast pass
        self.notification_manager = NotificationManager(self.config_manager)
        self.ssh = SSHManager()
        self.service_manager = ServiceManager(self.ssh)
        self.docker_manager = DockerManager(self.ssh)
        self._watchdog_stop = None

        # System tray
        self.tray = TrayManager(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Build layout while hidden (no flicker)
        self._build_layout()

        # Global mousewheel handler — routes scroll events from any widget
        # (buttons, labels, frames) up to the nearest scrollable ancestor.
        self.bind_all("<MouseWheel>", self._on_global_scroll)

        # Show splash, then reveal the main window
        self._show_splash()

    # ---------------------------------------------------------
    # LAYOUT
    # ---------------------------------------------------------
    def _build_layout(self):
        t = self.theme
        self.configure(bg=t.bg)

        # ── Main horizontal split: sidebar + content ──────────────────
        body = tk.Frame(self, bg=t.bg)
        body.pack(fill="both", expand=True, side="top")

        self.sidebar = Sidebar(body, self)
        self.sidebar.pack(side="left", fill="y")

        content = tk.Frame(body, bg=t.bg)
        content.pack(side="left", fill="both", expand=True)

        # ── Tab notebook — tab bar clipped out of view ────────────────
        # Wrap the notebook in a clipping frame. The notebook is placed
        # with y=-TAB_H so the tab strip sits above the frame's top edge
        # (tkinter clips children to the parent's bounds). height=TAB_H
        # adds that many pixels back so the content area fills the frame.
        TAB_H = 30
        nb_clip = tk.Frame(content, bg=t.bg)
        nb_clip.pack(fill="both", expand=True)

        self.tabs = ttk.Notebook(nb_clip)
        self.tabs.place(x=0, y=-TAB_H, relwidth=1.0, relheight=1.0, height=TAB_H)

        # Instantiate all tab panels (instantiation order = tab index)
        self.connection_panel = ConnectionPanel(self.tabs, self)   # 0
        self.quick_commands   = QuickCommandsPanel(self.tabs, self) # 1
        self.dashboard_tab    = DashboardTab(self.tabs, self)       # 2
        self.services_tab     = ServicesTab(self.tabs, self)        # 3
        self.docker_tab       = DockerTab(self.tabs, self)          # 4
        self.custom_tab       = CustomCommandsTab(self.tabs, self)  # 5
        self.log_viewer       = LogViewerTab(self.tabs, self)       # 6
        self.sabnzbd_tab      = SABnzbdTab(self.tabs, self)         # 7
        self.config_tab       = ConfigTab(self.tabs, self)          # 8
        self.sftp_tab         = SFTPTab(self.tabs, self)            # 9
        self.smart_tab        = SmartTab(self.tabs, self)           # 10
        self.arr_tab          = ArrTab(self.tabs, self)             # 11
        self.updates_tab      = UpdatesTab(self.tabs, self)         # 12
        self.sessions_tab     = SessionsTab(self.tabs, self)        # 13
        self.emby_tab         = EmbyTab(self.tabs, self)            # 14
        self.compose_tab      = ComposeTab(self.tabs, self)         # 15
        self.cron_tab         = CronTab(self.tabs, self)            # 16
        self.plex_tab         = PlexTab(self.tabs, self)            # 17
        self.jellyfin_tab     = JellyfinTab(self.tabs, self)        # 18
        self.notif_tab        = NotificationHistoryTab(self.tabs, self)  # 19
        self.server_tab       = ServerManagerTab(self.tabs, self)        # 20
        self.play_history_tab = PlayHistoryTab(self.tabs, self)          # 21
        self.vpn_tab          = VPNTab(self.tabs, self)                  # 22
        self.proxy_tab        = ReverseProxyTab(self.tabs, self)         # 23
        self.speedtest_tab    = SpeedtestTab(self.tabs, self)            # 24
        self.storage_health_tab = StorageHealthTab(self.tabs, self)     # 25
        self.ssl_tab          = SSLTab(self.tabs, self)                 # 26
        self.tailscale_tab    = TailscaleTab(self.tabs, self)           # 27
        self.bandwidth_tab    = BandwidthTab(self.tabs, self)           # 28
        self.backup_tab       = BackupTab(self.tabs, self)              # 29
        self.prowlarr_tab     = ProwlarrTab(self.tabs, self)            # 30

        for tab in [
            self.connection_panel, self.quick_commands, self.dashboard_tab,
            self.services_tab, self.docker_tab, self.custom_tab,
            self.log_viewer, self.sabnzbd_tab, self.config_tab,
            self.sftp_tab, self.smart_tab, self.arr_tab,
            self.updates_tab, self.sessions_tab, self.emby_tab,
            self.compose_tab, self.cron_tab,
            self.plex_tab, self.jellyfin_tab,
            self.notif_tab, self.server_tab, self.play_history_tab,
            self.vpn_tab, self.proxy_tab, self.speedtest_tab,
            self.storage_health_tab, self.ssl_tab, self.tailscale_tab,
            self.bandwidth_tab, self.backup_tab, self.prowlarr_tab,
        ]:
            self.tabs.add(tab)

        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Status bar at the very bottom
        self._build_status_bar()

        # Keyboard shortcuts
        self._bind_shortcuts()

    # ---------------------------------------------------------
    # SPLASH SCREEN
    # ---------------------------------------------------------
    def _show_splash(self):
        # Resolve splash.png path (works both in dev and frozen/installed)
        import sys as _sys
        if getattr(_sys, "frozen", False):
            _base = os.path.dirname(_sys.executable)
        else:
            _base = os.path.dirname(os.path.abspath(__file__))
        SPLASH_PNG = os.path.join(_base, "splash.png")

        # Try loading the actual splash image first (tk.PhotoImage supports PNG
        # natively in Python 3.8+ / Tk 8.6+ — no PIL required)
        _photo = None
        if os.path.exists(SPLASH_PNG):
            try:
                _photo = tk.PhotoImage(file=SPLASH_PNG)
            except Exception:
                _photo = None

        if _photo is not None:
            # ── Image splash ─────────────────────────────────────────
            W = _photo.width()
            H = _photo.height()
            BG = "#0b0e17"
            splash = tk.Toplevel(self)
            splash.overrideredirect(True)
            splash.attributes("-topmost", True)
            splash.attributes("-alpha", 0.0)
            splash.resizable(False, False)
            splash.configure(bg=BG)
            splash._photo = _photo   # prevent GC

            c = tk.Canvas(splash, width=W, height=H, bg=BG,
                          highlightthickness=0, bd=0)
            c.pack()
            c.create_image(0, 0, anchor="nw", image=_photo)

            # Progress bar over the image
            BAR_H = 4
            bar_track = c.create_rectangle(0, H-BAR_H, W, H,
                                            fill="#1a1d27", outline="")
            bar_fill  = c.create_rectangle(0, H-BAR_H, 0, H,
                                            fill=self.theme.blue, outline="")

            splash.update_idletasks()
            sw = splash.winfo_screenwidth()
            sh = splash.winfo_screenheight()
            splash.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

            TOTAL_MS = 400 + 2200 + 300
            def _progress(elapsed=0):
                ratio = min(elapsed / TOTAL_MS, 1.0)
                c.coords(bar_fill, 0, H-BAR_H, int(W * ratio), H)
                if ratio < 1.0:
                    self.after(30, _progress, elapsed + 30)
            _progress()
            self._splash_step(splash, 0)
            return

        # ── Canvas fallback (no image file found) ────────────────────
        W, H = 520, 300
        BG        = "#0b0e17"
        SURFACE   = "#141828"
        BLUE      = "#5b8ef0"
        BLUE_BRIGHT = "#7aaaff"
        TEXT      = "#e8eef8"
        TEXT_DIM  = "#6878a0"
        BORDER    = "#252d52"

        splash = tk.Toplevel(self)
        splash.overrideredirect(True)
        splash.attributes("-topmost", True)
        splash.attributes("-alpha", 0.0)
        splash.resizable(False, False)
        splash.configure(bg=BG)

        # ── Canvas fills the whole window ────────────────────────────
        c = tk.Canvas(splash, width=W, height=H, bg=BG,
                      highlightthickness=0, bd=0)
        c.pack()

        # Background card
        c.create_rectangle(0, 0, W, H, fill=BG, outline="")

        # Outer border glow
        c.create_rectangle(1, 1, W-1, H-1, outline=BORDER, width=1)
        c.create_rectangle(2, 2, W-2, H-2, outline="#1a2448", width=1)

        # Top accent bar
        c.create_rectangle(0, 0, W, 3, fill=BLUE, outline="")

        # Decorative grid lines (subtle)
        for x in range(0, W, 40):
            c.create_line(x, 3, x, H, fill="#0f1525", width=1)
        for y in range(0, H, 40):
            c.create_line(0, y, W, y, fill="#0f1525", width=1)

        # Icon circle
        cx, cy = W // 2, 105
        c.create_oval(cx-36, cy-36, cx+36, cy+36, fill=SURFACE, outline=BLUE, width=2)
        c.create_text(cx, cy, text="🖥", font=("Segoe UI", 26), fill=TEXT)

        # App name
        c.create_text(W//2, 168, text="All Clear Server Services",
                      font=("Segoe UI", 18, "bold"), fill=TEXT)

        # Subtitle
        c.create_text(W//2, 196, text="Media Server Manager",
                      font=("Segoe UI", 11), fill=TEXT_DIM)

        # Thin divider
        c.create_line(60, 218, W-60, 218, fill=BORDER, width=1)

        # Version / build tag
        c.create_text(W//2, 232, text="v1.0.0",
                      font=("Segoe UI", 9), fill=TEXT_DIM)

        # Progress bar track
        BAR_X1, BAR_Y1, BAR_X2, BAR_Y2 = 60, 258, W-60, 268
        c.create_rectangle(BAR_X1, BAR_Y1, BAR_X2, BAR_Y2,
                           fill=SURFACE, outline=BORDER, width=1)
        bar_fill = c.create_rectangle(BAR_X1+1, BAR_Y1+1, BAR_X1+1, BAR_Y2-1,
                                      fill=BLUE_BRIGHT, outline="")

        # Loading label
        loading_lbl = c.create_text(W//2, 283, text="Loading…",
                                    font=("Segoe UI", 9), fill=TEXT_DIM)

        # Centre on screen
        splash.update_idletasks()
        sw = splash.winfo_screenwidth()
        sh = splash.winfo_screenheight()
        splash.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        # Animate progress bar
        TOTAL_MS  = 400 + 2200 + 300
        BAR_W     = BAR_X2 - BAR_X1 - 2

        def _progress(elapsed=0):
            ratio = min(elapsed / TOTAL_MS, 1.0)
            fill_x = BAR_X1 + 1 + int(BAR_W * ratio)
            c.coords(bar_fill, BAR_X1+1, BAR_Y1+1, fill_x, BAR_Y2-1)
            pct = int(ratio * 100)
            c.itemconfig(loading_lbl, text=f"Loading…  {pct}%")
            if ratio < 1.0:
                self.after(30, _progress, elapsed + 30)

        _progress()

        # Fade-in → hold → fade-out → show main window
        self._splash_step(splash, 0)

    def _splash_step(self, splash, phase,
                     FADE_STEPS=20, FADE_MS=20, HOLD_MS=2200):
        try:
            if phase < FADE_STEPS:
                splash.attributes("-alpha", (phase + 1) / FADE_STEPS)
                self.after(FADE_MS, self._splash_step, splash, phase + 1)
            elif phase == FADE_STEPS:
                self.after(HOLD_MS, self._splash_step, splash, phase + 1)
            elif phase <= FADE_STEPS * 2:
                alpha = 1.0 - (phase - FADE_STEPS) / FADE_STEPS
                splash.attributes("-alpha", max(alpha, 0.0))
                self.after(FADE_MS, self._splash_step, splash, phase + 1)
            else:
                splash.destroy()
                self.deiconify()
                self._update_player_sidebar()
                self._update_server_sidebar()
                self.log_viewer._rebuild_sources()
                self.tray.start()
                self.after(3000, self.start_service_watchdog)
                self.after(5000, self.start_sab_toast_watcher)
        except tk.TclError:
            self.deiconify()
            self._update_player_sidebar()
            self._update_server_sidebar()
            self.log_viewer._rebuild_sources()
            self.tray.start()

    def _on_close(self):
        """Minimize to tray instead of closing (if tray is active)."""
        if self.tray._icon is not None:
            self.withdraw()
        else:
            self.tray.stop()
            self.destroy()

    # ---------------------------------------------------------
    # GLOBAL MOUSEWHEEL ROUTING
    # ---------------------------------------------------------
    def _on_global_scroll(self, event):
        """
        Route <MouseWheel> from any widget to its nearest scrollable ancestor.

        Strategy:
          - If the event widget is itself a scrollable Canvas (has a scrollregion)
            or a Text widget, let its own binding handle it (return early).
          - Otherwise walk up the parent chain until we find a Canvas with a
            scrollregion set, and scroll that instead.
        This fixes scroll-over-buttons on every tab without touching each tab file.
        """
        units = int(-1 * (event.delta / 120))
        w = event.widget

        # In Python 3.14+, event.widget may be a path string if the widget
        # was destroyed before the event fires. Guard against that.
        if isinstance(w, str):
            return

        # If the widget under the cursor is already scrollable, leave it alone.
        try:
            cls = w.winfo_class()
        except Exception:
            return
        if cls == "Text":
            return
        if cls == "Canvas":
            try:
                if w.cget("scrollregion"):
                    return
            except Exception:
                pass

        # Walk up to find the nearest scrollable Canvas ancestor.
        w = w.master
        while w is not None:
            try:
                if w.winfo_class() == "Canvas":
                    sr = w.cget("scrollregion")
                    if sr:
                        w.yview_scroll(units, "units")
                        return
                w = w.master
            except Exception:
                break

    # ---------------------------------------------------------
    # STATUS BAR
    # ---------------------------------------------------------
    def _build_status_bar(self):
        t = self.theme
        bar = tk.Frame(self, bg=t.surface_dark, height=28)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        # Top border line — Office uses a very subtle top edge
        tk.Frame(bar, bg="#1a1a1a", height=1).place(
            relx=0, rely=0, relwidth=1)

        # Animated pulse dot (Canvas with two ovals: glow ring + core)
        self._status_dot = tk.Canvas(
            bar, width=14, height=14,
            bg=t.surface_dark, highlightthickness=0,
        )
        self._status_dot.pack(side="left", padx=(14, 6), pady=8)
        self._status_dot.create_oval(2, 2, 12, 12,
                                     fill=t.status_stopped,
                                     outline="", tags="glow")
        self._status_dot.create_oval(4, 4, 10, 10,
                                     fill=t.status_stopped,
                                     outline="", tags="dot")
        self._pulse_job  = None
        self._connected  = False

        self._status_lbl = tk.Label(
            bar, text="Not connected",
            bg=t.surface_dark, fg=t.text_secondary,
            font=t.font_small,
        )
        self._status_lbl.pack(side="left")

        # Right side: app name
        tk.Label(
            bar,
            text="🖥  Media Server Manager",
            bg=t.surface_dark, fg=t.text_secondary,
            font=("Segoe UI", 10),
        ).pack(side="right", padx=14)

        self._alert_lbl = tk.Label(
            bar, text="",
            bg=t.surface_dark, fg=t.yellow,
            font=t.font_small,
        )
        self._alert_lbl.pack(side="right", padx=8)

    def update_status(self, connected: bool, host: str = ""):
        t = self.theme
        self._connected = connected
        color      = t.status_running if connected else t.status_stopped
        glow_color = t.glow_green     if connected else t.status_stopped
        text       = f"  {host}" if connected else "Not connected"
        fg         = t.text if connected else t.text_secondary

        self._status_dot.itemconfig("dot",  fill=color)
        self._status_dot.itemconfig("glow", fill=glow_color)
        self._status_lbl.config(text=text, fg=fg)

        # Start or stop pulse animation
        if connected:
            self._pulse_dot()
        else:
            if self._pulse_job:
                self.after_cancel(self._pulse_job)
                self._pulse_job = None

    def _pulse_dot(self, step=0):
        """Gentle fade in/out of the glow ring to simulate a heartbeat."""
        if not self._connected:
            return
        # 20 steps: 0→10 fade out glow, 10→20 fade in
        import math
        alpha = 0.3 + 0.7 * abs(math.sin(step * math.pi / 20))
        # Blend glow_green with surface_dark based on alpha
        r1, g1, b1 = 0x5f, 0xff, 0xb0    # glow_green #5fffb0
        r2, g2, b2 = 0x0a, 0x0e, 0x1a    # surface_dark
        r = int(r2 + (r1 - r2) * alpha)
        g = int(g2 + (g1 - g2) * alpha)
        b = int(b2 + (b1 - b2) * alpha)
        color = "#{:02x}{:02x}{:02x}".format(r, g, b)
        try:
            self._status_dot.itemconfig("glow", fill=color)
        except Exception:
            return
        self._pulse_job = self.after(60, self._pulse_dot, (step + 1) % 40)

    def fire_alerts(self, alerts):
        """Called from DashboardTab after each refresh with list of active alert strings."""
        if alerts:
            self._alert_lbl.config(text="  ⚠  " + "   ".join(alerts))
        else:
            self._alert_lbl.config(text="")
        self.notification_manager.notify(alerts)

    # ---------------------------------------------------------
    # KEYBOARD SHORTCUTS
    # ---------------------------------------------------------
    def _bind_shortcuts(self):
        for i in range(9):
            self.bind("<Key-{}>".format(i + 1),
                      lambda e, idx=i: self._switch_tab(idx))
        self.bind("<r>", lambda e: self._shortcut_refresh())
        self.bind("<R>", lambda e: self._shortcut_refresh())
        self.bind("<Escape>", lambda e: self._switch_tab(0))
        self.bind("<F5>", lambda e: self._shortcut_refresh())
        self.bind("<Control-f>", self._open_search)
        self.bind("<Control-F>", self._open_search)
        self.bind("<Control-slash>", self._show_shortcut_help)
        self.bind("<Control-question>", self._show_shortcut_help)
        self._search_overlay = None
        self._shortcut_help_win = None

    def _shortcut_refresh(self):
        if self._focused_on_input():
            return
        try:
            self.dashboard_tab.refresh()
        except Exception:
            pass

    def _focused_on_input(self):
        try:
            from tkinter import ttk
            w = self.focus_get()
            return isinstance(w, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox))
        except Exception:
            return False

    def _switch_tab(self, idx):
        if self._focused_on_input():
            return
        if idx < self.tabs.index("end"):
            self.tabs.select(idx)

    def _on_tab_changed(self, event):
        idx = self.tabs.index(self.tabs.select())
        self.sidebar.set_active(idx)
        _refresh_map = {
            2:  lambda: self.dashboard_tab.refresh(),
            3:  lambda: self.services_tab.refresh_all(),
            4:  lambda: self.docker_tab.refresh_all(),
            7:  lambda: self.sabnzbd_tab.refresh(),
            10: lambda: self.smart_tab._fetch(),
            11: lambda: self.arr_tab._fetch(),
            13: lambda: self.sessions_tab._fetch(),
            14: lambda: self.emby_tab._fetch(),
            15: lambda: self.compose_tab.refresh(),
            16: lambda: self.cron_tab.refresh(),
            17: lambda: self.plex_tab._fetch(),
            18: lambda: self.jellyfin_tab._fetch(),
            19: lambda: None,   # notification history — no fetch needed
            20: lambda: self.server_tab._load(),
        }
        fn = _refresh_map.get(idx)
        if fn:
            self.after(100, fn)

    def _start_reconnect_watchdog(self):
        import threading
        self._stop_reconnect_watchdog()
        stop_event = threading.Event()
        self._watchdog_stop = stop_event

        def _watchdog():
            while not stop_event.wait(30):
                if not self.ssh.is_alive():
                    result = self.ssh.reconnect()
                    if result is True:
                        self.after(0, lambda: self.update_status(
                            True, self.config_manager.last_host))
                    else:
                        self.after(0, lambda: self.update_status(False))

        threading.Thread(target=_watchdog, daemon=True).start()

    def _stop_reconnect_watchdog(self):
        if self._watchdog_stop:
            self._watchdog_stop.set()
            self._watchdog_stop = None

    def toggle_theme(self):
        """Flip dark <-> light, save to config, restart to apply."""
        import sys, os
        cfg = self.config_manager
        new_mode = "light" if cfg.theme_mode == "dark" else "dark"
        cfg.theme_mode = new_mode
        # Restart the process so the new theme is applied cleanly
        self.destroy()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def apply_config(self):
        """Re-apply config changes that affect live widgets."""
        self._update_player_sidebar()
        self._update_server_sidebar()
        self.log_viewer._rebuild_sources()

    def _update_player_sidebar(self):
        """Show/hide Plex, Jellyfin, VPN sidebar entries based on config."""
        cfg = self.config_manager
        if cfg.plex_token:
            self.sidebar.show_item(17)
        else:
            self.sidebar.hide_item(17)
        if cfg.jellyfin_apikey:
            self.sidebar.show_item(18)
        else:
            self.sidebar.hide_item(18)
        if cfg.vpn_enabled:
            self.sidebar.show_item(22)
        else:
            self.sidebar.hide_item(22)
        if cfg.proxy_enabled:
            self.sidebar.show_item(23)
        else:
            self.sidebar.hide_item(23)

    def _update_server_sidebar(self):
        """Rebuild the SERVERS section in the sidebar from current profiles."""
        self.sidebar.rebuild_servers(self.config_manager)

    def switch_server(self, profile):
        """Disconnect current SSH session and connect to a new server profile."""
        import threading
        self.show_toast("Switching Server",
                        "Connecting to {}…".format(profile.get("host", "")),
                        level="info")
        # Navigate to Connection tab so the user sees progress
        self.tabs.select(0)

        def _do():
            try:
                if self.ssh.connected:
                    self.ssh.disconnect()
            except Exception:
                pass
            host     = profile.get("host", "")
            port     = int(profile.get("port") or 22)
            username = profile.get("username", "")
            password = profile.get("password", "")
            key_path = profile.get("key_path", "").strip() or None
            try:
                ok, msg = self.ssh.connect(host, username, password,
                                           port=port, key_path=key_path)
                if ok:
                    # Persist as last_host / last_username for legacy compat
                    self.config_manager.last_host     = host
                    self.config_manager.last_username = username
                    self.after(0, lambda: self.show_toast(
                        "Connected", profile.get("name") or host, level="ok"))
                    self.after(0, self.dashboard_tab.refresh)
                else:
                    self.after(0, lambda m=msg: self.show_toast(
                        "Connection Failed", m, level="error"))
            except Exception as e:
                self.after(0, lambda m=str(e): self.show_toast(
                    "Connection Error", m, level="error"))

        threading.Thread(target=_do, daemon=True).start()

    # ---------------------------------------------------------
    # SIDEBAR BADGE  (called by ArrTab after each refresh)
    # ---------------------------------------------------------
    def set_arr_badge(self, missing_count):
        """Update the Arr sidebar button to show missing count badge."""
        self.after(0, lambda: self.sidebar.set_badge(11, missing_count))

    # ---------------------------------------------------------
    # IN-APP TOAST NOTIFICATIONS
    # ---------------------------------------------------------
    def show_toast(self, title, message, duration_ms=5000, level="info"):
        # Log to notification history
        try:
            self.notif_tab.add_entry(title, message, level)
        except Exception:
            pass
        t = self.theme
        color_map = {"info": t.blue, "ok": t.status_running,
                     "warn": t.yellow, "error": t.status_stopped}
        accent = color_map.get(level, t.blue)
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=t.surface)
        tk.Frame(toast, bg=accent, width=4).pack(side="left", fill="y")
        body = tk.Frame(toast, bg=t.surface, padx=12, pady=10)
        body.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=title, bg=t.surface, fg=t.text,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        if message:
            tk.Label(body, text=message, bg=t.surface, fg=t.text_muted,
                     font=t.font_small, wraplength=280, justify="left").pack(
                         anchor="w", pady=(2, 0))
        tk.Button(toast, text="x", command=toast.destroy,
                  bg=t.surface, fg=t.text_muted, bd=0, relief="flat",
                  font=("Segoe UI", 13), cursor="hand2").pack(side="right", padx=6)
        toast.update_idletasks()
        w = max(toast.winfo_reqwidth(), 320)
        h = toast.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        toast.geometry("{}x{}+{}+{}".format(w, h, sw - w - 24, sh - h - 60))
        toast.attributes("-alpha", 0.0)
        def _fadein(step=0, steps=10):
            try:
                toast.attributes("-alpha", (step + 1) / steps)
                if step < steps - 1:
                    self.after(20, _fadein, step + 1, steps)
            except tk.TclError:
                pass
        _fadein()
        self.after(duration_ms, lambda: toast.destroy() if toast.winfo_exists() else None)

    # ---------------------------------------------------------
    # SERVICE WATCHDOG
    # ---------------------------------------------------------
    def start_service_watchdog(self):
        import threading
        self._svc_prev_states = {}
        stop = threading.Event()
        self._svc_watchdog_stop = stop
        def _loop():
            while not stop.wait(60):
                if not self.ssh.connected:
                    continue
                sm  = self.service_manager
                cfg = self.config_manager.get_services()
                for name, data in cfg.items():
                    status = sm.get_status(data["service"])
                    prev   = self._svc_prev_states.get(name)
                    if prev == "running" and status in ("stopped", "failed"):
                        self.after(0, lambda n=name, s=status: self.show_toast(
                            "Service stopped", "{} is now {}".format(n, s), level="error"))
                    self._svc_prev_states[name] = status
        threading.Thread(target=_loop, daemon=True).start()

    # ---------------------------------------------------------
    # SABNZBD COMPLETION TOAST
    # ---------------------------------------------------------
    def start_sab_toast_watcher(self):
        import threading, urllib.request, json as _json
        self._sab_seen_ids = set()
        stop = threading.Event()
        self._sab_watcher_stop = stop
        def _loop():
            while not stop.wait(30):
                cfg  = self.config_manager
                host = cfg.last_host or "localhost"
                port = getattr(cfg, "sab_port", "8080")
                key  = getattr(cfg, "sab_apikey", "")
                if not key:
                    continue
                try:
                    url = ("http://{}:{}/sabnzbd/api?mode=history"
                           "&limit=5&output=json&apikey={}".format(host, port, key))
                    with urllib.request.urlopen(url, timeout=6) as r:
                        data = _json.loads(r.read())
                    slots = data.get("history", {}).get("slots", [])
                    for s in slots:
                        nzo_id = s.get("nzo_id", "")
                        status = s.get("status", "")
                        name   = s.get("name", "Unknown")
                        if status == "Completed" and nzo_id not in self._sab_seen_ids:
                            self._sab_seen_ids.add(nzo_id)
                            if len(self._sab_seen_ids) > 1:
                                self.after(0, lambda n=name: self.show_toast(
                                    "Download Complete", n, level="ok"))
                except Exception:
                    pass
        threading.Thread(target=_loop, daemon=True).start()

    def _open_search(self, event=None):
        if hasattr(self, "_search_overlay") and self._search_overlay:
            try:
                self._search_overlay.focus_set()
                return
            except tk.TclError:
                pass
        t = self.theme
        overlay = tk.Frame(self, bg=t.surface, padx=8, pady=6,
                           highlightbackground=t.card_border, highlightthickness=1)
        overlay.place(x=0, y=56, width=self.sidebar.EXPANDED_WIDTH)
        self._search_overlay = overlay
        var = tk.StringVar()
        entry = tk.Entry(overlay, textvariable=var, font=t.font_regular,
                         bg=t.surface_dark, fg=t.text,
                         insertbackground=t.blue, relief="flat", bd=4)
        entry.pack(fill="x")
        entry.focus_set()
        results_frame = tk.Frame(overlay, bg=t.surface)
        results_frame.pack(fill="x", pady=(4, 0))
        nav_items = self.sidebar._NAV_ITEMS
        def _update(*_):
            for w in results_frame.winfo_children():
                w.destroy()
            query = var.get().strip().lower()
            if not query:
                return
            matches = [(icon, label, idx) for icon, label, idx, _ in nav_items
                       if query in label.lower()]
            for icon, label, idx in matches[:6]:
                def _go(i=idx):
                    _close()
                    self.sidebar._nav_click(i)
                btn = tk.Button(results_frame,
                                text="{} {}".format(icon, label), command=_go,
                                bg=t.surface, fg=t.text,
                                activebackground=t.blue, activeforeground="#fff",
                                bd=0, relief="flat", font=t.font_regular,
                                anchor="w", padx=8, pady=4, cursor="hand2")
                btn.pack(fill="x")
        def _close(event=None):
            try:
                overlay.destroy()
            except tk.TclError:
                pass
            self._search_overlay = None
        def _on_key(event):
            if event.keysym == "Escape":
                _close()
            elif event.keysym == "Return":
                btns = results_frame.winfo_children()
                if btns:
                    btns[0].invoke()
        var.trace_add("write", _update)
        entry.bind("<KeyPress>", _on_key)

    def _show_shortcut_help(self, event=None):
        if self._shortcut_help_win and self._shortcut_help_win.winfo_exists():
            self._shortcut_help_win.lift()
            return
        t = self.theme
        win = tk.Toplevel(self)
        win.title("Keyboard Shortcuts")
        win.configure(bg=t.bg)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._shortcut_help_win = win

        hdr = tk.Frame(win, bg=t.surface, padx=20, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="\u2328  Keyboard Shortcuts",
                 bg=t.surface, fg=t.text, font=t.font_title).pack(side="left")
        tk.Button(hdr, text="\u2715", command=win.destroy,
                  bg=t.surface, fg=t.text_muted, bd=0, relief="flat",
                  font=("Segoe UI", 14), cursor="hand2").pack(side="right")

        body = tk.Frame(win, bg=t.bg, padx=24, pady=16)
        body.pack(fill="both")

        SHORTCUTS = [
            ("NAVIGATION", [
                ("1 \u2013 9",    "Jump to tab by number"),
                ("Escape",         "Go to Connection tab"),
                ("Ctrl + F",       "Open global search"),
                ("Ctrl + ?",       "Show this help overlay"),
            ]),
            ("ACTIONS", [
                ("R  /  F5",       "Refresh current tab"),
            ]),
        ]

        row_i = 0
        for section, items in SHORTCUTS:
            tk.Label(body, text=section,
                     bg=t.bg, fg=t.text_muted,
                     font=("Segoe UI", 8, "bold")).grid(
                         row=row_i, column=0, columnspan=2,
                         sticky="w", pady=(10 if row_i > 0 else 0, 4))
            row_i += 1
            for key, desc in items:
                key_lbl = tk.Label(body, text=key,
                                   bg=t.surface, fg=t.blue,
                                   font=t.font_mono, padx=8, pady=3,
                                   relief="flat",
                                   highlightbackground=t.card_border,
                                   highlightthickness=1)
                key_lbl.grid(row=row_i, column=0, sticky="w", padx=(0, 16), pady=3)
                tk.Label(body, text=desc,
                         bg=t.bg, fg=t.text,
                         font=t.font_small).grid(
                             row=row_i, column=1, sticky="w", pady=3)
                row_i += 1

        win.bind("<Escape>", lambda e: win.destroy())

    # --------------------------------------------------
if __name__ == "__main__":
    app = MediaServerManager()
    app.mainloop()
