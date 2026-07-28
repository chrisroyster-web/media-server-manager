from core.secret_exposure import classify


def test_known_url_exposed_secret_is_flagged_and_not_fixable():
    info = classify("sabnzbd_apikey")
    assert info["exposure"] == "url"
    assert info["fixable"] is False


def test_known_header_secret_is_marked_safe():
    info = classify("plex_token")
    assert info["exposure"] == "header"
    assert info["fixable"] is True


def test_unrecognized_key_reports_unknown_not_a_false_header():
    info = classify("sonarr_apikey")
    assert info["exposure"] == "unknown"
    assert info["fixable"] is None


def test_match_is_case_insensitive():
    info = classify("SABNZBD_APIKEY")
    assert info["exposure"] == "url"
