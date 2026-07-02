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
        self._dist_btn.configure(fg=t.status_stopped)
        self._dist_btn.pack(side="right", padx=(0, 6))

        self._upgrade_btn = tk.Button(apt_hdr, text="⬆  Run apt upgrade",
                                       command=self._run_upgrade)
        t.style_button(self._upgrade_btn)
        self._upgrade_btn.configure(fg=t.yellow)
        self._upgrade_btn.pack(side="right")

        apt_frame = tk.Frame(self, bg=t.bg)
        apt_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._apt_tree = self._make_tree(apt_frame,
            cols=("package", "current", "available", "arch"),
            headings=[
                ("package",   "Package",          260, "w"),
                ("current",   "Installed",         160, "w"),
                ("available", "Available",         160, "w"),
                ("arch",      "Arch",               80, "center"),
            ])

        # --- Docker section ---
        tk.Label(self, text="Docker Images",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(
            anchor="w", padx=16, pady=(4, 2))

        docker_frame = tk.Frame(self, bg=t.bg)
        docker_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._docker_tree = self._make_tree(docker_frame,
            cols=("container", "image", "status"),
            headings=[
                ("container", "Container",  200, "w"),
                ("image",     "Image",      300, "w"),
                ("status",    "Status",     120, "center"),
            ])

        # Output console for upgrade output
        tk.Label(self, text="Output", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=16, pady=(4, 0))
        self._console = tk.Text(self, height=6, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="x", padx=16, pady=(0, 4))
        self._console.tag_config("ok",   foreground=t.status_running)
        self._console.tag_config("warn", foreground=t.yellow)
        self._console.tag_config("err",  foreground=t.status_stopped)

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

            # 2. Docker image check — pull --dry-run not available everywhere,
            # so we compare local image digest to registry via docker pull output
            docker_cfg = self.controller.config_manager.get_docker()
            docker_results = []
            for name, data in docker_cfg.items():
                container = data.get("container", "")
                if not container:
                    continue
                # Get current image name
                img_out, _, _ = ssh.run(
                    "docker inspect --format '{{.Config.Image}}' " + container + " 2>/dev/null")
                image = img_out.strip() or container
                # Pull without extracting — just check if "Status: Image is up to date" or "newer"
                pull_out, _, pull_code = ssh.run_sudo(
                    "docker pull {}".format(image))
                pull_line = pull_out.strip()
                if "up to date" in pull_line.lower():
                    status = "Up to date"
                    tag    = "current"
                elif "newer" in pull_line.lower() or "pull complete" in pull_line.lower():
                    status = "Updated ✓"
                    tag    = "update"
                elif pull_code != 0:
                    status = "Check failed"
                    tag    = "unknown"
                else:
                    status = pull_line[:30] or "Unknown"
                    tag    = "unknown"
                docker_results.append((name, image, status, tag))

            self.after(0, lambda a=apt_packages, d=docker_results: self._populate(a, d))
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, apt_packages, docker_results):
        t = self.theme

        # APT tree
        self._apt_tree.delete(*self._apt_tree.get_children())
        for idx, (pkg, cur, avail, arch) in enumerate(apt_packages):
            tag = ("even" if idx % 2 == 0 else "odd", "update")
            self._apt_tree.insert("", "end",
                                   values=(pkg, cur, avail, arch), tags=tag)

        # Docker tree
        self._docker_tree.delete(*self._docker_tree.get_children())
        for idx, (name, image, status, stag) in enumerate(docker_results):
            row_tag = "even" if idx % 2 == 0 else "odd"
            self._docker_tree.insert("", "end",
                                      values=(name, image, status),
                                      tags=(row_tag, stag))

        # Summary cards
        for w in self._summary_frame.winfo_children():
            w.destroy()
        apt_count = len(apt_packages)
        docker_updated = sum(1 for _, _, _, tag in docker_results if tag == "update")

        for label, val, color in [
            ("Apt Updates",      str(apt_count),      t.yellow if apt_count else t.status_running),
            ("Docker Refreshed", str(docker_updated), t.cyan),
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
