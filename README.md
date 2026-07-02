# All Clear Server Services — Media Server Manager

A Python/Tkinter desktop control panel for managing a home media server over SSH.  
Connect once, and every service, container, metric, and alert is a click away.

---

## Features

### Connection & Navigation
- SSH connect via password or key file; auto-reconnect watchdog
- Wake-on-LAN from the connection panel
- Multi-server profile switcher (sidebar SERVERS section)
- Animated collapsible sidebar with active-state highlighting and section grouping
- Global search bar (Ctrl+F) to jump to any tab by name
- Keyboard shortcuts: 1–9 jump to tabs, R/F5 refreshes, Ctrl+? shows help overlay
- Dark / Light theme toggle (persisted across restarts)
- System tray icon — minimise to tray instead of closing
- Persistent connection status bar with animated heartbeat dot
- In-app toast notifications (bottom-right, fade in/out) logged to Notification History

### Dashboard
- Live CPU, RAM, disk, and network charts with configurable history
- GPU usage and temperature (nvidia-smi / sensors)
- Storage pool summary (ZFS / Btrfs / plain mounts)
- Top processes by CPU
- System uptime widget
- Configurable alert thresholds — flash status bar on breach

### Services & Docker
- Systemd service cards: Start / Stop / Restart / Status / Live log tail
- Docker container cards: Start / Stop / Restart / Logs / Inspect
  - Per-container CPU %, RAM usage, and colour-coded uptime
- Docker Compose manager — bring stacks up/down, view status
- Live log tail window (floating, scrolling, filterable) for both services and containers

### Media Apps
- **Emby / Plex / Jellyfin** — Now Playing sessions with progress bars; Message All users
- **Play History** — per-user watch history across all players
- **SABnzbd** — queue, history, speed graph; download-complete toast
- **Sonarr / Radarr / Prowlarr** — queue with missing-count badge
- **Overseerr / Jellyseerr** — request queue and status
- **Tautulli** — recent activity and stats
- **Uptime Kuma** — monitor status page with uptime percentages (24 h / 30 d)

### Server Metrics (optional Docker containers)
- **Netdata** (port 19999) — CPU, RAM, Disk I/O, Network with mini bar charts; sub-tabs for Disks and Network interfaces
- **Glances** (port 61208) — CPU, RAM, Swap, Load, top processes, filesystems, network, disk I/O; auto-detects API v3 / v4; optional basic auth

### Infrastructure
- **What's Up Docker (WUD)** — polls every hour; toast + Notification History entry when container updates are available
- **Uptime Kuma** — status page monitor with heartbeat and uptime data
- **Tailscale** — connection status and peer list
- **VPN** — ProtonVPN / WireGuard / OpenVPN status (optional sidebar entry)
- **Reverse Proxy** — Nginx / Caddy / Traefik config viewer (optional sidebar entry)
- **SSL Certificate** expiry checker
- **vnstat** bandwidth history
- **ZFS / Btrfs** pool health tab
- **S.M.A.R.T.** disk health tab
- **Backup Status** — last run time, size, errors from backup.sh log
- **Speedtest** — on-demand Speedtest CLI results
- **SFTP File Browser** — browse, upload, download files over SSH
- **Cron Job Viewer** — read system and user crontabs
- **Active SSH Sessions** viewer
- **Log Viewer** — multi-source log viewer (journalctl, docker logs, custom)
- **Quick Commands** — grouped, colour-coded one-click SSH commands
- **Server Manager** — multi-profile server management
- **Custom Commands** — user-defined SSH command buttons
- **Notification History** — all toasts logged with timestamp and level
- **Config tab** — all settings in one place with Test buttons and Export / Import

---

## Server-Side Prerequisites

All of the following run on the media server. Install only the ones you want — each feature in the app is optional and hidden from the sidebar until configured.

### Required (always)
- Ubuntu / Debian Linux server with SSH enabled
- Docker and Docker Compose

### Uptime Kuma (monitor status page)
```bash
docker run -d \
  --name uptime-kuma \
  --restart unless-stopped \
  -p 3001:3001 \
  -v uptime-kuma:/app/data \
  louislam/uptime-kuma:1
```
After starting: open `http://SERVER:3001`, create a status page, note the **slug** and generate an **API key** under Settings → API Keys.

### Netdata (real-time metrics)
```bash
docker run -d \
  --name netdata \
  --restart unless-stopped \
  -p 19999:19999 \
  --cap-add SYS_PTRACE \
  --security-opt apparmor=unconfined \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /etc/os-release:/host/etc/os-release:ro \
  netdata/netdata
```

### Glances (system metrics with REST API)
```bash
docker run -d \
  --name glances \
  --restart unless-stopped \
  -p 61208:61208 \
  -e GLANCES_OPT="-w" \
  --pid host \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  nicolargo/glances:latest-full
```
The `latest-full` image ships Glances v4 (`/api/4/`). The app auto-detects v3 vs v4.

