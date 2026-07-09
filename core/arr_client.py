# core/arr_client.py
"""
Minimal Sonarr/Radarr REST client (both use the same /api/v3 shape).
Extracted from ui/arr_tab.py so it's reusable outside that tab (e.g.
core/media_dedup.py) without pulling in any UI/Tk dependency.
"""

import urllib.request
import json


def api_get(host, port, apikey, path):
    """GET /api/v3/<path> and return parsed JSON, or raise on error."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v3/{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def api_post(host, port, apikey, path, body=None):
    """POST /api/v3/<path> with optional JSON body."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v3/{}".format(host, port, path)
    data = json.dumps(body).encode() if body else b"{}"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"X-Api-Key": apikey, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())
