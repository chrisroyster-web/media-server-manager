# core/mount_status.py
"""
Checks whether configured storage paths are still actual mount points, for
main.py's start_mount_watchdog(). A silently-dropped NFS/SMB mount doesn't
look like a failure to a plain `df` check -- the path is still a valid
directory, just one that has quietly fallen back to the underlying local
filesystem, so downloads/*arr apps keep writing there (and can fill the
root disk) without anything ever reporting the path as missing.
`mountpoint -q` is the actual signal: it fails once a path is no longer a
distinct mounted filesystem.
"""

import shlex


def check_mounts(ssh, mounts) -> dict:
    """
    mounts: iterable of configured paths (e.g. config_manager.get_storage_mounts()).
    Returns {path: True/False} -- True if still a real mount point.
    A path that can't be checked (SSH error, etc.) is omitted rather than
    reported as unmounted, so a transient SSH hiccup can't look like a drop.
    """
    if not mounts:
        return {}

    checks = " ; ".join(
        'if mountpoint -q {0}; then echo {0}"|MOUNTED"; else echo {0}"|NOT_MOUNTED"; fi'.format(
            shlex.quote(m))
        for m in mounts
    )
    out, _, _ = ssh.run(checks)

    result = {}
    for line in (out or "").splitlines():
        path, _, state = line.rpartition("|")
        if path:
            result[path] = (state == "MOUNTED")
    return result
