# core/plugin_updater.py
"""
Checks and updates the Emby-side SSE plugin that Tracearr's real-time
integration depends on: https://github.com/Tracearr/Media-Server-SSE

Unlike the apps in install_manager.py this isn't a container or a systemd
service of its own — it's a single DLL dropped into Emby's plugins folder,
loaded at Emby startup. So the shape of "check" and "update" here is
different from InstallManager's docker/service model:

  • Installed version comes from Emby's own REST API (GET /emby/Plugins),
    not from inspecting the file on disk — Emby is the source of truth for
    what it actually loaded.
  • Latest version comes from the plugin's GitHub Releases.
  • "Update" is a straight SSH file swap (backup old DLL, drop in the new
    one, fix ownership) followed by an emby-server restart to load it.

This mirrors the steps validated by hand against the real server on
2026-08-14: download the release zip, extract, `sudo cp` into
/var/lib/emby/plugins/, `chown emby:emby`, `systemctl restart emby-server`.
"""

import json
import re
import shlex
import urllib.request

GITHUB_REPO  = "Tracearr/Media-Server-SSE"
PLUGIN_DLL   = "Emby.Plugin.Sse.dll"
PLUGIN_DIR   = "/var/lib/emby/plugins"
_ASSET_NAME  = "Tracearr.Sse.Emby_{version}.zip"
# Matched case-insensitively against Emby's /Plugins listing — the plugin's
# display name in Emby is "Tracearr SSE" but this is deliberately loose so
# a rename upstream doesn't silently break detection.
_NAME_HINT   = "sse"


def _http_json(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_installed_version(emby_host: str, emby_port, emby_apikey: str) -> str:
    """Installed plugin version per Emby itself. "" if not found/unreachable."""
    if not emby_apikey:
        return ""
    url = f"http://{emby_host}:{emby_port}/emby/Plugins"
    try:
        plugins = _http_json(url, {"X-Emby-Token": emby_apikey})
    except Exception:
        return ""
    for p in plugins or []:
        if _NAME_HINT in str(p.get("Name", "")).lower():
            return str(p.get("Version", ""))
    return ""


def get_latest_version() -> str:
    """Latest release tag from GitHub, without the leading 'v'. "" on failure."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        data = _http_json(url, {"Accept": "application/vnd.github+json",
                                 "User-Agent": "media-server-manager"})
    except Exception:
        return ""
    return str(data.get("tag_name", "")).lstrip("vV")


def _version_tuple(v: str):
    return tuple(int(c) for c in re.split(r"[.\-]", v or "") if c.isdigit())


def is_update_available(installed: str, latest: str) -> bool:
    if not installed or not latest:
        return False
    it, lt = _version_tuple(installed), _version_tuple(latest)
    # Emby reports a trailing ".0" build component GitHub's tag doesn't
    # (e.g. installed "0.4.1.0" vs latest tag "0.4.1") — pad the shorter
    # tuple so that isn't mistaken for a real version difference.
    n = max(len(it), len(lt))
    it += (0,) * (n - len(it))
    lt += (0,) * (n - len(lt))
    return lt > it


def check(config_manager) -> dict:
    """
    Full status check against the active server's configured Emby instance.
    Returns {"installed": str, "latest": str, "update_available": bool, "error": str|None}
    """
    host, port, apikey = (config_manager.emby_host,
                           config_manager.emby_port,
                           config_manager.emby_apikey)
    if not apikey:
        return {"installed": "", "latest": "", "update_available": False,
                "error": "No Emby API key configured"}

    installed = get_installed_version(host, port, apikey)
    latest    = get_latest_version()

    if not installed:
        return {"installed": "", "latest": latest, "update_available": False,
                "error": "SSE plugin not installed, or Emby unreachable"}
    if not latest:
        return {"installed": installed, "latest": "", "update_available": False,
                "error": "Could not reach GitHub to check the latest version"}
    return {"installed": installed, "latest": latest,
            "update_available": is_update_available(installed, latest), "error": None}


def update(ssh, latest_version: str, log) -> bool:
    """
    Downloads the given release version on the server, swaps the plugin DLL
    in, and restarts emby-server to load it. `log(text, tag=None)` is called
    with progress lines, same convention as InstallManager._run_cmds.
    Returns True only if every step succeeded.
    """
    asset   = _ASSET_NAME.format(version=latest_version)
    url     = (f"https://github.com/{GITHUB_REPO}/releases/download/"
               f"v{latest_version}/{asset}")
    tmp_zip = "/tmp/tracearr_sse_emby_update.zip"
    tmp_dir = "/tmp/tracearr_sse_emby_update"

    def _step(desc, out, err, code, fatal=True):
        if (out or "").strip():
            log(out.strip() + "\n")
        if code != 0:
            log(f"  ✗ {desc} failed: {(err or out).strip()}\n", "error" if fatal else "warn")
        return code == 0

    log(f"  Downloading {asset}…\n")
    out, err, code = ssh.run(f"curl -sL -f -o {tmp_zip} {shlex.quote(url)}")
    if not _step("Download", out, err, code):
        return False

    log("  Extracting…\n")
    out, err, code = ssh.run(
        f"rm -rf {tmp_dir} && mkdir -p {tmp_dir} && unzip -o -q {tmp_zip} -d {tmp_dir} "
        f"&& test -f {tmp_dir}/{PLUGIN_DLL}")
    if not _step("Extract", out, err, code):
        return False

    # Non-fatal: a missing backup shouldn't block the update, just means
    # there was nothing to preserve (e.g. first-ever install).
    out, err, code = ssh.run_sudo(
        f"cp {PLUGIN_DIR}/{PLUGIN_DLL} /tmp/{PLUGIN_DLL}.bak 2>/dev/null || true")
    _step("Backup", out, err, code, fatal=False)

    log("  Installing new plugin version…\n")
    out, err, code = ssh.run_sudo(
        f"cp {tmp_dir}/{PLUGIN_DLL} {PLUGIN_DIR}/{PLUGIN_DLL} "
        f"&& chown emby:emby {PLUGIN_DIR}/{PLUGIN_DLL} "
        f"&& chmod 644 {PLUGIN_DIR}/{PLUGIN_DLL}")
    if not _step("Install", out, err, code):
        return False

    log("  Restarting emby-server…\n")
    out, err, code = ssh.run_sudo("systemctl restart emby-server")
    if not _step("Restart", out, err, code):
        return False

    ssh.run(f"rm -rf {tmp_zip} {tmp_dir}")
    log("  ✓ Plugin updated and Emby restarted.\n", "ok")
    return True
