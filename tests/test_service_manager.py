from core.service_manager import ServiceManager


class _FakeSSH:
    def __init__(self, connected=True):
        self.connected = connected
        self.run_calls = []
        self.run_sudo_calls = []
        self._run_result = ("", "", 0)
        self._run_sudo_result = ("", "", 0)

    def run(self, cmd):
        self.run_calls.append(cmd)
        return self._run_result

    def run_sudo(self, cmd):
        self.run_sudo_calls.append(cmd)
        return self._run_sudo_result


def test_get_status_returns_unknown_when_not_connected():
    sm = ServiceManager(_FakeSSH(connected=False))
    assert sm.get_status("sonarr") == "unknown"


def test_get_status_maps_systemctl_words_correctly():
    for word, expected in [("active", "running"), ("inactive", "stopped"),
                            ("failed", "failed"), ("activating", "unknown")]:
        ssh = _FakeSSH()
        ssh._run_result = (word, "", 0)
        sm = ServiceManager(ssh)
        assert sm.get_status("sonarr") == expected


def test_get_status_does_not_substring_match_active_inside_inactive():
    """'active' is literally a substring of 'inactive' — a naive `in`
    check would misreport every stopped service as running."""
    ssh = _FakeSSH()
    ssh._run_result = ("inactive", "", 3)
    sm = ServiceManager(ssh)
    assert sm.get_status("sonarr") == "stopped"


def test_get_status_quotes_the_service_name():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.get_status("weird; rm -rf /")
    assert "'weird; rm -rf /'" in ssh.run_calls[0]
    assert ssh.run_calls[0].startswith("systemctl is-active ")


def test_get_statuses_batches_into_one_round_trip():
    ssh = _FakeSSH()
    ssh._run_result = ("active\ninactive\nfailed\n", "", 0)
    sm = ServiceManager(ssh)
    result = sm.get_statuses(["sonarr", "radarr", "prowlarr"])
    assert result == {"sonarr": "running", "radarr": "stopped", "prowlarr": "failed"}
    assert len(ssh.run_calls) == 1


def test_get_statuses_handles_missing_trailing_lines():
    """If systemctl returns fewer lines than services requested (can
    happen if the output gets truncated), missing ones read as unknown
    rather than crashing on an index error."""
    ssh = _FakeSSH()
    ssh._run_result = ("active\n", "", 0)
    sm = ServiceManager(ssh)
    result = sm.get_statuses(["sonarr", "radarr"])
    assert result == {"sonarr": "running", "radarr": "unknown"}


def test_get_statuses_when_not_connected():
    sm = ServiceManager(_FakeSSH(connected=False))
    assert sm.get_statuses(["sonarr", "radarr"]) == {
        "sonarr": "unknown", "radarr": "unknown"}


def test_start_kills_orphans_before_starting():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.start("sonarr")
    assert len(ssh.run_sudo_calls) == 2
    assert "pkill" in ssh.run_sudo_calls[0]
    assert ssh.run_sudo_calls[1] == "systemctl start sonarr"


def test_start_when_not_connected():
    sm = ServiceManager(_FakeSSH(connected=False))
    assert sm.start("sonarr") == ("", "Not connected", 1)


def test_stop_also_kills_orphans_after_stopping():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.stop("sonarr")
    assert ssh.run_sudo_calls[0] == "systemctl stop sonarr"
    assert "pkill" in ssh.run_sudo_calls[1]


def test_restart_stops_kills_orphans_then_starts():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.restart("sonarr")
    assert ssh.run_sudo_calls[0] == "systemctl stop sonarr"
    assert "pkill" in ssh.run_sudo_calls[1]
    assert ssh.run_sudo_calls[2] == "systemctl start sonarr"


def test_logs_uses_plain_run_not_sudo():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.logs("sonarr", lines=50)
    assert ssh.run_calls[0] == "journalctl -u sonarr -n 50 --no-pager"
    assert ssh.run_sudo_calls == []


def test_full_status_uses_sudo():
    ssh = _FakeSSH()
    sm = ServiceManager(ssh)
    sm.full_status("sonarr")
    assert ssh.run_sudo_calls[0] == "systemctl status sonarr --no-pager"
