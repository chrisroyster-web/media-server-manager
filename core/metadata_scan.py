# core/metadata_scan.py
"""
Finds Emby library items with no Primary image.

This isn't a cosmetic nice-to-have: Emby's own ImageService.GetImage throws
a NullReferenceException (a 500, not a clean 404) for any item whose
ImageTags has no "Primary" entry -- reproduced by hand against a real item
on 2026-08-14 (Alaskan Bush People S07E06, Emby item 3106612, had zero
registered images). Anything that requests that item's image directly --
a client's poster grid, a third-party integration polling for thumbnails --
gets a 500 back instead, and an integration that retries on failure without
backoff can turn one missing image into thousands of requests in minutes.
That's exactly what happened: Tracearr's library sync hit this item and
generated a ~12,600-request storm against Emby, twice a day, until the
image was fixed.

Scoped deliberately narrow: only "no Primary image" is flagged, since
that's the one field this crash is reproducibly tied to. Missing backdrop/
logo/thumb images are common and mostly cosmetic (plenty of legitimate
items -- home videos, obscure reality-TV episodes -- have no stills on
TVDB/TMDB/OMDb to begin with); flagging those too would just bury the
real signal in noise.
"""

import json
import shlex
import urllib.parse
import urllib.request

_PAGE_SIZE  = 500
_ITEM_TYPES = "Movie,Series,Episode"
_TIMEOUT    = 10


def _get(host, port, apikey, path):
    url = "http://{}:{}/emby{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Emby-Token": apikey})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def scan(host, port, apikey) -> dict:
    """
    Pages through the whole library once. Returns:
      {"items": [...], "total_checked": int, "error": str|None}

    Each entry in `items` is
      {"id", "name", "type", "path", "series_name"}
    for an item with no Primary image tag. `path` is "" for types (Series)
    that have no single backing file — those can be flagged but not
    auto-fixed by generate_and_upload_thumbnail().
    """
    if not apikey:
        return {"items": [], "total_checked": 0, "error": "No Emby API key configured"}

    missing = []
    total_checked = 0
    start = 0
    while True:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": _ITEM_TYPES,
            "Fields": "Path,SeriesName",
            "Limit": str(_PAGE_SIZE),
            "StartIndex": str(start),
        }
        try:
            data = _get(host, port, apikey, "/Items?" + urllib.parse.urlencode(params))
        except Exception as e:
            return {"items": missing, "total_checked": total_checked,
                    "error": "Emby request failed: {}".format(e)}

        page = data.get("Items", []) or []
        if not page:
            break
        total_checked += len(page)
        for it in page:
            if "Primary" not in (it.get("ImageTags") or {}):
                missing.append({
                    "id":          str(it.get("Id", "")),
                    "name":        it.get("Name", ""),
                    "type":        it.get("Type", ""),
                    "path":        it.get("Path", "") or "",
                    "series_name": it.get("SeriesName", "") or "",
                })

        grand_total = data.get("TotalRecordCount", 0)
        start += len(page)
        if start >= grand_total:
            break

    return {"items": missing, "total_checked": total_checked, "error": None}


def generate_and_upload_thumbnail(ssh, host, port, apikey, item_id: str, video_path: str) -> dict:
    """
    Extracts a frame from the item's video file with ffmpeg (on the server,
    via SSH) and uploads it as the item's Primary image via the Emby API --
    the same two-step fix validated by hand against item 3106612.

    Only usable for items with a real backing file (Movie/Episode) -- a
    Series has no single video to extract from. Returns {"ok": bool, "error": str|None}.
    """
    if not video_path or not video_path.startswith("/"):
        return {"ok": False, "error": "No video file to extract a thumbnail from."}
    if not apikey:
        return {"ok": False, "error": "No Emby API key configured."}

    # Emby item ids are always numeric, but don't trust that blindly when
    # building a server-side path out of it.
    safe_id = "".join(c for c in item_id if c.isalnum()) or "unknown"
    tmp_jpg = "/tmp/metadata_scan_thumb_{}.jpg".format(safe_id)
    qpath   = shlex.quote(video_path)
    qtmp    = shlex.quote(tmp_jpg)

    # 5 minutes in avoids opening/title-card frames; fall back to a couple
    # seconds in for anything shorter than that (shorts, specials).
    for seek in (300, 5):
        ssh.run("ffmpeg -y -ss {} -i {} -frames:v 1 -q:v 3 {} >/dev/null 2>&1".format(
            seek, qpath, qtmp))
        check, _, _ = ssh.run("test -s {} && echo ok || echo missing".format(qtmp))
        if "ok" in check:
            break
    else:
        return {"ok": False, "error": "ffmpeg could not extract a frame from this file."}

    url = "http://localhost:{}/emby/Items/{}/Images/Primary".format(
        port, urllib.parse.quote(item_id, safe=""))
    header = shlex.quote("X-Emby-Token: {}".format(apikey))
    out, err, code = ssh.run(
        "curl -s -o /dev/null -w '%{{http_code}}' -X POST {} "
        "-H {} -H 'Content-Type: image/jpeg' --data-binary @{}".format(
            shlex.quote(url), header, qtmp))
    ssh.run("rm -f {}".format(qtmp))

    if code != 0 or out.strip() != "204":
        return {"ok": False, "error": "Emby upload returned HTTP {}".format(out.strip() or "?")}
    return {"ok": True, "error": None}


def diff_new_missing(baseline: list, items: list) -> tuple:
    """
    Compare this run's missing-image item IDs against the last-known
    baseline so a scheduled scan only alerts about genuinely NEW gaps, not
    the same still-missing item every night.

    Returns (new_baseline, newly_missing):
      new_baseline:  [item_id, ...] to persist for next time.
      newly_missing: [item dict, ...] -- ids missing now that weren't in
                      the baseline.
    """
    baseline_set = set(baseline)
    missing_ids  = {it["id"] for it in items}
    newly_missing = [it for it in items if it["id"] not in baseline_set]
    return sorted(missing_ids), newly_missing
