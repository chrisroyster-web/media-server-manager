#!/bin/bash
# rebuild-server.sh
#
# Standalone bare-metal rebuild script. Run this directly (console or SSH)
# on a freshly-installed minimal Ubuntu Server to restore it from the
# full-system-backup restic repo on the NAS — no workstation, no GUI app,
# no dependency on anything but this file and NAS/restic access.
#
# This is the scripted equivalent of RESTORE.md's manual procedure (and of
# the app's in-GUI Restore Wizard, ui/restore_dialog.py) — same safety
# check, same manifest-first/package-reinstall/exclude-boot phases, just
# ported to a self-contained script so a lost workstation is never a
# blocker for recovering the server itself.
#
# Usage: sudo bash rebuild-server.sh

set -euo pipefail

NAS_HOST_DEFAULT="192.168.4.50"
NAS_SHARE="wsbackup"
NAS_MOUNT="/mnt/nas/wsbackup"
RESTIC_REPO="/mnt/nas/wsbackup/fullsystem-restic"
INFO_DIR="/var/lib/media-fullbackup-info"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root: sudo bash rebuild-server.sh"
    exit 1
fi

echo "=== Bare-metal rebuild ==="
echo "This reinstalls packages and overwrites most of / on THIS machine from"
echo "a restic snapshot. Only run this against a machine you intend to fully"
echo "take over — it cannot be undone."
echo

# --- Safety check: refuse on an already-configured box -----------------
if [ -e /opt/media/backup.sh ] || [ -e /opt/media/full-system-backup.sh ]; then
    echo "REFUSED: this server already has backup.sh or full-system-backup.sh"
    echo "deployed — it does not look like a fresh install. Aborting."
    exit 1
fi

read -r -p "Type this machine's hostname ($(hostname)) to confirm: " CONFIRM_HOST
if [ "$CONFIRM_HOST" != "$(hostname)" ]; then
    echo "Hostname did not match. Aborting for safety."
    exit 1
fi

# --- Mount the NAS -------------------------------------------------------
if ! mountpoint -q "$NAS_MOUNT" 2>/dev/null; then
    read -r -p "NAS host [$NAS_HOST_DEFAULT]: " NAS_HOST
    NAS_HOST="${NAS_HOST:-$NAS_HOST_DEFAULT}"
    read -r -p "NAS username: " NAS_USER
    read -r -s -p "NAS password: " NAS_PASS
    echo

    apt-get update -qq
    apt-get install -y cifs-utils restic >/dev/null

    mkdir -p "$NAS_MOUNT"
    CRED_FILE=$(mktemp)
    printf 'username=%s\npassword=%s\n' "$NAS_USER" "$NAS_PASS" > "$CRED_FILE"
    chmod 600 "$CRED_FILE"
    if ! mount -t cifs "//$NAS_HOST/$NAS_SHARE" "$NAS_MOUNT" \
        -o "credentials=$CRED_FILE,vers=2.0,uid=0,gid=0,file_mode=0777,dir_mode=0777"; then
        rm -f "$CRED_FILE"
        echo "NAS mount failed. Aborting."
        exit 1
    fi
    rm -f "$CRED_FILE"
    echo "NAS mounted."
else
    apt-get update -qq
    apt-get install -y restic >/dev/null
fi

# --- Restic repo access ----------------------------------------------------
read -r -s -p "Restic repo password: " RESTIC_PASSWORD
echo
export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD

echo
echo "Available snapshots:"
restic snapshots --tag fullsystem
echo
read -r -p "Snapshot ID to restore (short ID from the list above): " SNAP_ID
if [ -z "$SNAP_ID" ]; then
    echo "No snapshot ID given. Aborting."
    exit 1
fi

echo
read -r -p "This will restore snapshot $SNAP_ID onto / on $(hostname), excluding /boot. Type YES to continue: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

# --- Phase 1: system manifest --------------------------------------------
echo "-- Restoring system manifest..."
restic restore "$SNAP_ID" --target / --include "$INFO_DIR"

# --- Phase 2: reinstall packages from the manifest ------------------------
echo "-- Updating package index..."
apt-get update -qq
echo "-- Reinstalling packages from manifest..."
xargs -a "$INFO_DIR/apt-manual-packages.txt" apt-get install -y

# --- Phase 3: restore everything else, excluding /boot --------------------
# /boot is deliberately left alone: the fresh install's own bootloader/
# kernel already matches this hardware, and restoring the old machine's
# /boot over it could break booting on new/different hardware. It's still
# in the snapshot and recoverable individually if ever needed:
#   restic restore <id> --target /tmp/boot-ref --include /boot
echo "-- Restoring everything else (excluding /boot) — this is the main step..."
restic restore "$SNAP_ID" --target / --exclude /boot

echo
echo "=== Restore finished ==="
echo "Next steps:"
echo "  1. Reboot."
echo "  2. Confirm services: systemctl status emby-server sonarr radarr prowlarr bazarr sabnzbdplus"
echo "  3. Confirm containers: docker ps"
echo "  4. Confirm NAS shares remount: mount -a"
echo "  5. Re-run backup.sh and full-system-backup.sh once manually (or via"
echo "     the app's Backup tab) to confirm both still work and to"
echo "     re-establish crontab entries if the restore didn't bring"
echo "     etc/cron.d and the root crontab back correctly."
echo "  6. /boot was NOT restored automatically — see RESTORE.md if you"
echo "     need anything from it."
