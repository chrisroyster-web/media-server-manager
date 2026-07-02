# All Clear Server Services — Media Server Manager

A Python/Tkinter desktop control panel for managing a home media server over SSH.
Connect once, and every service, container, metric, and alert is a click away.

---

## Getting Started

### 1. Install the app

**Using the installer (recommended, no Python required):**
Run `AllClearServerServices_Setup.exe` and follow the prompts. A Start Menu shortcut is created automatically.

**Running from source:**
```
1. Install Python 3.10+ from https://www.python.org/downloads/ — check "Add to PATH" during install.
2. pip install -r requirements.txt
3. python main.py
```

### 2. Connect to your server

Launch the app — you'll land on the **Connection** panel.

1. Enter your server's IP address or hostname, SSH username, and either a password or the path to an SSH private key.
2. Click **Connect**.
3. The first time you connect to a given server, the app trusts and remembers its SSH host key. If that key ever changes on a later connection, the app refuses to connect and warns you instead of silently proceeding — that usually means the server was reinstalled, or something is intercepting the connection. If you're sure the change is legitimate, delete the `known_hosts` file next to your config (`%APPDATA%\All Clear Server Services\known_hosts`) and reconnect to re-trust the new key.
4. Once connected, the sidebar populates and the **Dashboard** tab starts showing live CPU, RAM, disk, and network stats.

### 3. Configure the services you actually use

Open **Config** (gear icon at the bottom of the sidebar). It's organized into sections — Systemd Services, Docker Containers, and then one section per optional integration (Emby, Plex, Sonarr, qBittorrent, Cloudflare, and so on).

- You only need to fill in sections for things you actually run. Sidebar entries for anything left unconfigured stay dimmed and are skipped when the app refreshes.
- Every integration section has a **Test Connection** button — use it before saving to confirm the app can actually reach that service with the credentials you entered.
- A few sections (like Cloudflare) also have a small **?** button next to the header with setup instructions specific to that integration.
- Click **Save & Apply** at the top when you're done. Some changes (like enabling a previously-hidden sidebar tab) take effect immediately; others may ask for a restart.

### 4. You're set

Everything that only needs SSH — Docker, Cron Jobs, Backups, SFTP file browsing, Sessions, Firewall, and most of the **Infrastructure** and **Tools** sections — already works from step 2 and needs no further configuration.

A good first stop after connecting: the **Dashboard** for an overview, then **Services** and **Docker** to see what's actually running on the box.

---

## Features

### Connection & Navigation
- SSH connect via password or key file; auto-reconnect watchdog; trust-on-first-use host key verification (warns on unexpected key changes)
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
- Configurable alert rules (metric, operator, threshold, cooldown, delivery channel) — flash the status bar and/or notify on breach

### Media
- **Emby / Plex / Jellyfin** — unified Now Playing sessions with progress bars; kick or message a session
- **Media Library** — unified library browser across all three
- **Media Users** — unified user management (enable/disable, bitrate limits) across all three
- **Play History** — per-user watch history across all players
- **Watchstate** — sync watched/play-state between Plex, Emby, and Jellyfin

### Requests & Downloads
- **Sonarr / Radarr / Prowlarr** — combined Arr queue with missing-count badge, indexer health
- **Overseerr / Jellyseerr** — unified request queue and status
- **SABnzbd / qBittorrent** — queue, history, speed graph; download-complete toast

### Monitoring
- **Tautulli** — recent activity and stats
- **Uptime Kuma** — status page monitor with uptime percentages (24h / 30d)
- **Netdata** — real-time CPU/RAM/disk-I/O/network with mini bar charts
- **Glances** — CPU, RAM, swap, load, top processes, filesystems, network, disk I/O
- **Bandwidth** — vnstat daily/monthly history
- **Speedtest** — on-demand results
- **Sensors** — hardware temps/fans
- **Pi-hole / AdGuard Home** — stats and query log

### Infrastructure
- Systemd service cards: Start / Stop / Restart / Status / Live log tail (with confirmation before stop/restart)
- Docker container cards: Start / Stop / Restart / Logs / Inspect, per-container CPU %/RAM/uptime
- Docker Compose manager — bring stacks up/down, pull, view status
- Docker Volumes & Networks — inspect, prune, remove
- Restart Sequence — define an ordered stop/start sequence across services, containers, and stacks
- Cron Job Viewer and Systemd Timers viewer
- Scheduler — run your own automation tasks on an interval/daily/weekly schedule
- Install Apps — detect, install, start, reinstall, or uninstall 30+ self-hosted apps
- Active SSH Sessions, running Processes, listening Ports
- Disk Health (S.M.A.R.T.) and Storage Health (ZFS/Btrfs/df)
- VPN status (ProtonVPN / WireGuard / OpenVPN), Reverse Proxy config viewer (Nginx/Caddy/Traefik), Tailscale peers
- UFW Firewall rule viewer/editor
- **Cloudflare** — DNS record viewer/editor with dynamic-IP sync, recent WAF/security events, Tunnel status, one-click cache purge