### What's Up Docker — WUD (container update notifications)
```bash
docker run -d \
  --name wud \
  --restart unless-stopped \
  -p 3002:3000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e 'WUD_TRIGGER_HTTP_NTFY_URL=http://SERVER_IP:8090' \
  -e 'WUD_TRIGGER_HTTP_NTFY_METHOD=POST' \
  -e 'WUD_TRIGGER_HTTP_NTFY_HEADERS_CONTENT-TYPE=application/json' \
  -e 'WUD_TRIGGER_HTTP_NTFY_BODY={"topic":"mediaserver","title":"🐳 Update: ${container}","message":"${container} → ${current} can update to ${tag}","priority":3}' \
  getwud/wud
```
Replace `SERVER_IP` with your server's LAN IP. Port 3001 is taken by Uptime Kuma, so WUD runs on **3002**.

### ntfy (push notifications from WUD and the app)
```bash
docker run -d \
  --name ntfy \
  --restart unless-stopped \
  -p 8090:80 \
  -v /opt/media/ntfy/cache:/var/cache/ntfy \
  -v /opt/media/ntfy/etc:/etc/ntfy \
  binwiederhier/ntfy serve \
  --cache-file /var/cache/ntfy/cache.db
```
Port 8080 is taken by SABnzbd, so ntfy runs on **8090**. Open `http://SERVER:8090` in a browser and subscribe to the `mediaserver` topic. Install the ntfy mobile app and subscribe to the same topic for phone push notifications.

### vnstat (bandwidth history)
```bash
sudo apt install vnstat
sudo systemctl enable --now vnstat
```

### Speedtest CLI
```bash
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
sudo apt install speedtest
```

---

## Windows Client Setup

### 1. Install Python 3.10+
Download from https://www.python.org/downloads/ — check **Add to PATH**.

### 2. Clone or extract the project
```
cd C:\media-server-manager
```

### 3. Install Python dependencies
```
pip install -r requirements.txt
```

Dependencies: `paramiko` (SSH), `pillow` (images), `pystray` (system tray), `cffi`, `cryptography`, `bcrypt`.

### 4. Run
```
python main.py
```

---

## Configuration

Open the **Config** tab (gear icon in the sidebar). All sections have a **Test** button to verify connectivity before saving.

| Section | What to fill in |
|---|---|
| Systemd Services | Name, systemd unit name, port for each service |
| Docker Containers | Name, container name, port for each container |
| Storage Mounts | Paths to show in the Dashboard storage table |
| Dashboard | Auto-refresh interval (seconds) |
| Alert Thresholds | CPU %, RAM %, Disk %, CPU °C limits |
| SABnzbd | Port (default 8080), API key |
| Emby | Host, port (8096), API key |
| Plex | Host, Plex token |
| Jellyfin | Host, port (8096), API key |
| Sonarr | Host, port (8989), API key |
| Radarr | Host, port (7878), API key |
| Prowlarr | Host, port (9696), API key |
| Overseerr | Host, port (5055), API key |
| Jellyseerr | Host, port (5055), API key |
| Tautulli | Host, port (8181), API key |
| Uptime Kuma | Host, port (3001), slug, API key |
| Netdata | Host, port (19999) |
| Glances | Host, port (61208), username/password (if auth enabled) |
| What's Up Docker | Host, port (3002) |
| VPN | Enable/disable + type (ProtonVPN / WireGuard / OpenVPN) |
| Reverse Proxy | Enable/disable + type (Nginx / Caddy / Traefik) |
| Notifications | ntfy server, topic; SMTP email settings |

Sidebar entries for Plex, Jellyfin, Uptime Kuma, Netdata, Glances, VPN, and Reverse Proxy are hidden until their respective host/key fields are filled in and saved.

### Export / Import Config
Use **Export Config** to save a `media-server-config.json` backup. Use **Import Config** to restore it on a new machine — then restart the app.

---

## Building the Windows Installer

### 1. Install PyInstaller
```
pip install pyinstaller
```

### 2. Build
```
pyinstaller MediaServerManager.spec
```
Output: `dist\main\main.exe` (onedir bundle).

### 3. Create installer (requires Inno Setup 6)
```
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" AllClearServerServices_Setup.iss
```
Output: `installer_output\AllClearServerServices_v1.0.0_Setup.exe`

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| 1 – 9 | Jump to tab by number |
| Escape | Go to Connection tab |
| Ctrl + F | Open global search |
| Ctrl + ? | Show keyboard shortcut help |
| R / F5 | Refresh current tab |

---

## Backup

`backup.sh` runs weekly (Sunday 03:00 via root crontab) and copies config and data for:
- Emby library and config
- Sonarr, Radarr, Prowlarr, Bazarr
- SABnzbd
- Docker compose files
- Uptime Kuma data volume
- WUD and ntfy config directories
- System files (fstab, netplan, crontab)
- The backup and cleanup scripts themselves

Backups are written to `/mnt/nas/wsbackup/mediaserver/YYYYMMDD/` and pruned after 30 days.

Schedule (add with `sudo crontab -e`):
```
0 3 * * 0  /opt/media/backup.sh >> /var/log/media-backup.log 2>&1
```

---

## Port Reference

| Service | Port |
|---|---|
| Emby | 8096 |
| SABnzbd | 8080 |
| Sonarr | 8989 |
| Radarr | 7878 |
| Prowlarr | 9696 |
| Overseerr | 5055 |
| Jellyseerr | 5055 |
| Tautulli | 8181 |
| Uptime Kuma | 3001 |
| WUD | 3002 |
| ntfy | 8090 |
| Netdata | 19999 |
| Glances | 61208 |

---

## License

Copyright © 2026 All Clear Server Services LLC. All rights reserved.
