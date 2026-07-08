import hashlib
import json
import urllib.error
from unittest.mock import MagicMock, patch

from core import updater


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_is_configured_false_for_placeholder_repo(monkeypatch):
    monkeypatch.setattr(updater, "GITHUB_REPO", "your-github-org/your-repo")
    assert updater.is_configured() is False


def test_is_configured_false_without_a_slash(monkeypatch):
    monkeypatch.setattr(updater, "GITHUB_REPO", "notarepo")
    assert updater.is_configured() is False


def test_is_configured_true_for_a_real_looking_repo(monkeypatch):
    monkeypatch.setattr(updater, "GITHUB_REPO", "chrisroyster/all-clear-server-services")
    assert updater.is_configured() is True


def test_parse_version_handles_v_prefix_and_extra_components():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.2.3") == (1, 2, 3)
    assert updater.parse_version("2.0.0.1") == (2, 0, 0)


def test_parse_version_returns_zero_tuple_on_garbage():
    assert updater.parse_version("not-a-version") == (0, 0, 0)
    assert updater.parse_version("") == (0, 0, 0)


def test_is_newer_compares_semantically_not_lexically():
    assert updater.is_newer("v2.0.0", "v1.9.9") is True
    assert updater.is_newer("v1.10.0", "v1.9.0") is True  # 10 > 9 numerically
    assert updater.is_newer("v1.0.0", "v1.0.0") is False
    assert updater.is_newer("v1.0.0", "v2.0.0") is False


def test_find_installer_asset_returns_first_exe():
    release = {"assets": [
        {"name": "checksums.txt"},
        {"name": "AllClearServerServices_v3.0.0_Setup.exe"},
        {"name": "readme.md"},
    ]}
    asset = updater.find_installer_asset(release)
    assert asset["name"] == "AllClearServerServices_v3.0.0_Setup.exe"


def test_find_installer_asset_returns_none_when_no_exe():
    assert updater.find_installer_asset({"assets": [{"name": "readme.md"}]}) is None
    assert updater.find_installer_asset({}) is None


# ---------------------------------------------------------------------------
# check_latest_release() — network mocked
# ---------------------------------------------------------------------------

def test_check_latest_release_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(updater, "GITHUB_REPO", "your-github-org/your-repo")
    assert updater.check_latest_release() is None


def test_check_latest_release_parses_json_response(monkeypatch):
    monkeypatch.setattr(updater, "is_configured", lambda: True)
    payload = json.dumps({"tag_name": "v3.1.0", "assets": []}).encode()
    fake_resp = MagicMock()
    fake_resp.read.return_value = payload
    fake_resp.__enter__.return_value = fake_resp
    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = updater.check_latest_release()
    assert result["tag_name"] == "v3.1.0"


def test_check_latest_release_returns_none_on_network_error(monkeypatch):
    monkeypatch.setattr(updater, "is_configured", lambda: True)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
        assert updater.check_latest_release() is None


def test_check_latest_release_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(updater, "is_configured", lambda: True)
    fake_resp = MagicMock()
    fake_resp.read.return_value = b"not json"
    fake_resp.__enter__.return_value = fake_resp
    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert updater.check_latest_release() is None


# ---------------------------------------------------------------------------
# download_to_temp() — network mocked
# ---------------------------------------------------------------------------

def _fake_response(content: bytes, headers=None):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.headers = headers or {}
    chunks = [content[i:i + updater._CHUNK] for i in range(0, len(content), updater._CHUNK)] or [b""]
    resp.read.side_effect = chunks + [b""]
    return resp


def test_download_to_temp_writes_file_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    content = b"fake installer bytes"
    progress_calls = []
    with patch("urllib.request.urlopen", return_value=_fake_response(content)):
        result = updater.download_to_temp(
            "http://example.com/installer.exe",
            on_progress=lambda done, total: progress_calls.append((done, total)))

    assert result is not None
    assert progress_calls
    with open(result, "rb") as f:
        assert f.read() == content


def test_download_to_temp_verifies_sha256_and_accepts_matching_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    content = b"installer content for hashing"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    with patch("urllib.request.urlopen", return_value=_fake_response(content)):
        result = updater.download_to_temp(
            "http://example.com/installer.exe", expected_digest=digest)

    assert result is not None


def test_download_to_temp_rejects_mismatched_digest_and_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    content = b"installer content"
    wrong_digest = "sha256:" + ("0" * 64)
    errors = []

    with patch("urllib.request.urlopen", return_value=_fake_response(content)):
        result = updater.download_to_temp(
            "http://example.com/installer.exe", expected_digest=wrong_digest,
            on_error=lambda msg: errors.append(msg))

    assert result is None
    assert errors
    assert "integrity check" in errors[0]
    assert not (tmp_path / "AllClearServerServices_Update.exe").exists()


def test_download_to_temp_returns_none_and_calls_on_error_on_network_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    errors = []
    with patch("urllib.request.urlopen", side_effect=OSError("connection reset")):
        result = updater.download_to_temp(
            "http://example.com/installer.exe", on_error=lambda msg: errors.append(msg))
    assert result is None
    assert errors == ["Download failed."]
