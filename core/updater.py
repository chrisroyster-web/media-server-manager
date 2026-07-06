# core/updater.py
"""
GitHub release checker and installer downloader for the self-update feature.

To configure: set GITHUB_REPO to your "owner/repo" GitHub repository.
The updater expects GitHub releases to have a Windows installer asset whose
filename ends with .exe  (e.g. AllClearServerServices_v2.0.0_Setup.exe).
"""

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# CONFIGURE THIS for your repository
# ---------------------------------------------------------------------------
GITHUB_REPO = "your-github-org/all-clear-server-services"

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------
_API_URL = "https://api.github.com/repos/{}/releases/latest".format(GITHUB_REPO)
_TIMEOUT_API  = 10   # seconds for version check
_TIMEOUT_DL   = 120  # seconds for asset download (connection; stream is chunked)
_CHUNK        = 32768
_UA           = "AllClearServerServices-Updater"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """Return False if the GitHub repo hasn't been set to a real value."""
    return (GITHUB_REPO and
            "/" in GITHUB_REPO and
            not GITHUB_REPO.startswith("your-"))


def parse_version(v: str) -> tuple:
    """'v1.2.3' or '1.2.3' → (1, 2, 3).  Extra components are silently dropped."""
    try:
        return tuple(int(x) for x in v.lstrip("v").split(".")[:3])
    except Exception:
        return (0, 0, 0)


def is_newer(latest_tag: str, current: str) -> bool:
    """True when latest_tag is strictly newer than current."""
    try:
        return parse_version(latest_tag) > parse_version(current)
    except Exception:
        return False


def check_latest_release() -> dict | None:
    """
    Call the GitHub Releases API and return the latest release dict, or None
    on any network / parse failure.  Never raises.
    """
    if not is_configured():
        return None
    try:
        req = urllib.request.Request(
            _API_URL,
            headers={
                "User-Agent": _UA,
                "Accept":     "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_API) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def find_installer_asset(release: dict) -> dict | None:
    """Return the first .exe asset in a release dict, or None."""
    for asset in release.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            return asset
    return None


def download_to_temp(url: str,
                     total_hint: int = 0,
                     on_progress=None,
                     expected_digest: str | None = None,
                     on_error=None) -> str | None:
    """
    Stream-download *url* to a fixed temp path.
    on_progress(bytes_done, total_bytes) is called after every chunk.
    total_hint comes from the GitHub asset metadata (used when the CDN
    redirect drops the Content-Length header).

    expected_digest, when given, is the GitHub release asset's "digest"
    field (e.g. "sha256:<hex>"). The downloaded file's SHA-256 is checked
    against it before the path is returned; a mismatch deletes the file
    and fails the download rather than handing back a possibly-tampered
    installer. Assets without a published digest are not verified (nothing
    to check against) — same as before this was added.

    on_error(reason: str), when given, is called with a short human-readable
    explanation on failure — lets the caller distinguish "network problem"
    from "integrity check failed" instead of just getting None either way.

    Returns the local file path on success, None on any failure. Never raises.
    """
    dest = os.path.join(tempfile.gettempdir(), "AllClearServerServices_Update.exe")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        hasher = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=_TIMEOUT_DL) as resp:
            total = int(resp.headers.get("Content-Length") or total_hint or 0)
            done  = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)

        if expected_digest:
            algo, _, expected_hex = expected_digest.partition(":")
            if algo.lower() == "sha256" and expected_hex:
                if hasher.hexdigest().lower() != expected_hex.lower().strip():
                    try:
                        os.unlink(dest)
                    except Exception:
                        pass
                    if on_error:
                        on_error(
                            "Downloaded file failed its integrity check "
                            "(SHA-256 mismatch) — refusing to run it. This "
                            "could mean a corrupted download or a tampered "
                            "release asset. Try again, and if it keeps "
                            "happening, do not install it.")
                    return None

        return dest
    except Exception:
        try:
            os.unlink(dest)
        except Exception:
            pass
        if on_error:
            on_error("Download failed.")
        return None


def launch_installer_and_exit(installer_path: str, app_exe_path: str) -> None:
    """
    Write a self-deleting batch file that:
      1. Waits 2 s for this process to fully exit
      2. Runs the Inno Setup installer silently (UAC prompt handles elevation)
      3. Restarts the updated application
      4. Deletes itself

    Then spawns the batch as a fully detached process and returns immediately.
    The caller is responsible for calling sys.exit() / app.destroy() after this.
    """
    batch = os.path.join(tempfile.gettempdir(), "acss_update_run.bat")
    lines = [
        "@echo off",
        "timeout /t 2 /nobreak >nul",
        '"{}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART'.format(installer_path),
    ]
    if app_exe_path and os.path.isabs(app_exe_path):
        lines.append('if exist "{exe}" start "" "{exe}"'.format(exe=app_exe_path))
    lines.append('del "%~f0"')

    with open(batch, "w") as fh:
        fh.write("\r\n".join(lines) + "\r\n")

    subprocess.Popen(
        ["cmd", "/c", batch],
        creationflags=(subprocess.DETACHED_PROCESS |
                       subprocess.CREATE_NEW_PROCESS_GROUP),
        close_fds=True,
    )
