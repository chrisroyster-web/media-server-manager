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

Fix sources, tried in order, cheapest/best-quality first:
  1. TVmaze episode lookup (Episode items only) -- real broadcast stills,
     no API key needed. Confirmed to cover gaps TVDB/TMDB/OMDb miss: item
     3106612 ("Alaskan Bush People" S07E06) has nothing on any of Emby's
     own providers but TVmaze has an actual screencap for it.
  2. ffmpeg frame extraction on the server (any item with a video file) --
     always available as a fallback, just a generic frame rather than a
     real still.
Series-type items have neither a TVmaze episode lookup nor a video file,
so they're flagged but not auto-fixable by either source.
"""

import json
import shlex
import urllib.parse
import urllib.request

_PAGE_SIZE   = 500
_ITEM_TYPES  = "Movie,Series,Episode"
_TIMEOUT     = 10
_TVMAZE_BASE = "https://api.tvmaze.com"


def _get(host, port, apikey, path):
    url = "http://{}:{}/emby{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"X-Emby-Token": apikey})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def _get_external(url):
    req = urllib.request.Request(url, headers={"User-Agent": "media-server-manager"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def scan(host, port, apikey) -> dict:
    """
    Pages through the whole library once. Returns:
      {"items": [...], "total_checked": int, "error": str|None}

    Each entry in `items` is
      {"id", "name", "type", "path", "series_name", "series_id", "season", "episode"}
    for an item with no Primary image tag. `path` is "" for types (Series)
    that have no single backing file. `series_id`/`season`/`episode` are
    None outside of Episode items -- they're what generate_and_upload_
    thumbnail() needs to try a TVmaze lookup before falling back to ffmpeg.
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
            "Fields": "Path,SeriesName,ParentIndexNumber,IndexNumber",
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
                    "series_id":   str(it["SeriesId"]) if it.get("SeriesId") else None,
                    "season":      it.get("ParentIndexNumber"),
                    "episode":     it.get("IndexNumber"),
                })

        grand_total = data.get("TotalRecordCount", 0)
        start += len(page)
        if start >= grand_total:
            break

    return {"items": missing, "total_checked": total_checked, "error": None}


# Emby's ProviderIds key for a directly-embedded TVmaze id varies a bit by
# how it got there (Sonarr NFO import vs. manual entry) — check the common
# spellings before falling back to resolving one via the TVDB id.
_TVMAZE_KEYS = ("TV Maze", "TVMaze", "Tvmaze", "TvMaze")


def _series_tvmaze_id(host, port, apikey, series_id: str, cache: dict):
    """Resolves a series' TVmaze show id, preferring one Emby already has
    on file over a TVDB-id lookup. Cached per series_id since a bulk fix
    can touch dozens of episodes of the same show."""
    if series_id in cache:
        return cache[series_id]

    tvmaze_id = None
    try:
        data = _get(host, port, apikey, "/Items?" + urllib.parse.urlencode(
            {"Ids": series_id, "Fields": "ProviderIds"}))
        items = data.get("Items") or []
        provider_ids = items[0].get("ProviderIds", {}) if items else {}

        for key in _TVMAZE_KEYS:
            if provider_ids.get(key):
                tvmaze_id = str(provider_ids[key])
                break

        if not tvmaze_id and provider_ids.get("Tvdb"):
            lookup = _get_external(
                "{}/lookup/shows?thetvdb={}".format(
                    _TVMAZE_BASE, urllib.parse.quote(str(provider_ids["Tvdb"]))))
            if lookup and lookup.get("id"):
                tvmaze_id = str(lookup["id"])
    except Exception:
        tvmaze_id = None

    cache[series_id] = tvmaze_id
    return tvmaze_id


