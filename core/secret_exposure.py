# core/secret_exposure.py
"""
Static, hand-maintained map of which configured secrets this app sends as
a URL query parameter (visible in server access logs, reverse-proxy logs,
browser history, screenshots, etc.) vs. an HTTP header (or isn't an HTTP
secret at all). This can't be inferred from config.json alone -- it
reflects how each ui/*.py tab actually builds its requests, so it has to
be re-audited by hand whenever those call sites change.

Only the services below have been code-audited. Anything else reports as
"unknown" rather than a guessed "header" -- a false "safe" is worse than
an honest "not yet checked". A distinct "n/a" exposure means the opposite
kind of honesty: this secret genuinely never travels over HTTP at all
(e.g. a restic repo password only ever used for local encryption via SSH),
so "is it in a URL" isn't a meaningful question for it -- that's different
from "unknown", which means nobody's checked yet.
"""

EXPOSURE_MAP = [
    {"match": "sabnzbd_apikey", "service": "SABnzbd", "tab": "ui/sabnzbd_tab.py",
     "exposure": "url", "fixable": False,
     "note": "SABnzbd's API is query-param-only -- no header alternative."},
    {"match": "tautulli", "service": "Tautulli", "tab": "ui/tautulli_tab.py",
     "exposure": "url", "fixable": False,
     "note": "Tautulli's v2 API is query-param-only."},
    {"match": "pihole_apikey", "service": "Pi-hole", "tab": "ui/pihole_tab.py",
     "exposure": "url", "fixable": True,
     "note": "Sent as ?auth=<key> (Pi-hole v5 classic API, incl. on POST "
             "calls). Pi-hole v6 has a proper Bearer-session flow -- "
             "fixable if this app is migrated to target the v6 API."},
    {"match": "plex_token", "service": "Plex",
     "tab": "ui/library_tab.py, ui/play_history_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Sent as an X-Plex-Token header (fixed -- was previously a URL param)."},
    {"match": "uptime_kuma", "service": "Uptime Kuma", "tab": "ui/uptime_kuma_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an Authorization: Bearer header."},
    {"match": "emby_apikey", "service": "Emby", "tab": "ui/library_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Emby-Token header."},
    {"match": "jellyfin_apikey", "service": "Jellyfin", "tab": "ui/library_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Emby-Token header (Jellyfin uses the Emby API)."},
    {"match": "sonarr_apikey", "service": "Sonarr", "tab": "ui/arr_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Api-Key header (core/arr_client.py)."},
    {"match": "radarr_apikey", "service": "Radarr", "tab": "ui/arr_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Api-Key header (core/arr_client.py)."},
    {"match": "prowlarr_apikey", "service": "Prowlarr", "tab": "ui/prowlarr_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Api-Key header."},
    {"match": "bazarr_apikey", "service": "Bazarr", "tab": "ui/bazarr_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-API-KEY header."},
    {"match": "overseerr_apikey", "service": "Overseerr", "tab": "ui/media_requests_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Api-Key header (core/request_client.py)."},
    {"match": "jellyseerr_apikey", "service": "Jellyseerr", "tab": "ui/media_requests_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an X-Api-Key header (core/request_client.py)."},
    {"match": "cloudflare_api_token", "service": "Cloudflare", "tab": "ui/cloudflare_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an Authorization: Bearer header."},
    {"match": "notify_ntfy_token", "service": "ntfy", "tab": "core/notification_manager.py",
     "exposure": "header", "fixable": True,
     "note": "Already sent as an Authorization: Bearer header."},
    {"match": "glances_password", "service": "Glances", "tab": "ui/glances_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Sent as HTTP Basic Auth (an Authorization header), only "
             "when a username/password is actually configured."},
    {"match": "qbittorrent_password", "service": "qBittorrent", "tab": "ui/qbittorrent_tab.py",
     "exposure": "header", "fixable": True,
     "note": "Sent as a form-encoded POST body during login, not a URL "
             "param -- the resulting session is then reused via a cookie."},
    {"match": "restic_password", "service": "restic", "tab": "core/backup_status.py",
     "exposure": "n/a", "fixable": None,
     "note": "Never sent over HTTP -- written to a file on the server for "
             "restic's own local encryption, or passed inline as a shell "
             "env var. Not a URL/header question."},
    {"match": "nas_backup_password", "service": "NAS Hyper Backup",
     "tab": "core/hyperbackup_status.py",
     "exposure": "n/a", "fixable": None,
     "note": "Used only as an SSH credential to the NAS -- never sent over HTTP."},
]

_UNKNOWN = {
    "service": "", "tab": "", "exposure": "unknown", "fixable": None,
    "note": "Not code-audited yet -- verify the request code for this key "
            "before trusting whether it's exposed in a URL.",
}


def classify(key: str) -> dict:
    """Look up how `key` (a config key name) is transmitted, by substring
    match against EXPOSURE_MAP. Returns a dict with service/tab/exposure/
    fixable/note keys -- the _UNKNOWN fallback (not a guessed default) if
    nothing matches."""
    k = key.lower()
    for entry in EXPOSURE_MAP:
        if entry["match"] in k:
            return entry
    return dict(_UNKNOWN)
