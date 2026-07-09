import pytest

import core.media_dedup as media_dedup
from core.media_dedup import find_duplicate_and_orphaned_media


class _FakeSSH:
    def __init__(self, files_by_root):
        """files_by_root: {root_path: [(size, path), ...]}"""
        self.files_by_root = files_by_root

    def run(self, cmd):
        for root, files in self.files_by_root.items():
            if root in cmd:
                out = "".join("{}\t{}\n".format(size, path) for size, path in files)
                return (out, "", 0)
        return ("", "", 0)


SONARR_CFG = {"host": "localhost", "port": "8989", "apikey": "sonarr-key"}
RADARR_CFG = {"host": "localhost", "port": "7878", "apikey": "radarr-key"}
NO_KEY_CFG = {"host": "localhost", "port": "8989", "apikey": ""}


def _fake_api_get_factory(sonarr_series=None, sonarr_episodefiles=None,
                           sonarr_rootfolder=None, radarr_movies=None,
                           radarr_rootfolder=None):
    def _fake(host, port, apikey, path):
        if apikey == "sonarr-key":
            if path == "rootfolder":
                return sonarr_rootfolder or []
            if path == "series":
                return sonarr_series or []
            if path.startswith("episodefile?seriesId="):
                sid = int(path.split("=")[1])
                return (sonarr_episodefiles or {}).get(sid, [])
        if apikey == "radarr-key":
            if path == "rootfolder":
                return radarr_rootfolder or []
            if path == "movie":
                return radarr_movies or []
        return []
    return _fake


# ---------------------------------------------------------------------------

def test_no_apps_configured_returns_nothing():
    ssh = _FakeSSH({})
    result = find_duplicate_and_orphaned_media(ssh, NO_KEY_CFG, NO_KEY_CFG)
    assert result == {"groups": [], "errors": []}


def test_clean_sonarr_library_reports_no_groups(monkeypatch):
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        sonarr_rootfolder=[{"path": "/media/tv"}],
        sonarr_series=[{"id": 1, "title": "Show"}],
        sonarr_episodefiles={1: [{"path": "/media/tv/Show/Season 01/S01E01.mkv", "size": 100}]},
    ))
    ssh = _FakeSSH({"/media/tv": [(1000000, "/media/tv/Show/Season 01/S01E01.mkv")]})
    result = find_duplicate_and_orphaned_media(ssh, SONARR_CFG, NO_KEY_CFG)
    assert result["groups"] == []
    assert result["errors"] == []


def test_sonarr_full_season_of_distinct_episodes_is_not_flagged(monkeypatch):
    # Regression test: a season folder holding many distinct, all-tracked
    # episodes is normal and must NOT be reported just because the folder
    # has many files — only grouping by (folder, episode) construction
    # catches this; grouping by bare folder would false-positive here.
    episodes = [
        {"path": "/media/tv/Show/Season 01/Show - S01E{:02d} - Title.mkv".format(n),
         "size": 100}
        for n in range(1, 23)
    ]
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        sonarr_rootfolder=[{"path": "/media/tv"}],
        sonarr_series=[{"id": 1, "title": "Show"}],
        sonarr_episodefiles={1: episodes},
    ))
    ssh = _FakeSSH({"/media/tv": [(1000000, ep["path"]) for ep in episodes]})
    result = find_duplicate_and_orphaned_media(ssh, SONARR_CFG, NO_KEY_CFG)
    assert result["groups"] == []
    assert result["errors"] == []


def test_sonarr_extra_untracked_file_is_reported(monkeypatch):
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        sonarr_rootfolder=[{"path": "/media/tv"}],
        sonarr_series=[{"id": 1, "title": "Show"}],
        sonarr_episodefiles={1: [{"path": "/media/tv/Show/Season 01/S01E01.mkv", "size": 100}]},
    ))
    ssh = _FakeSSH({"/media/tv": [
        (1000000, "/media/tv/Show/Season 01/S01E01.mkv"),
        (900000,  "/media/tv/Show/Season 01/S01E01.old.mkv"),
    ]})
    result = find_duplicate_and_orphaned_media(ssh, SONARR_CFG, NO_KEY_CFG)
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["app"] == "sonarr"
    assert group["folder"] == "/media/tv/Show/Season 01"
    assert group["extra_bytes"] == 900000
    tracked_flags = {f["path"]: f["tracked"] for f in group["files"]}
    assert tracked_flags["/media/tv/Show/Season 01/S01E01.mkv"] is True
    assert tracked_flags["/media/tv/Show/Season 01/S01E01.old.mkv"] is False


