# core/lvm_status.py
"""
Checks for stranded/unallocated free space sitting in an LVM volume group,
for main.py's start_lvm_free_space_watchdog(). A plain `df -h` check never
catches this: the affected filesystems all report fine, because the problem
is space that was never turned into a filesystem in the first place.

This is exactly what happened during the 2026-08-24 MS-01 migration --
rebuild-server.sh restored /etc/fstab faithfully, but that only brings back
a line referencing the OLD box's logical volume UUID, which doesn't exist
on the fresh disk. Nothing failed loudly: /opt/media/downloads just quietly
became an ordinary directory inside the small root LV again, while 850GB of
a 951GB drive sat unallocated until someone happened to run `vgs`.
rebuild-server.sh's Phase 3.5 now fixes this automatically during a restore,
but this watchdog catches the same failure mode happening any other way
(a manual lvcreate that never got mounted, a botched migration, etc.).
"""

DEFAULT_THRESHOLD_GB = 5.0  # matches rebuild-server.sh's Phase 3.5 threshold


def check_vg_free_space(ssh, threshold_gb=DEFAULT_THRESHOLD_GB) -> list:
    """
    Returns a list of {"vg", "free_gb", "bad"} dicts, one per volume group
    reported by `vgs`. "bad" is True when more than threshold_gb sits
    unallocated. Never raises -- a probe failure (no LVM on this box, vgs
    not installed, SSH hiccup) just yields an empty list, same as no VGs
    existing.
    """
    out, _, code = ssh.run(
        "vgs --noheadings -o vg_name,vg_free --units g --nosuffix 2>/dev/null"
    )
    if code != 0 or not (out or "").strip():
        return []

    rows = []
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        vg_name, free_str = parts
        try:
            free_gb = float(free_str)
        except ValueError:
            continue
        rows.append({
            "vg": vg_name,
            "free_gb": free_gb,
            "bad": free_gb > threshold_gb,
        })
    return rows
