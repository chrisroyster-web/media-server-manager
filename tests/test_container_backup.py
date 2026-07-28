from core.container_backup import backup_container_mounts, MAX_MOUNT_BYTES


class _FakeSSH:
    def __init__(self):
        self._responses = []  # queue of (out, err, code), consumed in order
        self.commands = []    # every command passed to run_sudo(), in order

    def run_sudo(self, cmd):
        self.commands.append(cmd)
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def _info(mounts):
    return {"Mounts": mounts}


def test_no_mounts_is_a_no_op_ok_result():
    ssh = _FakeSSH()
    result = backup_container_mounts(ssh, "jellyseerr", _info([]))
    assert result == {"ok": True, "backed_up": [], "skipped": [], "failed": [],
                       "dir": "", "output": "No bind-mounted data to back up."}
    assert ssh.commands == []


def test_mkdir_failure_aborts_and_marks_every_mount_failed():
    ssh = _FakeSSH()
    ssh._responses = [("", "permission denied", 1)]
    mounts = [{"Source": "/opt/appdata/jellyseerr", "Destination": "/app/config"}]
    result = backup_container_mounts(ssh, "jellyseerr", _info(mounts))
    assert result["ok"] is False
    assert result["failed"] == ["/opt/appdata/jellyseerr"]
    assert "mkdir failed" in result["output"]


def test_oversized_mount_is_skipped_not_failed():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),                                  # mkdir -p
        (str(MAX_MOUNT_BYTES + 1), "", 0),             # du -sb (over cap)
        ("", "", 0),                                   # prune
    ]
    mounts = [{"Source": "/opt/media/library", "Destination": "/media"}]
    result = backup_container_mounts(ssh, "jellyfin", _info(mounts))
    assert result["ok"] is True
    assert result["skipped"] == ["/opt/media/library"]
    assert result["failed"] == []
    assert result["backed_up"] == []


def test_under_cap_mount_is_tarred_and_backed_up():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),          # mkdir -p
        ("1024", "", 0),      # du -sb (well under cap)
        ("", "", 0),          # tar czf
        ("", "", 0),          # prune
    ]
    mounts = [{"Source": "/opt/appdata/jellyseerr", "Destination": "/app/config"}]
    result = backup_container_mounts(ssh, "jellyseerr", _info(mounts))
    assert result["ok"] is True
    assert result["backed_up"] == ["/opt/appdata/jellyseerr"]
    assert result["skipped"] == []
    assert result["failed"] == []


def test_tar_failure_on_under_cap_mount_flips_ok_false_and_skips_prune():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),                    # mkdir -p
        ("1024", "", 0),                # du -sb
        ("", "tar: write error", 1),    # tar czf fails
    ]
    mounts = [{"Source": "/opt/appdata/jellyseerr", "Destination": "/app/config"}]
    result = backup_container_mounts(ssh, "jellyseerr", _info(mounts))
    assert result["ok"] is False
    assert result["failed"] == ["/opt/appdata/jellyseerr"]
    # No prune call after a failure -- only 3 run_sudo calls total (mkdir,
    # du, tar), not a 4th for pruning.
    assert len(ssh.commands) == 3


def test_prune_command_targets_the_per_container_backup_dir():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),      # mkdir -p
        ("1024", "", 0),  # du -sb
        ("", "", 0),      # tar czf
        ("", "", 0),      # prune
    ]
    mounts = [{"Source": "/opt/appdata/jellyseerr", "Destination": "/app/config"}]
    backup_container_mounts(ssh, "jellyseerr", _info(mounts),
                            backup_root="/opt/media-backups/recreate", keep=3)
    prune_cmd = ssh.commands[-1]
    assert "/opt/media-backups/recreate/jellyseerr" in prune_cmd
    assert "head -n -3" in prune_cmd
    assert "rm -rf" in prune_cmd


def test_mounts_without_source_or_destination_are_ignored():
    ssh = _FakeSSH()
    mounts = [{"Source": "", "Destination": "/app/config"},
              {"Source": "/opt/appdata/x", "Destination": ""}]
    result = backup_container_mounts(ssh, "x", _info(mounts))
    assert result["ok"] is True
    assert result["backed_up"] == result["skipped"] == result["failed"] == []
    assert ssh.commands == []
