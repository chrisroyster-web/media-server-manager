# core/log_sources.py
"""
Log source discovery and cross-source search for ui/log_viewer_tab.py.
Docker container log commands are discovered live (docker ps) rather than
hardcoded, since which containers exist varies per server — unlike the
tab's fixed systemd-service sources, which are always the same known set.
"""

_DOCKER_LOG_LINES = 150


def list_docker_log_sources(ssh) -> dict:
    """
    Every container (running or stopped) as a log source, e.g.:
        {"Docker: homarr": "docker logs --tail 150 homarr 2>&1"}
    Returns {} on any failure or empty listing — a missing/unreachable
    Docker daemon just means no Docker sources are offered, not an error.
    """
    out, _, code = ssh.run("docker ps -a --format '{{.Names}}' 2>/dev/null")
    if code != 0 or not out.strip():
        return {}
    sources = {}
    for name in out.strip().splitlines():
        name = name.strip()
        if not name:
            continue
        sources["Docker: {}".format(name)] = (
            "docker logs --tail {} {} 2>&1".format(_DOCKER_LOG_LINES, name))
    return sources


def search_sources(ssh, sources: dict, keyword: str, lines_per_source: int = _DOCKER_LOG_LINES) -> dict:
    """
    Run every source's command and keep only lines containing `keyword`
    (case-insensitive). Returns {source_name: [matching_line, ...]} —
    sources with zero matches, or whose command fails outright, are simply
    omitted. Never raises, so one bad source can't abort the whole search.
    """
    needle = keyword.lower()
    results = {}
    for name, cmd in sources.items():
        try:
            out, err, code = ssh.run(cmd)
        except Exception:
            continue
        text = out or err or ""
        if not text:
            continue
        matches = [line for line in text.splitlines() if needle in line.lower()]
        if matches:
            results[name] = matches
    return results
