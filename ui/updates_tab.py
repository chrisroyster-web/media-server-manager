# ui/updates_tab.py
"""
System & Docker update checker.
- apt: lists upgradable packages, can run apt upgrade
- Docker: checks if running containers have newer images available
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import shlex
import json

from core.container_backup import backup_container_mounts


class UpdatesTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="UPDATES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Check Now", command=self._refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(0, 8))

        # --- APT section ---
        apt_hdr = tk.Frame(self, bg=t.bg)
        apt_hdr.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(apt_hdr, text="System Packages  (apt)",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._dist_btn = tk.Button(apt_hdr, text="⬆⬆ Full Upgrade (dist)",
                                    command=lambda: self._run_upgrade(dist=True))
        t.style_button(self._dist_btn)
        self._dist_btn.configure(fg=t.status_stopped_text)
        self._dist_btn.pack(side="right", padx=(0, 6))

        self._upgrade_btn = tk.Button(apt_hdr, text="⬆  Run apt upgrade",
                                       command=self._run_upgrade)
        t.style_button(self._upgrade_btn)
        self._upgrade_btn.configure(fg=t.yellow)
        self._upgrade_btn.pack(side="right")

        apt_frame = tk.Frame(self, bg=t.bg)
        apt_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._apt_tree = self._make_tree(apt_frame,
            cols=("package", "current", "available", "arch", "status"),
            headings=[
                ("package",   "Package",          220, "w"),
                ("current",   "Installed",         140, "w"),
                ("available", "Available",         140, "w"),
                ("arch",      "Arch",               70, "center"),
                ("status",    "Status",            140, "center"),
            ])

        # --- Docker section ---
        docker_hdr = tk.Frame(self, bg=t.bg)
        docker_hdr.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(docker_hdr, text="Docker Images",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._apply_btn = tk.Button(docker_hdr, text="⬆  Apply Update",
                                     command=self._apply_update, state="disabled")
        t.style_button(self._apply_btn)
        self._apply_btn.pack(side="right")

        self._apply_all_btn = tk.Button(docker_hdr, text="⬆⬆ Apply All Updates",
                                         command=self._apply_all_updates, state="disabled")
        t.style_button(self._apply_all_btn)
        self._apply_all_btn.configure(fg=t.status_stopped_text)
        self._apply_all_btn.pack(side="right", padx=(0, 6))

        self._backup_before_recreate_var = tk.BooleanVar(
            value=self.controller.config_manager.get_recreate_backup_enabled())
        tk.Checkbutton(
            docker_hdr, text="Back up bind-mounted data before recreate (recommended)",
            variable=self._backup_before_recreate_var,
            command=self._on_backup_before_recreate_toggle,
            bg=t.bg, fg=t.text, selectcolor=t.surface_dark,
            activebackground=t.bg, font=t.font_small, bd=0,
            highlightthickness=0).pack(side="right", padx=(0, 16))

        docker_frame = tk.Frame(self, bg=t.bg)
        docker_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._docker_tree = self._make_tree(docker_frame,
            cols=("container", "image", "status"),
            headings=[
                ("container", "Container",  200, "w"),
                ("image",     "Image",      300, "w"),
                ("status",    "Status",     120, "center"),
            ])
        self._docker_tree.bind("<<TreeviewSelect>>", self._on_docker_select)
        self._docker_row_info = {}   # tree iid -> {"container", "image", "tag"}

        # Output console for upgrade output
        tk.Label(self, text="Output", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=16, pady=(4, 0))
        self._console = tk.Text(self, height=6, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="x", padx=16, pady=(0, 4))
        self._console.tag_config("ok",   foreground=t.status_running)
        self._console.tag_config("warn", foreground=t.yellow)
        self._console.tag_config("err",  foreground=t.status_stopped_text)

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # TREEVIEW HELPER
    # =========================================================
    def _make_tree(self, parent, cols, headings, height=8):
        t = self.theme
        style = ttk.Style()
        sid = "Upd{}.Treeview".format(id(parent))
        style.configure(sid, background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure(sid + ".Heading", background=t.surface_dark,
                        foreground=t.text_muted, font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map(sid, background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=sid, height=height, selectmode="browse")
        for col, text, width, anchor in headings:
            tree.heading(col, text=text, anchor=anchor)
            tree.column(col, width=width, minwidth=50,
                        anchor=anchor, stretch=(width > 150))
        tree.tag_configure("odd",      background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",     background=t.card_bg,      foreground=t.text)
        tree.tag_configure("update",   foreground=t.yellow)
        tree.tag_configure("current",  foreground=t.status_running)
        tree.tag_configure("unknown",  foreground=t.text_muted)
        tree.tag_configure("held",     foreground=t.text_muted)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    # =========================================================
    # REFRESH
    # =========================================================
    def _refresh(self):
        if getattr(self, "_fetching", False): return
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._refresh_btn.config(state="disabled", text="Checking…")
        self._upgrade_btn.config(state="disabled")
        self._set_status("Checking for updates…")
        self._log("Checking for updates…\n")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh

            # 1. apt-get update (quiet) then list upgradable
            self._log("Running apt-get update…\n", "warn")
            ssh.run_sudo("apt-get update -qq")

            out, _, _ = ssh.run(
                "apt list --upgradable 2>/dev/null | grep -v '^Listing'")
            apt_packages = []
            for line in out.strip().splitlines():
                # Format: package/repo version arch [upgradable from: old]
                try:
                    parts   = line.split()
                    pkg     = parts[0].split("/")[0]
                    avail   = parts[1]
                    arch    = parts[2]
                    old_ver = "--"
                    if "upgradable from:" in line:
                        old_ver = line.split("upgradable from:")[-1].strip().rstrip("]")
                    apt_packages.append((pkg, old_ver, avail, arch))
                except Exception:
                    continue

            # apt-mark hold stops apt-get upgrade from touching a package, but
            # `apt list --upgradable` lists held packages exactly like any
            # other -- it doesn't cross-reference dpkg selections. Fetch the
            # hold list separately so held packages can be flagged instead of
            # looking like a normal pending update that the upgrade button
            # will silently skip.
            held_out, _, _ = ssh.run("apt-mark showhold 2>/dev/null")
            held_pkgs = set(held_out.strip().splitlines())

            # 2. Docker image check — compare the image ID the container is
            # actually running against the freshly-pulled tag's image ID.
            # (Parsing docker pull's text output instead — "up to date" vs
            # "newer" — is unreliable across repeated checks: once an update
            # has been pulled once, the local cache already matches the
            # registry, so every later pull reports "up to date" even though
            # the *running* container was never recreated and is still on
            # the old image. Comparing IDs directly avoids that false
            # negative regardless of local cache state.)
            # Discover containers live rather than from a fixed list, so
            # anything running on the host gets checked -- including sidecars
            # (e.g. a stack's db/redis containers) that aren't individually
            # registered in config. Config is still used to give known
            # containers a friendly display name; anything else falls back
            # to its raw container name.
            docker_cfg = self.controller.config_manager.get_docker()
            container_to_name = {data.get("container", ""): name
                                  for name, data in docker_cfg.items() if data.get("container")}

            names_out, _, names_code = ssh.run("docker ps -a --format '{{.Names}}'")
            containers = sorted(c.strip() for c in names_out.strip().splitlines() if c.strip()) \
                if names_code == 0 else []

            docker_results = []
            for container in containers:
                name = container_to_name.get(container, container)
                q = shlex.quote(container)
                # .Config.Image = the tag the container was created from
                # .Image        = the image ID it's actually running right now
                insp_out, _, insp_code = ssh.run(
                    "docker inspect --format '{{.Config.Image}}|{{.Image}}' " + q + " 2>/dev/null")
                if insp_code != 0 or not insp_out.strip():
                    docker_results.append((name, container, "Not found", "unknown", container))
                    continue
                insp_parts = insp_out.strip().split("|", 1)
                image      = insp_parts[0] if insp_parts and insp_parts[0] else container
                running_id = insp_parts[1] if len(insp_parts) > 1 else ""

                pull_out, _, pull_code = ssh.run_sudo(
                    "docker pull {} 2>&1".format(shlex.quote(image)))
                if pull_code != 0:
                    # Custom-built images (e.g. tracearr-db's local
                    # TimescaleDB build) were never pushed anywhere, so
                    # there's no registry to check -- that's not a failed
                    # check, there's just nothing to compare against.
                    if "repository does not exist" in pull_out or "pull access denied" in pull_out:
                        status, tag = "Local build (no registry)", "current"
                    else:
                        status, tag = pull_out.strip()[:30] or "Check failed", "unknown"
                else:
                    new_id_out, _, _ = ssh.run(
                        "docker inspect --format '{{.Id}}' " + shlex.quote(image) + " 2>/dev/null")
                    new_id = new_id_out.strip()
                    if new_id and running_id and new_id != running_id:
                        status, tag = "Update available", "update"
                    else:
                        status, tag = "Up to date", "current"
                docker_results.append((name, image, status, tag, container))

            self.after(0, lambda a=apt_packages, d=docker_results, h=held_pkgs: self._populate(a, d, h))
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, apt_packages, docker_results, held_pkgs=None):
        t = self.theme
        held_pkgs = held_pkgs or set()

        # APT tree
        self._apt_tree.delete(*self._apt_tree.get_children())
        for idx, (pkg, cur, avail, arch) in enumerate(apt_packages):
            is_held = pkg in held_pkgs
            status  = "Held" if is_held else "Update available"
            tag = ("even" if idx % 2 == 0 else "odd", "held" if is_held else "update")
            self._apt_tree.insert("", "end",
                                   values=(pkg, cur, avail, arch, status), tags=tag)

        # Docker tree
        self._docker_tree.delete(*self._docker_tree.get_children())
        self._docker_row_info = {}
        for idx, (name, image, status, stag, container) in enumerate(docker_results):
            row_tag = "even" if idx % 2 == 0 else "odd"
            iid = self._docker_tree.insert("", "end",
                                      values=(name, image, status),
                                      tags=(row_tag, stag))
            self._docker_row_info[iid] = {
                "name": name, "image": image, "tag": stag, "container": container,
            }
        self._apply_btn.config(state="disabled")
        has_updates = any(r["tag"] == "update" for r in self._docker_row_info.values())
        self._apply_all_btn.config(state="normal" if has_updates else "disabled")

        # Summary cards
        for w in self._summary_frame.winfo_children():
            w.destroy()
        apt_count = len(apt_packages)
        docker_updated = sum(1 for _, _, _, tag, _ in docker_results if tag == "update")

        for label, val, color in [
            ("Apt Updates",      str(apt_count),      t.yellow if apt_count else t.status_running),
            ("Docker Updates",   str(docker_updated), t.yellow if docker_updated else t.status_running),
            ("Docker Checked",   str(len(docker_results)), t.text_muted),
        ]:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=label, bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            tk.Label(card, text=val, bg=t.card_bg,
                     fg=color, font=("Segoe UI", 18, "bold")).pack()

        self._upgrade_btn.config(state="normal" if apt_count else "disabled")
        self._dist_btn.config(state="normal")
        self._refresh_btn.config(state="normal", text="⟳ Check Now")
        self._last_lbl.config(text="Last check: " + time.strftime("%H:%M:%S"))
        self._set_status("{} apt package{} upgradable  —  {} Docker image{} checked".format(
            apt_count, "s" if apt_count != 1 else "",
            len(docker_results), "s" if len(docker_results) != 1 else ""))
        self._log("Done. {} apt packages upgradable.\n".format(apt_count), "ok")

    # =========================================================
    # APT UPGRADE
    # =========================================================
    def _run_upgrade(self, dist=False):
        cmd   = "dist-upgrade" if dist else "upgrade"
        title = "Run apt {}".format(cmd)
        msg   = (
            "This will run:\n\n"
            "  sudo apt-get {} -y\n\n"
            "on the remote server.{}Continue?"
        ).format(
            cmd,
            "\n\ndist-upgrade may install or remove packages\nto satisfy dependencies.\n\n" if dist else "\n\n"
        )
        if not messagebox.askyesno(title, msg, parent=self):
            return
        self._upgrade_btn.config(state="disabled", text="Upgrading…")
        self._dist_btn.config(state="disabled")
        self._log("\n--- Running apt-get {} ---\n".format(cmd), "warn")
        threading.Thread(target=self._do_upgrade, args=(cmd,), daemon=True).start()

    def _do_upgrade(self, cmd="upgrade"):
        ssh = self.controller.ssh
        out, err, code = ssh.run_sudo(
            "DEBIAN_FRONTEND=noninteractive apt-get {} -y".format(cmd))
        def _done(out=out, code=code):
            self._log(out + "\n", "ok" if code == 0 else "err")
            self._log("Exit code: {}\n".format(code),
                      "ok" if code == 0 else "err")
            self._upgrade_btn.config(state="normal", text="⬆  Run apt upgrade")
            self._dist_btn.config(state="normal")
            self._set_status("{} complete (exit {})".format(cmd, code),
                             "ok" if code == 0 else "error")
        self.after(0, _done)

    # =========================================================
    # DOCKER — APPLY UPDATE
    # =========================================================
    def _on_docker_select(self, _event=None):
        sel = self._docker_tree.selection()
        row = self._docker_row_info.get(sel[0]) if sel else None
        self._apply_btn.config(state="normal" if row and row["tag"] == "update" else "disabled")

    def _apply_update(self):
        sel = self._docker_tree.selection()
        if not sel:
            return
        row = self._docker_row_info.get(sel[0])
        if not row or not row["container"]:
            return
        self._apply_btn.config(state="disabled", text="Applying…")
        self._apply_all_btn.config(state="disabled")
        self._log("\n--- Applying update for {} ---\n".format(row["name"]), "warn")
        threading.Thread(target=self._do_apply_update,
                          args=(row["container"], row["name"], row["image"]),
                          daemon=True).start()

    def _do_apply_update(self, container, display_name, image):
        ssh = self.controller.ssh
        out, _, code = ssh.run("docker inspect {} 2>/dev/null".format(shlex.quote(container)))
        info = None
        if code == 0 and out.strip():
            try:
                data = json.loads(out)
                info = data[0] if data else None
            except Exception:
                info = None
        if info is None:
            self.after(0, lambda: self._finish_apply(
                False, "Could not inspect {} — is it still running?".format(container)))
            return

        labels      = (info.get("Config") or {}).get("Labels") or {}
        project     = labels.get("com.docker.compose.project")
        service     = labels.get("com.docker.compose.service")
        config_file = labels.get("com.docker.compose.project.config_files", "")

        if project and service:
            self._apply_via_compose(ssh, container, info, project, service, config_file, display_name)
        else:
            self._prompt_recreate(ssh, container, info, display_name, image)

    def _apply_via_compose(self, ssh, container, info, project, service, config_file, display_name):
        ok, msg = self._apply_via_compose_sync(
            ssh, container, info, project, service, config_file, display_name)
        self.after(0, lambda: self._finish_apply(ok, msg))

    def _apply_via_compose_sync(self, ssh, container, info, project, service, config_file, display_name):
        """Synchronous compose update: stop, optionally back up, `pull && up -d`.
        Returns (ok, message) instead of driving the single-item UI callback,
        so both the single "Apply Update" button and the "Apply All" batch
        runner share this one code path."""
        # -p (project name) alone isn't reliably enough for `pull`/`up` on every
        # Compose version -- those need to read the actual compose file, and not
        # every version can recover its location from container labels ("No
        # configuration file provided: not found"). Docker Compose stamps the
        # file path(s) it used onto every container it creates via the
        # com.docker.compose.project.config_files label, so use that directly.
        ff = " ".join("-f {}".format(shlex.quote(f.strip()))
                       for f in config_file.split(",") if f.strip())

        # Stop first (same as the standalone recreate path) so the backup
        # step tars a quiesced mount rather than one being actively written
        # to. `docker compose up -d` recreates/starts based on image hash
        # and container existence, not current running state, so a
        # pre-stopped container is handled correctly -- this is the same
        # state `docker stop <svc> && docker compose up -d` would leave a
        # human in.
        self._log("Stopping {}…\n".format(display_name))
        _, stop_err, stop_code = ssh.run("docker stop {}".format(shlex.quote(container)))
        if stop_code != 0:
            return False, ("Stop failed (exit {}) — update aborted, container "
                            "untouched: {}".format(stop_code, stop_err))

        backup_note = ""
        if self.controller.config_manager.get_recreate_backup_enabled():
            self._log("Backing up bind-mounted data…\n")
            cfg = self.controller.config_manager
            result = backup_container_mounts(
                ssh, container, info,
                backup_root=cfg.get_recreate_backup_dir(),
                keep=cfg.get_recreate_backup_keep())
            self.controller.audit_log(
                "docker.recreate_backup", container,
                detail="{} backed up, {} skipped, {} failed -> {}".format(
                    len(result["backed_up"]), len(result["skipped"]),
                    len(result["failed"]), result["dir"]),
                result="ok" if result["ok"] else "fail")
            self._log(result["output"] + "\n", "ok" if result["ok"] else "err")
            if not result["ok"]:
                return False, ("Backup failed before update — {} is stopped but "
                                "compose has NOT been run, nothing else was "
                                "touched. Fix the backup problem (disk space / "
                                "permissions on {}) and retry."
                                .format(display_name, result["dir"]))
            if result["backed_up"]:
                backup_note = " Pre-update backup saved to {}.".format(result["dir"])

        cmd = "docker compose {ff} -p {p} pull {s} && docker compose {ff} -p {p} up -d {s}".format(
            ff=ff, p=shlex.quote(project), s=shlex.quote(service))
        self._log("$ {}\n".format(cmd), "warn")
        out, err, code = ssh.run(cmd)
        self._log((out or "") + (err or "") + "\n", "ok" if code == 0 else "err")
        if code == 0:
            return True, "{} updated and recreated via compose.{}".format(display_name, backup_note)
        return False, "compose pull/up failed (exit {}) — see output above.{}".format(code, backup_note)

    # ---- Standalone (non-compose) container: best-effort recreate ----
    def _prompt_recreate(self, ssh, container, info, display_name, image):
        cmd = self._build_recreate_cmd(container, info, image)

        def _ask():
            msg = (
                "{} isn't managed by Docker Compose, so it has to be recreated "
                "directly. This is a best-effort clone of its current ports, "
                "volumes, environment variables, restart policy, and network — "
                "anything else (labels, extra hosts, capabilities, etc.) will "
                "NOT be preserved.\n\n"
                "Command that will run:\n\n{}\n\nContinue?"
            ).format(display_name, cmd)
            if messagebox.askyesno("Apply Update — {}".format(display_name), msg, parent=self):
                threading.Thread(target=self._run_recreate_with_backup,
                                  args=(ssh, container, info, image, display_name),
                                  daemon=True).start()
            else:
                self._finish_apply(None, "Cancelled.")
        self.after(0, _ask)

    def _on_backup_before_recreate_toggle(self):
        self.controller.config_manager.set_recreate_backup_enabled(
            self._backup_before_recreate_var.get())

    def _run_recreate_with_backup(self, ssh, container, info, image, display_name):
        ok, msg = self._apply_recreate_sync(ssh, container, info, image, display_name)
        self.after(0, lambda: self._finish_apply(ok, msg))

    def _apply_recreate_sync(self, ssh, container, info, image, display_name):
        """Staged, unlike a one-shot `stop && rm && run`: stop first (abort
        cleanly if that fails -- container untouched), then back up bind
        mounts if enabled (abort BEFORE rm if the backup itself fails --
        the container is left stopped-but-not-removed, which is
        recoverable), then rm && run. Strictly safer than a single shell
        command, which could leave zero containers running if the
        connection dropped mid-sequence. Returns (ok, message); shared by
        the single "Apply Update" button and the "Apply All" batch runner."""
        self._log("Stopping {}…\n".format(display_name))
        _, stop_err, stop_code = ssh.run_sudo("docker stop {}".format(shlex.quote(container)))
        if stop_code != 0:
            return False, ("Stop failed (exit {}) — recreate aborted, container "
                            "untouched: {}".format(stop_code, stop_err))

        backup_note = ""
        if self.controller.config_manager.get_recreate_backup_enabled():
            self._log("Backing up bind-mounted data…\n")
            cfg = self.controller.config_manager
            result = backup_container_mounts(
                ssh, container, info,
                backup_root=cfg.get_recreate_backup_dir(),
                keep=cfg.get_recreate_backup_keep())
            self.controller.audit_log(
                "docker.recreate_backup", container,
                detail="{} backed up, {} skipped, {} failed -> {}".format(
                    len(result["backed_up"]), len(result["skipped"]),
                    len(result["failed"]), result["dir"]),
                result="ok" if result["ok"] else "fail")
            self._log(result["output"] + "\n", "ok" if result["ok"] else "err")
            if not result["ok"]:
                return False, ("Backup failed before recreate — {} is stopped but "
                                "NOT removed, no data was touched. Fix the backup "
                                "problem (disk space / permissions on {}) and retry."
                                .format(display_name, result["dir"]))
            if result["backed_up"]:
                backup_note = " Pre-recreate backup saved to {}.".format(result["dir"])

        run_cmd = self._build_run_cmd(container, info, image)
        cmd = "docker rm {} && {}".format(shlex.quote(container), run_cmd)
        self._log("$ {}\n".format(cmd), "warn")
        out, err, code = ssh.run_sudo(cmd)
        self._log((out or "") + (err or "") + "\n", "ok" if code == 0 else "err")
        if code == 0:
            return True, "{} recreated on the new image.{}".format(display_name, backup_note)
        return False, ("Recreate failed (exit {}) — the old container may already be "
                        "stopped/removed. Check the output above.{}".format(code, backup_note))

    def _apply_one_sync(self, ssh, container, info, display_name, image):
        """Route a single container to its update path (compose vs. manual
        recreate) and run it synchronously. Used by the "Apply All" batch
        runner; the single-item flow instead calls _apply_via_compose /
        _run_recreate_with_backup directly since it also needs the
        recreate confirmation dialog first."""
        labels  = (info.get("Config") or {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        config_file = labels.get("com.docker.compose.project.config_files", "")
        if project and service:
            return self._apply_via_compose_sync(
                ssh, container, info, project, service, config_file, display_name)
        return self._apply_recreate_sync(ssh, container, info, image, display_name)

    def _build_recreate_cmd(self, container, info, image):
        """Preview text for the confirmation dialog only -- actual execution
        happens in stages via _run_recreate_with_backup()."""
        run_cmd = self._build_run_cmd(container, info, image)
        c = shlex.quote(container)
        return "docker stop {c} && docker rm {c} && {run}".format(c=c, run=run_cmd)

    def _build_run_cmd(self, container, info, image):
        cfg      = info.get("Config") or {}
        host_cfg = info.get("HostConfig") or {}
        name     = (info.get("Name") or "/" + container).lstrip("/")

        parts = ["docker", "run", "-d", "--name", shlex.quote(name)]

        policy = (host_cfg.get("RestartPolicy") or {}).get("Name") or ""
        if policy and policy != "no":
            retries = (host_cfg.get("RestartPolicy") or {}).get("MaximumRetryCount", 0)
            if policy == "on-failure" and retries:
                parts += ["--restart", "on-failure:{}".format(retries)]
            else:
                parts += ["--restart", policy]

        net_mode = host_cfg.get("NetworkMode") or ""
        if net_mode and net_mode not in ("default", "bridge"):
            parts += ["--network", shlex.quote(net_mode)]

        pid_mode = host_cfg.get("PidMode") or ""
        if pid_mode:
            parts += ["--pid", shlex.quote(pid_mode)]

        for cap in sorted(host_cfg.get("CapAdd") or []):
            parts += ["--cap-add", shlex.quote(cap)]

        for cap in sorted(host_cfg.get("CapDrop") or []):
            parts += ["--cap-drop", shlex.quote(cap)]

        for opt in (host_cfg.get("SecurityOpt") or []):
            parts += ["--security-opt", shlex.quote(opt)]

        for cport, bindings in sorted((host_cfg.get("PortBindings") or {}).items()):
            for b in (bindings or []):
                hostport = b.get("HostPort") or ""
                if not hostport:
                    continue
                hostip = b.get("HostIp") or ""
                spec = "{}:{}:{}".format(hostip, hostport, cport) if hostip else "{}:{}".format(hostport, cport)
                parts += ["-p", shlex.quote(spec)]

        for m in (info.get("Mounts") or []):
            src, dst = m.get("Source", ""), m.get("Destination", "")
            if not src or not dst:
                continue
            mode = "rw" if m.get("RW", True) else "ro"
            parts += ["-v", shlex.quote("{}:{}:{}".format(src, dst, mode))]

        for e in (cfg.get("Env") or []):
            parts += ["-e", shlex.quote(e)]

        parts.append(shlex.quote(image))

        for arg in (cfg.get("Cmd") or []):
            parts.append(shlex.quote(arg))

        return " ".join(parts)

    def _finish_apply(self, ok, message):
        self._apply_btn.config(state="normal", text="⬆  Apply Update")
        has_updates = any(r["tag"] == "update" for r in self._docker_row_info.values())
        self._apply_all_btn.config(state="normal" if has_updates else "disabled")
        self._log(message + "\n", "ok" if ok else ("err" if ok is False else "warn"))
        self._set_status(message, "ok" if ok else ("error" if ok is False else "info"))
        if ok:
            self.after(800, self._refresh)

    # =========================================================
    # DOCKER — APPLY ALL UPDATES
    # =========================================================
    def _apply_all_updates(self):
        pending = [row for row in self._docker_row_info.values() if row["tag"] == "update"]
        if not pending:
            return
        self._apply_btn.config(state="disabled")
        self._apply_all_btn.config(state="disabled", text="Preparing…")
        threading.Thread(target=self._prepare_apply_all, args=(pending,), daemon=True).start()

    def _prepare_apply_all(self, pending):
        """Inspect every pending container up front so the confirmation
        dialog can tell the user which ones are safe compose updates vs.
        which need a best-effort manual recreate — and so the batch run
        itself doesn't need to re-inspect anything."""
        ssh = self.controller.ssh
        plan = []
        for row in pending:
            container = row["container"]
            out, _, code = ssh.run("docker inspect {} 2>/dev/null".format(shlex.quote(container)))
            info = None
            if code == 0 and out.strip():
                try:
                    data = json.loads(out)
                    info = data[0] if data else None
                except Exception:
                    info = None
            labels = ((info or {}).get("Config") or {}).get("Labels") or {}
            method = ("compose" if labels.get("com.docker.compose.project")
                      and labels.get("com.docker.compose.service") else "recreate")
            plan.append(dict(row, info=info, method=method))
        self.after(0, lambda: self._confirm_apply_all(plan))

    def _confirm_apply_all(self, plan):
        lines = ["  • {} ({}) — {}".format(
            p["name"], p["image"],
            "compose" if p["method"] == "compose" else "MANUAL RECREATE"
            if p["info"] else "SKIP — not inspectable") for p in plan]
        n_recreate = sum(1 for p in plan if p["method"] == "recreate" and p["info"])
        warn = ("\n\n{} container{} will use a best-effort manual recreate "
                "(clones current ports/volumes/env/restart policy/network — "
                "anything else is not preserved). Watch the output console "
                "as it runs.".format(n_recreate, "s" if n_recreate != 1 else "")
                ) if n_recreate else ""
        msg = (
            "This will update {} container{} one at a time, in this order:\n\n{}\n\n"
            "Each is stopped, optionally backed up (per the checkbox above), "
            "then recreated on its new image. A failure on one does not stop "
            "the rest — you'll get a summary when it's done.{}\n\nContinue?"
        ).format(len(plan), "s" if len(plan) != 1 else "", "\n".join(lines), warn)

        if not messagebox.askyesno("Apply All Updates", msg, parent=self):
            self._apply_all_btn.config(state="normal", text="⬆⬆ Apply All Updates")
            self._on_docker_select()
            return

        runnable = [p for p in plan if p["info"] is not None]
        skipped  = [p for p in plan if p["info"] is None]
        for p in skipped:
            self._log("Skipping {} — could not inspect it (is it still "
                       "running?)\n".format(p["name"]), "err")

        self._log("\n=== Applying {} update{} ===\n".format(
            len(runnable), "s" if len(runnable) != 1 else ""), "warn")
        self._apply_all_btn.config(text="Applying All…")
        threading.Thread(target=self._do_apply_all,
                          args=(runnable, len(skipped)), daemon=True).start()

    def _do_apply_all(self, plan, pre_skipped):
        ssh = self.controller.ssh
        oks = []
        for p in plan:
            self._log("\n--- {} ---\n".format(p["name"]), "warn")
            ok, msg = self._apply_one_sync(ssh, p["container"], p["info"], p["name"], p["image"])
            self._log(msg + "\n", "ok" if ok else "err")
            oks.append(ok)

        ok_count   = sum(oks)
        total      = len(plan) + pre_skipped
        fail_count = total - ok_count
        summary = "Applied {}/{} update{} successfully.".format(
            ok_count, total, "s" if total != 1 else "")
        if fail_count:
            summary += " {} failed or skipped — see output above.".format(fail_count)
        self.after(0, lambda: self._finish_apply_all(fail_count == 0, summary))

    def _finish_apply_all(self, all_ok, message):
        self._apply_all_btn.config(state="normal", text="⬆⬆ Apply All Updates")
        self._log("\n=== " + message + " ===\n", "ok" if all_ok else "err")
        self._set_status(message, "ok" if all_ok else "error")
        self.after(800, self._refresh)

    # =========================================================
    # HELPERS
    # =========================================================
    def _log(self, text, tag=""):
        def _do():
            self._console.config(state="normal")
            self._console.insert("end", text, tag)
            self._console.see("end")
            self._console.config(state="disabled")
        self.after(0, _do)

    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status_lbl.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "error": t.status_stopped, "ok": t.status_running}
        self._status_lbl.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
