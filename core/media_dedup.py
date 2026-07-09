# core/media_dedup.py
"""
Finds duplicate/orphaned video files by comparing what's actually on disk
(via SSH) against what Sonarr/Radarr's own API says is the current file for
each episode/movie. Scanning is pure/read-only; delete_file() below is the
one operation that touches disk, and it's deliberately narrow — one
absolute path at a time, no globbing/recursion — so the UI's confirmation
step (see ui/media_dedup_tab.py) is the only thing standing between a click
and a real file deletion, with no room for a wildcard mistake to widen it.

Under normal Sonarr/Radarr operation (delete-on-upgrade is the default), a
genuine duplicate *in their database* is rare — what actually happens is a
leftover file sits on disk outside what the API points at, which is the same
thing as an "orphan." So both cases are found the same way: list every video
file on disk, group it with its siblings for the *same single* episode/movie,
and flag any group with more than one file.

Grouping is NOT simply "by folder" — Sonarr's convention is one folder per
*season*, holding every distinct episode's file together, so a normal
20-episode season folder would otherwise look like one giant false-positive
group. TV files are grouped by (folder, episode number) parsed from the
filename instead; Radarr's one-movie-per-folder convention means folder
alone is the right grouping key there.
"""

import posixpath
import re
import shlex

from core.arr_client import api_get as _api_get

_VIDEO_EXTS = ("*.mkv", "*.mp4", "*.avi", "*.ts", "*.m2ts", "*.wmv")

_EPISODE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')


def find_duplicate_and_orphaned_media(ssh, sonarr_cfg: dict, radarr_cfg: dict) -> dict:
    """
    sonarr_cfg / radarr_cfg: {"host", "port", "apikey"} — pass an empty
    apikey to skip that app entirely (contributes nothing, not an error).

    Returns {"groups": [...], "errors": [...]}. Each group:
      {"folder", "app", "files": [{"path", "size", "tracked"}], "extra_bytes"}
    Only folders with 2+ video files are included.
    """
    groups = []
    errors = []

    if sonarr_cfg.get("apikey"):
        try:
            groups += _scan_app(ssh, sonarr_cfg, "sonarr")
        except Exception as e:
            errors.append("sonarr: {}".format(e))

    if radarr_cfg.get("apikey"):
        try:
            groups += _scan_app(ssh, radarr_cfg, "radarr")
        except Exception as e:
            errors.append("radarr: {}".format(e))

    return {"groups": groups, "errors": errors}


def _scan_app(ssh, app_cfg: dict, app_name: str) -> list:
    host, port, apikey = app_cfg["host"], app_cfg["port"], app_cfg["apikey"]

    roots = _api_get(host, port, apikey, "rootfolder")
    if app_name == "sonarr":
        tracked, known_folders = _sonarr_tracked_paths(host, port, apikey), None
    else:
        tracked, known_folders = _radarr_tracked_paths_and_folders(host, port, apikey)

    groups = []
    for root in roots or []:
        path = root.get("path")
        if not path:
            continue
        on_disk = _list_video_files(ssh, path)
        groups += _group_files(on_disk, tracked, app_name, known_folders)
    return groups


def _sonarr_tracked_paths(host, port, apikey) -> set:
    """Sonarr's bulk /series payload doesn't embed file paths — one
    follow-up /episodefile?seriesId=X call per series is required."""
    tracked = set()
    for series in (_api_get(host, port, apikey, "series") or []):
        sid = series.get("id")
        if sid is None:
            continue
        for ep_file in (_api_get(host, port, apikey,
                                  "episodefile?seriesId={}".format(sid)) or []):
            if ep_file.get("path"):
                tracked.add(ep_file["path"])
    return tracked


