# core/smart_status.py
"""
S.M.A.R.T. disk health check, extracted from ui/smart_tab.py so it can run
from a background watchdog (main.py's start_disk_health_watchdog) without
any Tk dependency. Uses "sudo smartctl" via plain ssh.run(), same as the
tab -- this only works if smartctl is NOPASSWD-sudo on the server (or the
stored SSH password is enough for run_sudo-style prompts), which is already
a precondition for the tab itself working, so no new privilege wiring here.
"""

import shlex

_USB_MARKERS = (
    "specify device type",
    "Unknown USB bridge",
    "Unknown device type",
    "scsi error unsupported scsi opcode",
    "mandatory SMART command failed",
    "Read Device Identity failed",
    "Unsupported USB bridge",
)
_USB_DTYPES = ("-d sat", "-d sat,12", "-d usbsunplus",
               "-d usbprolific", "-d usbjmicron")


def _needs_flag(text):
    return any(m in (text or "") for m in _USB_MARKERS)


def _query_one(ssh, dev):
    result = {
        "device": dev, "model": "?", "health": "UNKNOWN",
        "reallocated": "--", "pending": "--", "uncorr": "--",
    }

    def _run_with_flag(flag, args, device):
        cmd = "sudo smartctl {} {} {}".format(flag, args, shlex.quote(device)).strip()
        o, e, _ = ssh.run(cmd)
        return o or "", e or ""

    info_out, info_err = ssh.run("sudo smartctl -i {}".format(shlex.quote(dev)))[0:2]
    info_out, info_err = info_out or "", info_err or ""
    dev_flag = ""
    usb_unsupported = False
    if _needs_flag(info_out + info_err):
        for dtype in _USB_DTYPES:
            o2, e2 = _run_with_flag(dtype, "-i", dev)
            if not _needs_flag(o2 + e2):
                dev_flag = dtype
                break
        else:
            usb_unsupported = True

    for line in info_out.splitlines():
        if line.startswith("Device Model") or line.startswith("Model Family"):
            result["model"] = line.split(":", 1)[-1].strip()[:30]
        elif line.startswith("Model Number") and result["model"] == "?":
            result["model"] = line.split(":", 1)[-1].strip()[:30]

    health_out, health_err = _run_with_flag(dev_flag, "-H", dev)
    combined_health = health_out + health_err
    if not dev_flag and _needs_flag(combined_health):
        for dtype in _USB_DTYPES:
            o2, e2 = _run_with_flag(dtype, "-H", dev)
            c2 = o2 + e2
            if not _needs_flag(c2):
                dev_flag = dtype
                combined_health = c2
                break

    if "PASSED" in combined_health:
        result["health"] = "PASSED"
    elif "FAILED" in combined_health:
        result["health"] = "FAILED"
    elif "OK" in combined_health:
        result["health"] = "OK"
    elif usb_unsupported or (_needs_flag(combined_health) and not dev_flag):
        result["health"] = "No SMART"
    else:
        result["health"] = "UNKNOWN"

    attrs_out, _ = _run_with_flag(dev_flag, "-A", dev)
    attr_map = {"5": "reallocated", "197": "pending", "198": "uncorr"}
    for line in attrs_out.splitlines():
        parts = line.split()
        if len(parts) >= 10 and parts[0] in attr_map:
            result[attr_map[parts[0]]] = parts[-1]

    return result


def check_smart_health(ssh) -> list:
    """
    Returns a list of {"device", "model", "health", "reallocated",
    "pending", "uncorr"} dicts, one per physical block device. "health" is
    one of PASSED/FAILED/OK/No SMART/UNKNOWN, matching ui/smart_tab.py.
    Never raises -- a probe failure just yields no rows, same as no disks
    being found.
    """
    out, _, code = ssh.run(
        "lsblk -d -o NAME,TYPE --noheadings 2>/dev/null | "
        "awk '$2==\"disk\"{print \"/dev/\"$1}'"
    )
    if code != 0 or not (out or "").strip():
        return []

    rows = []
    for dev in out.strip().splitlines():
        dev = dev.strip()
        if not dev:
            continue
        try:
            rows.append(_query_one(ssh, dev))
        except Exception:
            continue
    return rows
