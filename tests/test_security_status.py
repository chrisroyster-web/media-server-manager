from core.security_status import check_fail2ban_total_banned, check_ufw_active


class _FakeSSH:
    """.run() drives `which`/probe commands, .run_sudo() drives the
    privileged fail2ban-client / ufw calls -- matching how the tabs this
    was extracted from actually call them."""

    def __init__(self):
        self._run_responses      = []
        self._run_sudo_responses = []

    def run(self, cmd):
        if self._run_responses:
            return self._run_responses.pop(0)
        return ("", "", 0)

    def run_sudo(self, cmd):
        if self._run_sudo_responses:
            return self._run_sudo_responses.pop(0)
        return ("", "", 1)


# ---------------------------------------------------------------------------
# fail2ban
# ---------------------------------------------------------------------------

def test_fail2ban_not_installed_returns_none():
    ssh = _FakeSSH()
    ssh._run_responses = [("", "", 1)]  # which fail2ban-client fails
    assert check_fail2ban_total_banned(ssh) is None


def test_fail2ban_status_command_fails_returns_none():
    ssh = _FakeSSH()
    ssh._run_responses      = [("/usr/bin/fail2ban-client", "", 0)]
    ssh._run_sudo_responses = [("", "Permission denied", 1)]
    assert check_fail2ban_total_banned(ssh) is None


def test_fail2ban_sums_banned_across_jails():
    ssh = _FakeSSH()
    ssh._run_responses = [("/usr/bin/fail2ban-client", "", 0)]
    ssh._run_sudo_responses = [
        ("Status\n|- Jail list:\tsshd, nginx-http-auth\n", "", 0),
        ("Status for the jail: sshd\n"
         "|- Currently failed:\t2\n"
         "|- Currently banned:\t3\n"
         "|- Total banned:\t10\n", "", 0),
        ("Status for the jail: nginx-http-auth\n"
         "|- Currently failed:\t0\n"
         "|- Currently banned:\t1\n"
         "|- Total banned:\t4\n", "", 0),
    ]
    assert check_fail2ban_total_banned(ssh) == 4


def test_fail2ban_no_jails_returns_zero():
    ssh = _FakeSSH()
    ssh._run_responses = [("/usr/bin/fail2ban-client", "", 0)]
    ssh._run_sudo_responses = [("Status\n|- Jail list:\t\n", "", 0)]
    assert check_fail2ban_total_banned(ssh) == 0


# ---------------------------------------------------------------------------
# ufw
# ---------------------------------------------------------------------------

def test_ufw_active():
    ssh = _FakeSSH()
    ssh._run_sudo_responses = [
        ("Status: active\n\n     To                         Action      From\n", "", 0),
    ]
    assert check_ufw_active(ssh) is True


def test_ufw_inactive():
    ssh = _FakeSSH()
    ssh._run_sudo_responses = [("Status: inactive\n", "", 0)]
    assert check_ufw_active(ssh) is False


def test_ufw_not_installed_returns_none():
    ssh = _FakeSSH()
    ssh._run_sudo_responses = [("", "command not found", 1)]
    assert check_ufw_active(ssh) is None
