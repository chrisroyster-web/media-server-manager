import pytest

from core import metadata_scan


class _FakeSSH:
    """Same shape as the one in test_install_manager.py / test_plugin_updater.py."""
    def __init__(self):
        self.calls = []
        self._routes = {}
        self._default = ("", "", 0)

    def route(self, substring, out="", err="", code=0):
        self._routes[substring] = (out, err, code)

    def _resolve(self, cmd):
        for substring, result in self._routes.items():
            if substring in cmd:
                return result
        return self._default

    def run(self, cmd):
        self.calls.append(cmd)
        return self._resolve(cmd)


# ── scan() ───────────────────────────────────────────────────────────────────

def test_scan_no_api_key():
    result = metadata_scan.scan("host", "8096", "")
    assert result == {"items": [], "total_checked": 0, "error": "No Emby API key configured"}


def test_scan_flags_items_with_no_primary_tag(monkeypatch):
    monkeypatch.setattr(metadata_scan, "_get", lambda h, p, k, path: {
        "TotalRecordCount": 3,
        "Items": [
            {"Id": "1", "Name": "Has poster", "Type": "Movie", "Path": "/m/a.mkv",
             "ImageTags": {"Primary": "abc"}},
            {"Id": "2", "Name": "Bush Code", "Type": "Episode", "Path": "/tv/s07e06.mkv",
             "SeriesName": "Alaskan Bush People", "ImageTags": {}},
            {"Id": "3", "Name": "No tags at all", "Type": "Movie", "Path": "/m/c.mkv"},
        ],
    })
    result = metadata_scan.scan("host", "8096", "key")
    assert result["error"] is None
    assert result["total_checked"] == 3
    ids = {it["id"] for it in result["items"]}
    assert ids == {"2", "3"}
    bush_code = next(it for it in result["items"] if it["id"] == "2")
    assert bush_code["series_name"] == "Alaskan Bush People"
    assert bush_code["path"] == "/tv/s07e06.mkv"


def test_scan_paginates_until_total_reached(monkeypatch):
    pages = {
        0:   {"TotalRecordCount": 3, "Items": [
                 {"Id": "1", "Name": "a", "Type": "Movie", "ImageTags": {}},
                 {"Id": "2", "Name": "b", "Type": "Movie", "ImageTags": {}}]},
        2:   {"TotalRecordCount": 3, "Items": [
                 {"Id": "3", "Name": "c", "Type": "Movie", "ImageTags": {}}]},
    }
    calls = []

    def fake_get(h, p, k, path):
        import urllib.parse
        qs = dict(urllib.parse.parse_qsl(path.split("?", 1)[1]))
        start = int(qs["StartIndex"])
        calls.append(start)
        return pages[start]

    monkeypatch.setattr(metadata_scan, "_get", fake_get)
    result = metadata_scan.scan("host", "8096", "key")
    assert calls == [0, 2]
    assert result["total_checked"] == 3
    assert {it["id"] for it in result["items"]} == {"1", "2", "3"}


def test_scan_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(metadata_scan, "_get", lambda h, p, k, path:
                         {"TotalRecordCount": 500, "Items": []})
    result = metadata_scan.scan("host", "8096", "key")
    assert result["items"] == []
    assert result["total_checked"] == 0
    assert result["error"] is None


def test_scan_network_error_returns_partial_results(monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(metadata_scan, "_get", _boom)
    result = metadata_scan.scan("host", "8096", "key")
    assert result["items"] == []
    assert "Emby request failed" in result["error"]


# ── diff_new_missing() ──────────────────────────────────────────────────────

def test_diff_new_missing_flags_only_unseen_ids():
    items = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    new_baseline, newly_missing = metadata_scan.diff_new_missing(["1"], items)
    assert new_baseline == ["1", "2", "3"]
    assert {it["id"] for it in newly_missing} == {"2", "3"}


def test_diff_new_missing_empty_baseline_flags_everything():
    items = [{"id": "1"}, {"id": "2"}]
    new_baseline, newly_missing = metadata_scan.diff_new_missing([], items)
    assert new_baseline == ["1", "2"]
    assert len(newly_missing) == 2


def test_diff_new_missing_nothing_new():
    items = [{"id": "1"}]
    _, newly_missing = metadata_scan.diff_new_missing(["1", "2"], items)
    assert newly_missing == []


# ── generate_and_upload_thumbnail() ────────────────────────────────────────

def test_generate_and_upload_no_video_path():
    ssh = _FakeSSH()
    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "host", "8096", "key", "42", video_path="")
    assert result["ok"] is False
    assert ssh.calls == []  # never touches SSH for a Series with no file


def test_generate_and_upload_no_api_key():
    ssh = _FakeSSH()
    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "host", "8096", "", "42", video_path="/tv/ep.mkv")
    assert result["ok"] is False
    assert ssh.calls == []


def test_generate_and_upload_happy_path():
    ssh = _FakeSSH()
    ssh.route("test -s", out="ok")
    ssh.route("curl -s -o /dev/null", out="204", code=0)

    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "192.168.4.252", "8096", "testkey", "3106612",
        video_path="/mnt/nas/tvshows/S07E06.mkv")

    assert result == {"ok": True, "error": None}
    joined = " ".join(ssh.calls)
    assert "ffmpeg" in joined
    assert "3106612" in joined
    assert "/emby/Items/3106612/Images/Primary" in joined
    assert any(c.startswith("rm -f") for c in ssh.calls)  # temp file cleaned up


def test_generate_and_upload_retries_shorter_seek_when_first_fails():
    ssh = _FakeSSH()
    calls_to_test = {"n": 0}

    def resolve(cmd):
        if cmd.startswith("test -s"):
            calls_to_test["n"] += 1
            # First attempt (5-minute seek) fails; second (5s) succeeds.
            return ("ok", "", 0) if calls_to_test["n"] >= 2 else ("missing", "", 0)
        if cmd.startswith("curl"):
            return ("204", "", 0)
        return ("", "", 0)

    ssh.run = lambda cmd: (ssh.calls.append(cmd), resolve(cmd))[1]
    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "host", "8096", "key", "5", video_path="/shorts/clip.mkv")

    assert result["ok"] is True
    assert sum(1 for c in ssh.calls if c.startswith("ffmpeg")) == 2


def test_generate_and_upload_ffmpeg_never_produces_a_frame():
    ssh = _FakeSSH()
    ssh.route("test -s", out="missing")

    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "host", "8096", "key", "9", video_path="/broken/file.mkv")

    assert result["ok"] is False
    assert "ffmpeg" in result["error"]
    assert not any(c.startswith("curl") for c in ssh.calls)  # never tried to upload


def test_generate_and_upload_emby_rejects_the_image():
    ssh = _FakeSSH()
    ssh.route("test -s", out="ok")
    ssh.route("curl -s -o /dev/null", out="400", code=0)

    result = metadata_scan.generate_and_upload_thumbnail(
        ssh, "host", "8096", "key", "9", video_path="/movies/a.mkv")

    assert result["ok"] is False
    assert "400" in result["error"]
    assert any(c.startswith("rm -f") for c in ssh.calls)  # still cleans up on failure
