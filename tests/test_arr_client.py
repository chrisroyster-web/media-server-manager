import json
from unittest.mock import MagicMock, patch

from core.arr_client import api_get, api_post, api_delete


def _json_response(payload):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()
    return resp


def _status_response(status):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.status = status
    return resp


def test_api_get_builds_url_and_sends_apikey_header():
    with patch("urllib.request.urlopen", return_value=_json_response({"ok": True})) as m:
        result = api_get("192.168.1.5", "8989", "mykey", "queue?pageSize=50")
    req = m.call_args[0][0]
    assert req.full_url == "http://192.168.1.5:8989/api/v3/queue?pageSize=50"
    assert req.get_header("X-api-key") == "mykey"
    assert result == {"ok": True}


def test_api_get_strips_scheme_prefix_from_host():
    with patch("urllib.request.urlopen", return_value=_json_response({})) as m:
        api_get("https://192.168.1.5/", "8989", "mykey", "health")
    req = m.call_args[0][0]
    assert req.full_url == "http://192.168.1.5:8989/api/v3/health"


def test_api_post_sends_json_body_and_content_type():
    with patch("urllib.request.urlopen", return_value=_json_response({"id": 1})) as m:
        result = api_post("localhost", "7878", "mykey", "command",
                          {"name": "MoviesSearch", "movieIds": [42]})
    req = m.call_args[0][0]
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data.decode()) == {"name": "MoviesSearch", "movieIds": [42]}
    assert result == {"id": 1}


def test_api_delete_uses_delete_method_and_returns_status():
    with patch("urllib.request.urlopen", return_value=_status_response(200)) as m:
        status = api_delete("localhost", "8989", "mykey",
                            "queue/123?removeFromClient=true&blocklist=true")
    req = m.call_args[0][0]
    assert req.get_method() == "DELETE"
    assert req.full_url == "http://localhost:8989/api/v3/queue/123?removeFromClient=true&blocklist=true"
    assert req.get_header("X-api-key") == "mykey"
    assert status == 200
