# core/config_manager.py

import json
import os
import sys


class ConfigManager:
    """
    Handles persistent application settings.
    Stores sidebar state, last connection info, service/docker config,
    alert thresholds, and user preferences.
    """

    # Fallback used in dev mode (overridden in __init__ when frozen)
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
        "cpu":  80,   # %
        "ram":  85,   # %
        "disk": 90,   # %
        "temp": 85,   # °C
    }

    DEFAULT_CONFIG = {
        "sidebar_collapsed":          False,
        "sidebar_auto_collapse":      True,
        "last_host":                  "",
        "last_username":              "",
        "sabnzbd_apikey":             "",
        "sabnzbd_port":               "8080",
        "dashboard_refresh_interval": 30,
        "sonarr_host":   "localhost",
        "sonarr_port":   "8989",
        "sonarr_apikey": "",
        "radarr_host":   "localhost",
        "radarr_port":   "7878",
        "radarr_apikey": "",
        "emby_host":   "localhost",
        "emby_port":   "8096",
        "emby_apikey": "",
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
    }

    def __init__(self):
        # Compute config path at runtime so frozen-app detection always works.
        # Program Files is read-only; installed apps must write to AppData.
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
        except Exception:
            self.config = self.DEFAULT_CONFIG.copy()

    def save(self):
        with open(self.CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=4)

    # ---------------------------------------------------------
    # GETTERS / SETTERS
    # ---------------------------------------------------------
    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()

    # ---------------------------------------------------------
    # SERVICES / DOCKER / STORAGE
    # ---------------------------------------------------------
    def get_services(self):
        return self.config.get("services", self.DEFAULT_SERVICES)

    def set_services(self, data):
        self.config["services"] = data
        self.save()

    def get_docker(self):
        return self.config.get("docker", self.DEFAULT_DOCKER)

    def set_docker(self, data):
        self.config["docker"] = data
        self.save()

    def get_storage_mounts(self):
        return self.config.get("storage_mounts", self.DEFAULT_STORAGE_MOUNTS)

    def set_storage_mounts(self, mounts):
        self.config["storage_mounts"] = mounts
        self.save()

    # ---------------------------------------------------------
    # ALERT THRESHOLDS
    # ---------------------------------------------------------
    def get_thresholds(self):
        return self.config.get("thresholds", self.DEFAULT_THRESHOLDS)

    def set_thresholds(self, data):
        self.config["thresholds"] = data
        self.save()

    # ---------------------------------------------------------
    # PROPERTIES
    # ---------------------------------------------------------
    @property
    def sidebar_collapsed(self):
        return self.config.get("sidebar_collapsed", False)

    @sidebar_collapsed.setter
    def sidebar_collapsed(self, value):
        self.config["sidebar_collapsed"] = value
        self.save()

    @property
    def sidebar_auto_collapse(self):
        return self.config.get("sidebar_auto_collapse", True)

    @sidebar_auto_collapse.setter
    def sidebar_auto_collapse(self, value):
        self.config["sidebar_auto_collapse"] = value
        self.save()

    @property
    def last_host(self):
        return self.config.get("last_host", "")

    @last_host.setter
    def last_host(self, value):
        self.config["last_host"] = value
        self.save()

    @property
    def last_username(self):
        return self.config.get("last_username", "")

    @last_username.setter
    def last_username(self, value):
        self.config["last_username"] = value
        self.save()

    @property
    def sabnzbd_apikey(self):
        return self.config.get("sabnzbd_apikey", "")

    @sabnzbd_apikey.setter
    def sabnzbd_apikey(self, value):
        self.config["sabnzbd_apikey"] = value
        self.save()

    @property
    def sabnzbd_port(self):
        return self.config.get("sabnzbd_port", "8080")

    @sabnzbd_port.setter
    def sabnzbd_port(self, value):
        self.config["sabnzbd_port"] = value
        self.save()

    @property
    def dashboard_refresh_interval(self):
        return self.config.get("dashboard_refresh_interval", 30)

    @dashboard_refresh_interval.setter
    def dashboard_refresh_interval(self, value):
        self.config["dashboard_refresh_interval"] = int(value)
        self.save()

    @property
    def sonarr_host(self):   return self.config.get("sonarr_host", "localhost")
    @sonarr_host.setter
    def sonarr_host(self, v): self.config["sonarr_host"] = v; self.save()

    @property
    def sonarr_port(self):   return self.config.get("sonarr_port", "8989")
    @sonarr_port.setter
    def sonarr_port(self, v): self.config["sonarr_port"] = str(v); self.save()

    @property
    def sonarr_apikey(self):   return self.config.get("sonarr_apikey", "")
    @sonarr_apikey.setter
    def sonarr_apikey(self, v): self.config["sonarr_apikey"] = v; self.save()

    @property
    def radarr_host(self):   return self.config.get("radarr_host", "localhost")
    @radarr_host.setter
    def radarr_host(self, v): self.config["radarr_host"] = v; self.save()

    @property
    def radarr_port(self):   return self.config.get("radarr_port", "7878")
    @radarr_port.setter
    def radarr_port(self, v): self.config["radarr_port"] = str(v); self.save()

    @property
    def radarr_apikey(self):   return self.config.get("radarr_apikey", "")
    @radarr_apikey.setter
    def radarr_apikey(self, v): self.config["radarr_apikey"] = v; self.save()

    # --- Notification properties ---
    # --- Emby properties ---
    @property
    def emby_host(self):   return self.config.get("emby_host", "localhost")
    @emby_host.setter
    def emby_host(self, v): self.config["emby_host"] = v; self.save()

    @property
    def emby_port(self):   return self.config.get("emby_port", "8096")
    @emby_port.setter
    def emby_port(self, v): self.config["emby_port"] = str(v); self.save()

    @property
    def emby_apikey(self):   return self.config.get("emby_apikey", "")
    @emby_apikey.setter
    def emby_apikey(self, v): self.config["emby_apikey"] = v; self.save()

    # --- Plex properties ---
    @property
    def plex_host(self):   return self.config.get("plex_host", "localhost")
    @plex_host.setter
    def plex_host(self, v): self.config["plex_host"] = v; self.save()

    @property
    def plex_port(self):   return self.config.get("plex_port", "32400")
    @plex_port.setter
    def plex_port(self, v): self.config["plex_port"] = str(v); self.save()

    @property
    def plex_token(self):   return self.config.get("plex_token", "")
    @plex_token.setter
    def plex_token(self, v): self.config["plex_token"] = v; self.save()

    # --- Jellyfin properties ---
    @property
    def jellyfin_host(self):   return self.config.get("jellyfin_host", "localhost")
    @jellyfin_host.setter
    def jellyfin_host(self, v): self.config["jellyfin_host"] = v; self.save()

    @property
    def jellyfin_port(self):   return self.config.get("jellyfin_port", "8096")
    @jellyfin_port.setter
    def jellyfin_port(self, v): self.config["jellyfin_port"] = str(v); self.save()

    @property
    def jellyfin_apikey(self):   return self.config.get("jellyfin_apikey", "")
    @jellyfin_apikey.setter
    def jellyfin_apikey(self, v): self.config["jellyfin_apikey"] = v; self.save()

    # --- Notification properties ---
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
