from core.tunnel_exposure import parse_ingress_hostnames, compute_exposure, diff_new_unprotected


def test_parse_ingress_extracts_hostnames_and_skips_catchall():
    text = """
ingress:
  - hostname: jellyseerr.example.com
    service: http://localhost:5055
  - hostname: sonarr.example.com
    service: http://localhost:8989
  - service: http_status:404
"""
    assert parse_ingress_hostnames(text) == [
        "jellyseerr.example.com", "sonarr.example.com"]


def test_parse_ingress_returns_empty_on_malformed_yaml():
    assert parse_ingress_hostnames(":::not yaml:::") == []


def test_parse_ingress_returns_empty_when_no_ingress_key():
    assert parse_ingress_hostnames("tunnel: abc123\n") == []


def test_parse_ingress_returns_empty_for_non_dict_yaml():
    assert parse_ingress_hostnames("- just\n- a\n- list\n") == []


def test_compute_exposure_flags_unprotected_hostnames():
    result = compute_exposure(
        ["jellyseerr.example.com", "sonarr.example.com"],
        ["jellyseerr.example.com"])
    assert result == [
        {"hostname": "jellyseerr.example.com", "protected": True},
        {"hostname": "sonarr.example.com", "protected": False},
    ]


def test_compute_exposure_matches_path_scoped_access_domain_by_host():
    result = compute_exposure(["app.example.com"], ["app.example.com/admin"])
    assert result[0]["protected"] is True


def test_compute_exposure_empty_hostnames_returns_empty_list():
    assert compute_exposure([], ["app.example.com"]) == []


def test_diff_flags_hostname_not_in_baseline():
    new_baseline, newly = diff_new_unprotected([], ["jellyseerr.example.com"])
    assert newly == ["jellyseerr.example.com"]
    assert new_baseline == ["jellyseerr.example.com"]


def test_diff_does_not_reflag_hostname_already_in_baseline():
    new_baseline, newly = diff_new_unprotected(
        ["jellyseerr.example.com"], ["jellyseerr.example.com"])
    assert newly == []
    assert new_baseline == ["jellyseerr.example.com"]


def test_diff_baseline_reflects_current_state_not_accumulated():
    # A hostname that was unprotected before but is now protected (no
    # longer in current_unprotected) must drop out of the new baseline,
    # so if it later regresses back to unprotected it alerts again.
    new_baseline, newly = diff_new_unprotected(["old-host.example.com"], [])
    assert new_baseline == []
    assert newly == []


def test_diff_mix_of_known_and_new():
    new_baseline, newly = diff_new_unprotected(
        ["known.example.com"], ["known.example.com", "brandnew.example.com"])
    assert newly == ["brandnew.example.com"]
    assert set(new_baseline) == {"known.example.com", "brandnew.example.com"}
