import pytest

from core import install_manager
from core.install_manager import InstallManager, APP_REGISTRY, CATEGORIES, _ufw_ports_for


class _FakeSSH:
    def __init__(self, connected=True):
        self.connected = connected
        self.calls = []          # list of (kind, cmd) — kind is "run" or "sudo"
        self._routes = {}        # substring -> (out, err, code)
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


class _FakeClock:
    """Stand-in for the time module used by _wait_for_health, so tests
    don't burn real wall-clock seconds waiting out a health-check poll."""
    def __init__(self, start=1_000_000.0):
        self._now = start

    def time(self):
        return self._now

    def sleep(self, secs):
        self._now += secs


@pytest.fixture
def logs():
    entries = []
    def log(text, tag=None):
        entries.append((text, tag))
    log.entries = entries
    return log


def _simple_docker_app(**overrides):
    app = {
        "key": "testapp", "name": "Test App", "category": "Infrastructure",
        "desc": "test", "port": 8080, "container": "testapp",
        "image": "example/testapp:latest", "health_path": "/",
        "install_cmds": ["docker pull example/testapp:latest",
                         "docker run -d --name testapp example/testapp:latest"],
        "fix_cmds": ["docker restart testapp"],
        "reinstall_cmds": ["docker stop testapp", "docker rm testapp",
                          "docker pull example/testapp:latest",
                          "docker run -d --name testapp example/testapp:latest"],
    }
    app.update(overrides)
    return app


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"key", "name", "category", "desc", "port", "container",
                 "image", "health_path", "install_cmds", "fix_cmds", "reinstall_cmds"}


def test_every_registry_entry_has_the_required_keys():
    missing = []
    for app in APP_REGISTRY:
        gap = REQUIRED_KEYS - set(app.keys())
        if gap:
            missing.append((app.get("key", "?"), gap))
    assert not missing, missing


def test_registry_keys_are_unique():
    keys = [app["key"] for app in APP_REGISTRY]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate app keys: {dupes}"


def test_registry_categories_are_all_known():
    bad = [app["key"] for app in APP_REGISTRY if app["category"] not in CATEGORIES]
    assert not bad, f"apps with unrecognized category: {bad}"


def test_apps_with_a_container_have_an_image():
    """A container without a source image can never actually be pulled/run."""
    bad = [app["key"] for app in APP_REGISTRY if app.get("container") and not app.get("image")]
    assert not bad, bad


# ---------------------------------------------------------------------------
# _ufw_ports_for
# ---------------------------------------------------------------------------

def test_ufw_ports_for_uses_explicit_list_when_present():
    app = {"ufw_ports": ["32400/tcp", "32410:32414/udp"], "port": 8080}
    assert _ufw_ports_for(app) == ["32400/tcp", "32410:32414/udp"]


def test_ufw_ports_for_falls_back_to_single_port():
    assert _ufw_ports_for({"port": 8080}) == ["8080/tcp"]


def test_ufw_ports_for_empty_when_no_port_at_all():
    assert _ufw_ports_for({}) == []


# ---------------------------------------------------------------------------
# check_app
# ---------------------------------------------------------------------------

def test_check_app_docker_engine_not_installed():
    ssh = _FakeSSH()
    ssh.route("docker --version", out="not_found")
    im = InstallManager(ssh)
    result = im.check_app({"key": "docker"})
    assert result["state"] == "not_installed"


def test_check_app_docker_engine_running():
    ssh = _FakeSSH()
    ssh.route("docker --version", out="Docker version 27.1.1, build abc123")
    ssh.route("docker info", out="running")
    im = InstallManager(ssh)
    result = im.check_app({"key": "docker"})
    assert result["state"] == "running"
    assert "27.1.1" in result["version"]


def test_check_app_container_running_and_healthy():
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="running|example/testapp:latest|0")
    ssh.route("curl -sf", out="200")
    im = InstallManager(ssh)
    result = im.check_app(_simple_docker_app())
    assert result["state"] == "running"
    assert result["restart_count"] == 0


