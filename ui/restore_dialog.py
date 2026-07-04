# ui/restore_dialog.py
"""
Restore wizard — runs the bare-metal restore procedure documented in
RESTORE.md against a freshly-installed server, over the app's existing SSH
connection, instead of the user typing the commands by hand.

Opens from the Backup tab's "Restore from Snapshot..." button. Gated by a
safety check that refuses to proceed if the connected server already looks
configured (i.e. isn't actually a fresh install) — this runs
`restic restore ... --target /` against the target, which would badly
damage a live system if pointed at the wrong box.
"""
import json
import shlex
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from ui.backup_tab import RESTIC_REPO

INFO_DIR = "/var/lib/media-fullbackup-info"


class RestoreDialog(tk.Toplevel):

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.theme      = controller.theme
        self.ssh        = controller.ssh

        self._safety_ok  = False
        self._mounted    = False

        t = self.theme
        self.configure(bg=t.bg)
        self.title("Restore from Snapshot")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._center()

        if not self.ssh.connected:
            messagebox.showerror("Not Connected",
                                 "Connect to the target server first.",
                                 parent=self)
            self.destroy()
            return

        self.after(100, self._run_safety_check)
        self.wait_window(self)

    # ------------------------------------------------------------------
    def _build(self):
        t = self.theme
        outer = tk.Frame(self, bg=t.bg, padx=20, pady=16)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="⚠  Restore from Snapshot",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(anchor="w")
        tk.Label(outer,
                 text="Only ever run this against a freshly-installed server "
                      "you intend to fully overwrite. It cannot be undone.",
                 bg=t.bg, fg=t.status_stopped, font=t.font_small,
                 wraplength=440, justify="left").pack(anchor="w", pady=(2, 12))

        # ── Safety check ───────────────────────────────────────────
        safety = tk.Frame(outer, bg=t.surface, padx=14, pady=10)
        safety.pack(fill="x", pady=(0, 10))
        tk.Label(safety, text="1. Safety check", bg=t.surface, fg=t.text,
                 font=t.font_regular).pack(anchor="w")
        self._safety_lbl = tk.Label(safety, text="Checking…",
                                    bg=t.surface, fg=t.blue,
                                    font=t.font_small, wraplength=420,
                                    justify="left")
        self._safety_lbl.pack(anchor="w", pady=(4, 0))

        # ── NAS mount ──────────────────────────────────────────────
        self._nas_frame = tk.Frame(outer, bg=t.surface, padx=14, pady=10)
        self._nas_frame.pack(fill="x", pady=(0, 10))
        tk.Label(self._nas_frame, text="2. Mount the NAS", bg=t.surface,
                 fg=t.text, font=t.font_regular).pack(anchor="w")

        row = tk.Frame(self._nas_frame, bg=t.surface)
        row.pack(fill="x", pady=(6, 0))
        self._nas_host_var = tk.StringVar(value="192.168.4.50")
        self._nas_user_var = tk.StringVar()
        self._nas_pass_var = tk.StringVar()
        for lbl, var, secret in (
            ("Host", self._nas_host_var, False),
            ("Username", self._nas_user_var, False),
            ("Password", self._nas_pass_var, True),
        ):
            tk.Label(row, text=lbl, bg=t.surface, fg=t.text_secondary,
                     font=t.font_small).pack(side="left", padx=(0, 4))
            e = tk.Entry(row, textvariable=var, width=14,
                        show="*" if secret else "", font=t.font_regular)
            t.style_entry(e)
            e.pack(side="left", padx=(0, 10))

        self._mount_btn = tk.Button(self._nas_frame, text="Mount NAS",
                                    command=self._mount_nas, state="disabled")
        t.style_button(self._mount_btn)
        self._mount_btn.pack(anchor="w", pady=(8, 0))
        self._mount_status = tk.Label(self._nas_frame, text="",
                                      bg=t.surface, fg=t.text_muted,
                                      font=t.font_small)
        self._mount_status.pack(anchor="w", pady=(4, 0))

        # ── Restic password ──────────────────────────────────────────
        self._pw_frame = tk.Frame(outer, bg=t.surface, padx=14, pady=10)
        self._pw_frame.pack(fill="x", pady=(0, 10))
        tk.Label(self._pw_frame, text="3. Restic repo password", bg=t.surface,
                 fg=t.text, font=t.font_regular).pack(anchor="w")
        pw_row = tk.Frame(self._pw_frame, bg=t.surface)
        pw_row.pack(fill="x", pady=(6, 0))
        self._restic_pw_var = tk.StringVar(
            value=self.controller.config_manager.restic_password)
        self._pw_entry = tk.Entry(pw_row, textvariable=self._restic_pw_var,
                                  show="*", width=20, font=t.font_regular,
                                  state="disabled")
        t.style_entry(self._pw_entry)
        self._pw_entry.pack(side="left", padx=(0, 8))
        self._list_snap_btn = tk.Button(pw_row, text="List Snapshots",
                                        command=self._list_snapshots,
                                        state="disabled")
        t.style_button(self._list_snap_btn)
        self._list_snap_btn.pack(side="left")

        # ── Snapshot picker ────────────────────────────────────────
        self._snap_frame = tk.Frame(outer, bg=t.surface, padx=14, pady=10)
        self._snap_frame.pack(fill="x", pady=(0, 10))
        tk.Label(self._snap_frame, text="4. Pick a snapshot", bg=t.surface,
                 fg=t.text, font=t.font_regular).pack(anchor="w")
        self._snap_var = tk.StringVar()
        self._snap_combo = ttk.Combobox(self._snap_frame,
                                        textvariable=self._snap_var,
                                        state="disabled", width=32)
        self._snap_combo.pack(anchor="w", pady=(6, 0))
        self._snap_combo.bind("<<ComboboxSelected>>", self._on_snapshot_selected)
        self._snap_info_lbl = tk.Label(self._snap_frame, text="",
                                       bg=t.surface, fg=t.text_muted,
                                       font=t.font_small)
        self._snap_info_lbl.pack(anchor="w", pady=(4, 0))

        # ── Confirm ────────────────────────────────────────────────
        self._confirm_frame = tk.Frame(outer, bg=t.surface, padx=14, pady=10)
        self._confirm_frame.pack(fill="x", pady=(0, 10))
        self._confirm_host = (self.controller.config_manager.last_host or "").strip()
        tk.Label(self._confirm_frame,
                 text="5. Type the server address ({}) to confirm:".format(
                     self._confirm_host),
                 bg=t.surface, fg=t.text, font=t.font_regular,
                 wraplength=420, justify="left").pack(anchor="w")
        self._confirm_var = tk.StringVar()
        self._confirm_var.trace_add("write", self._check_confirm)
        e = tk.Entry(self._confirm_frame, textvariable=self._confirm_var,
                     font=t.font_regular, width=30)
        t.style_entry(e)
        e.pack(anchor="w", pady=(6, 0))

        self._restore_btn = tk.Button(outer, text="Restore Now",
                                      command=self._run_restore, state="disabled")
        t.style_button(self._restore_btn, "danger")
        self._restore_btn.pack(anchor="w", pady=(4, 10))

        # ── Log ────────────────────────────────────────────────────
        self._log = tk.Text(outer, height=8, width=64,
                            bg=t.surface_dark, fg=t.text_secondary,
                            font=t.font_mono, state="disabled",
                            relief="flat", padx=8, pady=6)
        self._log.pack(fill="both", expand=True)

        tk.Button(outer, text="Close", command=self.destroy).pack(
            anchor="e", pady=(10, 0))

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry("+{}+{}".format(pw - w // 2, ph - h // 2))

    def _log_line(self, text):
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    # ------------------------------------------------------------------
    # STEP 1 — SAFETY CHECK
    # ------------------------------------------------------------------
    def _run_safety_check(self):
        def worker():
            marker_out, _, _ = self.ssh.run(
                "test -e /opt/media/backup.sh -o -e /opt/media/full-system-backup.sh "
                "&& echo CONFIGURED || echo FRESH")
            configured = "CONFIGURED" in (marker_out or "")
            pkg_out, _, _ = self.ssh.run("dpkg --get-selections 2>/dev/null | wc -l")
            pkg_count = (pkg_out or "0").strip()
            self.after(0, lambda: self._on_safety_result(configured, pkg_count))

        threading.Thread(target=worker, daemon=True).start()

    def _on_safety_result(self, configured, pkg_count):
        t = self.theme
        if configured:
            self._safety_lbl.config(
                text="REFUSED: this server already has backup.sh or "
                     "full-system-backup.sh deployed — it does not look like "
                     "a fresh install. Restore blocked for safety.",
                fg=t.status_stopped)
            self._log_line("Safety check FAILED — target already configured.")
            return

        self._safety_ok = True
        self._safety_lbl.config(
            text="OK — no existing backup scripts found on this server "
                 "({} packages installed).".format(pkg_count),
            fg=t.status_running)
        self._mount_btn.config(state="normal")
        self._log_line("Safety check passed ({} packages installed).".format(pkg_count))

    # ------------------------------------------------------------------
    # STEP 2 — MOUNT NAS
    # ------------------------------------------------------------------
    def _mount_nas(self):
        if not self._safety_ok:
            return
        host = self._nas_host_var.get().strip()
        user = self._nas_user_var.get().strip()
        password = self._nas_pass_var.get()
        if not host or not user:
            messagebox.showerror("Missing Info", "Host and username are required.",
                                 parent=self)
            return

        self._mount_btn.config(state="disabled")
        self._mount_status.config(text="Mounting…", fg=self.theme.blue)

        def worker():
            cmd = (
                "if mountpoint -q /mnt/nas/wsbackup; then echo ALREADY_MOUNTED; else "
                "sudo apt-get install -y cifs-utils restic >/dev/null 2>&1; "
                "sudo mkdir -p /mnt/nas/wsbackup && "
                "printf 'username=%s\\npassword=%s\\n' {user} {password} "
                "| sudo tee /etc/nas-credentials-temp >/dev/null && "
                "sudo chmod 600 /etc/nas-credentials-temp && "
                "sudo mount -t cifs //{host}/wsbackup /mnt/nas/wsbackup "
                "-o credentials=/etc/nas-credentials-temp,vers=2.0,uid=0,gid=0,"
                "file_mode=0777,dir_mode=0777 "
                "&& echo MOUNT_OK || echo MOUNT_FAILED; "
                "sudo rm -f /etc/nas-credentials-temp; fi"
            ).format(user=shlex.quote(user), password=shlex.quote(password),
                     host=shlex.quote(host))
            out, err, code = self.ssh.run(cmd)
            ok = "MOUNT_OK" in (out or "") or "ALREADY_MOUNTED" in (out or "")
            self.after(0, lambda: self._on_mount_result(ok, out, err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_mount_result(self, ok, out, err):
        t = self.theme
        self._mount_btn.config(state="normal")
        if not ok:
            self._mount_status.config(
                text="Mount failed: {}".format((err or out or "unknown error").strip()[:150]),
                fg=t.status_stopped)
            self._log_line("NAS mount FAILED.")
            return
        self._mounted = True
        self._mount_status.config(text="Mounted.", fg=t.status_running)
        self._log_line("NAS mounted at /mnt/nas/wsbackup.")
        self._pw_entry.config(state="normal")
        self._list_snap_btn.config(state="normal")

    def _restic_env(self):
        """RESTIC_PASSWORD is passed inline per-command (never written to
        disk on the target) since it's typed fresh for this restore rather
        than coming from a file that may not exist yet on a bare box."""
        return "RESTIC_REPOSITORY={} RESTIC_PASSWORD={}".format(
            shlex.quote(RESTIC_REPO), shlex.quote(self._restic_pw_var.get()))

    # ------------------------------------------------------------------
    # STEPS 3-4 — RESTIC PASSWORD & SNAPSHOT PICKER
    # ------------------------------------------------------------------
    def _list_snapshots(self):
        if not self._restic_pw_var.get():
            messagebox.showerror("Missing Password",
                                 "Enter the restic repo password first.",
                                 parent=self)
            return
        self._list_snap_btn.config(state="disabled")
        self._log_line("Listing snapshots…")

        def worker():
            out, err, code = self.ssh.run(
                "sudo env {env} restic snapshots --tag fullsystem --json 2>&1".format(
                    env=self._restic_env()))
            self.after(0, lambda: self._on_snapshots_listed(out, err, code))

        threading.Thread(target=worker, daemon=True).start()

    def _on_snapshots_listed(self, out, err, code):
        self._list_snap_btn.config(state="normal")
        entries = []
        try:
            if code == 0:
                for snap in json.loads(out or "[]"):
                    entries.append("{}  {}".format(
                        snap.get("short_id", "?"), snap.get("time", "")[:16]))
        except (ValueError, TypeError):
            entries = []

        self._snap_combo.config(values=entries,
                                state="readonly" if entries else "disabled")
        if entries:
            self._snap_var.set(entries[0])
            self._on_snapshot_selected()
            self._log_line("Found {} snapshot(s).".format(len(entries)))
        else:
            self._log_line(
                "No snapshots found (or wrong password): {}".format(
                    (err or out or "").strip()[:200]))

    def _on_snapshot_selected(self, _event=None):
        snap = self._snap_var.get()
        if not snap:
            return
        snap_id = snap.split()[0]

        def worker():
            out, _, _ = self.ssh.run(
                "sudo env {env} restic stats {sid} --json 2>/dev/null".format(
                    env=self._restic_env(), sid=shlex.quote(snap_id)))
            try:
                stats = json.loads(out or "{}")
                size_gb = stats.get("total_size", 0) / 1e9
                text = "{:.2f} GB".format(size_gb)
            except (ValueError, TypeError):
                text = "size unavailable"
            self.after(0, lambda: self._snap_info_lbl.config(text=text))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # STEP 5 — CONFIRM
    # ------------------------------------------------------------------
    def _check_confirm(self, *_args):
        typed = self._confirm_var.get().strip()
        ready = (self._safety_ok and self._mounted and self._snap_var.get()
                 and self._confirm_host and typed == self._confirm_host)
        self._restore_btn.config(state="normal" if ready else "disabled")

    # ------------------------------------------------------------------
    # STEP 6 — RUN
    # ------------------------------------------------------------------
    def _run_restore(self):
        snap = self._snap_var.get()
        if not snap:
            return
        snap_id = snap.split()[0]
        if not messagebox.askyesno(
                "Confirm Restore",
                "This will restore restic snapshot {} onto / on {} "
                "(excluding /boot — the fresh install's own bootloader is "
                "left alone).\n\nThis cannot be undone. Continue?".format(
                    snap_id, self._confirm_host),
                parent=self):
            return

        self._restore_btn.config(state="disabled")
        env = self._restic_env()

        def worker():
            self.after(0, lambda: self._log_line("--- Restore started ---"))

            self.after(0, lambda: self._log_line(
                "Restoring system manifest…"))
            out, err, code = self.ssh.run(
                "sudo env {env} restic restore {sid} --target / "
                "--include {info} 2>&1".format(
                    env=env, sid=shlex.quote(snap_id),
                    info=shlex.quote(INFO_DIR)))
            self.after(0, lambda: self._log_line(
                "Manifest restore: exit {}".format(code)))

            self.after(0, lambda: self._log_line("Updating package index…"))
            out, err, code = self.ssh.run("sudo apt-get update 2>&1")
            self.after(0, lambda: self._log_line(
                "apt-get update: exit {}".format(code)))

            self.after(0, lambda: self._log_line("Reinstalling packages from manifest…"))
            out, err, code = self.ssh.run(
                "sudo xargs -a {info}/apt-manual-packages.txt "
                "apt-get install -y 2>&1".format(info=INFO_DIR))
            self.after(0, lambda: self._log_line(
                "Package reinstall: exit {}".format(code)))

            self.after(0, lambda: self._log_line(
                "Restoring everything else (excluding /boot) — this is the main step…"))
            out, err, code = self.ssh.run(
                "sudo env {env} restic restore {sid} --target / "
                "--exclude /boot 2>&1".format(env=env, sid=shlex.quote(snap_id)))
            if code == 0:
                self.after(0, lambda: self._log_line(
                    "Restore OK (exit {}).".format(code)))
            else:
                self.after(0, lambda: self._log_line(
                    "RESTORE FAILED (exit {}): {}".format(
                        code, (err or out or "")[-500:])))

            self.after(0, self._on_restore_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_restore_done(self):
        self._log_line("--- Restore finished ---")
        self._log_line(
            "Next: reboot, confirm services come up, then use the Backup "
            "tab's 'Save & Init Repo' and redeploy backup.sh / "
            "full-system-backup.sh to resume scheduled backups. /boot was "
            "NOT restored automatically — see RESTORE.md if you need "
            "anything from it.")
        messagebox.showinfo(
            "Restore Complete",
            "Restore finished. Reboot the server, then check services and "
            "redeploy the backup scripts from the Backup tab.",
            parent=self)
