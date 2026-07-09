# core/vuln_scanner.py
"""
Container image vulnerability scanning via Trivy (Aqua Security).

Scans the server's actual running images against the local Docker daemon
(no re-pull needed) and returns severity-ranked CVE counts. Every method
runs a single blocking SSH command and never raises — on any exec/parse
failure it returns an "error" dict/field instead, so a scan-all loop over
many images can't be aborted by one bad container.
"""

import json
import shlex


_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def list_scan_targets(ssh):
    """
    Every running/stopped container grouped by image, e.g.:
        [{"image": "lscr.io/linuxserver/sonarr", "containers": ["sonarr"]}, ...]
    Multiple containers sharing the same image are grouped into one entry
    so Scan All doesn't scan the same image twice.
    """
    out, _, code = ssh.run("docker ps -a --format '{{.Names}}\t{{.Image}}' 2>/dev/null")
    if code != 0 or not out.strip():
        return []

    by_image = {}
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name, image = parts
        by_image.setdefault(image, []).append(name)

    return [{"image": image, "containers": containers}
            for image, containers in by_image.items()]


def scan_image(ssh, image: str) -> dict:
    """
    Runs `trivy image` against one image and returns:
        {"critical": n, "high": n, "medium": n, "low": n, "cves": [...]}
    or {"error": "..."} on any failure. Each cve dict has:
        {"id", "severity", "pkg", "installed", "fixed", "title"}
    """
    cmd = "trivy image --format json --quiet {} 2>/dev/null".format(shlex.quote(image))
    out, err, code = ssh.run(cmd)

    if code != 0 or not out.strip():
        return {"error": (err or "trivy returned no output").strip()[:200]}

    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {"error": "Could not parse trivy JSON output."}

    counts = {sev.lower(): 0 for sev in _SEVERITIES}
    cves = []
    for result in (data.get("Results") or []):
        for vuln in (result.get("Vulnerabilities") or []):
            severity = (vuln.get("Severity") or "UNKNOWN").upper()
            if severity in _SEVERITIES:
                counts[severity.lower()] += 1
            cves.append({
                "id":        vuln.get("VulnerabilityID", ""),
                "severity":  severity,
                "pkg":       vuln.get("PkgName", ""),
                "installed": vuln.get("InstalledVersion", ""),
                "fixed":     vuln.get("FixedVersion", ""),
                "title":     vuln.get("Title", ""),
            })

    return {**counts, "cves": cves}


def diff_new_findings(baseline: dict, results: dict) -> tuple:
    """
    Compare this run's scan results against the last-known baseline to find
    genuinely NEW critical/high CVEs — not the full set every time, which
    would just re-alert forever about the same permanently-unfixed findings
    (e.g. an EOL package with no available fix).

    baseline: {image: [cve_id, ...]} — critical+high IDs as of last check.
    results:  {image: scan_image()-shaped dict} for this run.

    Returns (new_baseline, new_findings):
      new_baseline:  {image: [cve_id, ...]} to persist for next time.
      new_findings:  {image: [cve dict, ...]} — only for images that already
                      had a baseline entry. An image seen for the first time
                      populates new_baseline but is never reported as "new"
                      here, so enabling this feature doesn't immediately dump
                      every pre-existing CVE as a fresh alert.
    """
    new_baseline = {}
    new_findings = {}

    for image, result in results.items():
        if "error" in result:
            continue
        crit_high = [c for c in result.get("cves", [])
                     if c.get("severity") in ("CRITICAL", "HIGH")]
        current_ids = [c["id"] for c in crit_high]
        new_baseline[image] = current_ids

        if image not in baseline:
            continue  # first time seeing this image — establish baseline only

        previously_seen = set(baseline[image])
        new_for_image = [c for c in crit_high if c["id"] not in previously_seen]
        if new_for_image:
            new_findings[image] = new_for_image

    return new_baseline, new_findings
