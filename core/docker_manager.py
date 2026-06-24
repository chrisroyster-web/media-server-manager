# core/docker_manager.py

class DockerManager:
    """
    Provides Docker container control via SSH.
    Uses the SSHManager to run commands safely.
    """

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------
    def get_status(self, container_name):
        """
        Returns one of:
        - running
        - stopped
        - scheduled  (exited cleanly with a schedule/interval env var set)
        - paused
        - unknown
        """

        if not self.ssh.connected:
            return "unknown"

        cmd = f"docker inspect -f '{{{{.State.Status}}}}' {container_name}"
        out, err, code = self.ssh.run(cmd)

        if code != 0:
            # Inspect failed — fall back to name hint for well-known schedulers
            if "watchtower" in container_name.lower():
                return "scheduled"
            return "unknown"

        status = out.strip()

        if status == "paused":
            return "paused"

        if status in ("running", "exited"):
            # Check for schedule-related env vars so Watchtower (and similar
            # containers that run on a cron/interval) show as "scheduled"
            # regardless of whether the container is currently up or exited.
            env_cmd = (
                f"docker inspect -f "
                f"'{{{{range .Config.Env}}}}{{{{.}}}}|{{{{end}}}}' "
                f"{container_name}"
            )
            env_out, _, env_code = self.ssh.run(env_cmd)
            if env_code == 0:
                env_vars = env_out.strip().split("|")
                schedule_keys = (
                    "WATCHTOWER_SCHEDULE",
                    "WATCHTOWER_POLL_INTERVAL",
                    "WATCHTOWER_CRON_EXPR",
                    "SCHEDULE",
                    "CRON",
                )
                if any(
                    any(e.upper().startswith(k) for k in schedule_keys)
                    for e in env_vars
                ):
                    return "scheduled"
            return "running" if status == "running" else "stopped"

        return "unknown"

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------
    def start(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker start {container_name}")

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------
    def stop(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker stop {container_name}")

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------
    def restart(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker restart {container_name}")

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------
    def logs(self, container_name, lines=200):
        if not self.ssh.connected:
            return "", "Not connected", 1
        cmd = f"docker logs --tail {lines} {container_name}"
        return self.ssh.run(cmd)

    # ---------------------------------------------------------
    # INSPECT
    # ---------------------------------------------------------
    def inspect(self, container_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        cmd = f"docker inspect {container_name}"
        return self.ssh.run(cmd)

    # ---------------------------------------------------------
    # LIST CONTAINERS
    # ---------------------------------------------------------
    def list_containers(self):
        if not self.ssh.connected:
            return []
        cmd = "docker ps -a --format '{{.Names}}'"
        out, err, code = self.ssh.run(cmd)
        if code != 0:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]
