import json

from core.vuln_scanner import list_scan_targets, scan_image


class _FakeSSH:
    def __init__(self):
        self._responses = []  # list of (out, err, code), consumed in order

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def _trivy_payload(vulns):
    return json.dumps({"Results": [{"Target": "app", "Vulnerabilities": vulns}]})


# ---------------------------------------------------------------------------
# list_scan_targets
# ---------------------------------------------------------------------------

def test_list_scan_targets_groups_shared_image():
    ssh = _FakeSSH()
    ssh._responses = [(
        "sonarr\tlscr.io/linuxserver/sonarr\n"
        "radarr\tlscr.io/linuxserver/radarr\n"
        "tracearr-db\tpostgres:15\n"
        "tracearr-redis\tpostgres:15\n",  # contrived shared-image case
        "", 0,
    )]
    targets = list_scan_targets(ssh)
    by_image = {t["image"]: t["containers"] for t in targets}
    assert by_image["lscr.io/linuxserver/sonarr"] == ["sonarr"]
    assert by_image["lscr.io/linuxserver/radarr"] == ["radarr"]
    assert set(by_image["postgres:15"]) == {"tracearr-db", "tracearr-redis"}


def test_list_scan_targets_empty_on_nonzero_exit():
    ssh = _FakeSSH()
    ssh._responses = [("", "docker not found", 1)]
    assert list_scan_targets(ssh) == []


def test_list_scan_targets_empty_when_no_output():
    ssh = _FakeSSH()
    ssh._responses = [("", "", 0)]
    assert list_scan_targets(ssh) == []


def test_list_scan_targets_skips_malformed_lines():
    ssh = _FakeSSH()
    ssh._responses = [("not-a-valid-line-no-tab\nsonarr\tsonarr:latest\n", "", 0)]
    targets = list_scan_targets(ssh)
    assert len(targets) == 1
    assert targets[0]["image"] == "sonarr:latest"


# ---------------------------------------------------------------------------
# scan_image
# ---------------------------------------------------------------------------

def test_scan_image_counts_severities():
    ssh = _FakeSSH()
    ssh._responses = [(_trivy_payload([
        {"VulnerabilityID": "CVE-1", "Severity": "CRITICAL", "PkgName": "openssl",
         "InstalledVersion": "1.0", "FixedVersion": "1.1", "Title": "bad thing"},
        {"VulnerabilityID": "CVE-2", "Severity": "HIGH", "PkgName": "curl",
         "InstalledVersion": "7.0", "FixedVersion": "7.1", "Title": "another bad thing"},
        {"VulnerabilityID": "CVE-3", "Severity": "HIGH", "PkgName": "libc",
         "InstalledVersion": "2.0", "FixedVersion": "", "Title": "no fix yet"},
        {"VulnerabilityID": "CVE-4", "Severity": "LOW", "PkgName": "zlib",
         "InstalledVersion": "1.2", "FixedVersion": "1.3", "Title": "minor"},
    ]), "", 0)]

    result = scan_image(ssh, "example/image:latest")
    assert result["critical"] == 1
    assert result["high"] == 2
    assert result["medium"] == 0
    assert result["low"] == 1
    assert len(result["cves"]) == 4
    assert result["cves"][0]["id"] == "CVE-1"
    assert result["cves"][2]["fixed"] == ""


def test_scan_image_no_vulnerabilities():
    ssh = _FakeSSH()
    ssh._responses = [(_trivy_payload([]), "", 0)]
    result = scan_image(ssh, "example/image:latest")
    assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0, "cves": []}


def test_scan_image_handles_missing_results_key():
    ssh = _FakeSSH()
    ssh._responses = [(json.dumps({}), "", 0)]
    result = scan_image(ssh, "example/image:latest")
    assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0, "cves": []}


def test_scan_image_error_on_nonzero_exit():
    ssh = _FakeSSH()
    ssh._responses = [("", "unable to find image", 1)]
    result = scan_image(ssh, "example/image:latest")
    assert "error" in result


def test_scan_image_error_on_malformed_json():
    ssh = _FakeSSH()
    ssh._responses = [("not json at all", "", 0)]
    result = scan_image(ssh, "example/image:latest")
    assert "error" in result


def test_scan_image_ignores_unknown_severity():
    ssh = _FakeSSH()
    ssh._responses = [(_trivy_payload([
        {"VulnerabilityID": "CVE-5", "Severity": "UNKNOWN", "PkgName": "foo",
         "InstalledVersion": "1", "FixedVersion": "", "Title": "?"},
    ]), "", 0)]
    result = scan_image(ssh, "example/image:latest")
    assert result["critical"] == result["high"] == result["medium"] == result["low"] == 0
    assert len(result["cves"]) == 1
