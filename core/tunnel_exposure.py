# core/tunnel_exposure.py
"""
Cross-references a Cloudflare Tunnel's ingress rules (cloudflared's
config.yml, read via SSH by the caller) against the account's configured
Access applications (Cloudflare API, fetched by the caller) to flag
tunneled hostnames with no Access app in front of them -- reachable by
anyone who knows the URL, not gated behind Cloudflare Access auth.

Pure functions only -- SSH lives in ui/cloudflare_tab.py, the API call in
core/cloudflare_manager.py. Kept this way so it's unit-testable without
mocking either.
"""

import yaml


def parse_ingress_hostnames(config_yaml_text: str) -> list:
    """Parses cloudflared's config.yml `ingress:` list and returns the
    tunneled hostnames, skipping the catch-all entry (no `hostname` key).
    Returns [] on any parse failure or missing/malformed `ingress:` --
    never raises."""
    try:
        data = yaml.safe_load(config_yaml_text) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    ingress = data.get("ingress") or []
    return [rule["hostname"] for rule in ingress
            if isinstance(rule, dict) and rule.get("hostname")]


def compute_exposure(tunneled_hostnames: list, access_domains: list) -> list:
    """Cross-references tunneled hostnames against Access app domains.
    Returns [{"hostname": ..., "protected": bool}, ...] in tunnel order.
    Access domains may be path-scoped ("host/path") -- matched by the
    bare hostname portion, since a whole-hostname tunnel entry is
    "protected" as soon as ANY Access app exists for that host."""
    protected_hosts = {d.split("/", 1)[0] for d in access_domains}
    return [{"hostname": h, "protected": h in protected_hosts}
            for h in tunneled_hostnames]


def diff_new_unprotected(baseline: list, current_unprotected: list) -> tuple:
    """baseline: [hostname, ...] already known-unprotected as of the last
    check. current_unprotected: [hostname, ...] unprotected right now.
    Returns (new_baseline, newly_unprotected) -- newly_unprotected only
    contains hostnames not already in baseline, so an intentionally-public
    hostname (e.g. a status page) doesn't re-alert forever. new_baseline
    reflects current state (not accumulated), so a hostname that gets
    re-exposed after being fixed alerts again -- same semantics as
    core/vuln_scanner.py's diff_new_findings()."""
    new_baseline = list(current_unprotected)
    newly = [h for h in current_unprotected if h not in baseline]
    return new_baseline, newly
