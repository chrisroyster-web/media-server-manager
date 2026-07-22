# core/vpn_status.py
"""
Lightweight VPN connected/disconnected check, extracted from the detection
cascade in ui/vpn_tab.py (which also parses server/IP/protocol/uptime for
display -- none of that is needed for a background watchdog). Used by
main.py's start_vpn_watchdog() to catch an unexpected disconnect, which
matters if downloads route through the VPN.
"""


def check_vpn_connected(ssh):
    """
    Returns True/False, or None if connectivity couldn't be determined at
    all (e.g. no VPN tooling found) -- None is treated as "unknown, don't
    alert on it" by the caller rather than as a disconnect.
    """
    out, _, _ = ssh.run(
        "protonvpn-cli status 2>/dev/null || protonvpn status 2>/dev/null")
    if out and out.strip() and "command not found" not in out:
        for line in out.splitlines():
            low = line.lower()
            if "status" in low and ":" in line:
                state = line.split(":", 1)[1].strip().lower()
                return ("connected" in state or "active" in state) and \
                       "disconnected" not in state and "inactive" not in state
        # protonvpn-cli responded but had no parseable Status line
        return None

    svc_out, _, _ = ssh.run(
        "systemctl is-active protonvpn 2>/dev/null; "
        "systemctl is-active protonvpn-cli 2>/dev/null")
    if any(line.strip() == "active" for line in (svc_out or "").splitlines()):
        return True

    wg_out, _, _ = ssh.run("sudo wg show 2>/dev/null")
    if wg_out and wg_out.strip():
        return True

    ip_out, _, _ = ssh.run(
        "ip addr show 2>/dev/null | grep -E '(proton|tun|wg)[0-9]'")
    if ip_out and ip_out.strip():
        return True

    return False
