from core.vpn_status import check_vpn_connected


class _FakeSSH:
    def __init__(self):
        self._responses = []

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def test_protonvpn_cli_connected():
    ssh = _FakeSSH()
    ssh._responses = [("Status: Connected\nServer: US-1\n", "", 0)]
    assert check_vpn_connected(ssh) is True


def test_protonvpn_cli_disconnected():
    ssh = _FakeSSH()
    ssh._responses = [("Status: Disconnected\n", "", 0)]
    assert check_vpn_connected(ssh) is False


def test_protonvpn_cli_response_with_no_status_line_is_unknown():
    ssh = _FakeSSH()
    ssh._responses = [("Some unrelated output\n", "", 0)]
    assert check_vpn_connected(ssh) is None


def test_falls_back_to_systemd_when_protonvpn_cli_missing():
    ssh = _FakeSSH()
    ssh._responses = [
        ("bash: protonvpn-cli: command not found", "", 127),
        ("active\n", "", 0),  # systemctl is-active
    ]
    assert check_vpn_connected(ssh) is True


def test_falls_back_to_wireguard_when_no_systemd_unit():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 127),   # no protonvpn-cli
        ("inactive\ninactive\n", "", 0),   # systemctl checks, neither active
        ("interface: wg0\npeer: abc\n", "", 0),  # wg show has output
    ]
    assert check_vpn_connected(ssh) is True


def test_falls_back_to_interface_detection():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 127),
        ("inactive\ninactive\n", "", 0),
        ("", "", 0),  # wg show empty
        ("3: tun0: <POINTOPOINT>\n", "", 0),  # ip addr shows a tun interface
    ]
    assert check_vpn_connected(ssh) is True


def test_no_vpn_tooling_found_at_all_is_disconnected():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 127),
        ("inactive\ninactive\n", "", 0),
        ("", "", 0),
        ("", "", 0),
    ]
    assert check_vpn_connected(ssh) is False