def _tvmaze_episode_image_url(host, port, apikey, series_id, season, episode, cache: dict):
    """Real broadcast still for one episode, or None if TVmaze has nothing
    for it (common for very new or very obscure episodes -- not an error,
    just means the ffmpeg fallback runs instead)."""
    tvmaze_id = _series_tvmaze_id(host, port, apikey, series_id, cache)
    if not tvmaze_id:
        return None
    try:
        data = _get_external("{}/shows/{}/episodebynumber?season={}&number={}".format(
            _TVMAZE_BASE, tvmaze_id, int(season), int(episode)))
    except Exception:
        return None
    image = (data or {}).get("image") or {}
    return image.get("original") or image.get("medium")


def generate_and_upload_thumbnail(ssh, host, port, apikey, item_id: str, video_path: str,
                                   item_type: str = "", series_id=None, season=None,
                                   episode=None, tvmaze_cache: dict = None) -> dict:
    """
    Sets the item's Primary image from the best available source:
      1. TVmaze's real episode still, for Episode items with enough
         identifying info (series_id/season/episode) to look one up.
      2. A frame extracted from the video file with ffmpeg on the server,
         as a fallback -- the two-step fix validated by hand against item
         3106612 before TVmaze support existed.

    Only usable for items with a video file (Movie/Episode) or enough info
    for a TVmaze episode lookup -- a Series has neither.
    Returns {"ok": bool, "error": str|None, "source": "tvmaze"|"ffmpeg"|None}.
    """
    if not apikey:
        return {"ok": False, "error": "No Emby API key configured.", "source": None}

    can_tvmaze = bool(item_type == "Episode" and series_id
                       and season is not None and episode is not None)
    can_ffmpeg = bool(video_path and video_path.startswith("/"))
    if not can_tvmaze and not can_ffmpeg:
        return {"ok": False, "error": "No image source available for this item.", "source": None}

    # Emby item ids are always numeric, but don't trust that blindly when
    # building a server-side path out of it.
    safe_id = "".join(c for c in item_id if c.isalnum()) or "unknown"
    tmp_jpg = "/tmp/metadata_scan_thumb_{}.jpg".format(safe_id)
    qtmp    = shlex.quote(tmp_jpg)
    source  = None

    if can_tvmaze:
        try:
            image_url = _tvmaze_episode_image_url(
                host, port, apikey, series_id, season, episode,
                tvmaze_cache if tvmaze_cache is not None else {})
        except Exception:
            image_url = None
        if image_url:
            ssh.run("curl -sL -f -o {} {} >/dev/null 2>&1".format(qtmp, shlex.quote(image_url)))
            check, _, _ = ssh.run("test -s {} && echo ok || echo missing".format(qtmp))
            if "ok" in check:
                source = "tvmaze"

    if source is None and can_ffmpeg:
        qpath = shlex.quote(video_path)
        # 5 minutes in avoids opening/title-card frames; fall back to a
        # couple seconds in for anything shorter than that (shorts, specials).
        for seek in (300, 5):
            ssh.run("ffmpeg -y -ss {} -i {} -frames:v 1 -q:v 3 {} >/dev/null 2>&1".format(
                seek, qpath, qtmp))
            check, _, _ = ssh.run("test -s {} && echo ok || echo missing".format(qtmp))
            if "ok" in check:
                source = "ffmpeg"
                break

    if source is None:
        return {"ok": False,
                "error": "No image found via TVmaze, and ffmpeg could not extract a frame.",
                "source": None}

    url = "http://localhost:{}/emby/Items/{}/Images/Primary".format(
        port, urllib.parse.quote(item_id, safe=""))
    header = shlex.quote("X-Emby-Token: {}".format(apikey))
    out, err, code = ssh.run(
        "curl -s -o /dev/null -w '%{{http_code}}' -X POST {} "
        "-H {} -H 'Content-Type: image/jpeg' --data-binary @{}".format(
            shlex.quote(url), header, qtmp))
    ssh.run("rm -f {}".format(qtmp))

    if code != 0 or out.strip() != "204":
        return {"ok": False, "error": "Emby upload returned HTTP {}".format(out.strip() or "?"),
                "source": source}
    return {"ok": True, "error": None, "source": source}


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
