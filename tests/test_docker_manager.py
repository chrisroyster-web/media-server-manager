from core.docker_manager import DockerManager


class _FakeSSH:
    def __init__(self, connected=True):
        self.connected = connected
        self.run_calls = []
        self.run_sudo_calls = []
        self._responses = []  # list of (out, err, code), consumed in order

    def run(self, cmd):
        self.run_calls.append(cmd)
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)

    def run_sudo(self, cmd):
        self.run_sudo_calls.append(cmd)
        return ("", "", 0)


def test_get_status_when_not_connected():
    dm = DockerManager(_FakeSSH(connected=False))
    assert dm.get_status("sonarr") == "unknown"


def test_get_status_not_installed_on_nonzero_exit():
    ssh = _FakeSSH()
    ssh._responses = [("", "no such container", 1)]
    dm = DockerManager(ssh)
    assert dm.get_status("sonarr") == "not_installed"


def test_get_status_paused():
    ssh = _FakeSSH()
    ssh._responses = [("paused\n", "", 0)]
    dm = DockerManager(ssh)
    assert dm.get_status("sonarr") == "paused"


def test_get_status_running_without_schedule_env():
    ssh = _FakeSSH()
    ssh._responses = [("running\n", "", 0), ("PATH=/usr/bin|HOME=/root|", "", 0)]
    dm = DockerManager(ssh)
    assert dm.get_status("sonarr") == "running"


def test_get_status_exited_reports_stopped():
    ssh = _FakeSSH()
    ssh._responses = [("exited\n", "", 0), ("PATH=/usr/bin|", "", 0)]
    dm = DockerManager(ssh)
    assert dm.get_status("sonarr") == "stopped"


def test_get_status_detects_watchtower_schedule_env_var():
    ssh = _FakeSSH()
    ssh._responses = [
        ("running\n", "", 0),
        ("WATCHTOWER_SCHEDULE=0 0 3 * * *|PATH=/usr/bin|", "", 0),
    ]
    dm = DockerManager(ssh)
    assert dm.get_status("watchtower") == "scheduled"


def test_get_status_detects_schedule_regardless_of_running_or_exited():
    ssh = _FakeSSH()
    ssh._responses = [
        ("exited\n", "", 0),
        ("CRON=* * * * *|", "", 0),
    ]
    dm = DockerManager(ssh)
    assert dm.get_status("some-cron-container") == "scheduled"


def test_get_statuses_when_not_connected_or_empty():
    dm = DockerManager(_FakeSSH(connected=False))
    assert dm.get_statuses(["a", "b"]) == {"a": "unknown", "b": "unknown"}
    dm2 = DockerManager(_FakeSSH())
    assert dm2.get_statuses([]) == {}


def test_get_statuses_parses_batched_output():
    ssh = _FakeSSH()
    ssh._responses = [(
        "/sonarr|running|PATH=/usr/bin;\n"
        "/radarr|exited|PATH=/usr/bin;\n"
        "/watchtower|running|WATCHTOWER_SCHEDULE=0 0 3 * * *;\n",
        "", 0,
    )]
    dm = DockerManager(ssh)
    result = dm.get_statuses(["sonarr", "radarr", "watchtower"])
    assert result == {
        "sonarr": "running", "radarr": "stopped", "watchtower": "scheduled",
    }


def test_get_statuses_marks_missing_containers_as_not_installed():
    ssh = _FakeSSH()
    ssh._responses = [("/sonarr|running|PATH=/usr/bin;\n", "", 0)]
    dm = DockerManager(ssh)
    result = dm.get_statuses(["sonarr", "ghost-container"])
    assert result["sonarr"] == "running"
    assert result["ghost-container"] == "not_installed"


def test_get_statuses_handles_paused_container():
    ssh = _FakeSSH()
    ssh._responses = [("/sonarr|paused|;\n", "", 0)]
    dm = DockerManager(ssh)
    assert dm.get_statuses(["sonarr"]) == {"sonarr": "paused"}


def test_start_stop_restart_use_sudo_and_quote_the_name():
    ssh = _FakeSSH()
    dm = DockerManager(ssh)
    dm.start("my container")
    dm.stop("my container")
    dm.restart("my container")
    assert ssh.run_sudo_calls == [
        "docker start 'my container'",
        "docker stop 'my container'",
        "docker restart 'my container'",
    ]


def test_start_when_not_connected():
    dm = DockerManager(_FakeSSH(connected=False))
    assert dm.start("sonarr") == "Not connected"


def test_logs_uses_plain_run():
    ssh = _FakeSSH()
    dm = DockerManager(ssh)
    dm.logs("sonarr", lines=100)
    assert ssh.run_calls[0] == "docker logs --tail 100 sonarr"


def test_list_containers_parses_lines():
    ssh = _FakeSSH()
    ssh._responses = [("sonarr\nradarr\n\n", "", 0)]
    dm = DockerManager(ssh)
    assert dm.list_containers() == ["sonarr", "radarr"]


def test_list_containers_returns_empty_on_failure():
    ssh = _FakeSSH()
    ssh._responses = [("", "docker not found", 1)]
    dm = DockerManager(ssh)
    assert dm.list_containers() == []


def test_list_containers_when_not_connected():
    dm = DockerManager(_FakeSSH(connected=False))
    assert dm.list_containers() == []


def test_pull_resolves_image_then_pulls_it():
    ssh = _FakeSSH()
    ssh._responses = [("lscr.io/linuxserver/sonarr\n", "", 0), ("pulled ok\n", "", 0)]
    dm = DockerManager(ssh)
    out, err, code = dm.pull("sonarr")
    assert "docker pull lscr.io/linuxserver/sonarr" in ssh.run_calls[1]
    assert out == "pulled ok\n"


def test_pull_fails_gracefully_when_image_cannot_be_determined():
    ssh = _FakeSSH()
    ssh._responses = [("", "", 1)]
    dm = DockerManager(ssh)
    out, err, code = dm.pull("ghost")
    assert code == 1
    assert "Cannot determine image" in err


def test_prune_images_and_volumes():
    ssh = _FakeSSH()
    dm = DockerManager(ssh)
    dm.prune_images()
    dm.prune_volumes()
    assert ssh.run_calls == [
        "docker image prune -f 2>&1",
        "docker volume prune -f 2>&1",
    ]


def test_list_images_parses_and_matches_layer_counts():
    ssh = _FakeSSH()
    ssh._responses = [
        ("sonarr|latest|abcdef123456|500MB|3 weeks ago\n", "", 0),
        ("sha256:abcdef123456789012345678901234567890123456789012345678901234|42\n", "", 0),
    ]
    dm = DockerManager(ssh)
    images = dm.list_images()
    assert len(images) == 1
    assert images[0]["repo"] == "sonarr"
    assert images[0]["tag"] == "latest"
    assert images[0]["layers"] == "42"


def test_list_images_when_not_connected():
    dm = DockerManager(_FakeSSH(connected=False))
    assert dm.list_images() == []


def test_list_images_returns_empty_list_without_a_second_round_trip():
    ssh = _FakeSSH()
    ssh._responses = [("", "", 0)]
    dm = DockerManager(ssh)
    assert dm.list_images() == []
    assert len(ssh.run_calls) == 1  # no pointless layer-count lookup for zero images
