# core/ssl_status.py
"""
Checks TLS certificate expiry for host:port targets on the connected server,
via the same openssl s_client + x509 approach ui/ssl_tab.py uses for its
full multi-host audit. Kept standalone (no Tk dependency, no tab state) so
it can run from a background watchdog to feed the alert engine -- see
main.py's start_ssl_expiry_watchdog().
"""

import re
import datetime

WARN_DAYS = 30
CRIT_DAYS = 7


def _dq(value):
    """Escape for embedding inside a double-quoted bash -c "..." string."""
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def check_hosts_expiry(ssh, hosts) -> list:
    """
    hosts: iterable of (host, port) pairs.
    Returns a list of {"host", "port", "days", "status", "error"} dicts.
    status is one of "ok"/"warn"/"crit"/"error"; "days" is None on error.
    """
    results = []

    for host, port in hosts:
        def _try(connect_host, servername):
            cmd = (
                "bash -c \"timeout 10 openssl s_client "
                "-connect {c}:{p} -servername {s} </dev/null 2>/dev/null "
                "| openssl x509 -noout -text 2>/dev/null\""
                .format(c=_dq(connect_host), p=_dq(port), s=_dq(servername))
            )
            o, _, _ = ssh.run(cmd)
            return o if (o and "Not After" in o) else None

        out = (
            _try(host, host) or
            _try("localhost", host) or
            _try("127.0.0.1", host) or
            _try("localhost", "localhost") or
            None
        )

        if out is None:
            results.append({"host": host, "port": port, "days": None,
                            "status": "error", "error": "No cert returned"})
            continue

        days = None
        for line in out.splitlines():
            m = re.search(r'Not After\s*:\s*(.+)', line.strip())
            if not m:
                continue
            date_str = m.group(1).strip()
            for fmt in ("%b %d %H:%M:%S %Y %Z", "%b  %d %H:%M:%S %Y %Z"):
                try:
                    dt = datetime.datetime.strptime(date_str, fmt)
                    days = (dt - datetime.datetime.utcnow()).days
                    break
                except ValueError:
                    pass
            break

        if days is None:
            results.append({"host": host, "port": port, "days": None,
                            "status": "error", "error": "Could not parse expiry date"})
        elif days <= CRIT_DAYS:
            results.append({"host": host, "port": port, "days": days, "status": "crit"})
        elif days <= WARN_DAYS:
            results.append({"host": host, "port": port, "days": days, "status": "warn"})
        else:
            results.append({"host": host, "port": port, "days": days, "status": "ok"})

    return results
