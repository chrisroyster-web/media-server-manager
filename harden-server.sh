#!/bin/bash
# harden-server.sh
#
# Idempotent security hardening for a fresh or rebuilt server. Safe to
# re-run — every step checks current state first and skips if already
# applied. Exists so these settings are documented and reviewable in git,
# and reapplyable even on a from-scratch install (not just a restic
# restore via rebuild-server.sh, which would normally carry these same
# files over from a snapshot taken after they were first applied).
#
# Findings this addresses (from the 2026-07-08 security audit):
#   - SSH password authentication was enabled alongside NOPASSWD sudo for
#     the service account — a leaked/guessed password was a single step
#     from root. Key-based login was already working and used
#     exclusively by this app, so password auth is disabled outright
#     rather than touching sudo (several tabs in this app run sudo
#     commands over a plain, non-interactive SSH exec — removing
#     NOPASSWD would break those, for less benefit than closing the
#     password vector instead).
#   - X11Forwarding was enabled with no actual use for a headless server.
#   - Netdata (19999) and Glances (61208) were open to "Anywhere" in UFW.
#     Confirmed only Emby is port-forwarded from the router, so this
#     wasn't internet-facing in practice, but is tightened to the LAN
#     anyway as defense in depth in case that ever changes.
#
# Usage: sudo bash harden-server.sh

set -euo pipefail

LAN_CIDR="192.168.0.0/16"
SSHD_DROPIN="/etc/ssh/sshd_config.d/10-harden.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root: sudo bash harden-server.sh"
    exit 1
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "=== Server hardening ==="

# --- SSH: key-only login, no X11 forwarding --------------------------------
# Named to sort before any 50-*.conf (e.g. cloud-init's own drop-in, which
# on some images sets PasswordAuthentication yes) — sshd uses the first
# value it encounters per keyword, so this must load first to win.
if [ -f "$SSHD_DROPIN" ] && grep -q "^PasswordAuthentication no" "$SSHD_DROPIN" 2>/dev/null; then
    log "-- SSH hardening: already applied, skipping"
else
    log "-- SSH hardening: writing $SSHD_DROPIN"
    cat > "$SSHD_DROPIN" << 'EOF'
# Added by harden-server.sh - key-only login and no X11 forwarding.
PasswordAuthentication no
X11Forwarding no
EOF
    if ! sshd -t; then
        log "ERROR: sshd config is invalid after writing $SSHD_DROPIN — reverting."
        rm -f "$SSHD_DROPIN"
        exit 1
    fi
    systemctl reload ssh
    log "   applied and reloaded (existing sessions unaffected)"
fi

# --- UFW: restrict Netdata/Glances to the LAN ------------------------------
restrict_to_lan() {
    local port=$1
    local comment=$2
    if ufw status | grep -qE "^${port}/tcp\s+ALLOW\s+${LAN_CIDR//\//\\/}"; then
        log "-- UFW $port: already restricted to $LAN_CIDR, skipping"
        return
    fi
    log "-- UFW $port: restricting to $LAN_CIDR"
    ufw delete allow "${port}/tcp" >/dev/null 2>&1 || true
    ufw allow from "$LAN_CIDR" to any port "$port" proto tcp comment "$comment"
}
restrict_to_lan 19999 "Netdata - LAN only"
restrict_to_lan 61208 "Glances - LAN only"

log "=== Done ==="
log "Verify: sudo sshd -T | grep -E 'passwordauthentication|x11forwarding'"
log "Verify: sudo ufw status verbose | grep -E '19999|61208'"
