from core.mount_status import check_mounts


class _FakeSSH:
    def __init__(self, response):
        self._response = response

    def run(self, cmd):
        self.last_cmd = cmd
        return (self._response, "", 0)


def test_empty_mount_list_returns_empty_without_running_anything():
    ssh = _FakeSSH("")
    assert check_mounts(ssh, []) == {}
    assert not hasattr(ssh, "last_cmd")


def test_reports_mounted_and_unmounted_paths():
    ssh = _FakeSSH("/|MOUNTED\n/mnt/nas|NOT_MOUNTED\n")
    result = check_mounts(ssh, ["/", "/mnt/nas"])
    assert result == {"/": True, "/mnt/nas": False}


def test_path_with_spaces_round_trips_through_quoting():
    ssh = _FakeSSH("/mnt/nas with space|MOUNTED\n")
    result = check_mounts(ssh, ["/mnt/nas with space"])
    assert result == {"/mnt/nas with space": True}
    # Confirm the path was actually shell-quoted rather than passed raw.
    assert "'/mnt/nas with space'" in ssh.last_cmd


def test_unparseable_line_is_skipped():
    ssh = _FakeSSH("garbage-no-pipe\n/mnt/nas|MOUNTED\n")
    result = check_mounts(ssh, ["/mnt/nas"])
    assert result == {"/mnt/nas": True}
