# ui/backup_tab.py
"""
Backup status tab.
Parses restic / rsync / duplicati logs to show last backup time,
duration, size, and pass/fail status.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import re
import json
import os
import shlex

from ui.refresh_control import RefreshControl

# Defined before importing RestoreDialog (which imports this back) so the
# circular import resolves: by the time restore_dialog.py asks for
# RESTIC_REPO, this module already has it bound.
RESTIC_REPO = "/mnt/nas/wsbackup/fullsystem-restic"

from ui.restore_dialog import RestoreDialog


class BackupTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._jobs      = []
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="BACKUP STATUS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "backup",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # One row of Deploy/Run controls per script, so a second backup can
        # be added without reworking the deploy/run plumbing.
        ctrl_frame = tk.Frame(self, bg=t.bg)
        ctrl_frame.pack(fill="x", padx=16, pady=(0, 8))

        self._script_row(
            ctrl_frame, "Config Backup",
            local_name="backup.sh", remote_path="/opt/media/backup.sh",
            confirm_msg="Run backup.sh on the server now?\n"
                        "This may take several minutes.")

        self._script_row(
            ctrl_frame, "Full System Backup",
            local_name="full-system-backup.sh",
            remote_path="/opt/media/full-system-backup.sh",
            confirm_msg="Run full-system-backup.sh on the server now?\n"
                        "This backs up the entire root filesystem and can "
                        "take significantly longer than the config backup.")

        restic_row = tk.Frame(ctrl_frame, bg=t.bg)
        restic_row.pack(fill="x", pady=(4, 0))
        tk.Label(restic_row, text="Restic Repo", bg=t.bg,
                 fg=t.text_muted, font=t.font_small, width=18,
                 anchor="w").pack(side="left")
        self._restic_pw_var = tk.StringVar(
            value=self.controller.config_manager.restic_password)
        pw_entry = tk.Entry(restic_row, textvariable=self._restic_pw_var,
                            show="*", width=20, font=t.font_regular)
        t.style_entry(pw_entry)
        pw_entry.pack(side="left", padx=(0, 8))
        self._restic_init_btn = tk.Button(
            restic_row, text="Save & Init Repo",
            command=self._save_and_init_restic)
        t.style_button(self._restic_init_btn)
        self._restic_init_btn.pack(side="left")

        restore_row = tk.Frame(ctrl_frame, bg=t.bg)
        restore_row.pack(fill="x", pady=(4, 0))
        tk.Label(restore_row, text="Bare-Metal Restore", bg=t.bg,
                 fg=t.text_muted, font=t.font_small, width=18,
                 anchor="w").pack(side="left")
        self._restore_launch_btn = tk.Button(
            restore_row, text="⚠ Restore from Snapshot…",
            command=self._open_restore_dialog)
        t.style_button(self._restore_launch_btn, "danger")
        self._restore_launch_btn.pack(side="left")

        # Summary cards
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_ok   = self._stat_card(s_row, "OK",      "--", t.status_running)
        self._card_warn = self._stat_card(s_row, "Stale",   "--", t.yellow)
        self._card_fail = self._stat_card(s_row, "Failed",  "--", t.status_stopped)
        self._card_size = self._stat_card(s_row, "Total",   "--", t.cyan)

        # Jobs table
        tbl_frame = tk.Frame(self, bg=t.bg)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("BK.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("BK.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("BK.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("tool", "name", "status", "last_run", "duration", "size", "files", "dest")
        self._tree = ttk.Treeview(tbl_frame, columns=cols,
                                   show="headings", style="BK.Treeview")
        for col, w, lbl, anchor in [
            ("tool",     70,  "Tool",      "w"),
            ("name",    160,  "Job Name",  "w"),
            ("status",   80,  "Status",    "w"),
            ("last_run",140,  "Last Run",  "w"),
            ("duration", 80,  "Duration",  "e"),
            ("size",     80,  "Size",      "e"),
            ("files",    70,  "Files",     "e"),
            ("dest",    200,  "Dest/Repo", "w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anchor)
            self._tree.column(col, width=w, minwidth=40,
                              anchor=anchor, stretch=(col in ("name", "dest")))

        self._tree.tag_configure("ok",   foreground=t.status_running)
        self._tree.tag_configure("warn", foreground=t.yellow)
        self._tree.tag_configure("fail", foreground=t.status_stopped)
        self._tree.tag_configure("none", foreground=t.text_muted)

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Log detail panel
        det_frame = tk.Frame(self, bg=t.surface_dark,
                             highlightbackground=t.card_border, highlightthickness=1)
        det_frame.pack(fill="x", padx=16, pady=(4, 4))
        det_hdr = tk.Frame(det_frame, bg=t.surface_dark)
        det_hdr.pack(fill="x")
        tk.Label(det_hdr, text="Last log excerpt", bg=t.surface_dark,
                 fg=t.text_muted, font=t.font_small).pack(side="left", padx=8, pady=2)
        self._detail = tk.Text(det_frame, bg=t.surface_dark, fg=t.text_dim,
                               font=t.font_mono, height=5, state="disabled",
                               relief="flat", wrap="word", pady=4, padx=8)
        self._detail.pack(fill="x")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Status bar
        self._status = tk.Label(self, text="Press 'Refresh' to scan backup logs",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    def _script_row(self, parent, label, local_name, remote_path, confirm_msg):
        t = self.theme
        row = tk.Frame(parent, bg=t.bg)
        row.pack(fill="x", pady=(0, 4))
        tk.Label(row, text=label, bg=t.bg, fg=t.text_muted,
                 font=t.font_small, width=18, anchor="w").pack(side="left")

        deploy_btn = tk.Button(row, text="⬆ Deploy Script")
        t.style_button(deploy_btn)
        deploy_btn.pack(side="left", padx=(0, 8))
        deploy_btn.config(command=lambda: self._deploy_script(
            local_name, remote_path, deploy_btn))

        run_btn = tk.Button(row, text="▶ Run Now")
        t.style_button(run_btn)
        run_btn.pack(side="left")
        run_btn.config(command=lambda: self._run_backup(
            remote_path, confirm_msg, run_btn))

        return run_btn, deploy_btn

    def _open_restore_dialog(self):
        if not self.controller.ssh.connected:
            messagebox.showerror("Not Connected", "Connect to a server first.")
            return
        RestoreDialog(self, self.controller)

    # =========================================================
    # RESTIC REPO SETUP
    # =========================================================
    def _save_and_init_restic(self):
        if not self.controller.ssh.connected:
            messagebox.showerror("Not Connected", "Connect to a server first.")
            return
        password = self._restic_pw_var.get()
        if not password:
            messagebox.showerror("Missing Password",
                                 "Enter a repo password first.")
            return
        if not messagebox.askyesno(
                "Save & Init Repo",
                "This saves the password to this app's config and, on the "
                "server, installs restic and initializes the full-system "
                "backup repo if it doesn't already exist. Continue?"):
            return

        self.controller.config_manager.restic_password = password
        self._restic_init_btn.config(state="disabled")
        self._status.config(text="Setting up restic repo…",
                            bg=self.theme.blue, fg="#ffffff")

        def worker():
            # The password file and repo pointer live under this SSH login
            # user's own home (not /root), and the actual restic commands
            # run unprivileged: the wsbackup CIFS share is mounted
            # dir_mode=0777/file_mode=0777, so no sudo is needed to read or
            # write the repo itself. Only installing the restic package
            # needs root. full-system-backup.sh's cron job (which does run
            # as root) can still read this same file fine, since root
            # bypasses ordinary permission checks — see that script's
            # header comment for the full reasoning.
            cmd = (
                "if ! mountpoint -q /mnt/nas/wsbackup; then echo NAS_NOT_MOUNTED; else "
                "sudo apt-get install -y restic >/dev/null 2>&1; "
                "printf '%s' {pw} > ~/.restic-password && "
                "chmod 600 ~/.restic-password && "
                "mkdir -p ~/.config && "
                "printf 'RESTIC_REPOSITORY=%s\\n' {repo} > ~/.config/restic-repos && "
                "(env RESTIC_REPOSITORY={repo} RESTIC_PASSWORD_FILE=~/.restic-password "
                "restic snapshots >/dev/null 2>&1 || "
                "env RESTIC_REPOSITORY={repo} RESTIC_PASSWORD_FILE=~/.restic-password "
                "restic init) "
                "&& echo REPO_OK || echo REPO_FAILED; "
                "fi"
            ).format(pw=shlex.quote(password), repo=shlex.quote(RESTIC_REPO))
            out, err, code = self.controller.ssh.run(cmd)
            self.after(0, lambda: self._on_restic_init_done(out, err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_restic_init_done(self, out, err):
        self._restic_init_btn.config(state="normal")
        out = out or ""
        if "REPO_OK" in out:
            self._status.config(text="Restic repo ready.",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_running)
            messagebox.showinfo(
                "Repo Ready",
                "restic is installed and the backup repo is initialized.")
        elif "NAS_NOT_MOUNTED" in out:
            self._status.config(text="Restic setup failed: NAS not mounted",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            messagebox.showerror("Setup Failed",
                                 "/mnt/nas/wsbackup is not mounted. Mount "
                                 "the NAS share before initializing the repo.")
        else:
            msg = (err or out or "Unknown error").strip()[:400]
            self._status.config(
                text="Restic setup failed: {}".format(msg[:120]),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped)
            messagebox.showerror("Setup Failed", msg)

    def _stat_card(self, parent, label, value, color):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected", fg=self.theme.status_stopped)
            return
        self._status.config(text="Scanning backup logs…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        self._refresh_btn.config(state="disabled")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        ssh  = self.controller.ssh
        jobs = []
        try:
            # ── restic ──────────────────────────────────────────────────────
            rout, _, rcode = ssh.run(
                "command -v restic >/dev/null 2>&1 && echo FOUND || echo MISSING")
            if "FOUND" in (rout or ""):
                repos_out, _, _ = ssh.run(
                    "cat ~/.config/restic-repos 2>/dev/null || "
                    "grep -r 'RESTIC_REPOSITORY' /etc/cron* /etc/systemd/system "
                    "~/.local/share/systemd/user 2>/dev/null | "
                    "grep -o 'RESTIC_REPOSITORY=[^ ]*' | head -6")
                repos = re.findall(r'RESTIC_REPOSITORY=(\S+)', repos_out or "")
                for repo in repos or ["(default)"]:
                    env = "RESTIC_REPOSITORY={} RESTIC_PASSWORD_FILE=~/.restic-password".format(
                        shlex.quote(repo)) if repo != "(default)" else ""
                    snap_out, _, snap_code = ssh.run(
                        "{} restic snapshots --last --json 2>/dev/null".format(env))
                    if snap_code == 0 and snap_out.strip():
                        try:
                            snaps = json.loads(snap_out)
                            last = snaps[-1] if snaps else {}
                            ts   = last.get("time", "")
                            if ts:
                                dt   = datetime.datetime.fromisoformat(ts[:19])
                                age  = (datetime.datetime.utcnow() - dt).total_seconds()
                                days = age / 86400
                                st   = "ok" if days < 2 else ("warn" if days < 7 else "fail")
                                jobs.append({
                                    "tool": "restic", "name": repo.split("/")[-1] or "repo",
                                    "status": st, "last_run": dt.strftime("%Y-%m-%d %H:%M"),
                                    "duration": "--", "size": "--",
                                    "files": str(last.get("summary", {}).get("total_files_processed", "--")),
                                    "dest": repo, "log": str(last),
                                })
                        except Exception:
                            pass

            # ── rsync (via log files) ────────────────────────────────────────
            # Only look in directories likely to contain real backup logs.
            # Exclude /var/log/apt, /var/log/installer, /var/log/unattended-upgrades
            # which contain system package logs that mention rsync incidentally.
            log_dirs = ["/var/log/rsync", "/home", "/root", "/opt", "/srv"]
            rsync_logs, _, _ = ssh.run(
                "find {} -maxdepth 4 -name '*.log' 2>/dev/null "
                "| xargs grep -l '^rsync:' 2>/dev/null | head -6".format(
                    " ".join(log_dirs)))
            for log_path in (rsync_logs or "").splitlines():
                log_path = log_path.strip()
                if not log_path:
                    continue
                # Skip system/package-manager log paths
                skip_paths = ("/var/log/apt", "/var/log/installer",
                              "/var/log/unattended", "/var/log/dpkg")
                if any(log_path.startswith(s) for s in skip_paths):
                    continue
                tail, _, _ = ssh.run("tail -40 {}".format(shlex.quote(log_path)))
                job = self._parse_rsync_log(log_path, tail or "")
                if job:
                    jobs.append(job)

            # ── systemd backup units ─────────────────────────────────────────
            svc_out, _, _ = ssh.run(
                "systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | "
                "grep -iE 'backup|rsync|restic|borg|rclone|duplicati' | awk '{print $1}'")
            for svc in (svc_out or "").splitlines():
                svc = svc.strip()
                if not svc:
                    continue
                status_out, _, _ = ssh.run(
                    "systemctl show {} --property=ActiveState,ExecMainStatus,"
                    "InactiveEnterTimestamp 2>/dev/null".format(shlex.quote(svc)))
                props = dict(re.findall(r'(\w+)=(.*)', status_out or ""))
                active = props.get("ActiveState", "unknown")
                code   = props.get("ExecMainStatus", "")
                ts     = props.get("InactiveEnterTimestamp", "").strip()
                st     = "ok" if (active in ("active", "inactive") and code == "0") else (
                         "fail" if code not in ("0", "") else "none")
                jobs.append({
                    "tool": "systemd", "name": svc.replace(".service", ""),
                    "status": st, "last_run": ts[:16] if ts else "--",
                    "duration": "--", "size": "--", "files": "--",
                    "dest": svc, "log": status_out or "",
                })

            # ── Cron backup scripts (structured log format) ──────────────────
            # Finds any *backup*.log in /var/log that uses our timestamped format:
            #   [YYYY-MM-DD HH:MM:SS] === Backup started ===
            #   [YYYY-MM-DD HH:MM:SS] === Backup completed OK — SIZE written to PATH ===
            cron_logs, _, _ = ssh.run(
                "find /var/log -maxdepth 1 -name '*backup*.log' 2>/dev/null")
            for log_path in (cron_logs or "").splitlines():
                log_path = log_path.strip()
                if not log_path:
                    continue
                tail, _, _ = ssh.run(
                    "grep -a '=== Backup' {} 2>/dev/null | tail -20".format(shlex.quote(log_path)))
                job = self._parse_cron_backup_log(log_path, tail or "")
                if job:
                    jobs.append(job)

            # ── Duplicati REST API ───────────────────────────────────────────
            dup_out, _, dup_code = ssh.run(
                "curl -sf http://localhost:8200/api/v1/backups 2>/dev/null")
            if dup_code == 0 and dup_out.strip():
                try:
                    dup_data = json.loads(dup_out)
                    for bk in (dup_data if isinstance(dup_data, list) else []):
                        backup = bk.get("Backup", {})
                        prog   = bk.get("Progress", {})
                        name   = backup.get("Name", "--")
                        dest   = backup.get("TargetURL", "--")
                        last   = prog.get("LastEventID", "--")
                        jobs.append({
                            "tool": "duplicati", "name": name,
                            "status": "ok", "last_run": "--",
                            "duration": "--", "size": "--", "files": "--",
                            "dest": dest, "log": json.dumps(prog, indent=2),
                        })
                except Exception:
                    pass

            self.after(0, lambda: self._populate(jobs))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False
            self.after(0, lambda: self._refresh_btn.config(state="normal"))

    def _parse_rsync_log(self, path, text):
        name = re.sub(r'\.log$', '', path.split("/")[-1])
        # Look for rsync summary line
        m = re.search(r'Number of files: ([\d,]+)', text)
        files = m.group(1) if m else "--"
        m = re.search(r'Total transferred file size: ([\d,]+ bytes)', text)
        size = m.group(1) if m else "--"
        # Success marker
        ok = bool(re.search(r'sent \d+ bytes.*received \d+ bytes', text))
        # Timestamp from last line
        lines = [l for l in text.splitlines() if l.strip()]
        last  = lines[-1] if lines else ""
        ts_m  = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}', last)
        ts    = ts_m.group(0) if ts_m else "--"
        return {
            "tool": "rsync", "name": name,
            "status": "ok" if ok else "fail",
            "last_run": ts, "duration": "--",
            "size": size, "files": files,
            "dest": path, "log": text[-800:],
        }

    def _parse_cron_backup_log(self, path, text):
        """Parse logs written by our timestamped backup.sh format."""
        if "=== Backup" not in text:
            return None
        name = re.sub(r'[-_]backup.*\.log$', '', path.split("/")[-1]) or path.split("/")[-1]
        # Find last start timestamp
        starts = re.findall(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] === Backup started', text)
        ts = starts[-1] if starts else "--"
        # Determine status and size from last completion line
        ok_m   = re.search(r'=== Backup completed OK.*?(\d+[\.\d]*[KMGTP]?) written to (\S+)', text)
        fail_m = re.search(r'=== Backup completed with (\d+) error', text)
        if ok_m:
            st   = "ok"
            size = ok_m.group(1)
            dest = ok_m.group(2)
        elif fail_m:
            st   = "fail"
            size = "--"
            dest = path
        else:
            # Started but no completion line yet (currently running)
            st   = "warn"
            size = "--"
            dest = path
        # Compute staleness from last start time
        if ts != "--":
            try:
                dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                age = (datetime.datetime.now() - dt).total_seconds()
                if st == "ok" and age > 8 * 86400:
                    st = "warn"
            except Exception:
                pass
        return {
            "tool": "cron", "name": name,
            "status": st, "last_run": ts,
            "duration": "--", "size": size,
            "files": "--", "dest": dest,
            "log": text,
        }

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, jobs):
        self._jobs = jobs
        t = self.theme

        ok   = sum(1 for j in jobs if j["status"] == "ok")
        warn = sum(1 for j in jobs if j["status"] == "warn")
        fail = sum(1 for j in jobs if j["status"] == "fail")

        self._card_ok.config(text=str(ok),
                              fg=t.status_running if ok else t.text_muted)
        self._card_warn.config(text=str(warn),
                                fg=t.yellow if warn else t.text_muted)
        self._card_fail.config(text=str(fail),
                                fg=t.status_stopped if fail else t.text_muted)
        self._card_size.config(text="{} jobs".format(len(jobs)))

        self._tree.delete(*self._tree.get_children())
        for j in sorted(jobs, key=lambda x: (
                {"fail": 0, "warn": 1, "ok": 2, "none": 3}.get(x["status"], 4),
                x.get("name", ""))):
            tag = j["status"]
            self._tree.insert("", "end", values=(
                j["tool"], j["name"], j["status"],
                j["last_run"], j["duration"],
                j["size"], j["files"], j["dest"],
            ), tags=(tag,))

        if not jobs:
            self._status.config(
                text="No backup tools found (restic/rsync/duplicati/systemd backup units)",
                bg=t.surface_dark, fg=t.text_muted)
        elif fail:
            self._status.config(
                text="{} backup job{} FAILED".format(fail, "s" if fail != 1 else ""),
                bg=t.surface_dark, fg=t.status_stopped)
        elif warn:
            self._status.config(
                text="{} job{} may be stale".format(warn, "s" if warn != 1 else ""),
                bg=t.surface_dark, fg=t.yellow)
        else:
            self._status.config(
                text="{} backup job{} OK".format(ok, "s" if ok != 1 else ""),
                bg=t.surface_dark, fg=t.status_running)

    # =========================================================
    # DEPLOY SCRIPT
    # =========================================================
    def _deploy_script(self, local_name, remote_path, btn):
        if not self.controller.ssh.connected:
            messagebox.showerror("Not Connected", "Connect to a server first.")
            return
        local_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            local_name
        )
        if not os.path.exists(local_path):
            messagebox.showerror("File Not Found",
                                 "{} not found at:\n{}".format(local_name, local_path))
            return

        def worker():
            try:
                out, err, code = self.controller.ssh.put_file(
                    local_path, remote_path)
                if code == 0:
                    self.after(0, lambda: self._status.config(
                        text="Script deployed to {}".format(remote_path),
                        bg=self.theme.surface_dark, fg=self.theme.status_running))
                    self.after(0, lambda: messagebox.showinfo(
                        "Deployed", "{} uploaded to {}".format(local_name, remote_path)))
                else:
                    msg = (err or "Unknown error").strip()
                    self.after(0, lambda: messagebox.showerror("Deploy Failed", msg))
            finally:
                self.after(0, lambda: btn.config(state="normal"))

        btn.config(state="disabled")
        self._status.config(text="Deploying script…", bg=self.theme.blue, fg="#ffffff")
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # RUN BACKUP NOW
    # =========================================================
    def _run_backup(self, remote_path, confirm_msg, btn):
        if not self.controller.ssh.connected:
            messagebox.showerror("Not Connected", "Connect to a server first.")
            return
        if not messagebox.askyesno("Run Backup", confirm_msg):
            return

        def worker():
            try:
                self.after(0, lambda: self._status.config(
                    text="Backup running…", bg=self.theme.blue, fg="#ffffff"))
                _, err, code = self.controller.ssh.run("sudo {}".format(remote_path))
                if code == 0:
                    self.after(0, lambda: self._status.config(
                        text="Backup completed successfully",
                        bg=self.theme.surface_dark, fg=self.theme.status_running))
                    self.after(500, self.refresh)
                else:
                    msg = (err or "").strip()[:120]
                    self.after(0, lambda: self._status.config(
                        text="Backup failed (exit {}): {}".format(code, msg),
                        bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            finally:
                self.after(0, lambda: btn.config(state="normal"))

        btn.config(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # DETAIL PANEL
    # =========================================================
    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = self._tree.index(iid)
        sorted_jobs = sorted(self._jobs, key=lambda x: (
            {"fail": 0, "warn": 1, "ok": 2, "none": 3}.get(x["status"], 4),
            x.get("name", "")))
        if idx < len(sorted_jobs):
            job = sorted_jobs[idx]
            log_text = job.get("log", "(no log excerpt)")
            self._detail.config(state="normal")
            self._detail.delete("1.0", "end")
            self._detail.insert("end", log_text)
            self._detail.config(state="disabled")