def test_check_app_container_running_but_unhealthy():
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="running|example/testapp:latest|2")
    ssh.route("curl -sf", out="500")
    im = InstallManager(ssh)
    result = im.check_app(_simple_docker_app())
    assert result["state"] == "unhealthy"
    assert result["restart_count"] == 2


def test_check_app_container_exited_reports_stopped():
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="exited|example/testapp:latest|0")
    im = InstallManager(ssh)
    result = im.check_app(_simple_docker_app())
    assert result["state"] == "stopped"


def test_check_app_falls_back_to_systemd_when_no_container_found():
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="not_found")
    ssh.route("systemctl is-active", out="active")
    im = InstallManager(ssh)
    result = im.check_app({"key": "sonarr", "container": "sonarr",
                           "port": 8989, "health_path": None})
    assert result["state"] == "running"
    assert result["method"] == "service"


def test_check_app_reports_not_installed_when_nothing_found():
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="not_found")
    ssh.route("systemctl is-active", out="")
    im = InstallManager(ssh)
    result = im.check_app({"key": "sonarr", "container": "sonarr",
                           "port": 8989, "health_path": None})
    assert result["state"] == "not_installed"


def test_check_app_binary_tier_via_check_cmd():
    ssh = _FakeSSH()
    ssh.route("which restic", code=0)
    ssh.route("restic version", out="restic 0.16.0")
    im = InstallManager(ssh)
    app = {"key": "restic", "container": None,
          "check_cmd": "which restic", "version_cmd": "restic version"}
    result = im.check_app(app)
    assert result["state"] == "running"
    assert result["method"] == "binary"
    assert result["version"] == "restic 0.16.0"


def test_check_app_binary_tier_not_installed():
    ssh = _FakeSSH()
    ssh.route("which restic", code=1)
    im = InstallManager(ssh)
    app = {"key": "restic", "container": None, "check_cmd": "which restic"}
    result = im.check_app(app)
    assert result["state"] == "not_installed"


def test_check_app_unknown_when_no_container_and_no_check_cmd():
    ssh = _FakeSSH()
    im = InstallManager(ssh)
    result = im.check_app({"key": "mystery", "container": None})
    assert result["state"] == "unknown"


# ---------------------------------------------------------------------------
# _health_check / _wait_for_health
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("http_code,expected", [
    ("200", True), ("301", True), ("400", True), ("401", True), ("403", True),
    ("404", False), ("500", False), ("000", False),
])
def test_health_check_status_code_ranges(http_code, expected):
    ssh = _FakeSSH()
    ssh.route("curl -sf", out=http_code)
    im = InstallManager(ssh)
    assert im._health_check({"port": 8080, "health_path": "/"}) is expected


def test_health_check_trusts_docker_state_without_a_probe_configured():
    ssh = _FakeSSH()
    im = InstallManager(ssh)
    assert im._health_check({"port": None, "health_path": None}) is True


