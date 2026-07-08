# core/cloudflare_manager.py
"""
Thin wrapper around the Cloudflare API v4 (REST + GraphQL Analytics).

Auth is always a scoped API Token via the "Authorization: Bearer <token>"
header — never the legacy X-Auth-Email/X-Auth-Key pair. Every function
takes the token explicitly rather than reading config itself, so this
module has no dependency on ConfigManager and stays easy to test.
"""

import datetime
import json
import urllib.request
import urllib.error

API_BASE = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 10


class CloudflareError(Exception):
    """Raised with a human-readable message extracted from the API response."""


def _request(token, method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            raise CloudflareError("HTTP {} {}".format(e.code, e.reason))
        errors = payload.get("errors") or []
        msg = errors[0].get("message") if errors else "HTTP {}".format(e.code)
        raise CloudflareError(msg)
    except urllib.error.URLError as e:
        raise CloudflareError(str(e.reason))

    if not payload.get("success", False):
        errors = payload.get("errors") or []
        msg = errors[0].get("message") if errors else "Request failed"
        raise CloudflareError(msg)
    return payload.get("result")


def test_connection(token, zone_id):
    """Returns the zone's {name, status} dict, or raises CloudflareError."""
    zone = _request(token, "GET", "/zones/{}".format(zone_id))
    return {"name": zone.get("name", "?"), "status": zone.get("status", "?")}


# ---------------------------------------------------------------------------
# DNS records
# ---------------------------------------------------------------------------

def list_dns_records(token, zone_id):
    """Returns a list of {id, type, name, content, proxied, ttl} dicts."""
    records = _request(token, "GET",
        "/zones/{}/dns_records?per_page=100".format(zone_id)) or []
    return [
        {
            "id":      r.get("id", ""),
            "type":    r.get("type", ""),
            "name":    r.get("name", ""),
            "content": r.get("content", ""),
            "proxied": bool(r.get("proxied", False)),
            "ttl":     r.get("ttl", 1),
        }
        for r in records
    ]


def update_dns_record_content(token, zone_id, record_id, content):
    """Partial update — only changes the record's content (IP/target)."""
    return _request(token, "PATCH",
        "/zones/{}/dns_records/{}".format(zone_id, record_id),
        body={"content": content})


def create_dns_record(token, zone_id, record_type, name, content,
                      proxied=True, ttl=1):
    """Create a new DNS record. ttl=1 means "automatic" (Cloudflare's
    default for proxied records). Returns the created record dict."""
    return _request(token, "POST",
        "/zones/{}/dns_records".format(zone_id),
        body={
            "type": record_type, "name": name, "content": content,
            "proxied": proxied, "ttl": ttl,
        })


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def purge_cache(token, zone_id):
    """Purges everything cached for the zone. Irreversible-ish: causes a
    traffic spike back to origin until the cache repopulates."""
    return _request(token, "POST",
        "/zones/{}/purge_cache".format(zone_id),
        body={"purge_everything": True})


# ---------------------------------------------------------------------------
# Security / firewall events  (GraphQL Analytics API)
# ---------------------------------------------------------------------------

def list_security_events(token, zone_id, hours=24, limit=50):
    """
    Returns recent WAF/firewall block events for the zone as a list of dicts:
    {action, client_ip, path, country, rule_id, source, datetime, user_agent}.
    Requires a token with Zone > Analytics > Read permission.
    """
    now   = datetime.datetime.utcnow()
    since = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    {
      viewer {
        zones(filter: {zoneTag: "%s"}) {
          firewallEventsAdaptive(
            filter: {datetime_geq: "%s", datetime_leq: "%s"}
            limit: %d
            orderBy: [datetime_DESC]
          ) {
            action
            clientIP
            clientRequestPath
            clientCountryName
            datetime
            ruleId
            source
            userAgent
          }
        }
      }
    }
    """ % (zone_id, since, until, int(limit))

    url = API_BASE + "/graphql"
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise CloudflareError("HTTP {} {}".format(e.code, e.reason))
    except urllib.error.URLError as e:
        raise CloudflareError(str(e.reason))

    if payload.get("errors"):
        raise CloudflareError(payload["errors"][0].get("message", "GraphQL error"))

    zones = ((payload.get("data") or {}).get("viewer") or {}).get("zones") or []
    events = zones[0].get("firewallEventsAdaptive", []) if zones else []
    return [
        {
            "action":     e.get("action", ""),
            "client_ip":  e.get("clientIP", ""),
            "path":       e.get("clientRequestPath", ""),
            "country":    e.get("clientCountryName", ""),
            "rule_id":    e.get("ruleId", ""),
            "source":     e.get("source", ""),
            "datetime":   e.get("datetime", ""),
            "user_agent": e.get("userAgent", ""),
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# Cloudflare Tunnel status
# ---------------------------------------------------------------------------

def list_tunnels(token, account_id):
    """
    Returns active (non-deleted) tunnels for the account as a list of dicts:
    {id, name, status, connections} where connections is the count of live
    edge connections (0 means the tunnel is registered but not connected).
    Requires a token with Account > Cloudflare Tunnel > Read permission.
    """
    tunnels = _request(token, "GET",
        "/accounts/{}/cfd_tunnel?is_deleted=false&per_page=100".format(account_id)) or []
    return [
        {
            "id":          t.get("id", ""),
            "name":        t.get("name", "?"),
            "status":      t.get("status", "unknown"),
            "connections": len(t.get("connections") or []),
        }
        for t in tunnels
    ]
