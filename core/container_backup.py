# core/container_backup.py
"""
Tars a standalone (non-Compose) container's bind-mounted data before
ui/updates_tab.py's best-effort recreate path stops/removes/recreates it,
so a bad recreate (or a corrupting new image version) has something to
restore from. Reuses the exact same info["Mounts"] list UpdatesTab already
reads (from `docker inspect`) to build the recreate's -v flags.
"""

import shlex
import time

# Skip (not fail) any bind mount larger than this rather than tarring it --
# some containers (e.g. an *arr app) bind-mount the actual media library
# alongside a small config dir, and tarring a multi-TB mount on a routine
# update would turn a 10-second operation into a disk-filling one. This is
# meant as a safety net for small stateful config directories, not a full
# data backup.
MAX_MOUNT_BYTES = 5 * 1024 ** 3   # 5 GiB


def backup_container_mounts(ssh, container: str, info: dict,
                             backup_root: str = "/opt/media-backups/recreate",
                             keep: int = 3) -> dict:
    """
    tar czf's each bind-mounted host directory for `container` (from
    info["Mounts"], i.e. docker inspect's own view) into
    <backup_root>/<container>/<timestamp>/mount_N.tar.gz, then prunes
    older timestamp dirs for this container beyond `keep`. Runs via
    ssh.run_sudo -- bind sources like /opt/appdata are frequently
    root-owned.

    Returns {"ok": bool, "backed_up": [...], "skipped": [...],
    "failed": [...], "dir": str, "output": str}. "ok" is False only when a
    mount was actually attempted and failed -- oversized mounts are
    "skipped", not "failed", and don't block the caller. Never raises.
    """
    # Read-only mounts (e.g. netdata's /proc, /sys, /etc/passwd for host
    # introspection) can never be modified by the container, so a recreate
    # can't lose anything there -- and pseudo-filesystems like /sys fail a
    # plain tar anyway (files that shrink between stat and read, permission-
    # denied device nodes), which would otherwise abort the whole update.
    mounts = [m for m in (info.get("Mounts") or [])
              if m.get("Source") and m.get("Destination") and m.get("RW", True)]
    if not mounts:
        return {"ok": True, "backed_up": [], "skipped": [], "failed": [],
                "dir": "", "output": "No bind-mounted data to back up."}

    ts = time.strftime("%Y%m%d-%H%M%S")
    dest_dir = "{}/{}/{}".format(backup_root, container, ts)
    _, mkdir_err, mkdir_code = ssh.run_sudo("mkdir -p {}".format(shlex.quote(dest_dir)))
    if mkdir_code != 0:
        return {"ok": False, "backed_up": [], "skipped": [],
                "failed": [m["Source"] for m in mounts], "dir": dest_dir,
                "output": "mkdir failed: " + (mkdir_err or "")}

    backed_up, skipped, failed, outputs = [], [], [], []
    for i, m in enumerate(mounts):
        src = m["Source"]
        size_out, _, size_code = ssh.run_sudo(
            "du -sb {} 2>/dev/null | cut -f1".format(shlex.quote(src)))
        try:
            size_bytes = int((size_out or "0").strip())
        except ValueError:
            size_bytes = 0
        if size_code == 0 and size_bytes > MAX_MOUNT_BYTES:
            skipped.append(src)
            outputs.append("{}: SKIPPED ({} bytes > {} byte cap)".format(
                src, size_bytes, MAX_MOUNT_BYTES))
            continue

        archive = "{}/mount_{}.tar.gz".format(dest_dir, i)
        parent  = src.rsplit("/", 1)[0] or "/"
        base    = src.rsplit("/", 1)[-1]
        out, err, code = ssh.run_sudo("tar czf {} -C {} {} 2>&1".format(
            shlex.quote(archive), shlex.quote(parent), shlex.quote(base)))
        if code == 0:
            backed_up.append(src)
            outputs.append("{}: ok".format(src))
        else:
            failed.append(src)
            outputs.append("{}: FAILED\n{}".format(src, (out or "") + (err or "")))

    if failed:
        return {"ok": False, "backed_up": backed_up, "skipped": skipped,
                "failed": failed, "dir": dest_dir, "output": "\n".join(outputs)}

    _prune_old_backups(ssh, backup_root, container, keep)
    return {"ok": True, "backed_up": backed_up, "skipped": skipped,
            "failed": [], "dir": dest_dir, "output": "\n".join(outputs)}


def _prune_old_backups(ssh, backup_root: str, container: str, keep: int):
    """Best-effort -- a failed prune never blocks/fails the backup, it just
    leaves an extra old backup dir on disk."""
    base = "{}/{}".format(backup_root, container)
    ssh.run_sudo(
        "ls -1 {} 2>/dev/null | sort | head -n -{} | xargs -I{{}} rm -rf {}/{{}}"
        .format(shlex.quote(base), int(keep), shlex.quote(base)))