def test_wait_for_health_returns_immediately_on_first_success(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(install_manager.time, "time", clock.time)
    monkeypatch.setattr(install_manager.time, "sleep", clock.sleep)

    ssh = _FakeSSH()
    ssh.route("curl -sf", out="200")
    im = InstallManager(ssh)
    start = clock.time()
    assert im._wait_for_health({"port": 8080, "health_path": "/"}, timeout=8) is True
    assert clock.time() == start  # no polling delay needed


def test_wait_for_health_gives_up_after_timeout(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(install_manager.time, "time", clock.time)
    monkeypatch.setattr(install_manager.time, "sleep", clock.sleep)

    ssh = _FakeSSH()
    ssh.route("curl -sf", out="000")  # never healthy
    im = InstallManager(ssh)
    result = im._wait_for_health({"port": 8080, "health_path": "/"}, timeout=8, interval=2)
    assert result is False


def test_wait_for_health_without_a_probe_just_sleeps_once(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(install_manager.time, "time", clock.time)
    monkeypatch.setattr(install_manager.time, "sleep", clock.sleep)
    start = clock.time()

    ssh = _FakeSSH()
    im = InstallManager(ssh)
    assert im._wait_for_health({"port": None, "health_path": None}, timeout=8) is True
    assert clock.time() == start + 8


# ---------------------------------------------------------------------------
# _run_cmds
# ---------------------------------------------------------------------------

def test_run_cmds_routes_sudo_prefixed_commands_through_run_sudo(logs):
    ssh = _FakeSSH()
    im = InstallManager(ssh)
    ok = im._run_cmds(["echo hi", "sudo systemctl restart docker"], logs)
    assert ok is True
    assert ssh.calls == [
        ("run", "echo hi 2>&1"),
        ("sudo", "systemctl restart docker"),
    ]


def test_run_cmds_stops_at_first_failure(logs):
    ssh = _FakeSSH()
    ssh.route("false", code=1)
    im = InstallManager(ssh)
    ok = im._run_cmds(["true_cmd", "false", "never_runs"], logs)
    assert ok is False
    assert ssh.calls == [("run", "true_cmd 2>&1"), ("run", "false 2>&1")]


# ---------------------------------------------------------------------------
# _open_firewall_ports
# ---------------------------------------------------------------------------

def test_open_firewall_ports_skips_when_ufw_not_present(logs):
    ssh = _FakeSSH()
    ssh.route("which ufw", out="absent")
    im = InstallManager(ssh)
    im._open_firewall_ports(_simple_docker_app(), logs)
    assert not any(c == "sudo" for c, _ in ssh.calls)


def test_open_firewall_ports_skips_when_ufw_inactive(logs):
    ssh = _FakeSSH()
    ssh.route("which ufw", out="present")
    ssh.route("ufw status", out="Status: inactive")
    im = InstallManager(ssh)
    im._open_firewall_ports(_simple_docker_app(), logs)
    assert not any("allow" in cmd for _, cmd in ssh.calls)


def test_open_firewall_ports_opens_when_active(logs):
    ssh = _FakeSSH()
    ssh.route("which ufw", out="present")
    ssh.route("ufw status", out="Status: active")
    im = InstallManager(ssh)
    im._open_firewall_ports(_simple_docker_app(), logs)
    allow_calls = [cmd for kind, cmd in ssh.calls if "ufw allow" in cmd]
    assert allow_calls == ["ufw allow 8080/tcp"]


# ---------------------------------------------------------------------------
# install / start / fix / reinstall / uninstall orchestration
# ---------------------------------------------------------------------------

def test_install_skips_when_already_installed(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="running|example/testapp:latest|0")
    ssh.route("curl -sf", out="200")
    im = InstallManager(ssh)
    result = im.install(_simple_docker_app(), logs)
    assert result is True
    assert not any("docker pull" in cmd for _, cmd in ssh.calls)


def test_install_runs_install_cmds_when_not_installed(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect --format", out="not_found")
    ssh.route("systemctl is-active", out="")
    im = InstallManager(ssh)
    result = im.install(_simple_docker_app(), logs)
    assert result is True
    assert any("docker pull example/testapp:latest" in cmd for _, cmd in ssh.calls)


def test_start_uses_docker_when_container_exists(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect testapp", code=0)
    ssh.route("docker start", code=0)
    im = InstallManager(ssh)
    assert im.start(_simple_docker_app(), logs) is True
    assert any(cmd == "docker start testapp 2>&1" for _, cmd in ssh.calls)


def test_start_falls_back_to_systemctl_when_no_container(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect", code=1)
    ssh.route("systemctl list-unit-files", out="found")
    im = InstallManager(ssh)
    app = {"key": "sonarr", "container": "sonarr"}
    assert im.start(app, logs) is True
    assert any("systemctl start sonarr" in cmd for kind, cmd in ssh.calls if kind == "sudo")


def test_start_fails_when_nothing_found(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect", code=1)
    ssh.route("systemctl list-unit-files", out="no")
    im = InstallManager(ssh)
    assert im.start({"key": "totally-unknown", "container": None}, logs) is False


def test_fix_succeeds_at_tier_1_restart(monkeypatch, logs):
    clock = _FakeClock()
    monkeypatch.setattr(install_manager.time, "time", clock.time)
    monkeypatch.setattr(install_manager.time, "sleep", clock.sleep)

    ssh = _FakeSSH()
    ssh.route("which ufw", out="absent")
    ssh.route("docker restart", code=0)
    ssh.route("curl -sf", out="200")
    im = InstallManager(ssh)
    assert im.fix(_simple_docker_app(), logs) is True
    assert not any("docker pull" in cmd for _, cmd in ssh.calls)  # never reached tier 2


def test_fix_falls_through_to_tier_2_reinstall(monkeypatch, logs):
    clock = _FakeClock()
    monkeypatch.setattr(install_manager.time, "time", clock.time)
    monkeypatch.setattr(install_manager.time, "sleep", clock.sleep)

    ssh = _FakeSSH()
    ssh.route("which ufw", out="absent")
    ssh.route("docker restart", code=0)
    ssh.route("curl -sf", out="000")  # never healthy at any tier
    im = InstallManager(ssh)
    result = im.fix(_simple_docker_app(), logs)
    assert result is False
    assert any("docker pull example/testapp:latest" in cmd for _, cmd in ssh.calls)
    assert any("docker logs --tail=40" in cmd for _, cmd in ssh.calls)  # diagnostic dump


def test_reinstall_pulls_image_then_runs_reinstall_cmds(logs):
    ssh = _FakeSSH()
    ssh.route("which ufw", out="absent")
    im = InstallManager(ssh)
    result = im.reinstall(_simple_docker_app(), logs)
    assert result is True
    # reinstall() explicitly pulls app["image"] itself *and* runs
    # reinstall_cmds, which — matching the real registry's own entries
    # (portainer, watchtower, ...) — typically includes its own "docker
    # pull" step too. A harmless redundant pull, not a bug: docker pull
    # is idempotent, just costs an extra no-op network round trip.
    pull_calls = [cmd for _, cmd in ssh.calls if "docker pull" in cmd]
    assert len(pull_calls) == 2


def test_reinstall_fails_without_reinstall_cmds(logs):
    ssh = _FakeSSH()
    im = InstallManager(ssh)
    result = im.reinstall({"key": "x", "image": "", "reinstall_cmds": []}, logs)
    assert result is False


def test_uninstall_removes_existing_container(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect testapp", code=0)
    ssh.route("docker rm", code=0)
    im = InstallManager(ssh)
    assert im.uninstall(_simple_docker_app(), logs) is True
    assert any(cmd.startswith("docker stop") for _, cmd in ssh.calls)
    assert any(cmd.startswith("docker rm") for _, cmd in ssh.calls)


def test_uninstall_falls_back_to_systemctl_disable(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect", code=1)
    ssh.route("systemctl list-unit-files", out="found")
    ssh.route("systemctl disable --now", code=0)
    im = InstallManager(ssh)
    app = {"key": "sonarr", "container": "sonarr"}
    assert im.uninstall(app, logs) is True


def test_uninstall_fails_when_nothing_found(logs):
    ssh = _FakeSSH()
    ssh.route("docker inspect", code=1)
    ssh.route("systemctl list-unit-files", out="no")
    im = InstallManager(ssh)
    assert im.uninstall({"key": "totally-unknown", "container": None}, logs) is False


def test_check_docker_available():
    ssh = _FakeSSH()
    ssh.route("docker info", out="ok")
    im = InstallManager(ssh)
    assert im.check_docker_available() is True

    ssh2 = _FakeSSH()
    ssh2.route("docker info", out="fail")
    im2 = InstallManager(ssh2)
    assert im2.check_docker_available() is False
