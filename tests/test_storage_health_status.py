from core.storage_health_status import check_pool_health


class _FakeSSH:
    def __init__(self):
        self._responses = []

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def test_no_zfs_no_btrfs_falls_back_to_df():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),  # probe: neither zpool nor btrfs found
        ("Filesystem     Type  Size  Used Avail Use% Mounted on\n"
         "/dev/sda1      ext4   100G   50G   45G  53% /\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert len(pools) == 1
    assert pools[0]["name"] == "/"
    assert pools[0]["state"] == "ONLINE"
    assert pools[0]["fs"] == "df"


def test_df_fallback_flags_near_full_disk_as_critical():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),
        ("Filesystem     Type  Size  Used Avail Use% Mounted on\n"
         "/dev/sda1      ext4   100G   97G    3G  97% /\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert pools[0]["state"] == "CRITICAL"


def test_df_fallback_flags_mostly_full_disk_as_warning():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),
        ("Filesystem     Type  Size  Used Avail Use% Mounted on\n"
         "/dev/sda1      ext4   100G   88G   12G  88% /\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert pools[0]["state"] == "WARNING"


def test_df_fallback_skips_pseudo_filesystems():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),
        ("Filesystem     Type    Size  Used Avail Use% Mounted on\n"
         "tmpfs          tmpfs    16G     0   16G   0% /dev/shm\n"
         "/dev/sda1      ext4    100G   50G   45G  53% /\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert len(pools) == 1
    assert pools[0]["name"] == "/"


def test_zfs_pool_healthy():
    ssh = _FakeSSH()
    ssh._responses = [
        ("HAS_ZFS", "", 0),  # probe
        ("tank\tONLINE\t1T\t500G\t500G\n", "", 0),  # zpool list
    ]
    pools = check_pool_health(ssh)
    assert len(pools) == 1
    assert pools[0]["name"]  == "tank"
    assert pools[0]["state"] == "ONLINE"
    assert pools[0]["fs"]    == "zfs"


def test_zfs_pool_degraded():
    ssh = _FakeSSH()
    ssh._responses = [
        ("HAS_ZFS", "", 0),
        ("tank\tDEGRADED\t1T\t500G\t500G\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert pools[0]["state"] == "DEGRADED"


def test_btrfs_filesystem_reported_online():
    ssh = _FakeSSH()
    ssh._responses = [
        ("HAS_BTRFS", "", 0),  # probe
        ("Label: 'storage'  uuid: 1234-5678-abcd\n"
         "\tTotal devices 2 FS bytes used 100.00GiB\n"
         "\tdevid    1 size 500.00GiB used 100.00GiB path /dev/sdb\n", "", 0),
    ]
    pools = check_pool_health(ssh)
    assert len(pools) == 1
    assert pools[0]["name"] == "storage"
    assert pools[0]["state"] == "ONLINE"
    assert pools[0]["fs"]   == "btrfs"


def test_probe_failure_returns_empty():
    class _RaisingSSH(_FakeSSH):
        def run(self, cmd):
            raise RuntimeError("ssh dropped")
    assert check_pool_health(_RaisingSSH()) == []
