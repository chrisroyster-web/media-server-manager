# core/request_client.py
"""
Minimal Overseerr/Jellyseerr REST client (both share the same /api/v1 shape).
Mirrors core/arr_client.py's style so approve/decline actions in
ui/media_requests_tab.py aren't limited to the read-only GET helper that
tab already had.
"""

import urllib.request
import json


def api_get(host, port, apikey, path):
    """GET /api/v1/<path> and return parsed JSON, or raise on error."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v1/{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Api-Key": apikey})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def api_post(host, port, apikey, path, body=None):
    """POST /api/v1/<path> with optional JSON body."""
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/api/v1/{}".format(host, port, path)
    data = json.dumps(body).encode() if body else b"{}"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"X-Api-Key": apikey, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = resp.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode())
    except (json.JSONDecodeError, ValueError):
        return {}
