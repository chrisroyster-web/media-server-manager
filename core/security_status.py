# core/security_status.py
"""
Fail2ban ban totals and UFW active/inactive state, extracted from
ui/fail2ban_tab.py and ui/ufw_tab.py for main.py's start_security_watchdog().
Both tools already require sudo in their tabs (via ssh.run_sudo), so this
reuses the same access rather than needing anything new.
"""

import re
import shlex


def check_fail2ban_total_banned(ssh):
    """
    Returns the total "currently banned" count summed across all jails, or
    None if fail2ban isn't installed / fail2ban-client isn't reachable.
    """
    _, _, code = ssh.run("which fail2ban-client 2>/dev/null")
    if code != 0:
        return None

    out, _, code = ssh.run_sudo("fail2ban-client status")
    if code != 0:
        return None

    jail_names = []
    for line in out.splitlines():
        if "Jail list" in line or "Jails list" in line:
            _, _, rest = line.partition(":")
            jail_names = [j.strip() for j in rest.split(",") if j.strip()]
            break

    total = 0
    for jail in jail_names:
        out2, _, code2 = ssh.run_sudo("fail2ban-client status {}".format(shlex.quote(jail)))
        if code2 != 0:
            continue
        for line in out2.splitlines():
            clean = re.sub(r"[|`\-\\]", "", line).strip()
            if "Currently banned:" in clean:
                m = re.search(r"\d+", clean)
                if m:
                    total += int(m.group())
    return total


def check_ufw_active(ssh):
    """
    Returns True/False, or None if ufw isn't installed / status couldn't
    be read (e.g. sudo not permitted) -- None means "don't know", not
    "inactive", so the watchdog doesn't fire a false alarm on a box that
    just doesn't use ufw.
    """
    out, err, code = ssh.run_sudo("ufw status numbered 2>/dev/null")
    if code != 0 or not (out or "").strip():
        return None
    return "Status: active" in out
