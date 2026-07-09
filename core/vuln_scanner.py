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
