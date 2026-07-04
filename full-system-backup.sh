#!/bin/bash
# /opt/media/full-system-backup.sh
# Complete server backup to NAS, enough to restore from a bare minimum
# Ubuntu install (see RESTORE.md). Complements backup.sh, which only
# covers known app configs/databases.
#
# Backs up into a restic repository on the NAS rather than writing a plain
# tar archive: restic encrypts everything at rest (a plain tar of /etc would
# otherwise carry NAS credentials, API keys, and TLS private keys in the
# clear onto the NAS), deduplicates across weekly runs, and only transfers
# the bytes that changed instead of a full archive every time.
#
# Requires /home/mediasvr/.restic-password and an already-initialized repo
# — set both up once from the Backup tab's "Save & Init Repo" button before
# this script can run. It deliberately does not apt-install restic or
# auto-init the repo itself, so a misconfigured cron run fails loudly
# instead of silently bootstrapping a repo with the wrong password.
#
# The password file lives under the SSH login user's home, not /root, even
# though this script runs as root via cron: root can read it there fine
# (root bypasses permission checks), and it's the same path
# ui/backup_tab.py's unprivileged status-refresh code reads via `~` — that
# code never uses sudo, so a copy under /root would be invisible to it.
#
# Runs: Sunday 04:30 via root crontab (edit with: sudo crontab -e)
# Log:  /var/log/media-fullbackup.log

set -uo pipefail

REPO=/mnt/nas/wsbackup/fullsystem-restic
PASSWORD_FILE=/home/mediasvr/.restic-password
INFO_DIR=/var/lib/media-fullbackup-info
LOG=/var/log/media-fullbackup.log
KEEP_COUNT=8

export RESTIC_REPOSITORY=$REPO
export RESTIC_PASSWORD_FILE=$PASSWORD_FILE

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Backup started ==="

# --- Verify NAS is mounted --------------------------------------------------
if ! mountpoint -q /mnt/nas/wsbackup; then
    log "ERROR: /mnt/nas/wsbackup is not mounted. Aborting."
    exit 1
fi

# --- Verify restic is ready --------------------------------------------------
# Deliberately fail rather than apt-install/init here — see header comment.
if ! command -v restic >/dev/null 2>&1; then
    log "ERROR: restic is not installed. Run 'Save & Init Repo' from the Backup tab first. Aborting."
    exit 1
fi
if [ ! -f "$PASSWORD_FILE" ]; then
    log "ERROR: $PASSWORD_FILE not found. Run 'Save & Init Repo' from the Backup tab first. Aborting."
    exit 1
fi
if ! restic snapshots >/dev/null 2>&1; then
    log "ERROR: restic repo at $REPO is not accessible (not initialized, or wrong password). Aborting."
    exit 1
fi

errors=0

# --- System manifest (for restore-time package reinstall + reference) ------
# Written into $INFO_DIR so it travels inside the encrypted snapshot itself
# rather than as loose files next to it.
log "-- System manifest"
mkdir -p "$INFO_DIR"
dpkg --get-selections > "$INFO_DIR/dpkg-selections.txt" 2>>"$LOG" \
    && log "  OK  dpkg-selections.txt" || { log "  FAIL dpkg-selections.txt"; errors=$((errors+1)); }
apt-mark showmanual > "$INFO_DIR/apt-manual-packages.txt" 2>>"$LOG" \
    && log "  OK  apt-manual-packages.txt" || { log "  FAIL apt-manual-packages.txt"; errors=$((errors+1)); }
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE > "$INFO_DIR/lsblk.txt" 2>>"$LOG" \
    && log "  OK  lsblk.txt" || log "  SKIP lsblk.txt (command unavailable)"
blkid > "$INFO_DIR/blkid.txt" 2>>"$LOG" \
    && log "  OK  blkid.txt" || log "  SKIP blkid.txt (command unavailable)"
parted -l > "$INFO_DIR/parted.txt" 2>>"$LOG" \
    && log "  OK  parted.txt" || log "  SKIP parted.txt (command unavailable)"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' \
    > "$INFO_DIR/docker-images.txt" 2>>"$LOG" \
    && log "  OK  docker-images.txt" || log "  SKIP docker-images.txt (docker unavailable)"

# --- Backup -------------------------------------------------------------
# Explicit top-level dirs rather than "/ minus excludes" — simpler and more
# robust than juggling exclude-pattern anchoring. This naturally leaves out
# /usr (see RESTORE.md — reinstalled from the package manifest instead of
# copying potentially-incompatible old binaries), /proc /sys /dev /run /tmp,
# and anything else not listed. /boot is included here (so it's encrypted
# and versioned like everything else) but deliberately excluded at restore
# time — see RESTORE.md.
# --one-file-system still matters here: /opt has a separate mounted disk
# (/opt/media/downloads) nested under it that must not be descended into.
log "-- restic backup (one snapshot, ACLs/xattrs preserved natively)"
restic backup --one-file-system --tag fullsystem \
    /etc /home /root /opt /var /srv /boot "$INFO_DIR" 2>>"$LOG"
rc=$?
# restic exit 3 ("some source data could not be read") is expected/benign
# on a live system and not a real failure — same tolerance tar's exit 1 got.
if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ]; then
    log "  OK  restic backup (exit $rc)"
else
    log "  FAIL restic backup exited $rc"
    errors=$((errors+1))
fi

# --- Retention: keep the most recent KEEP_COUNT snapshots -------------------
log "-- Pruning to the most recent ${KEEP_COUNT} snapshots"
restic forget --tag fullsystem --keep-last "$KEEP_COUNT" --prune 2>>"$LOG" \
    && log "  OK  forget --prune" || { log "  FAIL forget --prune"; errors=$((errors+1)); }

# --- Repo pointer for the app's backup-status detection ---------------------
# Same home-directory reasoning as PASSWORD_FILE above.
mkdir -p /home/mediasvr/.config
echo "RESTIC_REPOSITORY=$REPO" > /home/mediasvr/.config/restic-repos

# --- Summary ----------------------------------------------------------------
USED=$(du -sh "$REPO" 2>/dev/null | cut -f1)
if [ "$errors" -eq 0 ]; then
    log "=== Backup completed OK — $USED written to $REPO ==="
else
    log "=== Backup completed with $errors error(s) — check log above ==="
    exit 1
fi