def _radarr_tracked_paths_and_folders(host, port, apikey):
    """
    Radarr embeds movieFile directly in /movie — no follow-up call needed.
    Also returns each movie's own folder (movie.path) — needed because not
    every library uses one-subfolder-per-movie; some place files directly
    in the root, and grouping "by folder" there would lump every unrelated
    movie in the root together into one nonsensical group.
    """
    tracked = set()
    known_folders = set()
    for movie in (_api_get(host, port, apikey, "movie") or []):
        movie_file = movie.get("movieFile") or {}
        if movie_file.get("path"):
            tracked.add(movie_file["path"])
        if movie.get("path"):
            known_folders.add(movie["path"])
    return tracked, known_folders


def _list_video_files(ssh, root_path: str) -> list:
    """
    One SSH round trip per root folder; returns [(size, path), ...].
    Prunes hidden directories (anything starting with '.') so NAS-generated
    metadata caches like Synology's .@__thumb/@eaDir folders — which mirror
    the original episode filenames and would otherwise look like real
    duplicate episodes — never get scanned in the first place.
    """
    name_clauses = " -o ".join("-iname {}".format(shlex.quote(ext)) for ext in _VIDEO_EXTS)
    cmd = ("find {} -type d -name '.*' -prune -o "
           "-type f \\( {} \\) -printf '%s\\t%p\\n' 2>/dev/null").format(
        shlex.quote(root_path), name_clauses)
    out, _, code = ssh.run(cmd)
    if code != 0 or not out.strip():
        return []
    files = []
    for line in out.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            files.append((int(parts[0]), parts[1]))
        except ValueError:
            continue
    return files


def _group_key(path: str, app_name: str, known_folders):
    """
    Radarr: one movie per folder is the common convention, so the folder is
    the right group *only when it's actually a known movie folder* — some
    libraries place files directly in the root instead, and grouping "by
    folder" there would lump every unrelated movie in the root into one
    nonsensical group. A file whose folder isn't a known movie folder gets
    a unique key so it's never merged with unrelated files.

    Sonarr: one folder holds a whole season's worth of *distinct* episodes,
    so grouping by folder alone would flag an entire normal season as one
    giant "duplicate." Group by (folder, episode number) instead, parsed
    from the filename; a file with no recognizable SxxEyy pattern gets its
    own unique key so it can't spuriously merge with unrelated episodes.
    """
    folder = posixpath.dirname(path)
    if app_name != "sonarr":
        if known_folders is not None and folder not in known_folders:
            return path  # unique — never flagged as a duplicate alone
        return folder
    m = _EPISODE_RE.search(posixpath.basename(path))
    if not m:
        return (folder, path)  # unique — never flagged as a duplicate alone
    season, episode = int(m.group(1)), int(m.group(2))
    return (folder, season, episode)


def _group_files(files: list, tracked: set, app_name: str, known_folders=None) -> list:
    by_key = {}
    for size, path in files:
        by_key.setdefault(_group_key(path, app_name, known_folders), []).append({
            "path": path, "size": size, "tracked": path in tracked,
        })

    groups = []
    for key, entries in by_key.items():
        if len(entries) < 2:
            continue
        sizes = sorted((f["size"] for f in entries), reverse=True)
        extra_bytes = sum(sizes[1:])  # everything but the single largest file
        groups.append({
            "folder": posixpath.dirname(entries[0]["path"]), "app": app_name,
            "files": entries, "extra_bytes": extra_bytes,
        })
    return groups


def delete_file(ssh, path: str):
    """
    Delete exactly one file on the server. Returns (True, "") on success,
    (False, error_message) on failure. Never raises. Refuses anything that
    isn't a plain absolute path — no globs, no relative paths, no shell
    metacharacters get a chance to matter since the path is quoted and
    passed to `rm -f` on a single literal file.
    """
    if not path or not path.startswith("/") or any(c in path for c in ("*", "?", "\n")):
        return False, "Refusing to delete: not a plain absolute file path."
    cmd = "rm -f {} && echo DELETED".format(shlex.quote(path))
    out, err, code = ssh.run(cmd)
    if code == 0 and "DELETED" in (out or ""):
        return True, ""
    return False, (err or out or "Unknown error").strip()[:200]
