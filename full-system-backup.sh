#!/bin/bash
# /opt/media/full-system-backup.sh
# Complete server backup to NAS, enough to restore from a bare minimum
# Ubuntu install (see RESTORE.md). Complements backup.sh, which only
# covers known app configs/databases.
#
# Writes ONE tar archive per snapshot rather than mirroring individual files
# onto the NAS share. The wsbackup CIFS mount is configured with
# file_mode=0777,dir_mode=0777,forceuid,forcegid (fine for backup.sh's plain
# `cp -r`, since that script never relied on exact permission fidelity) —
# which means it cannot represent real Unix permissions/ownership on files
# written directly through it at all. A tar archive's *internal* entries
# preserve permissions/ownership/ACLs correctly regardless of what the CIFS
# mount does to the archive file itself; the archive being 0777 on the NAS
# doesn't matter, only what's inside it does. This also avoids the very slow
# per-file CIFS round trips (ACL/xattr queries etc.) that a direct rsync
# mirror of ~260k files incurs — one large sequential write instead.
#
# Runs: Sunday 04:30 via root crontab (edit with: sudo crontab -e)
# Log:  /var/log/media-fullbackup.log

set -uo pipefail

BACKUP_ROOT=/mnt/nas/wsbackup/fullsystem
SNAPSHOT_DIR=$BACKUP_ROOT/$(date +%Y%m%d)
LOG=/var/log/media-fullbackup.log
KEEP_COUNT=8

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Backup started ==="

# --- Verify NAS is mounted --------------------------------------------------
if ! mountpoint -q /mnt/nas/wsbackup; then
    log "ERROR: /mnt/nas/wsbackup is not mounted. Aborting."
    exit 1
fi

errors=0
mkdir -p "$SNAPSHOT_DIR/system-info"
log "Destination: $SNAPSHOT_DIR"

# --- Root filesystem archive -------------------------------------------------
# Explicit top-level dirs rather than "/ minus excludes" — simpler and more
# robust than juggling tar exclude-pattern anchoring. This naturally leaves
# out /boot (archived separately below), /usr (see RESTORE.md — reinstalled
# from the package manifest instead of copying potentially-incompatible old
# binaries), /proc /sys /dev /run /tmp, and anything else not listed.
# --one-file-system still matters here: /opt has a separate mounted disk
# (/opt/media/downloads) nested under it that must not be descended into.
log "-- Root filesystem (tar, one archive, ACLs/xattrs preserved internally)"
set +e
tar --one-file-system --acls --xattrs -czf "$SNAPSHOT_DIR/root.tar.gz" \
    -C / etc home root opt var srv 2>>"$LOG"
rc=$?
set -e
# tar exit 1 ("some files changed while being archived") is expected/benign
# on a live system and not a real failure.
if [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ]; then
    log "  OK  root.tar.gz (exit $rc)"
else
    log "  FAIL root.tar.gz exited $rc"
    errors=$((errors+1))
fi

# --- Boot partitions (kept separate on purpose, see RESTORE.md) ------------
# /boot/efi is mounted under /boot, so one archive covers both.
log "-- Boot partitions"
if tar czf "$SNAPSHOT_DIR/boot.tar.gz" -C / boot 2>>"$LOG"; then
    log "  OK  boot.tar.gz"
else
    log "  FAIL boot.tar.gz"
    errors=$((errors+1))
fi

# --- System manifest (for restore-time package reinstall + reference) ------
log "-- System manifest"
dpkg --get-selections > "$SNAPSHOT_DIR/system-info/dpkg-selections.txt" 2>>"$LOG" \
    && log "  OK  dpkg-selections.txt" || { log "  FAIL dpkg-selections.txt"; errors=$((errors+1)); }
apt-mark showmanual > "$SNAPSHOT_DIR/system-info/apt-manual-packages.txt" 2>>"$LOG" \
    && log "  OK  apt-manual-packages.txt" || { log "  FAIL apt-manual-packages.txt"; errors=$((errors+1)); }
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE > "$SNAPSHOT_DIR/system-info/lsblk.txt" 2>>"$LOG" \
    && log "  OK  lsblk.txt" || log "  SKIP lsblk.txt (command unavailable)"
blkid > "$SNAPSHOT_DIR/system-info/blkid.txt" 2>>"$LOG" \
    && log "  OK  blkid.txt" || log "  SKIP blkid.txt (command unavailable)"
parted -l > "$SNAPSHOT_DIR/system-info/parted.txt" 2>>"$LOG" \
    && log "  OK  parted.txt" || log "  SKIP parted.txt (command unavailable)"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' \
    > "$SNAPSHOT_DIR/system-info/docker-images.txt" 2>>"$LOG" \
    && log "  OK  docker-images.txt" || log "  SKIP docker-images.txt (docker unavailable)"

# --- Retention: keep the most recent KEEP_COUNT snapshots -------------------
# find (not a glob) so a directory with zero/one entries doesn't error out
# under `set -e` + pipefail.
log "-- Pruning to the most recent ${KEEP_COUNT} snapshots"
find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | tail -n +$((KEEP_COUNT+1)) | cut -d' ' -f2- | while read -r old; do
    log "  Removing $old"
    rm -rf "$old"
done

# --- Summary ----------------------------------------------------------------
USED=$(du -sh "$SNAPSHOT_DIR" 2>/dev/null | cut -f1)
if [ "$errors" -eq 0 ]; then
    log "=== Backup completed OK — $USED written to $SNAPSHOT_DIR ==="
else
    log "=== Backup completed with $errors error(s) — check log above ==="
    exit 1
fi
