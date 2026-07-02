# core/config_manager.py

import json
import os
import sys
import copy

from . import secure_storage


def _walk_secrets(obj, transform):
    """Recursively apply transform(value) to every string value whose dict
    key name looks like a secret (password/apikey/token/...), in place."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and secure_storage.is_sensitive_key(k):
                obj[k] = transform(v)
            else:
                _walk_secrets(v, transform)
    elif isinstance(obj, list):
        for item in obj:
            _walk_secrets(item, transform)


class ConfigManager:
    """
    Handles persistent application settings.

    Two-tier config
    ---------------
    Global settings  — theme, notifications, sidebar prefs — live in the
                       top-level JSON dict and are always the same regardless
                       of which server is active.

    Per-server settings — services, docker, API keys, thresholds, etc. — live
                          in  servers[active_index]["settings"]  and are read
                          via _gs() / written via _ss().  Getters fall back to
                          the top-level dict so existing configs keep working
                          without any migration step.
    """

    CONFIG_PATH = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "config.json"))

    DEFAULT_SERVICES = {
        "Emby":     {"service": "emby-server",  "port": 8096},
        "Sonarr":   {"service": "sonarr",        "port": 8989},
        "Radarr":   {"service": "radarr",        "port": 7878},
        "Prowlarr": {"service": "prowlarr",      "port": 9797},
        "Bazarr":   {"service": "bazarr",        "port": 6767},
        "SABnzbd":  {"service": "sabnzbdplus",   "port": 8080},
    }

    DEFAULT_DOCKER = {
        "Tracearr":    {"container": "tracearr",    "port": 3000},
        "Homarr":      {"container": "homarr",      "port": 7575},
        "Uptime Kuma": {"container": "uptime-kuma", "port": 3001},
        "Watchtower":  {"container": "watchtower",  "port": None},
    }

    DEFAULT_STORAGE_MOUNTS = ["/", "/opt/media/downloads", "/mnt/nas/wsbackup"]

    DEFAULT_THRESHOLDS = {
        "cpu":  80,
        "ram":  85,
        "disk": 90,
        "temp": 85,
    }

    DEFAULT_ALERT_RULES = [
        {"id": "rule_cpu",  "name": "High CPU",       "metric": "cpu",
         "operator": ">=", "threshold": 80, "duration_minutes": 0,
         "cooldown_minutes": 60, "channels": ["toast", "ntfy", "email", "apprise"], "enabled": True},
        {"id": "rule_ram",  "name": "High RAM",       "metric": "ram",
         "operator": ">=", "threshold": 85, "duration_minutes": 0,
         "cooldown_minutes": 60, "channels": ["toast", "ntfy", "email", "apprise"], "enabled": True},
        {"id": "rule_disk", "name": "Low Disk Space", "metric": "disk",
         "operator": ">=", "threshold": 90, "duration_minutes": 0,
         "cooldown_minutes": 60, "channels": ["toast", "ntfy", "email", "apprise"], "enabled": True},
        {"id": "rule_temp", "name": "High Temp",      "metric": "temp",
         "operator": ">=", "threshold": 85, "duration_minutes": 0,
         "cooldown_minutes": 60, "channels": ["toast", "ntfy", "email", "apprise"], "enabled": False},
    ]

    DEFAULT_CONFIG = {
        "sidebar_collapsed":          False,
        "sidebar_auto_collapse":      True,
        "last_host":                  "",
        "last_username":              "",
        "dashboard_refresh_interval": 30,
        "notify_ntfy_enabled": False,
        "notify_ntfy_topic":   "",
        "notify_ntfy_server":  "https://ntfy.sh",
        "notify_ntfy_token":   "",
        "notify_email_enabled": False,
        "notify_email_to":     "",
        "notify_smtp_host":    "",
        "notify_smtp_port":    "587",
        "notify_smtp_user":    "",
        "notify_smtp_pass":    "",
        "notify_apprise_enabled": False,
        "notify_apprise_urls":    "",
    }

    def __init__(self):
        if getattr(sys, "frozen", False):
            appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
            self.CONFIG_PATH = os.path.join(
                appdata, "All Clear Server Services", "config.json")
        self.config = {}
        self._ensure_config_file()
        self._load()

    # ---------------------------------------------------------
    # CONFIG FILE HANDLING
    # ---------------------------------------------------------
    def _ensure_config_file(self):
        assets_dir = os.path.dirname(self.CONFIG_PATH)
        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir)
        if not os.path.exists(self.CONFIG_PATH):
            with open(self.CONFIG_PATH, "w") as f:
                json.dump(self.DEFAULT_CONFIG, f, indent=4)

    def _load(self):
        try:
            with open(self.CONFIG_PATH, "r") as f:
                self.config = json.load(f)
            _walk_secrets(self.config, secure_storage.decrypt)
        except Exception:
            self.config = self.DEFAULT_CONFIG.copy()

    def save(self):
        # Encrypt secrets only in the on-disk copy — self.config stays
        # plaintext in memory so every other call site is unaffected.
        on_disk = copy.deepcopy(self.config)
        _walk_secrets(on_disk, secure_storage.encrypt)
        with open(self.CONFIG_PATH, "w") as f:
            json.dump(on_disk, f, indent=4)

    def load(self):
        self._load()

    # ---------------------------------------------------------
    # GENERIC GET / SET  (global config)
    # ---------------------------------------------------------
    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()

    # ---------------------------------------------------------
    # PER-SERVER HELPERS
    # ---------------------------------------------------------
    def _active_settings(self) -> dict:
        """Return the settings dict for the active server (read-only view)."""
        servers = self.config.get("servers", [])
        idx = self.get_active_server_index()
        if servers and 0 <= idx < len(servers):
            return servers[idx].get("settings", {})
        return {}

    def _gs(self, key, default=None):
        """Get a per-server setting, falling back to the global config."""
        return self._active_settings().get(key, self.config.get(key, default))

    def _ss(self, key, value):
        """Set a per-server setting on the active server (global fallback if none)."""
        servers = self.config.get("servers", [])
        idx = self.get_active_server_index()
        if servers and 0 <= idx < len(servers):
            if "settings" not in servers[idx]:
                servers[idx]["settings"] = {}
            servers[idx]["settings"][key] = value
        else:
            self.config[key] = value
        self.save()

    def update_server_settings(self, updates: dict):
        """Bulk-write multiple keys to the active server's settings in one save."""
        servers = self.config.get("servers", [])
        idx = self.get_active_server_index()
        if servers and 0 <= idx < len(servers):
            if "settings" not in servers[idx]:
                servers[idx]["settings"] = {}
            servers[idx]["settings"].update(updates)
        else:
            self.config.update(updates)
        self.save()

    # ---------------------------------------------------------
    # SERVICES / DOCKER / STORAGE / THRESHOLDS  (per-server)
    # ---------------------------------------------------------
    def get_services(self):
        return self._gs("services", self.DEFAULT_SERVICES)

    def set_services(self, data):
        self._ss("services", data)

    def get_docker(self):
        return self._gs("docker", self.DEFAULT_DOCKER)

    def set_docker(self, data):
        self._ss("docker", data)

    def get_storage_mounts(self):
        return self._gs("storage_mounts", self.DEFAULT_STORAGE_MOUNTS)

    def set_storage_mounts(self, mounts):
        self._ss("storage_mounts", mounts)

    def get_thresholds(self):
        return self._gs("thresholds", self.DEFAULT_THRESHOLDS)

    def set_thresholds(self, data):
        self._ss("thresholds", data)

    def get_alert_rules(self):
        return self._gs("alert_rules", [dict(r) for r in self.DEFAULT_ALERT_RULES])

    def set_alert_rules(self, rules):
        self._ss("alert_rules", rules)

    # ---------------------------------------------------------
    # SERVER PROFILES
    # ---------------------------------------------------------
    def get_servers(self):
        servers = list(self.config.get("servers", []))
        if not servers:
            host = self.config.get("last_host", "")
            user = self.config.get("last_username", "")
            if host:
                servers = [{"name": host, "host": host, "port": "22",
                            "username": user, "password": "", "key_path": "",
                            "notes": ""}]
        return servers

    def set_servers(self, servers):
        self.config["servers"] = servers
        self.save()

    def upsert_server(self, host: str, username: str = "", port: str = "22",
                      password: str = "", key_path: str = ""):
        """Add or update a server in the list (matched by host).
        Credentials are only overwritten when a non-empty value is supplied."""
        servers = list(self.config.get("servers", []))
        for srv in servers:
            if srv.get("host", "") == host:
                if username:
                    srv["username"] = username
                if password:
                    srv["password"] = password
                if key_path:
                    srv["key_path"] = key_path
                self.config["servers"] = servers
                self.save()
                return
        if host:
            servers.append({"name": host, "host": host, "port": port,
                            "username": username, "password": password,
                            "key_path": key_path, "notes": ""})
            self.config["servers"] = servers
            self.save()

    def get_active_server_index(self):
        return self.config.get("active_server_index", 0)

    def set_active_server_index(self, idx):
        self.config["active_server_index"] = idx
        self.save()

    def get_active_server(self):
        servers = self.get_servers()
        idx = self.get_active_server_index()
        if servers and 0 <= idx < len(servers):
            return servers[idx]
        return None

    # ---------------------------------------------------------
    # GLOBAL PROPERTIES  (UI / app-wide — same for all servers)
    # ---------------------------------------------------------
    @property
    def sidebar_collapsed(self):
        return self.config.get("sidebar_collapsed", False)
    @sidebar_collapsed.setter
    def sidebar_collapsed(self, value):
        self.config["sidebar_collapsed"] = value; self.save()

    @property
    def sidebar_auto_collapse(self):
        return self.config.get("sidebar_auto_collapse", True)
    @sidebar_auto_collapse.setter
    def sidebar_auto_collapse(self, value):
        self.config["sidebar_auto_collapse"] = value; self.save()

    @property
    def last_host(self):
        return self.config.get("last_host", "")
    @last_host.setter
    def last_host(self, value):
        self.config["last_host"] = value; self.save()

    @property
    def last_username(self):
        return self.config.get("last_username", "")
    @last_username.setter
    def last_username(self, value):
        self.config["last_username"] = value; self.save()

    @property
    def theme_mode(self): return self.config.get("theme_mode", "dark")
    @theme_mode.setter
    def theme_mode(self, v): self.config["theme_mode"] = v; self.save()

    @property
    def metrics_retention_days(self):
        return int(self.config.get("metrics_retention_days", 30))
    @metrics_retention_days.setter
    def metrics_retention_days(self, v):
        self.config["metrics_retention_days"] = int(v); self.save()

    @property
    def db_path(self) -> str:
        return os.path.join(os.path.dirname(self.CONFIG_PATH), "metrics.db")

    @property
    def config_path(self) -> str:
        return self.CONFIG_PATH

    # Per-tab auto-refresh intervals are global UI preferences
    def get_tab_refresh(self, tab_name):
        return self.config.get("tab_refresh_{}".format(tab_name),
                               {"enabled": True, "interval_s": 30})

    def set_tab_refresh(self, tab_name, enabled, interval_s):
        self.config["tab_refresh_{}".format(tab_name)] = {
            "enabled": bool(enabled), "interval_s": int(interval_s)}
        self.save()

    # ---------------------------------------------------------
    # PER-SERVER PROPERTIES
    # ---------------------------------------------------------

    # --- Wake-on-LAN ---
    @property
    def wol_mac(self): return self._gs("wol_mac", "")
    @wol_mac.setter
    def wol_mac(self, v): self._ss("wol_mac", v)

    @property
    def wol_broadcast(self): return self._gs("wol_broadcast", "255.255.255.255")
    @wol_broadcast.setter
    def wol_broadcast(self, v): self._ss("wol_broadcast", v)

    # --- Dashboard ---
    @property
    def dashboard_refresh_interval(self): return self._gs("dashboard_refresh_interval", 30)
    @dashboard_refresh_interval.setter
    def dashboard_refresh_interval(self, v): self._ss("dashboard_refresh_interval", int(v))

    # --- SABnzbd ---
    @property
    def sabnzbd_apikey(self): return self._gs("sabnzbd_apikey", "")
    @sabnzbd_apikey.setter
    def sabnzbd_apikey(self, v): self._ss("sabnzbd_apikey", v)

    @property
    def sabnzbd_port(self): return self._gs("sabnzbd_port", "8080")
    @sabnzbd_port.setter
    def sabnzbd_port(self, v): self._ss("sabnzbd_port", str(v))

    @property
    def sabnzbd_host(self): return self._gs("sabnzbd_host", "localhost")
    @sabnzbd_host.setter
    def sabnzbd_host(self, v): self._ss("sabnzbd_host", v)

    # --- qBittorrent ---
    @property
    def qbittorrent_host(self): return self._gs("qbittorrent_host", "")
    @qbittorrent_host.setter
    def qbittorrent_host(self, v): self._ss("qbittorrent_host", v)

    @property
    def qbittorrent_port(self): return self._gs("qbittorrent_port", "8080")
    @qbittorrent_port.setter
    def qbittorrent_port(self, v): self._ss("qbittorrent_port", str(v))

    @property
    def qbittorrent_username(self): return self._gs("qbittorrent_username", "admin")
    @qbittorrent_username.setter
    def qbittorrent_username(self, v): self._ss("qbittorrent_username", v)

    @property
    def qbittorrent_password(self): return self._gs("qbittorrent_password", "")
    @qbittorrent_password.setter
    def qbittorrent_password(self, v): self._ss("qbittorrent_password", v)

    # --- Sonarr ---
    @property
    def sonarr_host(self): return self._gs("sonarr_host", "localhost")
    @sonarr_host.setter
    def sonarr_host(self, v): self._ss("sonarr_host", v)

    @property
    def sonarr_port(self): return self._gs("sonarr_port", "8989")
    @sonarr_port.setter
    def sonarr_port(self, v): self._ss("sonarr_port", str(v))

    @property
    def sonarr_apikey(self): return self._gs("sonarr_apikey", "")
    @sonarr_apikey.setter
    def sonarr_apikey(self, v): self._ss("sonarr_apikey", v)

    # --- Radarr ---
    @property
    def radarr_host(self): return self._gs("radarr_host", "localhost")
    @radarr_host.setter
    def radarr_host(self, v): self._ss("radarr_host", v)

    @property
    def radarr_port(self): return self._gs("radarr_port", "7878")
    @radarr_port.setter
    def radarr_port(self, v): self._ss("radarr_port", str(v))

    @property
    def radarr_apikey(self): return self._gs("radarr_apikey", "")
    @radarr_apikey.setter
    def radarr_apikey(self, v): self._ss("radarr_apikey", v)

    # --- Prowlarr ---
    @property
    def prowlarr_host(self): return self._gs("prowlarr_host", "localhost")
    @prowlarr_host.setter
    def prowlarr_host(self, v): self._ss("prowlarr_host", v)

    @property
    def prowlarr_port(self): return self._gs("prowlarr_port", "9797")
    @prowlarr_port.setter
    def prowlarr_port(self, v): self._ss("prowlarr_port", str(v))

    @property
    def prowlarr_apikey(self): return self._gs("prowlarr_apikey", "")
    @prowlarr_apikey.setter
    def prowlarr_apikey(self, v): self._ss("prowlarr_apikey", v)

    # --- Emby ---
    @property
    def emby_host(self): return self._gs("emby_host", "localhost")
    @emby_host.setter
    def emby_host(self, v): self._ss("emby_host", v)

    @property
    def emby_port(self): return self._gs("emby_port", "8096")
    @emby_port.setter
    def emby_port(self, v): self._ss("emby_port", str(v))

    @property
    def emby_apikey(self): return self._gs("emby_apikey", "")
    @emby_apikey.setter
    def emby_apikey(self, v): self._ss("emby_apikey", v)

    # --- Plex ---
    @property
    def plex_host(self): return self._gs("plex_host", "localhost")
    @plex_host.setter
    def plex_host(self, v): self._ss("plex_host", v)

    @property
    def plex_port(self): return self._gs("plex_port", "32400")
    @plex_port.setter
    def plex_port(self, v): self._ss("plex_port", str(v))

    @property
    def plex_token(self): return self._gs("plex_token", "")
    @plex_token.setter
    def plex_token(self, v): self._ss("plex_token", v)

    # --- Jellyfin ---
    @property
    def jellyfin_host(self): return self._gs("jellyfin_host", "localhost")
    @jellyfin_host.setter
    def jellyfin_host(self, v): self._ss("jellyfin_host", v)

    @property
    def jellyfin_port(self): return self._gs("jellyfin_port", "8096")
    @jellyfin_port.setter
    def jellyfin_port(self, v): self._ss("jellyfin_port", str(v))

    @property
    def jellyfin_apikey(self): return self._gs("jellyfin_apikey", "")
    @jellyfin_apikey.setter
    def jellyfin_apikey(self, v): self._ss("jellyfin_apikey", v)

    # --- Overseerr ---
    @property
    def overseerr_host(self): return self._gs("overseerr_host", "localhost")
    @overseerr_host.setter
    def overseerr_host(self, v): self._ss("overseerr_host", v)

    @property
    def overseerr_port(self): return self._gs("overseerr_port", "5055")
    @overseerr_port.setter
    def overseerr_port(self, v): self._ss("overseerr_port", str(v))

    @property
    def overseerr_apikey(self): return self._gs("overseerr_apikey", "")
    @overseerr_apikey.setter
    def overseerr_apikey(self, v): self._ss("overseerr_apikey", v)

    # --- Jellyseerr ---
    @property
    def jellyseerr_host(self): return self._gs("jellyseerr_host", "localhost")
    @jellyseerr_host.setter
    def jellyseerr_host(self, v): self._ss("jellyseerr_host", v)

    @property
    def jellyseerr_port(self): return self._gs("jellyseerr_port", "5055")
    @jellyseerr_port.setter
    def jellyseerr_port(self, v): self._ss("jellyseerr_port", str(v))

    @property
    def jellyseerr_apikey(self): return self._gs("jellyseerr_apikey", "")
    @jellyseerr_apikey.setter
    def jellyseerr_apikey(self, v): self._ss("jellyseerr_apikey", v)

    # --- Tautulli ---
    @property
    def tautulli_host(self): return self._gs("tautulli_host", "localhost")
    @tautulli_host.setter
    def tautulli_host(self, v): self._ss("tautulli_host", v)

    @property
    def tautulli_port(self): return self._gs("tautulli_port", "8181")
    @tautulli_port.setter
    def tautulli_port(self, v): self._ss("tautulli_port", str(v))

    @property
    def tautulli_apikey(self): return self._gs("tautulli_apikey", "")
    @tautulli_apikey.setter
    def tautulli_apikey(self, v): self._ss("tautulli_apikey", v)

    # --- Uptime Kuma ---
    @property
    def uptime_kuma_host(self): return self._gs("uptime_kuma_host", "")
    @uptime_kuma_host.setter
    def uptime_kuma_host(self, v): self._ss("uptime_kuma_host", v)

    @property
    def uptime_kuma_port(self): return self._gs("uptime_kuma_port", "3001")
    @uptime_kuma_port.setter
    def uptime_kuma_port(self, v): self._ss("uptime_kuma_port", str(v))

    @property
    def uptime_kuma_slug(self): return self._gs("uptime_kuma_slug", "default")
    @uptime_kuma_slug.setter
    def uptime_kuma_slug(self, v): self._ss("uptime_kuma_slug", v)

    @property
    def uptime_kuma_apikey(self): return self._gs("uptime_kuma_apikey", "")
    @uptime_kuma_apikey.setter
    def uptime_kuma_apikey(self, v): self._ss("uptime_kuma_apikey", v)

    # --- Netdata ---
    @property
    def netdata_host(self): return self._gs("netdata_host", "")
    @netdata_host.setter
    def netdata_host(self, v): self._ss("netdata_host", v)

    @property
    def netdata_port(self): return self._gs("netdata_port", "19999")
    @netdata_port.setter
    def netdata_port(self, v): self._ss("netdata_port", str(v))

    # --- Glances ---
    @property
    def glances_host(self): return self._gs("glances_host", "")
    @glances_host.setter
    def glances_host(self, v): self._ss("glances_host", v)

    @property
    def glances_port(self): return self._gs("glances_port", "61208")
    @glances_port.setter
    def glances_port(self, v): self._ss("glances_port", str(v))

    # --- Watchstate ---
    @property
    def watchstate_host(self): return self._gs("watchstate_host", "")
    @watchstate_host.setter
    def watchstate_host(self, v): self._ss("watchstate_host", v)

    @property
    def watchstate_port(self): return self._gs("watchstate_port", "8090")
    @watchstate_port.setter
    def watchstate_port(self, v): self._ss("watchstate_port", str(v))

    @property
    def glances_username(self): return self._gs("glances_username", "")
    @glances_username.setter
    def glances_username(self, v): self._ss("glances_username", v)

    @property
    def glances_password(self): return self._gs("glances_password", "")
    @glances_password.setter
    def glances_password(self, v): self._ss("glances_password", v)

    # --- WUD (What's Up Docker) ---
    @property
    def wud_host(self): return self._gs("wud_host", "")
    @wud_host.setter
    def wud_host(self, v): self._ss("wud_host", v)

    @property
    def wud_port(self): return self._gs("wud_port", "3000")
    @wud_port.setter
    def wud_port(self, v): self._ss("wud_port", str(v))

    # --- Pi-hole / AdGuard Home ---
    @property
    def pihole_host(self): return self._gs("pihole_host", "")
    @pihole_host.setter
    def pihole_host(self, v): self._ss("pihole_host", v)

    @property
    def pihole_port(self): return self._gs("pihole_port", "80")
    @pihole_port.setter
    def pihole_port(self, v): self._ss("pihole_port", str(v))

    @property
    def pihole_apikey(self): return self._gs("pihole_apikey", "")
    @pihole_apikey.setter
    def pihole_apikey(self, v): self._ss("pihole_apikey", v)

    @property
    def pihole_type(self): return self._gs("pihole_type", "pihole")
    @pihole_type.setter
    def pihole_type(self, v): self._ss("pihole_type", v)

    @property
    def adguard_username(self): return self._gs("adguard_username", "admin")
    @adguard_username.setter
    def adguard_username(self, v): self._ss("adguard_username", v)

    # --- VPN ---
    @property
    def vpn_enabled(self): return bool(self._gs("vpn_enabled", False))
    @vpn_enabled.setter
    def vpn_enabled(self, v): self._ss("vpn_enabled", bool(v))

    @property
    def vpn_type(self): return self._gs("vpn_type", "ProtonVPN")
    @vpn_type.setter
    def vpn_type(self, v): self._ss("vpn_type", v)

    # --- Reverse Proxy ---
    @property
    def proxy_enabled(self): return bool(self._gs("proxy_enabled", False))
    @proxy_enabled.setter
    def proxy_enabled(self, v): self._ss("proxy_enabled", bool(v))

    # --- Tailscale ---
    @property
    def tailscale_enabled(self): return bool(self._gs("tailscale_enabled", False))
    @tailscale_enabled.setter
    def tailscale_enabled(self, v): self._ss("tailscale_enabled", bool(v))

    @property
    def proxy_type(self): return self._gs("proxy_type", "Auto-detect")
    @proxy_type.setter
    def proxy_type(self, v): self._ss("proxy_type", v)

    # ---------------------------------------------------------
    # NOTIFICATION PROPERTIES  (global — shared across servers)
    # ---------------------------------------------------------
    @property
    def notify_ntfy_enabled(self): return bool(self.config.get("notify_ntfy_enabled", False))
    @notify_ntfy_enabled.setter
    def notify_ntfy_enabled(self, v): self.config["notify_ntfy_enabled"] = bool(v); self.save()

    @property
    def notify_ntfy_topic(self): return self.config.get("notify_ntfy_topic", "")
    @notify_ntfy_topic.setter
    def notify_ntfy_topic(self, v): self.config["notify_ntfy_topic"] = v; self.save()

    @property
    def notify_ntfy_server(self): return self.config.get("notify_ntfy_server", "https://ntfy.sh")
    @notify_ntfy_server.setter
    def notify_ntfy_server(self, v): self.config["notify_ntfy_server"] = v; self.save()

    @property
    def notify_ntfy_token(self): return self.config.get("notify_ntfy_token", "")
    @notify_ntfy_token.setter
    def notify_ntfy_token(self, v): self.config["notify_ntfy_token"] = v; self.save()

    @property
    def notify_email_enabled(self): return bool(self.config.get("notify_email_enabled", False))
    @notify_email_enabled.setter
    def notify_email_enabled(self, v): self.config["notify_email_enabled"] = bool(v); self.save()

    @property
    def notify_email_to(self): return self.config.get("notify_email_to", "")
    @notify_email_to.setter
    def notify_email_to(self, v): self.config["notify_email_to"] = v; self.save()

    @property
    def notify_smtp_host(self): return self.config.get("notify_smtp_host", "")
    @notify_smtp_host.setter
    def notify_smtp_host(self, v): self.config["notify_smtp_host"] = v; self.save()

    @property
    def notify_smtp_port(self): return self.config.get("notify_smtp_port", "587")
    @notify_smtp_port.setter
    def notify_smtp_port(self, v): self.config["notify_smtp_port"] = str(v); self.save()

    @property
    def notify_smtp_user(self): return self.config.get("notify_smtp_user", "")
    @notify_smtp_user.setter
    def notify_smtp_user(self, v): self.config["notify_smtp_user"] = v; self.save()

    @property
    def notify_smtp_pass(self): return self.config.get("notify_smtp_pass", "")
    @notify_smtp_pass.setter
    def notify_smtp_pass(self, v): self.config["notify_smtp_pass"] = v; self.save()

    @property
    def notify_apprise_enabled(self): return bool(self.config.get("notify_apprise_enabled", False))
    @notify_apprise_enabled.setter
    def notify_apprise_enabled(self, v): self.config["notify_apprise_enabled"] = bool(v); self.save()

    @property
    def notify_apprise_urls(self): return self.config.get("notify_apprise_urls", "")
    @notify_apprise_urls.setter
    def notify_apprise_urls(self, v): self.config["notify_apprise_urls"] = v; self.save()

    def get_apprise_url_list(self):
        """One Apprise service URL per line, blank lines and '#' comments ignored."""
        return [
            line.strip() for line in self.notify_apprise_urls.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
