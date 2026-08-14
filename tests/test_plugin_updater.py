import pytest

from core import plugin_updater


class _FakeSSH:
    """Same shape as the one in test_install_manager.py."""
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
        self.calls.append(("run", cmd))
        return self._resolve(cmd)

    def run_sudo(self, cmd):
        self.calls.append(("sudo", cmd))
        return self._resolve(cmd)


class _FakeConfigManager:
    def __init__(self, host="192.168.4.252", port="8096", apikey="testkey"):
        self.emby_host = host
        self.emby_port = port
        self.emby_apikey = apikey


@pytest.fixture
def logs():
    entries = []
    def log(text, tag=None):
        entries.append((text, tag))
    log.entries = entries
    return log


# ── version comparison ──────────────────────────────────────────────────────

@pytest.mark.parametrize("installed,latest,expected", [
    ("0.2.0.0", "0.4.1", True),        # real bug this feature was built for
    ("0.4.1.0", "0.4.1", False),       # Emby's trailing .0 isn't a real diff
    ("0.4.1", "0.4.1", False),
    ("0.4.1", "0.4.0", False),         # installed newer than latest tag
    ("1.0.0", "1.0.0.1", True),
    ("", "0.4.1", False),              # unknown installed version
    ("0.4.1", "", False),              # unknown latest version
])
def test_is_update_available(installed, latest, expected):
    assert plugin_updater.is_update_available(installed, latest) is expected


# ── check() ──────────────────────────────────────────────────────────────────

def test_check_no_api_key():
    cfg = _FakeConfigManager(apikey="")
    result = plugin_updater.check(cfg)
    assert result["error"] == "No Emby API key configured"
    assert result["update_available"] is False


def test_check_reports_update_available(monkeypatch):
    monkeypatch.setattr(plugin_updater, "get_installed_version", lambda h, p, k: "0.2.0.0")
    monkeypatch.setattr(plugin_updater, "get_latest_version", lambda: "0.4.1")
    result = plugin_updater.check(_FakeConfigManager())
    assert result == {
        "installed": "0.2.0.0", "latest": "0.4.1",
        "update_available": True, "error": None,
    }


def test_check_up_to_date(monkeypatch):
    monkeypatch.setattr(plugin_updater, "get_installed_version", lambda h, p, k: "0.4.1.0")
    monkeypatch.setattr(plugin_updater, "get_latest_version", lambda: "0.4.1")
    result = plugin_updater.check(_FakeConfigManager())
    assert result["update_available"] is False
    assert result["error"] is None


def test_check_plugin_not_installed(monkeypatch):
    monkeypatch.setattr(plugin_updater, "get_installed_version", lambda h, p, k: "")
    monkeypatch.setattr(plugin_updater, "get_latest_version", lambda: "0.4.1")
    result = plugin_updater.check(_FakeConfigManager())
    assert "not installed" in result["error"]


def test_check_github_unreachable(monkeypatch):
    monkeypatch.setattr(plugin_updater, "get_installed_version", lambda h, p, k: "0.4.1.0")
    monkeypatch.setattr(plugin_updater, "get_latest_version", lambda: "")
    result = plugin_updater.check(_FakeConfigManager())
    assert "GitHub" in result["error"]
    assert result["installed"] == "0.4.1.0"


# ── get_installed_version() / get_latest_version() ─────────────────────────

def test_get_installed_version_no_apikey_short_circuits(monkeypatch):
    # Should never hit the network when there's no key to auth with.
    def _boom(*a, **k):
        raise AssertionError("should not be called")
    monkeypatch.setattr(plugin_updater, "_http_json", _boom)
    assert plugin_updater.get_installed_version("host", "8096", "") == ""


def test_get_installed_version_matches_by_name_hint(monkeypatch):
    monkeypatch.setattr(plugin_updater, "_http_json", lambda url, headers=None, timeout=8: [
        {"Name": "TheTVDB", "Version": "1.6.6.0"},
        {"Name": "Tracearr SSE", "Version": "0.4.1.0"},
    ])
    assert plugin_updater.get_installed_version("host", "8096", "key") == "0.4.1.0"


