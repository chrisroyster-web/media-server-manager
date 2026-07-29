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


def test_vim_variants_are_flagged_bundled():
    for pkg in ("vim-common", "vim-tiny"):
        info = classify_pkg(pkg)
        assert info["bundled"] is True, pkg
        assert info["tool"] == "Vim"


def test_perl_variants_are_flagged_bundled():
    for pkg in ("perl", "perl-base", "libperl5.40", "perl-modules-5.40"):
        info = classify_pkg(pkg)
        assert info["bundled"] is True, pkg
        assert info["tool"] == "Perl"


def test_unrelated_pkg_does_not_match_vim_or_perl():
    for pkg in ("curl", "libcurl4", "bsdutils", "gzip"):
        info = classify_pkg(pkg)
        assert info["bundled"] is False, pkg
