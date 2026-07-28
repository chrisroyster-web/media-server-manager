# core/secret_exposure.py
"""
Static, hand-maintained map of which configured secrets this app sends as
a URL query parameter (visible in server access logs, reverse-proxy logs,
browser history, screenshots, etc.) vs. an HTTP header. This can't be
inferred from config.json alone -- it reflects how each ui/*.py tab
actually builds its HTTP requests, so it has to be re-audited by hand
whenever those call sites change.

Only the services below have been code-audited. Anything else reports as
"unknown" rather than a guessed "header" -- a false "safe" is worse than
an honest "not yet checked".
"""

EXPOSURE_MAP = [
    {"match": "sabnzbd_apikey", "service": "SABnzbd", "tab": "ui/sabnzbd_tab.py",
     "exposure": "url", "fixable": False,
     "note": "SABnzbd's API is query-param-only -- no header alternative."},
    {"match": "tautulli", "service": "Tautulli", "tab": "ui/tautulli_tab.py",
     "exposure": "url", "fixable": False,
     "note": "Tautulli's v2 API is query-param-only."},
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