def test_get_installed_version_not_found(monkeypatch):
    monkeypatch.setattr(plugin_updater, "_http_json", lambda url, headers=None, timeout=8: [
        {"Name": "TheTVDB", "Version": "1.6.6.0"},
    ])
    assert plugin_updater.get_installed_version("host", "8096", "key") == ""


def test_get_installed_version_network_error_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise OSError("unreachable")
    monkeypatch.setattr(plugin_updater, "_http_json", _boom)
    assert plugin_updater.get_installed_version("host", "8096", "key") == ""


def test_get_latest_version_strips_v_prefix(monkeypatch):
    monkeypatch.setattr(plugin_updater, "_http_json",
                         lambda url, headers=None, timeout=8: {"tag_name": "v0.4.1"})
    assert plugin_updater.get_latest_version() == "0.4.1"


def test_get_latest_version_network_error_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise OSError("unreachable")
    monkeypatch.setattr(plugin_updater, "_http_json", _boom)
    assert plugin_updater.get_latest_version() == ""


# ── update() ─────────────────────────────────────────────────────────────────

def test_update_happy_path(logs):
    ssh = _FakeSSH()
    ssh.route("curl -sL -f -o", code=0)
    ssh.route("unzip -o -q", code=0)
    ssh.route("cp /var/lib/emby/plugins", code=0)   # backup step
    ssh.route("cp /tmp/tracearr_sse_emby_update", code=0)  # install step
    ssh.route("systemctl restart emby-server", code=0)

    ok = plugin_updater.update(ssh, "0.4.1", logs)

    assert ok is True
    ran = [cmd for _, cmd in ssh.calls]
    assert any("Tracearr.Sse.Emby_0.4.1.zip" in c for c in ran)
    assert any("v0.4.1/Tracearr.Sse.Emby_0.4.1.zip" in c for c in ran)  # correct release URL shape
    assert any(k == "sudo" and "systemctl restart emby-server" in c for k, c in ssh.calls)
    assert any("✓ Plugin updated" in text for text, _ in logs.entries)


def test_update_download_failure_aborts(logs):
    ssh = _FakeSSH()
    ssh.route("curl -sL -f -o", err="curl: (22) 404", code=22)

    ok = plugin_updater.update(ssh, "0.4.1", logs)

    assert ok is False
    # Should not have gone on to extract or restart Emby.
    assert not any("unzip" in c for _, c in ssh.calls)
    assert not any("systemctl restart" in c for _, c in ssh.calls)


def test_update_extract_failure_aborts(logs):
    ssh = _FakeSSH()
    ssh.route("curl -sL -f -o", code=0)
    ssh.route("unzip -o -q", err="bad zip", code=1)

    ok = plugin_updater.update(ssh, "0.4.1", logs)

    assert ok is False
    assert not any("systemctl restart" in c for _, c in ssh.calls)


def test_update_backup_failure_is_non_fatal(logs):
    """A missing prior DLL to back up (e.g. first-ever install) shouldn't
    block the update — only the install/restart steps are fatal."""
    ssh = _FakeSSH()
    ssh.route("curl -sL -f -o", code=0)
    ssh.route("unzip -o -q", code=0)
    ssh.route("cp /var/lib/emby/plugins", err="No such file", code=1)  # backup
    ssh.route("cp /tmp/tracearr_sse_emby_update", code=0)              # install
    ssh.route("systemctl restart emby-server", code=0)

    ok = plugin_updater.update(ssh, "0.4.1", logs)

    assert ok is True


def test_update_restart_failure_aborts(logs):
    ssh = _FakeSSH()
    ssh.route("curl -sL -f -o", code=0)
    ssh.route("unzip -o -q", code=0)
    ssh.route("cp /var/lib/emby/plugins", code=0)
    ssh.route("cp /tmp/tracearr_sse_emby_update", code=0)
    ssh.route("systemctl restart emby-server", err="unit not found", code=1)

    ok = plugin_updater.update(ssh, "0.4.1", logs)

    assert ok is False
    assert any("Restart failed" in text for text, tag in logs.entries if tag == "error")
