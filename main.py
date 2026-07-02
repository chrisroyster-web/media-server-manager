import os
import threading
import tkinter as tk
from tkinter import ttk

from core.config_manager import ConfigManager
from core.notification_manager import NotificationManager
from core.alert_engine import AlertEngine, METRIC_META
from core import updater as _updater
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
from ui.tautulli_tab import TautulliTab
from ui.uptime_kuma_tab import UptimeKumaTab
from ui.netdata_tab import NetdataTab
from ui.glances_tab import GlancesTab
from ui.aggregate_tab import AggregateTab
from ui.library_tab import LibraryTab
from ui.now_playing_tab import NowPlayingTab
from ui.media_requests_tab import MediaRequestsTab
from ui.media_users_tab import MediaUsersTab
from ui.scheduler_tab import SchedulerTab
from ui.install_tab import InstallTab
from ui.fail2ban_tab import Fail2banTab
from ui.restart_sequence_tab import RestartSequenceTab
from ui.qbittorrent_tab import QBittorrentTab
from ui.disk_usage_tab import DiskUsageTab
from ui.process_tab import ProcessTab
from ui.ufw_tab import UFWTab
from ui.docker_stats_tab import DockerStatsTab
from ui.ports_tab import PortsTab
from ui.sensors_tab import SensorsTab
from ui.pihole_tab import PiholeTab
from ui.network_toolkit_tab import NetworkToolkitTab
from ui.docker_volumes_tab import DockerVolumesTab
from ui.systemd_timers_tab import SystemdTimersTab
from ui.watchstate_tab import WatchstateTab
from ui.cloudflare_tab import CloudflareTab
from core.metrics_store import MetricsStore
from core.scheduler import TaskScheduler

from ui.theme import Theme


APP_VERSION = "2.0.0"

_TAB_NAMES = {
    0: "Connect", 1: "Quick Commands", 2: "Dashboard",
    3: "Services", 4: "Docker", 5: "Custom Commands",
    6: "Log Viewer", 7: "SABnzbd", 8: "Config",
    9: "Files", 10: "Disk Health", 11: "Arr",
    12: "Updates", 13: "Sessions", 14: "Emby",
    15: "Compose", 16: "Cron Jobs", 17: "Plex",
    18: "Jellyfin", 19: "Notifications", 20: "All Servers",
    21: "Play History", 22: "VPN", 23: "Reverse Proxy",
    24: "Speedtest", 25: "Storage Health", 26: "SSL Certs",
    27: "Tailscale", 28: "Bandwidth", 29: "Backups",
    30: "Prowlarr", 33: "Tautulli", 34: "Uptime Kuma",
    35: "Netdata", 36: "Glances", 37: "All Servers",
    40: "Media Library", 41: "Requests",
    42: "Media Users", 43: "Now Playing",
    44: "Automation",  45: "Install Apps",
    46: "Fail2ban",   47: "Restart Sequence",
    48: "qBittorrent", 49: "Disk Usage",
    50: "Processes",   51: "UFW Firewall",
    52: "Docker Stats", 53: "Ports",
    54: "Sensors",     55: "Pi-hole",
    56: "Net Toolkit", 57: "Docker Volumes",
    58: "Timers",     59: "Watchstate",
    60: "Cloudflare",
}


