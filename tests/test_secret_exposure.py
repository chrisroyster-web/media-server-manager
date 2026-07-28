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
    info = classify("some_future_service_apikey")
    assert info["exposure"] == "unknown"
    assert info["fixable"] is None


def test_match_is_case_insensitive():
    info = classify("SABNZBD_APIKEY")
    assert info["exposure"] == "url"


def test_arr_stack_keys_are_header_based():
    for key in ("sonarr_apikey", "radarr_apikey", "prowlarr_apikey", "bazarr_apikey"):
        info = classify(key)
        assert info["exposure"] == "header", key
        assert info["fixable"] is True, key


def test_request_manager_keys_are_header_based():
    for key in ("overseerr_apikey", "jellyseerr_apikey"):
        info = classify(key)
        assert info["exposure"] == "header", key


def test_cloudflare_and_ntfy_tokens_are_header_based():
    assert classify("cloudflare_api_token")["exposure"] == "header"
    assert classify("notify_ntfy_token")["exposure"] == "header"


def test_pihole_is_url_exposed_but_fixable():
    info = classify("pihole_apikey")
    assert info["exposure"] == "url"
    assert info["fixable"] is True


def test_qbittorrent_and_glances_are_header_based():
    assert classify("qbittorrent_password")["exposure"] == "header"
    assert classify("glances_password")["exposure"] == "header"


def test_non_http_secrets_report_not_applicable_not_unknown():
    for key in ("restic_password", "nas_backup_password"):
        info = classify(key)
        assert info["exposure"] == "n/a", key
        assert info["fixable"] is None, key
