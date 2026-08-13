# core/service_manager.py

import re
import shlex


class ServiceManager:
    """
    Provides systemd service control via SSH.
    Uses the SSHManager to run commands safely.
    """

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------
    def get_status(self, service_name):
        """
        Returns one of:
        - running
        - stopped
        - failed
        - unknown
        """

        if not self.ssh.connected:
            return "unknown"

        cmd = f"systemctl is-active {shlex.quote(service_name)}"
        out, err, code = self.ssh.run(cmd)
        return self._parse_status_word(out.strip())

    def get_statuses(self, service_names):
        """
        Batched version of get_status() — one remote round trip instead of
        one per service. Returns {service_name: status}.
        """
        if not self.ssh.connected or not service_names:
            return {name: "unknown" for name in service_names}

        quoted = " ".join(shlex.quote(name) for name in service_names)
        out, err, code = self.ssh.run(f"systemctl is-active {quoted}")
        lines = out.splitlines()
        return {
            name: self._parse_status_word(lines[i].strip() if i < len(lines) else "")
            for i, name in enumerate(service_names)
        }

    # ---------------------------------------------------------
    # LISTENING PORTS
    # ---------------------------------------------------------
    # `systemctl is-active` only proves the unit's process is running — it
    # says nothing about whether the ports that process is supposed to bind
    # actually came up (e.g. Emby's HTTPS listener silently not binding
    # because the network wasn't ready yet at startup, while the process
    # itself stays "active" the whole time). This checks real listening
    # sockets so that class of failure is visible instead of showing "running".
    def get_listening_ports(self):
        """
        Returns the set of TCP ports currently in LISTEN state on the
        server, as ints. One remote round trip covers every service —
        callers just check `port in listening_ports`.
        """
        if not self.ssh.connected:
            return set()

        out, err, code = self.ssh.run("ss -tln 2>/dev/null || netstat -tln 2>/dev/null")
        ports = set()
        for line in out.splitlines():
            if "LISTEN" not in line:
                continue
            # Local Address:Port is whichever whitespace-separated column
            # has a colon in it (position varies slightly between `ss` and
            # `netstat` output) — take the trailing :port off of it.
            cols = line.split()
            local_col = next((c for c in cols if ":" in c and c != "LISTEN"), None)
            if not local_col:
                continue
            m = re.search(r':(\d+)$', local_col)
            if m:
                ports.add(int(m.group(1)))
        return ports

    @staticmethod
    def _parse_status_word(word):
        # Exact match, not substring — "active" is literally a substring of
        # "inactive", so a naive `"active" in word` check misreports every
        # stopped service as running.
        if word == "active":
            return "running"
        if word == "inactive":
            return "stopped"
        if word == "failed":
            return "failed"
        return "unknown"

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------
    def start(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        svc = shlex.quote(service_name)
        # Kill any orphaned processes that would block the port before starting
        self.ssh.run_sudo(f"pkill -if {svc} 2>/dev/null; true")
        return self.ssh.run_sudo(f"systemctl start {svc}")

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------
    def stop(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        svc = shlex.quote(service_name)
        out, err, code = self.ssh.run_sudo(f"systemctl stop {svc}")
        # Also kill processes not in the systemd cgroup (started outside systemd)
        self.ssh.run_sudo(f"pkill -if {svc} 2>/dev/null; true")
        return out, err, code

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------
    def restart(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        svc = shlex.quote(service_name)
        self.ssh.run_sudo(f"systemctl stop {svc}")
        # Kill any orphaned processes before starting fresh
        self.ssh.run_sudo(f"pkill -if {svc} 2>/dev/null; true")
        return self.ssh.run_sudo(f"systemctl start {svc}")

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------
    def logs(self, service_name, lines=200):
        """
        Returns the last N lines of logs for the service.
        """

        if not self.ssh.connected:
            return "", "Not connected", 1

        cmd = f"journalctl -u {shlex.quote(service_name)} -n {int(lines)} --no-pager"
        return self.ssh.run(cmd)

    # ---------------------------------------------------------
    # FULL STATUS (systemctl status)
    # ---------------------------------------------------------
    def full_status(self, service_name):
        """
        Returns the full systemctl status output.
        """

        if not self.ssh.connected:
            return "", "Not connected", 1

        cmd = f"systemctl status {shlex.quote(service_name)} --no-pager"
        return self.ssh.run_sudo(cmd)
