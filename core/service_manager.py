# core/service_manager.py

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

        cmd = f"systemctl is-active {service_name}"
        out, err, code = self.ssh.run(cmd)

        if "active" in out:
            return "running"
        if "inactive" in out:
            return "stopped"
        if "failed" in out:
            return "failed"

        return "unknown"

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------
    def start(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        # Kill any orphaned processes that would block the port before starting
        self.ssh.run_sudo(f"pkill -if '{service_name}' 2>/dev/null; true")
        return self.ssh.run_sudo(f"systemctl start {service_name}")

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------
    def stop(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        out, err, code = self.ssh.run_sudo(f"systemctl stop {service_name}")
        # Also kill processes not in the systemd cgroup (started outside systemd)
        self.ssh.run_sudo(f"pkill -if '{service_name}' 2>/dev/null; true")
        return out, err, code

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------
    def restart(self, service_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        self.ssh.run_sudo(f"systemctl stop {service_name}")
        # Kill any orphaned processes before starting fresh
        self.ssh.run_sudo(f"pkill -if '{service_name}' 2>/dev/null; true")
        return self.ssh.run_sudo(f"systemctl start {service_name}")

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------
    def logs(self, service_name, lines=200):
        """
        Returns the last N lines of logs for the service.
        """

        if not self.ssh.connected:
            return "", "Not connected", 1

        cmd = f"journalctl -u {service_name} -n {lines} --no-pager"
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

        cmd = f"systemctl status {service_name} --no-pager"
        return self.ssh.run_sudo(cmd)
