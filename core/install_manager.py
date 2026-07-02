# core/install_manager.py
"""
App installation, health-check, and auto-fix manager.

All installations use Docker to ensure isolation and config preservation.
User data lives in $HOME/docker/<name>/config/ so recreating a container never
destroys the user's settings.

Safe-by-design:
  • Only the named container is ever touched.
  • No apt upgrade, no system-package changes, no cross-container edits.
  • Config volumes survive reinstall / image updates.
"""

import time
import shlex

CATEGORIES = [
    "Infrastructure",
    "Media Servers",
    "Download Clients",
    "Arr Suite",
    "Request Managers",
    "Monitoring",
    "Dashboard",
]

_RSU = "--restart unless-stopped"
_LS  = "lscr.io/linuxserver"


def _ls(img):
    return f"{_LS}/{img}"


def _puid(uid=1000, gid=1000):
    return f"-e PUID={uid} -e PGID={gid}"


# ---------------------------------------------------------------------------
# Registry  — ordered by category / install dependency
# ---------------------------------------------------------------------------
APP_REGISTRY = [

    # ── Infrastructure ───────────────────────────────────────────────────
    {
        "key": "docker",
        "name": "Docker Engine",
        "category": "Infrastructure",
        "desc": "Container runtime — required by all Docker-based apps",
        "port": None,
        "container": None,
        "image": None,
        "health_path": None,
        "install_cmds": [
            "curl -fsSL https://get.docker.com -o /tmp/get-docker.sh",
            "sudo sh /tmp/get-docker.sh",
            "sudo systemctl enable --now docker",
            "sudo usermod -aG docker $(whoami) || true",
        ],
        "fix_cmds": ["sudo systemctl restart docker"],
        "reinstall_cmds": [],
    },
    {
        "key": "portainer",
        "name": "Portainer CE",
        "category": "Infrastructure",
        "desc": "Docker management UI — browse containers, images, volumes",
        "port": 9000,
        "container": "portainer",
        "image": "portainer/portainer-ce:latest",
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/portainer/data",
            "docker pull portainer/portainer-ce:latest",
            (f"docker run -d --name portainer -p 9000:9000 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"-v $HOME/docker/portainer/data:/data {_RSU} portainer/portainer-ce:latest"),
        ],
        "fix_cmds": ["docker restart portainer"],
        "reinstall_cmds": [
            "docker stop portainer 2>/dev/null || true",
            "docker rm   portainer 2>/dev/null || true",
            "docker pull portainer/portainer-ce:latest",
            (f"docker run -d --name portainer -p 9000:9000 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"-v $HOME/docker/portainer/data:/data {_RSU} portainer/portainer-ce:latest"),
        ],
    },
    {
        "key": "watchtower",
        "name": "Watchtower",
        "category": "Infrastructure",
        "desc": "Auto-updates running containers to latest image daily",
        "port": None,
        "container": "watchtower",
        "image": "containrrr/watchtower",
        "health_path": None,
        "install_cmds": [
            "docker pull containrrr/watchtower",
            (f"docker run -d --name watchtower "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"{_RSU} containrrr/watchtower --cleanup --interval 86400"),
        ],
        "fix_cmds": ["docker restart watchtower"],
        "reinstall_cmds": [
            "docker stop watchtower 2>/dev/null || true",
            "docker rm   watchtower 2>/dev/null || true",
            "docker pull containrrr/watchtower",
            (f"docker run -d --name watchtower "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"{_RSU} containrrr/watchtower --cleanup --interval 86400"),
        ],
    },
    {
        "key": "nginx_proxy_manager",
        "name": "Nginx Proxy Manager",
        "category": "Infrastructure",
        "desc": "Reverse proxy with SSL termination and web management UI",
        "port": 81,
        "container": "nginx-proxy-manager",
        "image": "jc21/nginx-proxy-manager:latest",
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/nginx-proxy-manager/data $HOME/docker/nginx-proxy-manager/letsencrypt",
            "docker pull jc21/nginx-proxy-manager:latest",
            (f"docker run -d --name nginx-proxy-manager "
             "-p 80:80 -p 443:443 -p 81:81 "
             "-v $HOME/docker/nginx-proxy-manager/data:/data "
             "-v $HOME/docker/nginx-proxy-manager/letsencrypt:/etc/letsencrypt "
             f"{_RSU} jc21/nginx-proxy-manager:latest"),
        ],
        "fix_cmds": ["docker restart nginx-proxy-manager"],
        "reinstall_cmds": [
            "docker stop nginx-proxy-manager 2>/dev/null || true",
            "docker rm   nginx-proxy-manager 2>/dev/null || true",
            "docker pull jc21/nginx-proxy-manager:latest",
            (f"docker run -d --name nginx-proxy-manager "
             "-p 80:80 -p 443:443 -p 81:81 "
             "-v $HOME/docker/nginx-proxy-manager/data:/data "
             "-v $HOME/docker/nginx-proxy-manager/letsencrypt:/etc/letsencrypt "
             f"{_RSU} jc21/nginx-proxy-manager:latest"),
        ],
    },

    # ── Media Servers ────────────────────────────────────────────────────
    {
        "key": "jellyfin",
        "name": "Jellyfin",
        "category": "Media Servers",
        "desc": "Free & open-source media server — movies, TV, music",
        "port": 8096,
        "container": "jellyfin",
        "image": "jellyfin/jellyfin",
        "health_path": "/health",
        "install_cmds": [
            "mkdir -p $HOME/docker/jellyfin/config $HOME/docker/jellyfin/cache",
            "docker pull jellyfin/jellyfin",
            (f"docker run -d --name jellyfin --network host "
             "-v $HOME/docker/jellyfin/config:/config "
             f"-v $HOME/docker/jellyfin/cache:/cache {_RSU} jellyfin/jellyfin"),
        ],
        "fix_cmds": ["docker restart jellyfin"],
        "reinstall_cmds": [
            "docker stop jellyfin 2>/dev/null || true",
            "docker rm   jellyfin 2>/dev/null || true",
            "docker pull jellyfin/jellyfin",
            (f"docker run -d --name jellyfin --network host "
             "-v $HOME/docker/jellyfin/config:/config "
             f"-v $HOME/docker/jellyfin/cache:/cache {_RSU} jellyfin/jellyfin"),
        ],
    },
    {
        "key": "plex",
        "name": "Plex Media Server",
        "category": "Media Servers",
        "desc": "Media server with rich clients and broad device support",
        "port": 32400,
        "container": "plex",
        "image": "plexinc/pms-docker",
        "health_path": "/identity",
        # Runs with --network host, so unlike Docker -p apps it bypasses
        # Docker's NAT rules entirely — UFW's default-deny INPUT policy is
        # what actually gates access, so every one of these needs its own rule.
        "ufw_ports": ["32400/tcp", "32410/udp", "32412:32414/udp"],
        "install_cmds": [
            "mkdir -p $HOME/docker/plex/config $HOME/docker/plex/transcode",
            "docker pull plexinc/pms-docker",
            (f"docker run -d --name plex --network host "
             "-e PLEX_CLAIM='' "
             "-v $HOME/docker/plex/config:/config "
             "-v $HOME/docker/plex/transcode:/transcode "
             # Mirrors the host's NAS mount 1:1 so library paths in Plex
             # match paths on the server exactly — read-only, Plex only scans/streams.
             "-v /mnt/nas:/mnt/nas:ro "
             f"{_RSU} plexinc/pms-docker"),
        ],
        "fix_cmds": ["docker restart plex"],
        "reinstall_cmds": [
            "docker stop plex 2>/dev/null || true",
            "docker rm   plex 2>/dev/null || true",
            "docker pull plexinc/pms-docker",
            (f"docker run -d --name plex --network host "
             "-e PLEX_CLAIM='' "
             "-v $HOME/docker/plex/config:/config "
             "-v $HOME/docker/plex/transcode:/transcode "
             "-v /mnt/nas:/mnt/nas:ro "
             f"{_RSU} plexinc/pms-docker"),
        ],
    },
    {
        "key": "emby",
        "name": "Emby Server",
        "category": "Media Servers",
        "desc": "Media server with Emby Premiere optional subscription",
        "port": 8096,
        "container": "emby",
        "image": "emby/embyserver",
        "health_path": "/System/Info/Public",
        "install_cmds": [
            "mkdir -p $HOME/docker/emby/config",
            "docker pull emby/embyserver",
            (f"docker run -d --name emby --network host "
             "-v $HOME/docker/emby/config:/config "
             f"-e UID=1000 -e GID=1000 {_RSU} emby/embyserver"),
        ],
        "fix_cmds": ["docker restart emby"],
        "reinstall_cmds": [
            "docker stop emby 2>/dev/null || true",
            "docker rm   emby 2>/dev/null || true",
            "docker pull emby/embyserver",
            (f"docker run -d --name emby --network host "
             "-v $HOME/docker/emby/config:/config "
             f"-e UID=1000 -e GID=1000 {_RSU} emby/embyserver"),
        ],
    },

    # ── Download Clients ─────────────────────────────────────────────────
    {
        "key": "sabnzbd",
        "name": "SABnzbd",
        "category": "Download Clients",
        "desc": "Usenet binary newsreader / download client",
        "port": 8080,
        "container": "sabnzbd",
        "image": _ls("sabnzbd"),
        "health_path": "/sabnzbd/",
        "install_cmds": [
            "mkdir -p $HOME/docker/sabnzbd/config $HOME/docker/sabnzbd/downloads $HOME/docker/sabnzbd/incomplete",
            f"docker pull {_ls('sabnzbd')}",
            (f"docker run -d --name sabnzbd -p 8080:8080 "
             "-v $HOME/docker/sabnzbd/config:/config "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             "-v $HOME/docker/sabnzbd/incomplete:/incomplete-downloads "
             f"{_puid()} {_RSU} {_ls('sabnzbd')}"),
        ],
        "fix_cmds": ["docker restart sabnzbd"],
        "reinstall_cmds": [
            "docker stop sabnzbd 2>/dev/null || true",
            "docker rm   sabnzbd 2>/dev/null || true",
            f"docker pull {_ls('sabnzbd')}",
            (f"docker run -d --name sabnzbd -p 8080:8080 "
             "-v $HOME/docker/sabnzbd/config:/config "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             "-v $HOME/docker/sabnzbd/incomplete:/incomplete-downloads "
             f"{_puid()} {_RSU} {_ls('sabnzbd')}"),
        ],
    },
    {
        "key": "qbittorrent",
        "name": "qBittorrent",
        "category": "Download Clients",
        "desc": "BitTorrent client with web UI (WebUI on :8082)",
        "port": 8082,
        "container": "qbittorrent",
        "image": _ls("qbittorrent"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/qbittorrent/config $HOME/docker/qbittorrent/downloads",
            f"docker pull {_ls('qbittorrent')}",
            (f"docker run -d --name qbittorrent "
             "-p 8082:8080 -p 6881:6881 -p 6881:6881/udp "
             "-v $HOME/docker/qbittorrent/config:/config "
             "-v $HOME/docker/qbittorrent/downloads:/downloads "
             f"-e WEBUI_PORT=8080 {_puid()} {_RSU} {_ls('qbittorrent')}"),
        ],
        "fix_cmds": ["docker restart qbittorrent"],
        "reinstall_cmds": [
            "docker stop qbittorrent 2>/dev/null || true",
            "docker rm   qbittorrent 2>/dev/null || true",
            f"docker pull {_ls('qbittorrent')}",
            (f"docker run -d --name qbittorrent "
             "-p 8082:8080 -p 6881:6881 -p 6881:6881/udp "
             "-v $HOME/docker/qbittorrent/config:/config "
             "-v $HOME/docker/qbittorrent/downloads:/downloads "
             f"-e WEBUI_PORT=8080 {_puid()} {_RSU} {_ls('qbittorrent')}"),
        ],
    },

    # ── Arr Suite ────────────────────────────────────────────────────────
    {
        "key": "sonarr",
        "name": "Sonarr",
        "category": "Arr Suite",
        "desc": "TV series manager — monitors RSS, downloads, renames",
        "port": 8989,
        "container": "sonarr",
        "image": _ls("sonarr"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/sonarr/config /media/tv",
            f"docker pull {_ls('sonarr')}",
            (f"docker run -d --name sonarr -p 8989:8989 "
             "-v $HOME/docker/sonarr/config:/config "
             "-v /media/tv:/tv "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('sonarr')}"),
        ],
        "fix_cmds": ["docker restart sonarr"],
        "reinstall_cmds": [
            "docker stop sonarr 2>/dev/null || true",
            "docker rm   sonarr 2>/dev/null || true",
            f"docker pull {_ls('sonarr')}",
            (f"docker run -d --name sonarr -p 8989:8989 "
             "-v $HOME/docker/sonarr/config:/config "
             "-v /media/tv:/tv "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('sonarr')}"),
        ],
    },
    {
        "key": "radarr",
        "name": "Radarr",
        "category": "Arr Suite",
        "desc": "Movie manager — monitors RSS, downloads, renames",
        "port": 7878,
        "container": "radarr",
        "image": _ls("radarr"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/radarr/config /media/movies",
            f"docker pull {_ls('radarr')}",
            (f"docker run -d --name radarr -p 7878:7878 "
             "-v $HOME/docker/radarr/config:/config "
             "-v /media/movies:/movies "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('radarr')}"),
        ],
        "fix_cmds": ["docker restart radarr"],
        "reinstall_cmds": [
            "docker stop radarr 2>/dev/null || true",
            "docker rm   radarr 2>/dev/null || true",
            f"docker pull {_ls('radarr')}",
            (f"docker run -d --name radarr -p 7878:7878 "
             "-v $HOME/docker/radarr/config:/config "
             "-v /media/movies:/movies "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('radarr')}"),
        ],
    },
    {
        "key": "lidarr",
        "name": "Lidarr",
        "category": "Arr Suite",
        "desc": "Music manager — monitors RSS, downloads, organizes",
        "port": 8686,
        "container": "lidarr",
        "image": _ls("lidarr"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/lidarr/config /media/music",
            f"docker pull {_ls('lidarr')}",
            (f"docker run -d --name lidarr -p 8686:8686 "
             "-v $HOME/docker/lidarr/config:/config "
             "-v /media/music:/music "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('lidarr')}"),
        ],
        "fix_cmds": ["docker restart lidarr"],
        "reinstall_cmds": [
            "docker stop lidarr 2>/dev/null || true",
            "docker rm   lidarr 2>/dev/null || true",
            f"docker pull {_ls('lidarr')}",
            (f"docker run -d --name lidarr -p 8686:8686 "
             "-v $HOME/docker/lidarr/config:/config "
             "-v /media/music:/music "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('lidarr')}"),
        ],
    },
    {
        "key": "readarr",
        "name": "Readarr",
        "category": "Arr Suite",
        "desc": "Book & audiobook manager — downloads and organizes",
        "port": 8787,
        "container": "readarr",
        "image": _ls("readarr"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/readarr/config /media/books",
            f"docker pull {_ls('readarr')}",
            (f"docker run -d --name readarr -p 8787:8787 "
             "-v $HOME/docker/readarr/config:/config "
             "-v /media/books:/books "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('readarr')}"),
        ],
        "fix_cmds": ["docker restart readarr"],
        "reinstall_cmds": [
            "docker stop readarr 2>/dev/null || true",
            "docker rm   readarr 2>/dev/null || true",
            f"docker pull {_ls('readarr')}",
            (f"docker run -d --name readarr -p 8787:8787 "
             "-v $HOME/docker/readarr/config:/config "
             "-v /media/books:/books "
             "-v $HOME/docker/sabnzbd/downloads:/downloads "
             f"{_puid()} {_RSU} {_ls('readarr')}"),
        ],
    },
    {
        "key": "bazarr",
        "name": "Bazarr",
        "category": "Arr Suite",
        "desc": "Automatic subtitle downloader for Sonarr & Radarr",
        "port": 6767,
        "container": "bazarr",
        "image": _ls("bazarr"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/bazarr/config",
            f"docker pull {_ls('bazarr')}",
            (f"docker run -d --name bazarr -p 6767:6767 "
             "-v $HOME/docker/bazarr/config:/config "
             "-v /media/movies:/movies "
             "-v /media/tv:/tv "
             f"{_puid()} {_RSU} {_ls('bazarr')}"),
        ],
        "fix_cmds": ["docker restart bazarr"],
        "reinstall_cmds": [
            "docker stop bazarr 2>/dev/null || true",
            "docker rm   bazarr 2>/dev/null || true",
            f"docker pull {_ls('bazarr')}",
            (f"docker run -d --name bazarr -p 6767:6767 "
             "-v $HOME/docker/bazarr/config:/config "
             "-v /media/movies:/movies "
             "-v /media/tv:/tv "
             f"{_puid()} {_RSU} {_ls('bazarr')}"),
        ],
    },
    {
        "key": "prowlarr",
        "name": "Prowlarr",
        "category": "Arr Suite",
        "desc": "Indexer manager / proxy — feeds Sonarr, Radarr, etc.",
        "port": 9696,
        "container": "prowlarr",
        "image": _ls("prowlarr"),
        "health_path": "/ping",
        "install_cmds": [
            "mkdir -p $HOME/docker/prowlarr/config",
            f"docker pull {_ls('prowlarr')}",
            (f"docker run -d --name prowlarr -p 9696:9696 "
             "-v $HOME/docker/prowlarr/config:/config "
             f"{_puid()} {_RSU} {_ls('prowlarr')}"),
        ],
        "fix_cmds": ["docker restart prowlarr"],
        "reinstall_cmds": [
            "docker stop prowlarr 2>/dev/null || true",
            "docker rm   prowlarr 2>/dev/null || true",
            f"docker pull {_ls('prowlarr')}",
            (f"docker run -d --name prowlarr -p 9696:9696 "
             "-v $HOME/docker/prowlarr/config:/config "
             f"{_puid()} {_RSU} {_ls('prowlarr')}"),
        ],
    },

    # ── Request Managers ─────────────────────────────────────────────────
    {
        "key": "overseerr",
        "name": "Overseerr",
        "category": "Request Managers",
        "desc": "Media request & discovery tool for Plex",
        "port": 5055,
        "container": "overseerr",
        "image": "sctx/overseerr",
        "health_path": "/api/v1/status",
        "install_cmds": [
            "mkdir -p $HOME/docker/overseerr/config",
            "docker pull sctx/overseerr",
            (f"docker run -d --name overseerr -p 5055:5055 "
             f"-v $HOME/docker/overseerr/config:/app/config {_RSU} sctx/overseerr"),
        ],
        "fix_cmds": ["docker restart overseerr"],
        "reinstall_cmds": [
            "docker stop overseerr 2>/dev/null || true",
            "docker rm   overseerr 2>/dev/null || true",
            "docker pull sctx/overseerr",
            (f"docker run -d --name overseerr -p 5055:5055 "
             f"-v $HOME/docker/overseerr/config:/app/config {_RSU} sctx/overseerr"),
        ],
    },
    {
        "key": "jellyseerr",
        "name": "Jellyseerr",
        "category": "Request Managers",
        "desc": "Media request & discovery tool for Jellyfin / Emby",
        "port": 5056,
        "container": "jellyseerr",
        "image": "fallenbagel/jellyseerr",
        "health_path": "/api/v1/status",
        "install_cmds": [
            "mkdir -p $HOME/docker/jellyseerr/config",
            "docker pull fallenbagel/jellyseerr",
            (f"docker run -d --name jellyseerr -p 5056:5055 "
             f"-v $HOME/docker/jellyseerr/config:/app/config {_RSU} fallenbagel/jellyseerr"),
        ],
        "fix_cmds": ["docker restart jellyseerr"],
        "reinstall_cmds": [
            "docker stop jellyseerr 2>/dev/null || true",
            "docker rm   jellyseerr 2>/dev/null || true",
            "docker pull fallenbagel/jellyseerr",
            (f"docker run -d --name jellyseerr -p 5056:5055 "
             f"-v $HOME/docker/jellyseerr/config:/app/config {_RSU} fallenbagel/jellyseerr"),
        ],
    },

    # ── Monitoring ───────────────────────────────────────────────────────
    {
        "key": "tautulli",
        "name": "Tautulli",
        "category": "Monitoring",
        "desc": "Plex usage statistics, history, and notifications",
        "port": 8181,
        "container": "tautulli",
        "image": _ls("tautulli"),
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/tautulli/config",
            f"docker pull {_ls('tautulli')}",
            (f"docker run -d --name tautulli -p 8181:8181 "
             "-v $HOME/docker/tautulli/config:/config "
             f"{_puid()} {_RSU} {_ls('tautulli')}"),
        ],
        "fix_cmds": ["docker restart tautulli"],
        "reinstall_cmds": [
            "docker stop tautulli 2>/dev/null || true",
            "docker rm   tautulli 2>/dev/null || true",
            f"docker pull {_ls('tautulli')}",
            (f"docker run -d --name tautulli -p 8181:8181 "
             "-v $HOME/docker/tautulli/config:/config "
             f"{_puid()} {_RSU} {_ls('tautulli')}"),
        ],
    },
    {
        "key": "uptime_kuma",
        "name": "Uptime Kuma",
        "category": "Monitoring",
        "desc": "Self-hosted uptime monitor with status pages",
        "port": 3001,
        "container": "uptime-kuma",
        "image": "louislam/uptime-kuma:1",
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/uptime-kuma/data",
            "docker pull louislam/uptime-kuma:1",
            (f"docker run -d --name uptime-kuma -p 3001:3001 "
             f"-v $HOME/docker/uptime-kuma/data:/app/data {_RSU} louislam/uptime-kuma:1"),
        ],
        "fix_cmds": ["docker restart uptime-kuma"],
        "reinstall_cmds": [
            "docker stop uptime-kuma 2>/dev/null || true",
            "docker rm   uptime-kuma 2>/dev/null || true",
            "docker pull louislam/uptime-kuma:1",
            (f"docker run -d --name uptime-kuma -p 3001:3001 "
             f"-v $HOME/docker/uptime-kuma/data:/app/data {_RSU} louislam/uptime-kuma:1"),
        ],
    },
    {
        "key": "netdata",
        "name": "Netdata",
        "category": "Monitoring",
        "desc": "Real-time performance monitoring — CPU, RAM, network, Docker",
        "port": 19999,
        "container": "netdata",
        "image": "netdata/netdata",
        "health_path": "/api/v1/info",
        "install_cmds": [
            "docker pull netdata/netdata",
            (f"docker run -d --name netdata --network host --pid host "
             "-v /proc:/host/proc:ro "
             "-v /sys:/host/sys:ro "
             "-v /etc/os-release:/host/etc/os-release:ro "
             "-v /var/run/docker.sock:/var/run/docker.sock:ro "
             "--cap-add SYS_PTRACE --security-opt apparmor=unconfined "
             f"{_RSU} netdata/netdata"),
        ],
        "fix_cmds": ["docker restart netdata"],
        "reinstall_cmds": [
            "docker stop netdata 2>/dev/null || true",
            "docker rm   netdata 2>/dev/null || true",
            "docker pull netdata/netdata",
            (f"docker run -d --name netdata --network host --pid host "
             "-v /proc:/host/proc:ro "
             "-v /sys:/host/sys:ro "
             "-v /etc/os-release:/host/etc/os-release:ro "
             "-v /var/run/docker.sock:/var/run/docker.sock:ro "
             "--cap-add SYS_PTRACE --security-opt apparmor=unconfined "
             f"{_RSU} netdata/netdata"),
        ],
    },
    {
        "key": "glances",
        "name": "Glances",
        "category": "Monitoring",
        "desc": "Cross-platform system monitoring web dashboard",
        "port": 61208,
        "container": "glances",
        "image": "nicolargo/glances:latest",
        "health_path": "/",
        "install_cmds": [
            "docker pull nicolargo/glances:latest",
            (f"docker run -d --name glances --pid host -p 61208:61208 "
             "-v /var/run/docker.sock:/var/run/docker.sock:ro "
             f"-e GLANCES_OPT=-w {_RSU} nicolargo/glances:latest"),
        ],
        "fix_cmds": ["docker restart glances"],
        "reinstall_cmds": [
            "docker stop glances 2>/dev/null || true",
            "docker rm   glances 2>/dev/null || true",
            "docker pull nicolargo/glances:latest",
            (f"docker run -d --name glances --pid host -p 61208:61208 "
             "-v /var/run/docker.sock:/var/run/docker.sock:ro "
             f"-e GLANCES_OPT=-w {_RSU} nicolargo/glances:latest"),
        ],
    },

    {
        "key": "wud",
        "name": "What's Up Docker",
        "category": "Monitoring",
        "desc": "Monitors Docker images for updates and notifies you",
        "port": 3002,
        "container": "wud",
        "image": "fmartinou/whats-up-docker:latest",
        "health_path": "/api/containers",
        "install_cmds": [
            "mkdir -p $HOME/docker/wud/store",
            "docker pull fmartinou/whats-up-docker:latest",
            (f"docker run -d --name wud -p 3002:3000 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"-v $HOME/docker/wud/store:/store {_RSU} fmartinou/whats-up-docker:latest"),
        ],
        "fix_cmds": ["docker restart wud"],
        "reinstall_cmds": [
            "docker stop wud 2>/dev/null || true",
            "docker rm   wud 2>/dev/null || true",
            "docker pull fmartinou/whats-up-docker:latest",
            (f"docker run -d --name wud -p 3002:3000 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             f"-v $HOME/docker/wud/store:/store {_RSU} fmartinou/whats-up-docker:latest"),
        ],
    },

    {
        "key": "watchstate",
        "name": "Watchstate",
        "category": "Monitoring",
        "desc": "Syncs watched/play state between Plex, Emby, and Jellyfin",
        # Container listens on 8080 internally, but that collides with
        # SABnzbd's default web UI port on the host — map to 8090 instead.
        "port": 8090,
        "container": "watchstate",
        "image": "ghcr.io/arabcoders/watchstate:latest",
        "health_path": "/v1/api/system/healthcheck",
        "install_cmds": [
            "mkdir -p $HOME/docker/watchstate/data",
            "docker pull ghcr.io/arabcoders/watchstate:latest",
            # Image requires --user to match the host UID that owns the bind
            # mount (unlike PUID/PGID-style linuxserver.io images) — detect
            # it live instead of hardcoding, since it varies per server.
            (f'docker run -d --name watchstate -p 8090:8080 '
             '--user "$(id -u):$(id -g)" '
             "-v $HOME/docker/watchstate/data:/config:rw "
             f"{_RSU} ghcr.io/arabcoders/watchstate:latest"),
        ],
        "fix_cmds": ["docker restart watchstate"],
        "reinstall_cmds": [
            "docker stop watchstate 2>/dev/null || true",
            "docker rm   watchstate 2>/dev/null || true",
            "docker pull ghcr.io/arabcoders/watchstate:latest",
            (f'docker run -d --name watchstate -p 8090:8080 '
             '--user "$(id -u):$(id -g)" '
             "-v $HOME/docker/watchstate/data:/config:rw "
             f"{_RSU} ghcr.io/arabcoders/watchstate:latest"),
        ],
    },

    {
        "key":          "fail2ban",
        "name":         "Fail2ban",
        "category":     "Monitoring",
        "desc":         "Intrusion prevention — bans IPs with too many failed auth attempts",
        "port":         None,
        "container":    None,
        "image":        None,
        "health_path":  None,
        "check_cmd":    "which fail2ban-client",
        "version_cmd":  "fail2ban-client --version 2>&1 | head -1",
        "install_cmds": [
            "sudo apt-get update -qq",
            "sudo apt-get install -y fail2ban",
            "sudo systemctl enable fail2ban",
            "sudo systemctl start fail2ban",
        ],
        "fix_cmds": [
            "sudo systemctl restart fail2ban",
        ],
        "reinstall_cmds": [
            "sudo apt-get install -y --reinstall fail2ban",
            "sudo systemctl restart fail2ban",
        ],
        "uninstall_cmds": [
            "sudo systemctl stop fail2ban",
            "sudo systemctl disable fail2ban",
            "sudo apt-get remove -y fail2ban",
        ],
    },

    {
        "key":          "vmstat",
        "name":         "vmstat",
        "category":     "Monitoring",
        "desc":         "Virtual memory statistics — reports on processes, memory, swap, I/O, and CPU (part of procps)",
        "port":         None,
        "container":    None,
        "image":        None,
        "health_path":  None,
        "check_cmd":    "which vmstat",
        "version_cmd":  "vmstat --version 2>&1 | head -1",
        "install_cmds": [
            "sudo apt-get update -qq",
            "sudo apt-get install -y procps",
        ],
        "fix_cmds": [],
        "reinstall_cmds": [
            "sudo apt-get install -y --reinstall procps",
        ],
        "uninstall_cmds": [
            "sudo apt-get remove -y procps",
        ],
    },

    # ── Dashboard ────────────────────────────────────────────────────────
    {
        "key": "homarr",
        "name": "Homarr",
        "category": "Dashboard",
        "desc": "Sleek home-lab dashboard with Docker integration",
        "port": 7575,
        "container": "homarr",
        "image": "ghcr.io/homarr-labs/homarr:latest",
        "health_path": "/",
        "install_cmds": [
            "mkdir -p $HOME/docker/homarr/config $HOME/docker/homarr/data",
            "docker pull ghcr.io/homarr-labs/homarr:latest",
            (f"docker run -d --name homarr -p 7575:7575 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             "-v $HOME/docker/homarr/config:/app/data/configs "
             "-v $HOME/docker/homarr/data:/data "
             f"{_RSU} ghcr.io/homarr-labs/homarr:latest"),
        ],
        "fix_cmds": ["docker restart homarr"],
        "reinstall_cmds": [
            "docker stop homarr 2>/dev/null || true",
            "docker rm   homarr 2>/dev/null || true",
            "docker pull ghcr.io/homarr-labs/homarr:latest",
            (f"docker run -d --name homarr -p 7575:7575 "
             "-v /var/run/docker.sock:/var/run/docker.sock "
             "-v $HOME/docker/homarr/config:/app/data/configs "
             "-v $HOME/docker/homarr/data:/data "
             f"{_RSU} ghcr.io/homarr-labs/homarr:latest"),
        ],
    },
]

# key → app dict for fast lookup
APP_BY_KEY = {app["key"]: app for app in APP_REGISTRY}


def _ufw_ports_for(app: dict) -> list:
    """
    Port specs to open in UFW for this app, e.g. ["32400/tcp", "32412:32414/udp"].
    An explicit "ufw_ports" list on the app wins; otherwise falls back to the
    single declared web port (covers the common -p <port>:<port> Docker case).
    """
    if "ufw_ports" in app:
        return app["ufw_ports"]
    port = app.get("port")
    return [f"{port}/tcp"] if port else []

# Known systemd / init.d service names for natively-installed apps.
# These are tried in order when no Docker container is found for that app.
# Multiple names cover different distros / install methods.
_KNOWN_SERVICES = {
    "emby":                ["emby-server"],
    "plex":                ["plexmediaserver", "plexmediaserver.service"],
    "jellyfin":            ["jellyfin"],
    "sabnzbd":             ["sabnzbdplus", "sabnzbd"],
    "qbittorrent":         ["qbittorrent-nox", "qbittorrent"],
    "sonarr":              ["sonarr"],
    "radarr":              ["radarr"],
    "lidarr":              ["lidarr"],
    "readarr":             ["readarr"],
    "bazarr":              ["bazarr"],
    "prowlarr":            ["prowlarr", "Prowlarr"],
    "overseerr":           ["overseerr"],
    "jellyseerr":          ["jellyseerr"],
    "tautulli":            ["tautulli"],
    "uptime_kuma":         ["uptime-kuma", "uptime_kuma"],
    "netdata":             ["netdata"],
    "glances":             ["glances"],
    # Infrastructure apps are Docker-only; no native service names needed.
}


# ---------------------------------------------------------------------------
# InstallManager
# ---------------------------------------------------------------------------

class InstallManager:
    """
    Runs all SSH commands for checking, installing, and fixing apps.
    All methods are blocking and intended to be called from background threads.
    """

    def __init__(self, ssh):
        self.ssh = ssh

    # ── Status check ────────────────────────────────────────────────────

    def check_docker_available(self):
        """True when Docker daemon is reachable."""
        out, _, _ = self.ssh.run("docker info >/dev/null 2>&1 && echo ok || echo fail")
        return out.strip() == "ok"

    def check_app(self, app: dict) -> dict:
        """
        Full status check for one app.
        Returns: {"state": str, "version": str, "restart_count": int, "method": str}
        state: not_installed | stopped | running | unhealthy | error
        method: docker | service | none
        """
        key = app["key"]

        # ── Docker Engine is a special case ──────────────────────────
        if key == "docker":
            out, _, _ = self.ssh.run("docker --version 2>/dev/null || echo not_found")
            stripped = out.strip()
            if not stripped or "not_found" in stripped:
                return {"state": "not_installed", "version": "", "method": "none", "restart_count": 0}
            out2, _, _ = self.ssh.run(
                "docker info >/dev/null 2>&1 && echo running || echo stopped")
            state = "running" if "running" in out2 else "stopped"
            version = ""
            try:
                version = stripped.split("version")[-1].split(",")[0].strip()
            except Exception:
                pass
            return {"state": state, "version": version, "method": "service", "restart_count": 0}

        container = app.get("container")
        if not container:
            # ── Tier 3: binary / package check ──────────────────────
            check_cmd = app.get("check_cmd")
            if check_cmd:
                _, _, chk_code = self.ssh.run(f"{check_cmd} 2>/dev/null")
                if chk_code == 0:
                    version = ""
                    vcmd = app.get("version_cmd")
                    if vcmd:
                        vout, _, _ = self.ssh.run(f"{vcmd} 2>/dev/null")
                        version = vout.strip().splitlines()[0] if vout.strip() else ""
                    return {"state": "running", "version": version,
                            "method": "binary", "restart_count": 0}
                return {"state": "not_installed", "version": "",
                        "method": "none", "restart_count": 0}
            return {"state": "unknown", "version": "", "method": "none", "restart_count": 0}

        # ── Docker container check ───────────────────────────────────
        fmt = "{{.State.Status}}|{{.Config.Image}}|{{.RestartCount}}"
        out, _, _ = self.ssh.run(
            f"docker inspect --format '{fmt}' {shlex.quote(container)} 2>/dev/null || echo not_found")
        raw = out.strip()

        if raw == "not_found" or not raw:
            # ── Tier 2: native systemd service check ────────────────
            # Only trust two authoritative signals: Docker (above) and
            # systemd. pgrep and port probes produce too many false
            # positives (log-rotation jobs, other apps on the same port,
            # leftover unit files with unrelated processes).
            for svc in _KNOWN_SERVICES.get(key, []):
                q = shlex.quote(svc)
                out2, _, _ = self.ssh.run(
                    f"systemctl is-active {q} 2>/dev/null; true")
                svc_state = out2.strip()
                if svc_state == "active":
                    return {"state": "running", "version": "", "method": "service", "restart_count": 0}
                if svc_state in ("inactive", "failed"):
                    # Confirm the unit file actually exists so we don't
                    # misread systemd's generic "inactive" for unknown units.
                    chk, _, _ = self.ssh.run(
                        f"systemctl list-unit-files {q}.service 2>/dev/null "
                        f"| grep -q {shlex.quote(svc)} && echo found || echo no")
                    if chk.strip() == "found":
                        return {"state": "stopped", "version": "", "method": "service", "restart_count": 0}

            # No Docker container, no known systemd unit → not installed.
            return {"state": "not_installed", "version": "", "method": "none", "restart_count": 0}

        parts = raw.split("|")
        docker_state = parts[0] if parts else "unknown"
        restart_count = 0
        try:
            restart_count = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            pass

        if docker_state == "running":
            healthy = self._health_check(app)
            state   = "running" if healthy else "unhealthy"
        elif docker_state in ("exited", "dead", "created", "paused"):
            state = "stopped"
        else:
            state = "stopped"

        return {
            "state": state,
            "version": "",
            "method": "docker",
            "restart_count": restart_count,
        }

    def _health_check(self, app: dict) -> bool:
        """
        Runs a curl health probe on the server.
        Returns True when the HTTP status is 2xx, 3xx, 400, 401, or 403
        (apps often gate the root with auth — a 401 means the app is alive).
        """
        port = app.get("port")
        path = app.get("health_path")
        if not port or not path:
            return True  # no probe defined — trust Docker state
        url = f"http://localhost:{port}{path}"
        out, _, _ = self.ssh.run(
            f"curl -sf -o /dev/null -w '%{{http_code}}' --max-time 6 '{url}' 2>/dev/null || echo 000")
        code = out.strip()
        return code[:1] in ("2", "3") or code in ("400", "401", "403")

    def _wait_for_health(self, app: dict, timeout: int, interval: int = 2) -> bool:
        """
        If the app has a real HTTP health probe configured, poll it every
        `interval`s up to `timeout`s and return as soon as it passes —
        usually much faster than always waiting the full timeout, since
        most containers come back up in a second or two. Apps with no
        health_path/port have nothing real to poll, so just wait the full
        settle time once, same as before.
        """
        if not app.get("port") or not app.get("health_path"):
            time.sleep(timeout)
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._health_check(app):
                return True
            time.sleep(interval)
        return self._health_check(app)

    # ── Operations ──────────────────────────────────────────────────────

    def _run_cmds(self, cmds: list, log) -> bool:
        """
        Execute shell commands in sequence.
        log(text) is called with each line of output.
        Returns True only if every command exits 0.
        """
        for cmd in cmds:
            log(f"  $ {cmd}\n", "cmd")
            stripped = cmd.lstrip()
            if stripped.startswith("sudo "):
                out, err, code = self.ssh.run_sudo(stripped[5:])
            else:
                out, err, code = self.ssh.run(f"{cmd} 2>&1")
            combined = (out or "").strip()
            if combined:
                log(combined + "\n")
            if code != 0:
                log(f"  ✗ exit {code}\n", "error")
                return False
        return True

    def _open_firewall_ports(self, app: dict, log) -> None:
        """
        Best-effort: open this app's ports in UFW if UFW is installed and active.
        Idempotent (ufw allow on an existing rule is a no-op) and never fails
        the calling operation — a missing/inactive firewall is not an error.
        """
        ports = _ufw_ports_for(app)
        if not ports:
            return
        status, _, code = self.ssh.run("which ufw >/dev/null 2>&1 && echo present || echo absent")
        if code != 0 or "present" not in status:
            return
        active, _, _ = self.ssh.run_sudo("ufw status | head -1")
        if "active" not in active.lower():
            return
        log(f"  Opening firewall port(s) for {app['name']}: {', '.join(ports)}\n")
        for spec in ports:
            out, err, code = self.ssh.run_sudo(f"ufw allow {shlex.quote(spec)}")
            if code != 0:
                log(f"  ✗ ufw allow {spec} failed: {(err or out).strip()}\n", "warn")

    def install(self, app: dict, log) -> bool:
        """Install the app from scratch. Safe to call even if already installed
        (pre-flight check returns True immediately)."""
        existing = self.check_app(app)
        if existing["state"] != "not_installed":
            log(f"  Already {existing['state']} — skipping install.\n", "warn")
            return True
        cmds = app.get("install_cmds", [])
        if not cmds:
            log("  No install commands defined for this app.\n", "warn")
            return False
        ok = self._run_cmds(cmds, log)
        if ok:
            self._open_firewall_ports(app, log)
        return ok

    def start(self, app: dict, log) -> bool:
        """Start a stopped container or native service."""
        container = app.get("container")
        key = app["key"]

        # Try Docker first — only if the container actually exists
        if container:
            qc = shlex.quote(container)
            _, _, inspect_code = self.ssh.run(
                f"docker inspect {qc} >/dev/null 2>&1")
            if inspect_code == 0:
                log(f"  $ docker start {container}\n", "cmd")
                out, _, code = self.ssh.run(f"docker start {qc} 2>&1")
                if (out or "").strip():
                    log(out.strip() + "\n")
                if code != 0:
                    log(f"  ✗ exit {code}\n", "error")
                return code == 0

        # Fall back to systemctl for native installs
        for svc in _KNOWN_SERVICES.get(key, []):
            q = shlex.quote(svc)
            chk, _, _ = self.ssh.run(
                f"systemctl list-unit-files {q}.service 2>/dev/null | grep -q {q} && echo found || echo no")
            if chk.strip() != "found":
                continue
            log(f"  $ sudo systemctl start {svc}\n", "cmd")
            out, _, code = self.ssh.run_sudo(f"systemctl start {q}")
            if (out or "").strip():
                log(out.strip() + "\n")
            if code != 0:
                log(f"  ✗ exit {code}\n", "error")
            return code == 0

        log("  ✗ No Docker container or known service found to start.\n", "error")
        return False

    def fix(self, app: dict, log) -> bool:
        """
        Tiered repair — only touches the named container, preserves volumes.

        Tier 1: docker restart — fast, non-destructive
        Tier 2: pull latest image + recreate container (volumes untouched)
        Fallback: dump recent logs for manual review
        """
        # Retroactively cover apps installed before ufw_ports existed, or
        # whose rule was never added — cheap and idempotent, so always run it.
        self._open_firewall_ports(app, log)

        container = app.get("container")
        if not container:
            # Binary/package tools: fix = reinstall
            cmds = app.get("reinstall_cmds", app.get("install_cmds", []))
            if cmds:
                return self._run_cmds(cmds, log)
            return False

        # Tier 1: restart
        log(f"  [Tier 1] Restarting {container}…\n")
        out, _, code = self.ssh.run(f"docker restart {shlex.quote(container)} 2>&1")
        if (out or "").strip():
            log(out.strip() + "\n")
        if self._wait_for_health(app, timeout=8):
            log("  ✓ Healthy after restart.\n", "ok")
            return True

        # Tier 2: pull + recreate (config volumes preserved by bind mounts)
        log(f"  [Tier 2] Pulling fresh image and recreating {container}…\n")
        reinstall_ok = self._run_cmds(app.get("reinstall_cmds", []), log)
        if not reinstall_ok:
            return False
        if self._wait_for_health(app, timeout=12):
            log("  ✓ Healthy after image refresh.\n", "ok")
            return True

        # Fallback: show logs for manual diagnosis
        log("\n  Still unhealthy — recent container logs:\n", "warn")
        log_out, _, _ = self.ssh.run(f"docker logs --tail=40 {shlex.quote(container)} 2>&1")
        log((log_out or "").strip() + "\n")
        return False

    def reinstall(self, app: dict, log) -> bool:
        """
        Pull latest image and recreate the container.
        Config bind-mounted volumes ($HOME/docker/<name>/config/) are preserved.
        """
        image = app.get("image", "")
        if image:
            log(f"  Pulling latest image: {image}\n")
            self._run_cmds([f"docker pull {shlex.quote(image)}"], log)
        cmds = app.get("reinstall_cmds", [])
        if not cmds:
            log("  No reinstall commands defined.\n", "warn")
            return False
        ok = self._run_cmds(cmds, log)
        if ok:
            self._open_firewall_ports(app, log)
        return ok

    def uninstall(self, app: dict, log) -> bool:
        """
        Remove the app's Docker container (config volumes are preserved).
        Falls back to systemctl disable --now for native services.
        """
        container = app.get("container")
        key = app["key"]

        if container:
            qc = shlex.quote(container)
            _, _, inspect_code = self.ssh.run(
                f"docker inspect {qc} >/dev/null 2>&1")
            if inspect_code == 0:
                log(f"  $ docker stop {container}\n", "cmd")
                out, _, _ = self.ssh.run(f"docker stop {qc} 2>&1")
                if (out or "").strip():
                    log(out.strip() + "\n")

                log(f"  $ docker rm {container}\n", "cmd")
                out, _, code = self.ssh.run(f"docker rm {qc} 2>&1")
                if (out or "").strip():
                    log(out.strip() + "\n")
                if code == 0:
                    log(f"  ✓ Container removed. Config in $HOME/docker/{key}/config/ is preserved.\n", "ok")
                    return True
                log(f"  ✗ exit {code}\n", "error")
                return False
            log(f"  Docker container '{container}' not found — checking native service.\n", "warn")

        for svc in _KNOWN_SERVICES.get(key, []):
            q = shlex.quote(svc)
            chk, _, _ = self.ssh.run(
                f"systemctl list-unit-files {q}.service 2>/dev/null "
                f"| grep -q {q} && echo found || echo no")
            if chk.strip() != "found":
                continue
            log(f"  $ sudo systemctl disable --now {svc}\n", "cmd")
            out, _, code = self.ssh.run_sudo(f"systemctl disable --now {q}")
            if (out or "").strip():
                log(out.strip() + "\n")
            if code == 0:
                log(f"  ✓ Service {svc} disabled and stopped.\n", "ok")
            else:
                log(f"  ✗ exit {code}\n", "error")
            return code == 0

        # Fallback: app-defined uninstall commands (e.g. apt-get remove)
        uninstall_cmds = app.get("uninstall_cmds", [])
        if uninstall_cmds:
            return self._run_cmds(uninstall_cmds, log)

        log("  ✗ No container or known service found to uninstall.\n", "error")
        return False
