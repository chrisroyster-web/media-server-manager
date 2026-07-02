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

# --- Arr backup zips (in-app Backup → Create Backup .zip files) -------------
# The arr apps generate timestamped .zip snapshots when you click "Create Backup"
# in their web UI. These may live inside the bind-mount paths above OR in an
# alternate location depending on install method / Docker volume layout.
# We keep the 5 most recent per app so the NAS copy doesn't grow unbounded.
log "-- Arr backup zips"
mkdir -p "$BACKUP_DIR/arr-zips"
for _app in sonarr radarr prowlarr bazarr; do
    _app_zips_found=0
    for _base in "/opt/media/$_app" "/var/lib/$_app"; do
        for _subdir in Backups backups; do
            _zip_dir="$_base/$_subdir"
            [ -d "$_zip_dir" ] || continue
            # Read the 5 most-recently-modified zips into an array (no subshell
            # so errors from safe_cp still increment the outer $errors counter)
            mapfile -t _zips < <(
                find "$_zip_dir" -name "*.zip" -type f \
                    -printf '%T@ %p\n' 2>/dev/null \
                    | sort -rn | head -5 | cut -d' ' -f2-
            )
            if [ "${#_zips[@]}" -gt 0 ]; then
                mkdir -p "$BACKUP_DIR/arr-zips/$_app"
                for _z in "${_zips[@]}"; do
                    safe_cp "$_z" "$BACKUP_DIR/arr-zips/$_app/"
                done
                _app_zips_found=1
            fi
        done
    done
    [ "$_app_zips_found" -eq 0 ] && log "  SKIP $_app (no Backups/ directory or zip files found)"
done
unset _app _base _subdir _zip_dir _zips _z _app_zips_found

# --- SABnzbd ----------------------------------------------------------------
log "-- SABnzbd"
mkdir -p "$BACKUP_DIR/sabnzbd"
# Copy the config file (live settings)
safe_cp /home/mediasvr/.sabnzbd/sabnzbd.ini   "$BACKUP_DIR/sabnzbd/"
# SABnzbd writes backup zips to the complete directory. Copy the 5 most recent.
mapfile -t _sab_zips < <(
    find /opt/media/downloads/complete -name "*.zip" -type f \
        -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -5 | cut -d' ' -f2-
)
if [ "${#_sab_zips[@]}" -gt 0 ]; then
    for _z in "${_sab_zips[@]}"; do
        safe_cp "$_z" "$BACKUP_DIR/sabnzbd/"
    done
else
    log "  SKIP SABnzbd backup zips (none found in /opt/media/downloads/complete)"
fi
unset _sab_zips _z

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

# WUD — config is stored in env vars; dump them so the container can be recreated
log "-- WUD"
mkdir -p "$BACKUP_DIR/docker/wud"
docker inspect wud --format '{{json .Config.Env}}' 2>/dev/null \
    | python3 -m json.tool > "$BACKUP_DIR/docker/wud/wud-env.json" \
    && log "  OK  WUD env vars" \
    || log "  SKIP WUD (container not running)"

# ntfy — cache DB and config directory
log "-- ntfy"
mkdir -p "$BACKUP_DIR/docker/ntfy"
safe_cp /opt/media/ntfy/cache   "$BACKUP_DIR/docker/ntfy/cache"
safe_cp /opt/media/ntfy/etc     "$BACKUP_DIR/docker/ntfy/etc"

# Glances — no persistent config by default; skip unless customised
log "-- Glances"
if [ -d /opt/media/glances ]; then
    safe_cp /opt/media/glances "$BACKUP_DIR/docker/glances"
else
    log "  SKIP Glances (no /opt/media/glances directory)"
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
