#!/bin/bash
# /opt/media/backup.sh
# Media server config backup to NAS
# Runs: Sunday 03:00 via root crontab (edit with: sudo crontab -e)
# Log:  /var/log/media-backup.log

set -euo pipefail

BACKUP_ROOT=/mnt/nas/wsbackup/mediaserver
BACKUP_DIR=$BACKUP_ROOT/$(date +%Y%m%d)
LOG=/var/log/media-backup.log
KEEP_DAYS=30

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Backup started ==="

# --- Verify NAS is mounted --------------------------------------------------
if ! mountpoint -q /mnt/nas/wsbackup; then
    log "ERROR: /mnt/nas/wsbackup is not mounted. Aborting."
    exit 1
fi

mkdir -p "$BACKUP_DIR"
log "Destination: $BACKUP_DIR"

errors=0

safe_cp() {
    local src=$1
    local dst=$2
    if [ -e "$src" ]; then
        cp -r "$src" "$dst" && log "  OK  $src" || { log "  FAIL $src"; errors=$((errors+1)); }
    else
        log "  SKIP $src (not found)"
    fi
}

# --- Emby -------------------------------------------------------------------
log "-- Emby"
mkdir -p "$BACKUP_DIR/emby"
safe_cp /var/lib/emby/data/library.db          "$BACKUP_DIR/emby/"
safe_cp /var/lib/emby/data/users.db            "$BACKUP_DIR/emby/"
safe_cp /var/lib/emby/config                   "$BACKUP_DIR/emby/config"
safe_cp /var/lib/emby/plugins                  "$BACKUP_DIR/emby/plugins"

# --- Arr apps ---------------------------------------------------------------
log "-- Arr apps"
mkdir -p "$BACKUP_DIR/arr"
safe_cp /opt/media/sonarr                      "$BACKUP_DIR/arr/sonarr"
safe_cp /opt/media/radarr                      "$BACKUP_DIR/arr/radarr"
safe_cp /opt/media/prowlarr                    "$BACKUP_DIR/arr/prowlarr"
safe_cp /opt/media/bazarr                      "$BACKUP_DIR/arr/bazarr"

# --- SABnzbd ----------------------------------------------------------------
log "-- SABnzbd"
mkdir -p "$BACKUP_DIR/sabnzbd"
safe_cp /home/mediasvr/.sabnzbd/sabnzbd.ini   "$BACKUP_DIR/sabnzbd/"

# --- Docker (compose files + Uptime Kuma data volume) -----------------------
log "-- Docker"
mkdir -p "$BACKUP_DIR/docker"
safe_cp /opt/media/tracearr/docker-compose.yml "$BACKUP_DIR/docker/tracearr-compose.yml"
safe_cp /opt/media/homarr/docker-compose.yml   "$BACKUP_DIR/docker/homarr-compose.yml"

# Uptime Kuma stores data in a named Docker volume; export it if present
UK_VOL=$(docker inspect uptime-kuma \
    --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' \
    2>/dev/null || true)
if [ -n "$UK_VOL" ] && [ -d "$UK_VOL" ]; then
    safe_cp "$UK_VOL" "$BACKUP_DIR/docker/uptime-kuma-data"
else
    log "  SKIP Uptime Kuma volume (container not running or volume not found)"
fi

# --- System config ----------------------------------------------------------
log "-- System"
mkdir -p "$BACKUP_DIR/system"
safe_cp /etc/fstab                                       "$BACKUP_DIR/system/"
safe_cp /etc/netplan/00-installer-config.yaml            "$BACKUP_DIR/system/"
safe_cp /etc/crontab                                     "$BACKUP_DIR/system/"
safe_cp /etc/cron.d                                      "$BACKUP_DIR/system/cron.d"
# Root's crontab (the one with backup.sh and cleanup.sh entries)
crontab -l -u root > "$BACKUP_DIR/system/root-crontab.txt" 2>/dev/null \
    && log "  OK  root crontab" || log "  SKIP root crontab"

# --- Backup scripts themselves -----------------------------------------------
log "-- Scripts"
mkdir -p "$BACKUP_DIR/scripts"
safe_cp /opt/media/backup.sh                   "$BACKUP_DIR/scripts/"
safe_cp /opt/media/cleanup.sh                  "$BACKUP_DIR/scripts/"

# --- Retention: remove backups older than KEEP_DAYS -------------------------
log "-- Pruning backups older than ${KEEP_DAYS} days"
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +${KEEP_DAYS} | while read -r old; do
    log "  Removing $old"
    rm -rf "$old"
done

# --- Summary ----------------------------------------------------------------
USED=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
if [ "$errors" -eq 0 ]; then
    log "=== Backup completed OK — $USED written to $BACKUP_DIR ==="
else
    log "=== Backup completed with $errors error(s) — check log above ==="
    exit 1
fi
