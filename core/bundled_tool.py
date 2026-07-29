# core/bundled_tool.py
"""
Static, hand-maintained map of package names known to come from a bundled
sub-component of a container image (e.g. an embedded browser) rather than
directly-relevant, actually-exercised server software -- so their CVE
counts can be called out separately instead of silently inflating the
headline risk number on the Vulnerability Scan tab.

Confirmed-bundled entries only -- classify_pkg() never guesses. A package
not in BUNDLED_TOOL_MAP is real, first-party surface area until someone
actually verifies otherwise and adds an entry here.
"""

BUNDLED_TOOL_MAP = [
    {"match": "chromium", "tool": "Chromium",
     "note": "Bundled with uptime-kuma for its optional 'real browser "
             "monitor' type -- not used by this deployment."},
    {"match": "vim-", "tool": "Vim",
     "note": "Bundled in netdata's base image (vim-common/vim-tiny) -- "
             "the monitoring daemon has no use for a text editor."},
    {"match": "perl", "tool": "Perl",
     "note": "Bundled in postgres's base image as a transitive Debian "
             "dependency -- this deployment's tracearr postgres instance "
             "has no PL/Perl extension loaded (confirmed against its "
             "docker-compose.yml: plain POSTGRES_USER/PASSWORD/DB env "
             "vars only). Re-audit this entry if PL/Perl is ever added."},
]

_NOT_BUNDLED = {"tool": "", "note": "", "bundled": False}


def classify_pkg(pkg: str) -> dict:
    """Look up whether `pkg` (Trivy's PkgName) is a known-bundled,
    verified-unused tool, by substring match against BUNDLED_TOOL_MAP.
    Returns {"tool", "note", "bundled"} -- the honest _NOT_BUNDLED
    fallback if nothing matches (never guesses)."""
    p = pkg.lower()
    for entry in BUNDLED_TOOL_MAP:
        if entry["match"] in p:
            return {"tool": entry["tool"], "note": entry["note"], "bundled": True}
    return dict(_NOT_BUNDLED)
