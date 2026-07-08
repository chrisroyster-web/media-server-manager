import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from core import cloudflare_manager as cf


def _ok_response(result, success=True, errors=None):
    payload = {"success": success, "result": result}
    if errors:
        payload["errors"] = errors
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()
    return resp


def _http_error(code, reason, body=None):
    fp = MagicMock()
    fp.read.return_value = json.dumps(body).encode() if body else b""
    return urllib.error.HTTPError("http://x", code, reason, {}, fp)


# ---------------------------------------------------------------------------
# _request() error handling (exercised indirectly through test_connection)
# ---------------------------------------------------------------------------

def test_test_connection_returns_name_and_status():
    with patch("urllib.request.urlopen",
               return_value=_ok_response({"name": "example.com", "status": "active"})):
        result = cf.test_connection("tok", "zone123")
    assert result == {"name": "example.com", "status": "active"}


def test_request_raises_cloudflare_error_on_http_error_with_json_body():
    err = _http_error(403, "Forbidden", {"errors": [{"message": "Invalid token"}]})
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(cf.CloudflareError, match="Invalid token"):
            cf.test_connection("bad-token", "zone123")


def test_request_raises_cloudflare_error_on_http_error_without_json_body():
    err = _http_error(500, "Internal Server Error")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(cf.CloudflareError, match="HTTP 500"):
            cf.test_connection("tok", "zone123")


def test_request_raises_cloudflare_error_on_url_error():
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("name resolution failed")):
        with pytest.raises(cf.CloudflareError, match="name resolution failed"):
            cf.test_connection("tok", "zone123")


def test_request_raises_cloudflare_error_when_success_is_false():
    with patch("urllib.request.urlopen",
               return_value=_ok_response(None, success=False,
                                          errors=[{"message": "Zone not found"}])):
        with pytest.raises(cf.CloudflareError, match="Zone not found"):
            cf.test_connection("tok", "zone123")


# ---------------------------------------------------------------------------
# DNS records
# ---------------------------------------------------------------------------

def test_list_dns_records_normalizes_fields():
    raw = [
        {"id": "r1", "type": "A", "name": "home.example.com",
         "content": "1.2.3.4", "proxied": True, "ttl": 1},
        {"id": "r2", "type": "CNAME", "name": "www.example.com",
         "content": "example.com"},  # missing proxied/ttl entirely
    ]
    with patch("urllib.request.urlopen", return_value=_ok_response(raw)):
        records = cf.list_dns_records("tok", "zone123")

    assert len(records) == 2
    assert records[0] == {
        "id": "r1", "type": "A", "name": "home.example.com",
        "content": "1.2.3.4", "proxied": True, "ttl": 1,
    }
    assert records[1]["proxied"] is False  # defaulted
    assert records[1]["ttl"] == 1


def test_list_dns_records_handles_none_result():
    with patch("urllib.request.urlopen", return_value=_ok_response(None)):
        assert cf.list_dns_records("tok", "zone123") == []


def test_update_dns_record_content_sends_patch_with_new_content():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["method"] = req.get_method()
        captured["data"] = json.loads(req.data.decode())
        return _ok_response({"id": "r1", "content": "5.6.7.8"})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = cf.update_dns_record_content("tok", "zone123", "r1", "5.6.7.8")

    assert captured["method"] == "PATCH"
    assert captured["data"] == {"content": "5.6.7.8"}
    assert result["content"] == "5.6.7.8"


# ---------------------------------------------------------------------------
# Cache purge
# ---------------------------------------------------------------------------

def test_purge_cache_sends_purge_everything_true():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = json.loads(req.data.decode())
        return _ok_response({"id": "purge1"})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        cf.purge_cache("tok", "zone123")

    assert captured["data"] == {"purge_everything": True}


# ---------------------------------------------------------------------------
# Tunnels
# ---------------------------------------------------------------------------

def test_list_tunnels_counts_connections():
    raw = [
        {"id": "t1", "name": "home-tunnel", "status": "healthy",
         "connections": [{"id": "c1"}, {"id": "c2"}]},
        {"id": "t2", "name": "backup-tunnel", "status": "down", "connections": []},
    ]
    with patch("urllib.request.urlopen", return_value=_ok_response(raw)):
        tunnels = cf.list_tunnels("tok", "acct123")

    assert tunnels[0]["connections"] == 2
    assert tunnels[1]["connections"] == 0


# ---------------------------------------------------------------------------
# Security events (GraphQL)
# ---------------------------------------------------------------------------

def test_list_security_events_parses_graphql_response():
    payload = {
        "data": {
            "viewer": {
                "zones": [{
                    "firewallEventsAdaptive": [{
                        "action": "block", "clientIP": "1.2.3.4",
                        "clientRequestPath": "/wp-login.php",
                        "clientCountryName": "US", "datetime": "2026-01-01T00:00:00Z",
                        "ruleId": "abc", "source": "waf", "userAgent": "curl/8.0",
                    }],
                }],
            },
        },
    }
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()

    with patch("urllib.request.urlopen", return_value=resp):
        events = cf.list_security_events("tok", "zone123")

    assert len(events) == 1
    assert events[0]["action"] == "block"
    assert events[0]["client_ip"] == "1.2.3.4"
    assert events[0]["path"] == "/wp-login.php"


def test_list_security_events_returns_empty_when_no_zones():
    payload = {"data": {"viewer": {"zones": []}}}
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=resp):
        assert cf.list_security_events("tok", "zone123") == []


def test_list_security_events_raises_on_graphql_errors():
    payload = {"errors": [{"message": "insufficient permissions"}]}
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(cf.CloudflareError, match="insufficient permissions"):
            cf.list_security_events("tok", "zone123")
