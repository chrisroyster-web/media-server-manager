# ui/backup_tab.py
"""
Backup status tab.
Parses restic / rsync / duplicati logs to show last backup time,
duration, size, and pass/fail status.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
import shlex

from ui.refresh_control import RefreshControl
from core.backup_status import check_backup_jobs
from core.hyperbackup_status import check_hyperbackup_status
from core.arr_backup_status import check_arr_backup_jobs

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

        # NAS Hyper Backup monitor -- separate host/credentials from the
        # media server, so its own SSH connection (opened in
        # core/hyperbackup_status.py) needs its own settings rather than
        # reusing self.controller.ssh.
        cfg = self.controller.config_manager
        nas_row = tk.Frame(ctrl_frame, bg=t.bg)
        nas_row.pack(fill="x", pady=(4, 0))
        tk.Label(nas_row, text="NAS Backup Monitor", bg=t.bg,
                 fg=t.text_muted, font=t.font_small, width=18,
                 anchor="w").pack(side="left")
        self._nas_enabled_var = tk.BooleanVar(value=cfg.nas_backup_enabled)
        tk.Checkbutton(nas_row, text="Enabled", variable=self._nas_enabled_var,
                       bg=t.bg, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.bg, font=t.font_small,
                       bd=0, highlightthickness=0).pack(side="left", padx=(0, 8))
        tk.Label(nas_row, text="Host:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._nas_host_var = tk.StringVar(value=cfg.nas_backup_host)
        host_entry = tk.Entry(nas_row, textvariable=self._nas_host_var,
                              width=15, font=t.font_regular)
        t.style_entry(host_entry)
        host_entry.pack(side="left", padx=(4, 8))
        tk.Label(nas_row, text="User:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._nas_user_var = tk.StringVar(value=cfg.nas_backup_username)
        user_entry = tk.Entry(nas_row, textvariable=self._nas_user_var,
                              width=12, font=t.font_regular)
        t.style_entry(user_entry)
        user_entry.pack(side="left", padx=(4, 8))
        tk.Label(nas_row, text="Password:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._nas_pw_var = tk.StringVar(value=cfg.nas_backup_password)
        nas_pw_entry = tk.Entry(nas_row, textvariable=self._nas_pw_var,
                                show="*", width=14, font=t.font_regular)
        t.style_entry(nas_pw_entry)
        nas_pw_entry.pack(side="left", padx=(4, 8))
        self._nas_save_btn = tk.Button(
            nas_row, text="Save", command=self._save_nas_backup_settings)
        t.style_button(self._nas_save_btn)
        self._nas_save_btn.pack(side="left")

        nas_row2 = tk.Frame(ctrl_frame, bg=t.bg)
        nas_row2.pack(fill="x", pady=(2, 0))
        tk.Label(nas_row2, text="", bg=t.bg, width=18,
                 anchor="w").pack(side="left")
        tk.Label(nas_row2, text="SSH Key Path:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._nas_key_var = tk.StringVar(value=cfg.nas_backup_key_path)
        nas_key_entry = tk.Entry(nas_row2, textvariable=self._nas_key_var,
                                 width=30, font=t.font_regular)
        t.style_entry(nas_key_entry)
        nas_key_entry.pack(side="left", padx=(4, 8))
        tk.Label(nas_row2,
                 text="Leave password blank to use this key "
                      "(blank key path falls back to ~/.ssh/id_rsa).",
                 bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8)).pack(side="left")

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
            ("tool",     95,  "Tool",      "w"),
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
        self._tree.tag_configure("fail", foreground=t.status_stopped_text)
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
                                fg=self.theme.status_stopped_text)
            messagebox.showerror("Setup Failed",
                                 "/mnt/nas/wsbackup is not mounted. Mount "
                                 "the NAS share before initializing the repo.")
        else:
            msg = (err or out or "Unknown error").strip()[:400]
            self._status.config(
                text="Restic setup failed: {}".format(msg[:120]),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)
            messagebox.showerror("Setup Failed", msg)

    # =========================================================
    # NAS BACKUP MONITOR SETTINGS
    # =========================================================
    def _save_nas_backup_settings(self):
        cfg = self.controller.config_manager
        cfg.nas_backup_enabled  = self._nas_enabled_var.get()
        cfg.nas_backup_host     = self._nas_host_var.get().strip()
        cfg.nas_backup_username = self._nas_user_var.get().strip()
        cfg.nas_backup_password = self._nas_pw_var.get()
        cfg.nas_backup_key_path = self._nas_key_var.get().strip()
        self._status.config(text="NAS backup monitor settings saved.",
                            bg=self.theme.surface_dark, fg=self.theme.status_running)
        self.refresh()

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
            self._status.config(text="Not connected", fg=self.theme.status_stopped_text)
            return
        self._status.config(text="Scanning backup logs…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        self._refresh_btn.config(state="disabled")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            jobs = check_backup_jobs(ssh)
            # Separate host/credentials from the media server -- its own
            # dedicated SSH connection, opened and closed within this call.
            jobs += check_hyperbackup_status(self.controller.config_manager)
            # Sonarr/Radarr's own scheduled config backups, via their REST
            # API rather than SSH -- reuses the same host/apikey ArrTab uses.
            jobs += check_arr_backup_jobs(self.controller.config_manager)
            self.after(0, lambda: self._populate(jobs))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False
            self.after(0, lambda: self._refresh_btn.config(state="normal"))

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
                                fg=t.status_stopped_text if fail else t.text_muted)
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
                bg=t.surface_dark, fg=t.status_stopped_text)
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
                self.controller.audit_log(
                    "backup.run", remote_path,
                    detail=(err or "").strip()[:200],
                    result="ok" if code == 0 else "fail")
                if code == 0:
                    self.after(0, lambda: self._status.config(
                        text="Backup completed successfully",
                        bg=self.theme.surface_dark, fg=self.theme.status_running))
                    self.after(500, self.refresh)
                else:
                    msg = (err or "").strip()[:120]
                    self.after(0, lambda: self._status.config(
                        text="Backup failed (exit {}): {}".format(code, msg),
                        bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
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
