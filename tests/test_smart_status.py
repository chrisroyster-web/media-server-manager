from core.smart_status import check_smart_health


class _FakeSSH:
    def __init__(self):
        self._responses = []

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


_INFO_OUT = "Device Model:     Samsung SSD 860 EVO\n"
_HEALTH_PASSED = "SMART overall-health self-assessment test result: PASSED\n"
_HEALTH_FAILED = "SMART overall-health self-assessment test result: FAILED!\n"
def _attr_line(attr_id, name, raw_val):
    # Real smartctl -A output is 10 whitespace-separated fields; the parser
    # requires len(parts) >= 10 before it'll even look at attr_id/raw_val.
    return "{:>3} {:<24}0x0033   100   100   010    Pre-fail  Always   -       {}\n".format(
        attr_id, name, raw_val)


_ATTRS_CLEAN = (
    _attr_line(5, "Reallocated_Sector_Ct", 0) +
    _attr_line(197, "Current_Pending_Sector", 0) +
    _attr_line(198, "Offline_Uncorrectable", 0)
)
_ATTRS_BAD = (
    _attr_line(5, "Reallocated_Sector_Ct", 3) +
    _attr_line(197, "Current_Pending_Sector", 0) +
    _attr_line(198, "Offline_Uncorrectable", 0)
)


def test_no_disks_found_returns_empty():
    ssh = _FakeSSH()
    ssh._responses = [("", "", 1)]
    assert check_smart_health(ssh) == []


def test_healthy_drive_reports_passed():
    ssh = _FakeSSH()
    ssh._responses = [
        ("/dev/sda", "", 0),          # lsblk
        (_INFO_OUT, "", 0),            # -i
        (_HEALTH_PASSED, "", 0),       # -H
        (_ATTRS_CLEAN, "", 0),         # -A
    ]
    rows = check_smart_health(ssh)
    assert len(rows) == 1
    assert rows[0]["device"] == "/dev/sda"
    assert rows[0]["health"] == "PASSED"
    assert rows[0]["reallocated"] == "0"


def test_failed_drive_reports_failed():
    ssh = _FakeSSH()
    ssh._responses = [
        ("/dev/sda", "", 0),
        (_INFO_OUT, "", 0),
        (_HEALTH_FAILED, "", 0),
        (_ATTRS_CLEAN, "", 0),
    ]
    rows = check_smart_health(ssh)
    assert rows[0]["health"] == "FAILED"


def test_nonzero_reallocated_sectors_are_captured():
    ssh = _FakeSSH()
    ssh._responses = [
        ("/dev/sda", "", 0),
        (_INFO_OUT, "", 0),
        (_HEALTH_PASSED, "", 0),
        (_ATTRS_BAD, "", 0),
    ]
    rows = check_smart_health(ssh)
    assert rows[0]["reallocated"] == "3"


def test_multiple_devices_each_queried():
    ssh = _FakeSSH()
    ssh._responses = [
        ("/dev/sda\n/dev/sdb", "", 0),
        (_INFO_OUT, "", 0), (_HEALTH_PASSED, "", 0), (_ATTRS_CLEAN, "", 0),
        (_INFO_OUT, "", 0), (_HEALTH_FAILED, "", 0), (_ATTRS_CLEAN, "", 0),
    ]
    rows = check_smart_health(ssh)
    assert len(rows) == 2
    assert rows[0]["device"] == "/dev/sda"
    assert rows[1]["device"] == "/dev/sdb"
    assert rows[0]["health"] == "PASSED"
    assert rows[1]["health"] == "FAILED"


def test_a_probe_exception_is_skipped_not_fatal():
    class _RaisingSSH(_FakeSSH):
        calls = 0
        def run(self, cmd):
            _RaisingSSH.calls += 1
            if _RaisingSSH.calls == 1:
                return ("/dev/sda", "", 0)
            raise RuntimeError("ssh dropped")
    ssh = _RaisingSSH()
    rows = check_smart_health(ssh)
    assert rows == []