def test_radarr_movie_file_embedded_and_extra_reported(monkeypatch):
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        radarr_rootfolder=[{"path": "/media/movies"}],
        radarr_movies=[{
            "id": 1, "title": "A Movie", "hasFile": True,
            "path": "/media/movies/A Movie (2020)",
            "movieFile": {"path": "/media/movies/A Movie (2020)/movie.mkv", "size": 500},
        }],
    ))
    ssh = _FakeSSH({"/media/movies": [
        (2000000, "/media/movies/A Movie (2020)/movie.mkv"),
        (2000000, "/media/movies/A Movie (2020)/movie-sample.mkv"),
    ]})
    result = find_duplicate_and_orphaned_media(ssh, NO_KEY_CFG, RADARR_CFG)
    assert len(result["groups"]) == 1
    assert result["groups"][0]["app"] == "radarr"
    assert result["groups"][0]["extra_bytes"] == 2000000


def test_radarr_loose_files_directly_in_root_are_not_lumped_together(monkeypatch):
    # Regression test: a library where movies sit directly in the root
    # (no per-movie subfolder) must NOT have every unrelated movie merged
    # into one giant "group" just because they share the same parent dir.
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        radarr_rootfolder=[{"path": "/media/movies"}],
        radarr_movies=[
            {"id": 1, "title": "Movie One", "hasFile": True,
             "path": "/media/movies/Movie One (2020)",
             "movieFile": {"path": "/media/movies/Movie One.mkv", "size": 500}},
            {"id": 2, "title": "Movie Two", "hasFile": True,
             "path": "/media/movies/Movie Two (2021)",
             "movieFile": {"path": "/media/movies/Movie Two.mkv", "size": 500}},
        ],
    ))
    ssh = _FakeSSH({"/media/movies": [
        (500, "/media/movies/Movie One.mkv"),
        (500, "/media/movies/Movie Two.mkv"),
        (500, "/media/movies/Movie Three.mkv"),
    ]})
    result = find_duplicate_and_orphaned_media(ssh, NO_KEY_CFG, RADARR_CFG)
    assert result["groups"] == []


def test_both_apps_scanned_together(monkeypatch):
    monkeypatch.setattr(media_dedup, "_api_get", _fake_api_get_factory(
        sonarr_rootfolder=[{"path": "/media/tv"}],
        sonarr_series=[{"id": 1, "title": "Show"}],
        sonarr_episodefiles={1: [{"path": "/media/tv/Show/S01E01.mkv", "size": 100}]},
        radarr_rootfolder=[{"path": "/media/movies"}],
        radarr_movies=[{"id": 1, "title": "Movie", "hasFile": True,
                        "path": "/media/movies/Movie",
                        "movieFile": {"path": "/media/movies/Movie/movie.mkv", "size": 500}}],
    ))
    ssh = _FakeSSH({
        "/media/tv": [(100, "/media/tv/Show/S01E01.mkv"),
                      (50, "/media/tv/Show/S01E01.dup.mkv")],
        "/media/movies": [(500, "/media/movies/Movie/movie.mkv")],
    })
    result = find_duplicate_and_orphaned_media(ssh, SONARR_CFG, RADARR_CFG)
    assert len(result["groups"]) == 1
    assert result["groups"][0]["app"] == "sonarr"


def test_api_failure_contributes_to_errors_not_a_crash(monkeypatch):
    def _raise(host, port, apikey, path):
        raise ConnectionError("could not connect")
    monkeypatch.setattr(media_dedup, "_api_get", _raise)
    ssh = _FakeSSH({})
    result = find_duplicate_and_orphaned_media(ssh, SONARR_CFG, NO_KEY_CFG)
    assert result["groups"] == []
    assert len(result["errors"]) == 1
    assert "sonarr" in result["errors"][0]
