# core/storage_health_status.py
"""
ZFS/Btrfs pool (and plain-df fallback) health check, extracted from
ui/storage_health_tab.py so it can run from a background watchdog (main.py's
start_disk_health_watchdog) without any Tk dependency.
"""

import re
import shlex


def check_pool_health(ssh) -> list:
    """
    Returns a list of {"name", "state", "fs"} dicts, one per ZFS pool /
    Btrfs filesystem / (as a fallback, when neither is present) mounted
    filesystem past capacity thresholds. "state" mirrors
    ui/storage_health_tab.py: ONLINE/DEGRADED/WARNING/FAULTED/UNAVAIL/
    REMOVED/CRITICAL/unknown. Never raises -- a probe failure yields no rows.
    """
    try:
        probe, _, _ = ssh.run(
            "command -v zpool 2>/dev/null && echo HAS_ZFS || true;"
            "command -v btrfs 2>/dev/null && echo HAS_BTRFS || true")
    except Exception:
        return []
    has_zfs   = "HAS_ZFS"   in (probe or "")
    has_btrfs = "HAS_BTRFS" in (probe or "")

    pools = []

    if has_zfs:
        out, _, _ = ssh.run(
            "zpool list -H -o name,health,size,alloc,free 2>/dev/null")
        for line in (out or "").strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                name, health = parts[0], parts[1]
                pools.append({"name": name, "state": health, "fs": "zfs"})

    if has_btrfs:
        out, _, _ = ssh.run("sudo btrfs filesystem show 2>/dev/null")
        cur = None
        for line in (out or "").splitlines():
            line = line.strip()
            m = re.match(r"Label: (\S+)\s+uuid: ([0-9a-f-]+)", line)
            if m:
                cur = {"name": m.group(1).strip("'"), "state": "unknown", "fs": "btrfs"}
                pools.append(cur)
            if cur and re.search(r"Total devices (\d+)", line):
                cur["state"] = "ONLINE"

    if not pools:
        out, _, _ = ssh.run("df -hT 2>/dev/null")
        skip_types = {
            "tmpfs", "devtmpfs", "devpts", "sysfs", "proc",
            "cgroup", "cgroup2", "pstore", "bpf", "tracefs",
            "hugetlbfs", "mqueue", "securityfs", "overlay",
            "squashfs", "efivarfs", "debugfs", "fusectl",
            "configfs", "ramfs", "nsfs", "autofs",
        }
        skip_mounts = set()
        pending = ""
        for raw_line in (out or "").splitlines():
            if raw_line.startswith("Filesystem"):
                pending = ""
                continue
            combined = (pending + " " + raw_line).strip() if pending else raw_line
            parts = combined.split()
            if len(parts) < 7:
                pending = combined
                continue
            pending = ""
            fstype = parts[1]
            pct    = parts[5]
            mount  = " ".join(parts[6:])
            if fstype.lower() in skip_types or mount in skip_mounts:
                continue
            skip_prefixes = ("/sys", "/proc", "/dev/shm", "/run", "/snap", "/boot/efi")
            if any(mount.startswith(p) for p in skip_prefixes):
                continue
            skip_mounts.add(mount)
            try:
                pct_int = int(pct.rstrip("%"))
            except ValueError:
                pct_int = 0
            state = "CRITICAL" if pct_int >= 95 else ("WARNING" if pct_int >= 85 else "ONLINE")
            pools.append({"name": mount, "state": state, "fs": "df"})

    return pools