### Tools
- SFTP file browser (upload/download/rename/delete)
- Multi-source Log Viewer (journalctl, docker logs, custom)
- Custom Commands — user-defined SSH command buttons
- Quick Commands — grouped, colour-coded one-click SSH commands
- SSL certificate expiry checker
- Fail2ban jail monitor with one-click unban
- Backup status and on-demand run
- Update checker (apt packages + Docker images) with one-click apply
- Disk Usage breakdown, Network Toolkit (ping/traceroute/DNS)
- Notification History — every toast logged with timestamp and level
- Config — all settings in one place with Test buttons and Export / Import

---

## Security

- **Secrets encrypted at rest.** SSH passwords, SMTP credentials, and every service API key/token are encrypted with Windows DPAPI before being written to `config.json`, tied to your Windows login — not stored in plaintext.
- **SSH host-key verification.** The app remembers each server's SSH host key after the first connection and refuses to connect (with a clear warning) if that key ever changes unexpectedly, rather than silently trusting whatever key shows up.
- **Shell-safe command construction.** Every value pulled from your server or typed into a form is properly quoted before being used in a remote command, closing off shell-injection paths.
- **Verified self-updates.** Downloaded installer updates are checked against the published SHA-256 before being run.

---

## Server-Side Prerequisites

All of the following run on the media server. Install only the ones you want — each feature in the app is optional and hidden from the sidebar until configured.

### Required (always)
- Ubuntu / Debian Linux server with SSH enabled
- Docker and Docker Compose (for the Docker/Compose/Install Apps tabs)

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

> Watchstate's default port in this app is also 8090 — if you run both ntfy and Watchstate, change one of them in Config to avoid a collision.

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

### Cloudflare (DNS, security events, Tunnel status, cache purge)
No server-side install needed — this integration talks to Cloudflare's API directly, not your server. You just need a scoped API Token, your Zone ID, and (optionally) your Account ID. Click the **?** button next to the Cloudflare section in Config for exact token permissions and where to find your IDs.

---

## Configuration Reference

Open the **Config** tab (gear icon in the sidebar). Every integration section has a **Test** button to verify connectivity before saving.

| Section | What to fill in |
|---|---|
| Systemd Services | Name, systemd unit name, port for each service |
| Docker Containers | Name, container name, port for each container (drives the Dashboard status cards and Updates tab) |
| Storage Mounts | Paths to show in the Dashboard storage table |
| Dashboard | Auto-refresh interval (seconds) |
| Alert Rules | Metric, operator, threshold, duration, cooldown, and delivery channels (toast / ntfy / email / apprise) per rule |
| SABnzbd | Host, port (default 8080), API key |
| qBittorrent | Host, port (default 8080), username, password |
| Pi-hole / AdGuard Home | Type, host, port, API key (Pi-hole) or username + password (AdGuard) |
| Emby | Host, port (8096), API key |
| Plex | Host, port (32400), Plex token |
| Jellyfin | Host, port (8096), API key |
| Sonarr | Host, port (8989), API key |
| Radarr | Host, port (7878), API key |
| Prowlarr | Host, port (9797), API key |
| Overseerr | Host, port (5055), API key |
| Jellyseerr | Host, port (5055), API key |
| Tautulli | Host, port (8181), API key |
| Uptime Kuma | Host, port (3001), slug, API key |
| Netdata | Host, port (19999) |
| Glances | Host, port (61208), username/password (if auth enabled) |
| What's Up Docker | Host, port (defaults to 3000 — set to 3002 if you used the docker run example below, which maps it to 3002 to avoid colliding with Uptime Kuma) |
| Watchstate | Host, port (default 8090) |
| Cloudflare | API Token, Zone ID, Account ID (optional, for Tunnel status) — see the **?** button in this section |
| VPN | Enable/disable + type (ProtonVPN / WireGuard / OpenVPN) |
| Reverse Proxy | Enable/disable + type (Nginx / Caddy / Traefik) |
| Tailscale | Enable/disable to show the Tailscale tab |
| Notifications | ntfy server, topic; SMTP email settings |

Sidebar entries for optional integrations stay hidden/dimmed until their host/key fields are filled in and saved.

### Export / Import Config
Use **Export Config** to save a backup of your settings file. Use **Import Config** to restore it (on the same or a new machine), then restart the app. Secrets stay encrypted in the exported file and only decrypt correctly under the same Windows login that exported them.

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
Output: `installer_output\AllClearServerServices_v2.0.0_Setup.exe`

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

You can also trigger a backup on demand from the **Backups** tab or the **Quick Commands** panel.

---

## Port Reference

| Service | Port |
|---|---|
| Emby | 8096 |
| Plex | 32400 |
| SABnzbd | 8080 *(change one if you also run qBittorrent)* |
| qBittorrent | 8080 *(change one if you also run SABnzbd)* |
| Sonarr | 8989 |
| Radarr | 7878 |
| Prowlarr | 9797 |
| Overseerr | 5055 |
| Jellyseerr | 5055 |
| Tautulli | 8181 |
| Uptime Kuma | 3001 |
| WUD | 3002 |
| ntfy | 8090 |
| Watchstate | 8090 *(change one if you also run ntfy)* |
| Netdata | 19999 |
| Glances | 61208 |
| Pi-hole | 80 |

---

## License

Copyright © 2026 All Clear Server Services LLC. All rights reserved.
