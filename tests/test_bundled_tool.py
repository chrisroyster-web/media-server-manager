from core.bundled_tool import classify_pkg


def test_known_bundled_pkg_is_flagged():
    info = classify_pkg("chromium")
    assert info["bundled"] is True
    assert info["tool"] == "Chromium"


def test_bundled_variant_pkg_name_matches_via_substring():
    info = classify_pkg("chromium-common")
    assert info["bundled"] is True


def test_unrecognized_pkg_reports_not_bundled():
    info = classify_pkg("openssl")
    assert info["bundled"] is False
    assert info["tool"] == ""


def test_match_is_case_insensitive():
    info = classify_pkg("CHROMIUM")
    assert info["bundled"] is True
