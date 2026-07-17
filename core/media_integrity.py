# core/media_integrity.py
"""
Finds corrupt/unplayable video files in the Sonarr/Radarr-managed library by
running ffprobe against every video file on disk (via SSH) and flagging
anything whose container/stream metadata fails to parse.

Scanning a real library one SSH round trip per file would mean thousands of
round trips, so run_scan() instead pipes a small Python script through
python3 on the server (python3 is confirmed present there — see the wtmp
reader in ui/sessions_tab.py for the same base64-encoded-script pattern) that
walks the tree and runs ffprobe locally, emitting one JSON line per file.
That sidesteps shell-escaping problems entirely: filenames and ffprobe error
text land inside json.dumps() rather than a hand-rolled delimiter format.

This module is pure/read-only — it never deletes or modifies anything on the
server.
"""

import base64
import json
import shlex

from core.arr_client import api_get as _api_get

_VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".wmv", ".m4v", ".mov")

# Runs on the server via python3. Per-file ffprobe timeout matters: a
# genuinely corrupt/truncated file is exactly the kind of input that can
# make ffprobe hang instead of failing fast.
_SCAN_PY = r'''
import json, os, subprocess, sys

exts = {exts!r}
roots = sys.argv[1:]

for root in roots:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            try:
                proc = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", path],
                    capture_output=True, text=True, timeout=30)
                duration = proc.stdout.strip()
                err = proc.stderr.strip()
                ok = proc.returncode == 0 and bool(duration)
            except subprocess.TimeoutExpired:
                ok, duration, err = False, "", "ffprobe timed out after 30s"
            except Exception as e:
                ok, duration, err = False, "", str(e)
            print(json.dumps({{"path": path, "size": size, "ok": ok,
                               "duration": duration, "error": err[:300]}}))
'''.format(exts=set(_VIDEO_EXTS))


def get_scan_roots(sonarr_cfg: dict, radarr_cfg: dict) -> tuple:
    """
    sonarr_cfg / radarr_cfg: {"host", "port", "apikey"} — pass an empty
    apikey to skip that app entirely (contributes nothing, not an error).

    Returns (roots, errors) — roots is a de-duplicated list of root-folder
    paths pulled from whichever app(s) are configured.
    """
    roots = []
    errors = []

    for cfg, name in ((sonarr_cfg, "sonarr"), (radarr_cfg, "radarr")):
        if not cfg.get("apikey"):
            continue
        try:
            for entry in (_api_get(cfg["host"], cfg["port"], cfg["apikey"], "rootfolder") or []):
                path = entry.get("path")
                if path and path not in roots:
                    roots.append(path)
        except Exception as e:
            errors.append("{}: {}".format(name, e))

    return roots, errors


def run_scan(ssh, roots: list) -> dict:
    """
    One SSH round trip for the whole library. Returns:
        {"files": [{"path", "size", "ok", "duration", "error"}, ...], "error": None}
    or {"files": [], "error": "..."} if the remote script itself failed to run
    (e.g. python3 missing) — distinct from a per-file ffprobe failure, which
    is recorded as ok=False on that file instead.
    """
    if not roots:
        return {"files": [], "error": None}

    b64 = base64.b64encode(_SCAN_PY.encode()).decode()
    quoted_roots = " ".join(shlex.quote(r) for r in roots)
    cmd = "echo {} | base64 -d | python3 - {} 2>&1".format(shlex.quote(b64), quoted_roots)
    out, err, code = ssh.run(cmd)

    files = []
    for line in (out or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            files.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue

    if code != 0 and not files:
        return {"files": [], "error": (err or out or "scan script failed").strip()[:300]}
    return {"files": files, "error": None}


def verify_file(ssh, path: str) -> dict:
    """
    On-demand deeper check for a single file: actually decodes the stream
    (ffprobe alone only reads container/stream metadata, so it can miss
    mid-file frame corruption). Deliberately not run library-wide — a full
    decode is far slower than a metadata read.
    """
    if not path or not path.startswith("/"):
        return {"ok": False, "error": "Refusing to verify: not a plain absolute file path."}
    cmd = "timeout 60 ffmpeg -v error -xerror -i {} -f null - 2>&1".format(shlex.quote(path))
    out, err, code = ssh.run(cmd)
    text = (out or err or "").strip()
    return {"ok": code == 0 and not text, "error": text[:500]}


def diff_new_corrupt(baseline: list, files: list) -> tuple:
    """
    Compare this run's corrupt-file paths against the last-known baseline so
    a scheduled scan only alerts about genuinely NEW breakage, not the same
    still-broken file every night.

    baseline: [path, ...] corrupt as of the last check.
    files:    this run's run_scan()["files"] list.

    Returns (new_baseline, newly_corrupt):
      new_baseline:   [path, ...] to persist for next time.
      newly_corrupt:  [file dict, ...] — paths that are corrupt now but
                       weren't in the baseline.
    """
    baseline_set = set(baseline)
    corrupt_now = [f for f in files if not f.get("ok")]
    corrupt_paths = {f["path"] for f in corrupt_now}
    newly_corrupt = [f for f in corrupt_now if f["path"] not in baseline_set]
    return sorted(corrupt_paths), newly_corrupt