class MediaServerManager(tk.Tk):
    """
    Main application window.
    """

    def __init__(self):
        super().__init__()
        self.withdraw()   # hidden until splash finishes

        self.title("All Clear Server Services")
        self.geometry("1500x1000")
        self.minsize(1200, 850)

        # Core components — theme_mode read before Theme() so colors are right
        self.config_manager = ConfigManager()
        self.theme = Theme(mode=self.config_manager.theme_mode)
        self.theme.apply_ttk_styles(self)   # global ttk contrast pass
        self.notification_manager = NotificationManager(self.config_manager)
        self.alert_engine         = AlertEngine(self.config_manager)
        self.metrics_store = MetricsStore(self.config_manager.db_path)
        self.metrics_store.prune_old(self.config_manager.metrics_retention_days)
        self.ssh = SSHManager()
        self.service_manager = ServiceManager(self.ssh)
        self.docker_manager = DockerManager(self.ssh)
        self.scheduler = TaskScheduler(self.config_manager, self.ssh)
        self._watchdog_stop    = None
        self._connected        = False   # early init so _update_title is safe
        self._current_tab_name = ""

        # System tray
        self.tray = TrayManager(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Build layout while hidden (no flicker)
        self._build_layout()
        self.scheduler.on_run_done = self._on_task_done

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
        self._stub_14         = tk.Frame(self.tabs)                 # 14 (retired - now_playing_tab)
        self.compose_tab      = ComposeTab(self.tabs, self)         # 15
        self.cron_tab         = CronTab(self.tabs, self)            # 16
        self._stub_17         = tk.Frame(self.tabs)                 # 17 (retired - now_playing_tab)
        self._stub_18         = tk.Frame(self.tabs)                 # 18 (retired - now_playing_tab)
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
        self._stub_31         = tk.Frame(self.tabs)                      # 31 (retired - media_requests_tab)
        self._stub_32         = tk.Frame(self.tabs)                      # 32 (retired - media_requests_tab)
        self.tautulli_tab     = TautulliTab(self.tabs, self)            # 33
        self.uptime_kuma_tab  = UptimeKumaTab(self.tabs, self)          # 34
        self.netdata_tab      = NetdataTab(self.tabs, self)             # 35
        self.glances_tab      = GlancesTab(self.tabs, self)             # 36
        self.aggregate_tab       = AggregateTab(self.tabs, self)          # 37
        self._stub_38         = tk.Frame(self.tabs)                      # 38 (retired - media_users_tab)
        self._stub_39         = tk.Frame(self.tabs)                      # 39 (retired - media_users_tab)
        self.library_tab         = LibraryTab(self.tabs, self)          # 40
        self.media_requests_tab  = MediaRequestsTab(self.tabs, self)   # 41
        self.media_users_tab     = MediaUsersTab(self.tabs, self)      # 42
        self.now_playing_tab     = NowPlayingTab(self.tabs, self)      # 43
        self.scheduler_tab         = SchedulerTab(self.tabs, self)          # 44
        self.install_tab           = InstallTab(self.tabs, self)            # 45
        self.fail2ban_tab          = Fail2banTab(self.tabs, self)           # 46
        self.restart_sequence_tab  = RestartSequenceTab(self.tabs, self)    # 47
        self.qbittorrent_tab       = QBittorrentTab(self.tabs, self)        # 48
        self.disk_usage_tab        = DiskUsageTab(self.tabs, self)          # 49
        self.process_tab           = ProcessTab(self.tabs, self)            # 50
        self.ufw_tab               = UFWTab(self.tabs, self)                # 51
        self.docker_stats_tab      = DockerStatsTab(self.tabs, self)        # 52
        self.ports_tab             = PortsTab(self.tabs, self)              # 53
        self.sensors_tab           = SensorsTab(self.tabs, self)            # 54
        self.pihole_tab            = PiholeTab(self.tabs, self)             # 55
        self.network_toolkit_tab   = NetworkToolkitTab(self.tabs, self)    # 56
        self.docker_volumes_tab    = DockerVolumesTab(self.tabs, self)     # 57
        self.systemd_timers_tab    = SystemdTimersTab(self.tabs, self)     # 58
        self.watchstate_tab        = WatchstateTab(self.tabs, self)        # 59
        self.cloudflare_tab        = CloudflareTab(self.tabs, self)        # 60

        for tab in [
            self.connection_panel, self.quick_commands, self.dashboard_tab,
            self.services_tab, self.docker_tab, self.custom_tab,
            self.log_viewer, self.sabnzbd_tab, self.config_tab,
            self.sftp_tab, self.smart_tab, self.arr_tab,
            self.updates_tab, self.sessions_tab, self._stub_14,
            self.compose_tab, self.cron_tab,
            self._stub_17, self._stub_18,
            self.notif_tab, self.server_tab, self.play_history_tab,
            self.vpn_tab, self.proxy_tab, self.speedtest_tab,
            self.storage_health_tab, self.ssl_tab, self.tailscale_tab,
            self.bandwidth_tab, self.backup_tab, self.prowlarr_tab,
            self._stub_31, self._stub_32, self.tautulli_tab,
            self.uptime_kuma_tab, self.netdata_tab, self.glances_tab,
            self.aggregate_tab,
            self._stub_38, self._stub_39,
            self.library_tab,
            self.media_requests_tab, self.media_users_tab, self.now_playing_tab,
            self.scheduler_tab, self.install_tab,
            self.fail2ban_tab, self.restart_sequence_tab,
            self.qbittorrent_tab, self.disk_usage_tab,
            self.process_tab, self.ufw_tab, self.docker_stats_tab,
            self.ports_tab, self.sensors_tab,
            self.pihole_tab, self.network_toolkit_tab,
            self.docker_volumes_tab, self.systemd_timers_tab,
            self.watchstate_tab, self.cloudflare_tab,
        ]:
            self.tabs.add(tab)

        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.tabs.select(2)   # open on Dashboard, not Connection

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
        c.create_text(W//2, 232, text="v{}".format(APP_VERSION),
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
                self.after(500,   self._auto_connect)
                self.after(3000,  self.start_service_watchdog)
                self.after(5000,  self.start_sab_toast_watcher)
                self.after(6000,  self.scheduler.start)
                self.after(12000, self._check_for_update_bg)
                self._maybe_show_onboarding()
        except tk.TclError:
            self.deiconify()
            self._update_player_sidebar()
            self._update_server_sidebar()
            self.log_viewer._rebuild_sources()
            self.tray.start()
            self.after(500, self._auto_connect)

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

        # "Connect" button — opens the Connection panel (tab 0), which is no
        # longer in the sidebar nav but still available here.
        self._conn_btn = tk.Button(
            bar, text="⚡ Connect",
            command=lambda: self.tabs.select(0),
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat",
            font=("Segoe UI Semibold", 9),
            padx=12, pady=3,
            cursor="hand2",
        )
        self._conn_btn.pack(side="left", padx=(12, 0))
        self._conn_btn.bind("<Enter>",
            lambda e: self._conn_btn.configure(bg=t.blue_bright))
        self._conn_btn.bind("<Leave>",
            lambda e: self._conn_btn.configure(
                bg=t.status_running if self._connected else t.blue))

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

        # Update badge — hidden until a newer version is detected
        self._update_badge = tk.Button(
            bar, text="↑ Update available",
            command=self._show_update_dialog,
            bg=t.cyan, fg="#000000",
            bd=0, relief="flat",
            font=("Segoe UI Semibold", 9),
            padx=10, pady=3,
            cursor="hand2",
        )
        # Not packed yet — shown by _on_update_found()

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

        # Update the Connect button to reflect current state
        if connected:
            self._conn_btn.configure(text="✓ Connected", bg=t.status_running)
        else:
            self._conn_btn.configure(text="⚡ Connect", bg=t.blue)
        self._update_title()

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

    def fire_metric_alerts(self, metrics: dict):
        """Called from DashboardTab with current metric values after each refresh."""
        fired = self.alert_engine.evaluate(metrics)
        if fired:
            labels = [r["name"] for r, v in fired]
            self._alert_lbl.config(text="  ⚠  " + "   ".join(labels))
            threading.Thread(
                target=self._dispatch_rule_alerts,
                args=(fired,),
                daemon=True,
            ).start()
        else:
            self._alert_lbl.config(text="")

    def _dispatch_rule_alerts(self, fired: list):
        """Background thread: fire each rule's channels."""
        nm = self.notification_manager
        for rule, value in fired:
            metric  = rule.get("metric", "cpu")
            label, unit = METRIC_META.get(metric, (metric, ""))
            op      = rule.get("operator", ">=")
            thresh  = rule.get("threshold", "?")
            name    = rule.get("name", "Alert")
            title   = "⚠ {}".format(name)
            body    = "{} {} {}{} (now {:.1f}{})".format(
                label, op, thresh, unit, value, unit)
            channels = rule.get("channels", ["toast", "ntfy", "email"])
            if "toast" in channels:
                self.after(0, lambda t=title, b=body:
                           self.show_toast(t, b, level="warn"))
            # ntfy and email are dispatched sync from this background thread
            nm.send_rule_alert_sync(title, body, channels)

    # ---------------------------------------------------------
    # SELF-UPDATE
    # ---------------------------------------------------------

    def _check_for_update_bg(self):
        """Background startup check — silently skipped if repo not configured."""
        if not _updater.is_configured():
            return
        def _worker():
            release = _updater.check_latest_release()
            if release and _updater.is_newer(release.get("tag_name", ""), APP_VERSION):
                self.after(0, lambda r=release: self._on_update_found(r))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_found(self, release):
        """Called on the UI thread when a newer version is available."""
        tag = release.get("tag_name", "")
        # Show the update badge in the status bar
        self._update_badge.config(text="↑ v{} available".format(tag.lstrip("v")))
        self._update_badge.pack(side="right", padx=(0, 8))
        # Toast notification (non-blocking)
        self.show_toast(
            "Update Available",
            "v{} is ready — click '↑ Update' in the status bar to install.".format(
                tag.lstrip("v")),
            duration_ms=8000,
            level="ok",
        )

    def _show_update_dialog(self):
        """Open the update dialog (also called from About dialog and status bar badge)."""
        from ui.update_dialog import UpdateDialog
        # Don't open a second dialog if one is already open
        existing = getattr(self, "_update_dialog_win", None)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        self._update_dialog_win = UpdateDialog(self, self, current_version=APP_VERSION)

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
        idx = self.tabs.index(self.tabs.select())
        self._trigger_tab_refresh(idx)

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
        self._current_tab_name = _TAB_NAMES.get(idx, "")
        self._update_title()
        self.after(100, lambda: self._trigger_tab_refresh(idx))

    def _trigger_tab_refresh(self, idx):
        m = {
            2:  lambda: self.dashboard_tab.refresh(),
            3:  lambda: self.services_tab.refresh_all(),
            4:  lambda: self.docker_tab.refresh_all(),
            7:  lambda: self.sabnzbd_tab.refresh(),
            10: lambda: self.smart_tab._fetch(),
            11: lambda: self.arr_tab._fetch(),
            13: lambda: self.sessions_tab._refresh(),
            34: lambda: self.uptime_kuma_tab.refresh(),
            35: lambda: self.netdata_tab.refresh(),
            36: lambda: self.glances_tab.refresh(),
            28: lambda: self.bandwidth_tab.refresh(),
            25: lambda: self.storage_health_tab.refresh(),
            9:  lambda: self.sftp_tab._navigate(self.sftp_tab._current_path, push_history=False),
            6:  lambda: self.log_viewer.fetch(),
            29: lambda: self.backup_tab.refresh(),
            15: lambda: self.compose_tab.refresh(),
            16: lambda: self.cron_tab.refresh(),
            20: lambda: self.server_tab._load(),
            40: lambda: self.library_tab.on_show(),
            21: lambda: self.play_history_tab.refresh(),
            30: lambda: self.prowlarr_tab.refresh(),
            22: lambda: self.vpn_tab.refresh(),
            23: lambda: self.proxy_tab.refresh(),
            26: lambda: self.ssl_tab.refresh(),
            27: lambda: self.tailscale_tab.refresh(),
            12: lambda: self.updates_tab._refresh(),
            19: lambda: self.notif_tab._load_from_db(),
            33: lambda: self.tautulli_tab.refresh(),
            37: lambda: self.aggregate_tab.refresh(),
            41: lambda: self.media_requests_tab.on_show(),
            42: lambda: self.media_users_tab.on_show(),
            43: lambda: self.now_playing_tab._fetch(),
            44: lambda: self.scheduler_tab.on_show(),
            45: lambda: self.install_tab.on_show(),
            46: lambda: self.fail2ban_tab.on_show(),
            47: lambda: self.restart_sequence_tab.on_show(),
            48: lambda: self.qbittorrent_tab.on_show(),
            50: lambda: self.process_tab.on_show(),
            51: lambda: self.ufw_tab.on_show(),
            52: lambda: self.docker_stats_tab.on_show(),
            53: lambda: self.ports_tab.on_show(),
            54: lambda: self.sensors_tab.on_show(),
            55: lambda: self.pihole_tab.on_show(),
            56: lambda: self.network_toolkit_tab.on_show(),
            57: lambda: self.docker_volumes_tab.on_show(),
            58: lambda: self.systemd_timers_tab.on_show(),
            59: lambda: self.watchstate_tab.refresh(),
            60: lambda: self.cloudflare_tab.on_show(),
        }
        fn = m.get(idx)
        if fn:
            try:
                fn()
            except Exception:
                pass

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
        self.config_tab.reload()
        self.sabnzbd_tab.refresh()
        profile = self.config_manager.get_active_server()
        if profile:
            self.connection_panel.refresh_for_server(profile)

    def _update_player_sidebar(self):
        """Dim/undim sidebar entries based on config — all items always visible."""
        cfg = self.config_manager
        sb  = self.sidebar

        # ── MEDIA ──────────────────────────────────────────────────────
        has_media = bool(cfg.plex_token or cfg.jellyfin_apikey or cfg.emby_apikey)
        if has_media:
            sb.undim_item(43)   # Now Playing
            sb.undim_item(40)   # Media Library
        else:
            sb.dim_item(43, "Add a Plex, Jellyfin, or Emby API key in Config → Media")
            sb.dim_item(40, "Add a Plex, Jellyfin, or Emby API key in Config → Media")

        if cfg.jellyfin_apikey or cfg.emby_apikey:
            sb.undim_item(42)   # Media Users
        else:
            sb.dim_item(42, "Add a Jellyfin or Emby API key in Config → Media")

        # ── REQUESTS ───────────────────────────────────────────────────
        if cfg.prowlarr_apikey:
            sb.undim_item(30)
        else:
            sb.dim_item(30, "Add a Prowlarr API key in Config → Arr / Requests")

        if cfg.overseerr_apikey or cfg.jellyseerr_apikey:
            sb.undim_item(41)   # unified Requests
        else:
            sb.dim_item(41, "Add an Overseerr or Jellyseerr API key in Config → Arr / Requests")

        # ── MONITORING ─────────────────────────────────────────────────
        if cfg.tautulli_apikey:
            sb.undim_item(33)
        else:
            sb.dim_item(33, "Add a Tautulli API key in Config → Monitoring")
        if cfg.uptime_kuma_host:
            sb.undim_item(34)
        else:
            sb.dim_item(34, "Set the Uptime Kuma host in Config → Monitoring")
        if cfg.netdata_host:
            sb.undim_item(35)
        else:
            sb.dim_item(35, "Set the Netdata host in Config → Monitoring")
        if cfg.glances_host:
            sb.undim_item(36)
        else:
            sb.dim_item(36, "Set the Glances host in Config → Monitoring")
        if cfg.pihole_host:
            sb.undim_item(55)
        else:
            sb.dim_item(55, "Set the Pi-hole / AdGuard host in Config → Pi-hole")
        if cfg.watchstate_host:
            sb.undim_item(59)
        else:
            sb.dim_item(59, "Set the Watchstate host in Config → Monitoring")
        if cfg.cloudflare_api_token and cfg.cloudflare_zone_id:
            sb.undim_item(60)
        else:
            sb.dim_item(60, "Set your Cloudflare API Token and Zone ID in Config → Monitoring")

        # ── INFRA ──────────────────────────────────────────────────────
        if cfg.vpn_enabled:
            sb.undim_item(22)
        else:
            sb.dim_item(22, "Enable VPN monitoring in Config → VPN")
        if cfg.proxy_enabled:
            sb.undim_item(23)
        else:
            sb.dim_item(23, "Enable Reverse Proxy in Config → Reverse Proxy")
        if cfg.tailscale_enabled:
            sb.undim_item(27)
        else:
            sb.dim_item(27, "Enable Tailscale in Config → Tailscale")

    def _update_server_sidebar(self):
        """Rebuild the SERVERS section in the sidebar from current profiles."""
        self.sidebar.rebuild_servers(self.config_manager)

    def switch_server(self, profile):
        """Disconnect current SSH session and connect to a new server profile."""
        import threading
        self.show_toast("Switching Server",
                        "Connecting to {}…".format(profile.get("host", "")),
                        level="info")

        def _do():
            self.after(0, lambda: self.update_status(False))
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
                result = self.ssh.connect(
                    host=host, port=port, username=username,
                    password=password or None, key_path=key_path)
                if result is True:
                    # Persist as last_host / last_username for legacy compat
                    self.config_manager.last_host     = host
                    self.config_manager.last_username = username
                    self.config_manager.upsert_server(
                        host, username=username, port=str(port),
                        password=password or "", key_path=key_path or "")
                    # Point active_server_index at this profile so per-server
                    # config reads go to the right server's settings dict.
                    servers = self.config_manager.get_servers()
                    for i, srv in enumerate(servers):
                        if srv.get("host") == host:
                            self.config_manager.set_active_server_index(i)
                            break
                    label = profile.get("name") or host
                    self.after(0, lambda: self.update_status(True, host))
                    self.after(0, self._start_reconnect_watchdog)
                    self.after(0, lambda: self.show_toast("Connected", label, level="ok"))
                    self.after(0, lambda: self.connection_panel._log(
                        "Connected to {} ({})".format(label, host), "success"))
                    self.after(0, self.apply_config)
                    self.after(100, self.dashboard_tab.refresh)
                else:
                    self.after(0, lambda m=result: self.show_toast(
                        "Connection Failed", m, level="error"))
                    self.after(0, lambda m=result: self.connection_panel._log(
                        "Connection failed: {}".format(m), "error"))
            except Exception as e:
                self.after(0, lambda m=str(e): self.show_toast(
                    "Connection Error", m, level="error"))
                self.after(0, lambda m=str(e): self.connection_panel._log(
                    "Connection error: {}".format(m), "error"))

        threading.Thread(target=_do, daemon=True).start()

    def _auto_connect(self):
        """Connect to the last-used server on startup if credentials are saved."""
        profile = self.config_manager.get_active_server()
        if not profile or not profile.get("host"):
            return
        has_password = bool((profile.get("password") or "").strip())
        has_key = (bool((profile.get("key_path") or "").strip()) or
                   os.path.exists(os.path.expanduser("~/.ssh/id_rsa")))
        if not has_password and not has_key:
            return
        self.switch_server(profile)

    def open_server_dialog(self, profile=None):
        """Open the Add / Edit Server modal dialog."""
        from ui.server_dialog import ServerDialog
        ServerDialog(self, self, profile=profile)

    # ---------------------------------------------------------
    # SIDEBAR BADGES
    # ---------------------------------------------------------
    def set_arr_badge(self, missing_count):
        """Update the Arr sidebar button to show missing count badge."""
        self.after(0, lambda: self.sidebar.set_badge(11, missing_count))

    def set_requests_badge(self, pending_count):
        """Update the Requests sidebar button to show pending count badge."""
        self.after(0, lambda: self.sidebar.set_badge(41, pending_count))

    # ---------------------------------------------------------
    # IN-APP TOAST NOTIFICATIONS
    # ---------------------------------------------------------
    def show_toast(self, title, message, duration_ms=5000, level="info"):
        # Persist to SQLite
        try:
            server_id = (self.config_manager.get_active_server() or {}).get("name", "default")
            self.metrics_store.insert_notification(server_id, level, title, message or "")
        except Exception:
            pass
        # Log to notification history tab
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
    # TASK SCHEDULER CALLBACKS
    # ---------------------------------------------------------
    def _on_task_done(self, task_id, task_name, exit_code, output, notify_on_failure):
        """Called from the scheduler's background thread after each task run."""
        if exit_code != 0:
            self.after(0, lambda n=task_name, c=exit_code: self.show_toast(
                f"Task failed: {n}", f"Exit code {c}",
                level="error", duration_ms=8000))
            if notify_on_failure:
                self.notification_manager.send_alert(
                    f"Scheduled task failed: {task_name}",
                    f"Exit code {exit_code}\n\n{output[:1000]}",
                )
        self.after(0, self._refresh_scheduler_if_active)

    def _refresh_scheduler_if_active(self):
        try:
            sel_idx = self.tabs.index(self.tabs.select())
            my_idx  = self.tabs.index(self.scheduler_tab)
            if sel_idx == my_idx:
                self.scheduler_tab.refresh()
        except Exception:
            pass

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

    def _update_title(self):
        base      = "All Clear Server Services"
        connected = getattr(self, "_connected", False)
        tab_name  = getattr(self, "_current_tab_name", "")
        if connected:
            host = self.config_manager.last_host
            if tab_name:
                self.title("{} — {}  ·  {}".format(base, host, tab_name))
            else:
                self.title("{} — {}".format(base, host))
        elif tab_name:
            self.title("{} — {}".format(base, tab_name))
        else:
            self.title(base)

    def _show_about(self, event=None):
        if hasattr(self, "_about_win") and self._about_win and self._about_win.winfo_exists():
            self._about_win.lift()
            return
        t = self.theme
        win = tk.Toplevel(self)
        self._about_win = win
        win.title("About All Clear")
        win.configure(bg=t.bg)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        tk.Frame(win, bg=t.blue, height=4).pack(fill="x")

        body = tk.Frame(win, bg=t.bg, padx=44, pady=28)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="\U0001f5a5", bg=t.bg, fg=t.blue,
                 font=("Segoe UI", 40)).pack()
        tk.Label(body, text="All Clear Server Services", bg=t.bg, fg=t.text,
                 font=("Segoe UI Semibold", 16)).pack(pady=(10, 2))
        tk.Label(body, text="Version {}".format(APP_VERSION), bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 10)).pack()

        check_btn = tk.Button(body, text="Check for Updates",
                              command=lambda: (win.destroy(), self._show_update_dialog()))
        t.style_button(check_btn)
        check_btn.pack(pady=(10, 0))

        tk.Frame(body, bg=t.card_border, height=1).pack(fill="x", pady=20)

        tk.Label(body,
                 text="A unified media server management tool\n"
                      "for Plex, Emby, Jellyfin, and supporting services.",
                 bg=t.bg, fg=t.text_muted, font=("Segoe UI", 10),
                 justify="center").pack()

        tk.Label(body, text="© 2026 Chris Royster", bg=t.bg, fg=t.text_dim,
                 font=("Segoe UI", 9)).pack(pady=(14, 0))

        close_btn = tk.Button(body, text="Close", command=win.destroy)
        t.style_button(close_btn)
        close_btn.pack(pady=(20, 0))

        win.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = win.winfo_reqwidth()
        h  = win.winfo_reqheight()
        win.geometry("{}x{}+{}+{}".format(w, h, (sw - w) // 2, (sh - h) // 2))
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------------------------------------------------------
    # FIRST-RUN ONBOARDING
    # ---------------------------------------------------------
    def _maybe_show_onboarding(self):
        cfg = self.config_manager
        already_shown = cfg.get("onboarding_shown", False)
        has_servers   = bool(cfg.get_servers() or cfg.last_host)
        if already_shown or has_servers:
            return
        cfg.set("onboarding_shown", True)
        self.after(400, self._show_onboarding)

    def _show_onboarding(self):
        t = self.theme
        win = tk.Toplevel(self)
        win.title("Welcome")
        win.configure(bg=t.bg)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.grab_set()

        # Top accent bar
        tk.Frame(win, bg=t.blue, height=4).pack(fill="x")

        body = tk.Frame(win, bg=t.bg, padx=40, pady=32)
        body.pack(fill="both")

        tk.Label(body, text="🖥", bg=t.bg, fg=t.text,
                 font=("Segoe UI", 40)).pack()
        tk.Label(body, text="Welcome to All Clear Server Services",
                 bg=t.bg, fg=t.text,
                 font=("Segoe UI Semibold", 15)).pack(pady=(14, 0))
        tk.Label(body,
                 text="Monitor and manage your media server from one place.\n"
                      "Start by connecting to your server and adding API keys\n"
                      "for Plex, Emby, Jellyfin, and other services.",
                 bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 10),
                 justify="center").pack(pady=(10, 0))

        tk.Frame(body, bg=t.card_border, height=1).pack(fill="x", pady=24)

        steps = [
            ("1", "Connect",  "Click ⚡ Connect in the status bar and enter your server credentials."),
            ("2", "Configure","Open Config (⚙) and add API keys for your media apps."),
            ("3", "Explore",  "Navigate via the sidebar — the Dashboard updates automatically."),
        ]
        for num, heading, desc in steps:
            row = tk.Frame(body, bg=t.bg)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=num, bg=t.blue, fg="#fff",
                     font=("Segoe UI Semibold", 10),
                     width=2, padx=6, pady=2).pack(side="left")
            col = tk.Frame(row, bg=t.bg)
            col.pack(side="left", padx=12)
            tk.Label(col, text=heading, bg=t.bg, fg=t.text,
                     font=("Segoe UI Semibold", 10), anchor="w").pack(anchor="w")
            tk.Label(col, text=desc, bg=t.bg, fg=t.text_muted,
                     font=("Segoe UI", 9), anchor="w",
                     wraplength=360, justify="left").pack(anchor="w")

        btns = tk.Frame(body, bg=t.bg)
        btns.pack(pady=(24, 0))

        def _connect():
            win.destroy()
            self.tabs.select(0)

        go = tk.Button(btns, text="⚡ Connect to Server", command=_connect)
        t.style_button(go, "primary")
        go.pack(side="left", padx=(0, 10))

        tk.Button(btns, text="Explore on my own", command=win.destroy,
                  bg=t.surface, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_regular,
                  padx=12, pady=5, cursor="hand2").pack(side="left")

        win.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = win.winfo_reqwidth()
        h  = win.winfo_reqheight()
        win.geometry("{}x{}+{}+{}".format(w, h, (sw - w) // 2, (sh - h) // 2))
        win.bind("<Escape>", lambda e: win.destroy())

    # --------------------------------------------------
if __name__ == "__main__":
    app = MediaServerManager()
    app.mainloop()
