from core.lvm_status import check_vg_free_space


class _FakeSSH:
    def __init__(self, response, code=0):
        self._response = response
        self._code = code

    def run(self, cmd):
        self.last_cmd = cmd
        return (self._response, "", self._code)


def test_no_lvm_returns_empty():
    ssh = _FakeSSH("", code=1)
    assert check_vg_free_space(ssh) == []


def test_empty_output_returns_empty():
    ssh = _FakeSSH("")
    assert check_vg_free_space(ssh) == []


def test_small_free_space_is_not_flagged_bad():
    ssh = _FakeSSH("ubuntu-vg 2.10\n")
    rows = check_vg_free_space(ssh)
    assert rows == [{"vg": "ubuntu-vg", "free_gb": 2.10, "bad": False}]


def test_large_free_space_is_flagged_bad():
    ssh = _FakeSSH("ubuntu-vg 850.82\n")
    rows = check_vg_free_space(ssh)
    assert rows == [{"vg": "ubuntu-vg", "free_gb": 850.82, "bad": True}]


def test_custom_threshold_is_respected():
    ssh = _FakeSSH("ubuntu-vg 10.0\n")
    rows = check_vg_free_space(ssh, threshold_gb=20.0)
    assert rows[0]["bad"] is False


def test_multiple_volume_groups():
    ssh = _FakeSSH("ubuntu-vg 850.82\ndata-vg 1.0\n")
    rows = check_vg_free_space(ssh)
    assert len(rows) == 2
    assert rows[0] == {"vg": "ubuntu-vg", "free_gb": 850.82, "bad": True}
    assert rows[1] == {"vg": "data-vg", "free_gb": 1.0, "bad": False}


def test_unparseable_line_is_skipped():
    ssh = _FakeSSH("garbage line here\nubuntu-vg 850.82\n")
    rows = check_vg_free_space(ssh)
    assert rows == [{"vg": "ubuntu-vg", "free_gb": 850.82, "bad": True}]
