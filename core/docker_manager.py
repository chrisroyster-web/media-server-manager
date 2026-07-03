# core/docker_manager.py

import shlex


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

        cmd = f"docker inspect -f '{{{{.State.Status}}}}' {shlex.quote(container_name)}"
        out, err, code = self.ssh.run(cmd)

        if code != 0:
            return "not_installed"

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
                f"{shlex.quote(container_name)}"
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

    def get_statuses(self, container_names):
        """
        Batched version of get_status() — one remote round trip instead of
        up to two per container. Returns {container_name: status}.
        """
        if not self.ssh.connected or not container_names:
            return {name: "unknown" for name in container_names}

        quoted = " ".join(shlex.quote(n) for n in container_names)
        fmt = "{{.Name}}|{{.State.Status}}|{{range .Config.Env}}{{.}};{{end}}"
        out, _, _ = self.ssh.run(f"docker inspect -f '{fmt}' {quoted} 2>/dev/null")

        schedule_keys = (
            "WATCHTOWER_SCHEDULE", "WATCHTOWER_POLL_INTERVAL",
            "WATCHTOWER_CRON_EXPR", "SCHEDULE", "CRON",
        )
        found = {}
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) < 2:
                continue
            # docker inspect always prefixes .Name with "/"
            name  = parts[0].lstrip("/")
            state = parts[1]
            env_str = parts[2] if len(parts) > 2 else ""

            if state == "paused":
                found[name] = "paused"
            elif state in ("running", "exited"):
                env_vars = [e for e in env_str.split(";") if e]
                is_scheduled = any(
                    any(e.upper().startswith(k) for k in schedule_keys)
                    for e in env_vars
                )
                found[name] = "scheduled" if is_scheduled else (
                    "running" if state == "running" else "stopped")
            else:
                found[name] = "unknown"

        # Names that never appeared in the output failed to inspect
        # (container doesn't exist), matching get_status()'s code!=0 case.
        return {name: found.get(name, "not_installed") for name in container_names}

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------
    def start(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker start {shlex.quote(container_name)}")

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------
    def stop(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker stop {shlex.quote(container_name)}")

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------
    def restart(self, container_name):
        if not self.ssh.connected:
            return "Not connected"

        return self.ssh.run_sudo(f"docker restart {shlex.quote(container_name)}")

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------
    def logs(self, container_name, lines=200):
        if not self.ssh.connected:
            return "", "Not connected", 1
        cmd = f"docker logs --tail {int(lines)} {shlex.quote(container_name)}"
        return self.ssh.run(cmd)

    # ---------------------------------------------------------
    # INSPECT
    # ---------------------------------------------------------
    def inspect(self, container_name):
        if not self.ssh.connected:
            return "", "Not connected", 1
        cmd = f"docker inspect {shlex.quote(container_name)}"
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

    # ---------------------------------------------------------
    # PULL
    # ---------------------------------------------------------
    def pull(self, container_name):
        """Pull the latest version of the image used by a container."""
        if not self.ssh.connected:
            return "", "Not connected", 1
        out, _, code = self.ssh.run(
            f"docker inspect -f '{{{{.Config.Image}}}}' {shlex.quote(container_name)} 2>/dev/null")
        if code != 0 or not out.strip():
            return "", f"Cannot determine image for {container_name}", 1
        image = out.strip()
        return self.ssh.run(f"docker pull {shlex.quote(image)} 2>&1")

    # ---------------------------------------------------------
    # PRUNE
    # ---------------------------------------------------------
    def prune_images(self):
        """Remove all dangling (unused) images."""
        if not self.ssh.connected:
            return "", "Not connected", 1
        return self.ssh.run("docker image prune -f 2>&1")

    def prune_volumes(self):
        """Remove all unused volumes."""
        if not self.ssh.connected:
            return "", "Not connected", 1
        return self.ssh.run("docker volume prune -f 2>&1")

    # ---------------------------------------------------------
    # LIST IMAGES
    # ---------------------------------------------------------
    def list_images(self):
        """Return list of dicts describing local Docker images, including layer counts."""
        if not self.ssh.connected:
            return []
        out, _, _ = self.ssh.run(
            "docker images --format "
            "'{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}|{{.CreatedSince}}' 2>/dev/null")
        images = []
        for line in out.strip().splitlines():
            parts = line.split("|")
            if len(parts) == 5:
                images.append({
                    "repo": parts[0], "tag": parts[1], "id": parts[2],
                    "size": parts[3], "created": parts[4], "layers": "?",
                })
        if not images:
            return images
        # Fetch layer counts with a single inspect call across all image IDs
        ids_str = " ".join(shlex.quote(img["id"]) for img in images)
        layer_out, _, _ = self.ssh.run(
            f"docker image inspect {ids_str} "
            f"--format '{{{{.Id}}}}|{{{{len .RootFS.Layers}}}}' 2>/dev/null")
        layer_map = {}
        for line in layer_out.strip().splitlines():
            parts = line.split("|")
            if len(parts) == 2:
                full_id = parts[0]
                # docker images shows first 12 hex chars; inspect gives sha256:<64-hex>
                short_id = full_id[7:19] if full_id.startswith("sha256:") else full_id[:12]
                layer_map[short_id] = parts[1]
        for img in images:
            img["layers"] = layer_map.get(img["id"], "?")
        return images
