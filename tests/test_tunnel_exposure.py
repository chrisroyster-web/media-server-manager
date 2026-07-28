from core.tunnel_exposure import parse_ingress_hostnames, compute_exposure


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
