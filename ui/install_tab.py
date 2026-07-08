# ui/install_tab.py
"""
App Installer tab.

Lists every app supported by this tool, shows its current status on the
connected server, and lets the user install, start, fix, or reinstall it
via Docker with a single click.

Safety guarantees (enforced by InstallManager):
  • Only the named container is ever touched.
  • Config volumes (/opt/<name>/config/) survive reinstall.
  • No apt upgrade, no system-wide changes, no cross-container edits.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import shlex

from core.install_manager import APP_REGISTRY, CATEGORIES, InstallManager


# ── Status display metadata ────────────────────────────────────────────────
_DOT = {
    "unknown":       "#555566",
    "checking":      "#5b8ef0",   # blue
    "not_installed": "#555566",   # grey
    "running":       "#22c55e",   # green
    "stopped":       "#f5c518",   # yellow
    "unhealthy":     "#f97316",   # orange
    "error":         "#ef4444",   # red
}
_LABEL = {
    "unknown":       "—",
    "checking":      "Checking…",
    "not_installed": "Not installed",
    "running":       "Running",
    "stopped":       "Stopped",
    "unhealthy":     "Unhealthy",
    "error":         "Error",
}


class InstallTab(tk.Frame):
    """Browse, install, and repair supported apps on the connected server."""

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller  = controller
        self.theme       = t
        self._im         = None          # InstallManager, created on first use
        self._rows       = {}            # key → row-widget dict
        self._statuses   = {}            # key → status dict
        self._checks     = {}            # key → BooleanVar (checkbox)
        self._busy       = False
        self._scanned_host = None
        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self.theme

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")

        tk.Label(hdr, text="📦  App Installer",
                 bg=t.surface_dark, fg=t.text,
                 font=t.font_title, anchor="w",
                 ).pack(side="left", padx=18, pady=14)

        self._scan_btn = tk.Button(
            hdr, text="⟳  Scan All",
            command=self._scan_all,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat", font=t.font_small,
            padx=14, pady=4, cursor="hand2",
        )
        self._scan_btn.pack(side="right", padx=(0, 14), pady=10)

        self._fix_btn = tk.Button(
            hdr, text="🔧  Fix All Broken",
            command=self._fix_all_broken,
            bg=t.yellow, fg="#000000",
            bd=0, relief="flat", font=t.font_small,
            padx=14, pady=4, cursor="hand2",
        )
        self._fix_btn.pack(side="right", padx=(0, 6), pady=10)

        self._install_btn = tk.Button(
            hdr, text="⬇  Install Selected",
            command=self._install_selected,
            bg=t.status_running, fg="#ffffff",
            bd=0, relief="flat", font=t.font_small,
            padx=14, pady=4, cursor="hand2",
        )
        self._install_btn.pack(side="right", padx=(0, 6), pady=10)

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # ── Note bar ──────────────────────────────────────────────────────
        note = tk.Frame(self, bg=t.surface, padx=18, pady=7)
        note.pack(fill="x")
        tk.Label(note,
                 text="All installs use Docker.  Config data is preserved under "
                      "/opt/<app>/config/ — reinstalling a container never loses settings.",
                 bg=t.surface, fg=t.text_muted, font=t.font_small, anchor="w",
                 ).pack(side="left")

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # ── PanedWindow: app list (top) / console (bottom) ────────────────
        pane = tk.PanedWindow(self, orient="vertical",
                               bg=t.card_border, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        # ── App list pane ─────────────────────────────────────────────────
        list_outer = tk.Frame(pane, bg=t.bg)
        pane.add(list_outer, minsize=320, stretch="always")

        canvas = tk.Canvas(list_outer, bg=t.bg, highlightthickness=0)
        sb = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._list_body = tk.Frame(canvas, bg=t.bg)
        self._list_win  = canvas.create_window((0, 0), window=self._list_body, anchor="nw")
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._list_win, width=e.width))
        self._list_body.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_app_rows()

        # ── Console pane ──────────────────────────────────────────────────
        con_outer = tk.Frame(pane, bg=t.surface_dark)
        pane.add(con_outer, minsize=130, stretch="never")

        con_hdr = tk.Frame(con_outer, bg=t.surface_dark, padx=14, pady=5)
        con_hdr.pack(fill="x")
        tk.Label(con_hdr, text="OUTPUT",
                 bg=t.surface_dark, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(con_hdr, text="Clear",
                  command=self._clear_console,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small,
                  cursor="hand2").pack(side="right")

        con_sb = ttk.Scrollbar(con_outer, orient="vertical")
        self._console = tk.Text(
            con_outer,
            bg=t.surface_dark, fg=t.text,
            font=t.font_mono,
            bd=0, relief="flat",
            state="disabled", wrap="word",
            height=10,
            yscrollcommand=con_sb.set,
        )
        con_sb.configure(command=self._console.yview)
        con_sb.pack(side="right", fill="y")
        self._console.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        self._console.tag_configure("cmd",     foreground=t.cyan)
        self._console.tag_configure("ok",      foreground=t.status_running)
        self._console.tag_configure("error",   foreground=t.status_stopped_text)
        self._console.tag_configure("warn",    foreground=t.yellow)
        self._console.tag_configure("section",
                                    foreground=t.blue_bright,
                                    font=("Segoe UI Semibold", 9))

    # ──────────────────────────────────────────────────────────────────────
    # APP ROWS
    # ──────────────────────────────────────────────────────────────────────

    def _build_app_rows(self):
        t = self.theme
        apps_by_cat = {}
        for app in APP_REGISTRY:
            apps_by_cat.setdefault(app["category"], []).append(app)

        for cat in CATEGORIES:
            apps = apps_by_cat.get(cat, [])
            if not apps:
                continue

            # Category section header
            sec = tk.Frame(self._list_body, bg=t.bg)
            sec.pack(fill="x", padx=16, pady=(14, 4))
            tk.Label(sec, text=cat.upper(),
                     bg=t.bg, fg=t.text_muted,
                     font=("Segoe UI", 8, "bold")).pack(side="left")
            tk.Frame(sec, bg=t.card_border, height=1).pack(
                side="left", fill="x", expand=True, padx=(10, 0), pady=7)

            for app in apps:
                self._build_row(app)

        tk.Frame(self._list_body, bg=t.bg, height=16).pack()

    def _build_row(self, app):
        t   = self.theme
        key = app["key"]

        row = tk.Frame(self._list_body, bg=t.surface,
                       highlightbackground=t.card_border, highlightthickness=1)
        row.pack(fill="x", padx=16, pady=(0, 3))

        inner = tk.Frame(row, bg=t.surface, padx=10, pady=7)
        inner.pack(fill="x")

        # Checkbox (controls batch install / fix selection)
        var = tk.BooleanVar(value=False)
        self._checks[key] = var
        tk.Checkbutton(inner, variable=var,
                       bg=t.surface, activebackground=t.surface,
                       bd=0, relief="flat", cursor="hand2",
                       ).pack(side="left", padx=(0, 6))

        # Status dot
        dot = tk.Canvas(inner, width=12, height=12,
                        bg=t.surface, highlightthickness=0)
        dot.pack(side="left", padx=(0, 10))
        dot.create_oval(1, 1, 11, 11, fill=_DOT["unknown"], outline="")

        # App name
        tk.Label(inner, text=app["name"],
                 bg=t.surface, fg=t.text,
                 font=t.font_regular,
                 width=24, anchor="w").pack(side="left")

        # Status label
        status_lbl = tk.Label(inner, text="—",
                               bg=t.surface, fg=t.text_dim,
                               font=t.font_small,
                               width=15, anchor="w")
        status_lbl.pack(side="left")

        # Port chip
        port_txt = f":{app['port']}" if app.get("port") else ""
        tk.Label(inner, text=port_txt,
                 bg=t.surface, fg=t.text_dim,
                 font=t.font_mono,
                 width=7, anchor="w").pack(side="left")

        # ── Action buttons (right side) — packed before desc so they get priority
        btn_frame = tk.Frame(inner, bg=t.surface)
        btn_frame.pack(side="right")

        # Description — truncated so it never crowds the buttons
        _MAX_DESC = 60
        desc_text = app["desc"]
        if len(desc_text) > _MAX_DESC:
            desc_text = desc_text[:_MAX_DESC - 1] + "…"
        tk.Label(inner, text=desc_text,
                 bg=t.surface, fg=t.text_dim,
                 font=t.font_small, anchor="w",
                 ).pack(side="left", fill="x", expand=True, padx=(4, 10))

        # Packed right-to-left → display order left-to-right: [action][reinstall][uninstall]
        uninstall_btn = tk.Button(
            btn_frame, text="Uninstall",
            command=lambda a=app: self._do_uninstall(a),
            bg=t.surface_dark, fg=t.text_dim,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=3, cursor="hand2", state="disabled",
        )
        uninstall_btn.pack(side="right", padx=(4, 0))

        reinstall_btn = tk.Button(
            btn_frame, text="Reinstall",
            command=lambda a=app: self._do_reinstall(a),
            bg=t.surface_dark, fg=t.text_dim,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=3, cursor="hand2", state="disabled",
        )
        reinstall_btn.pack(side="right", padx=(4, 0))

        action_btn = tk.Button(
            btn_frame, text="—",
            command=lambda a=app: self._do_action(a),
            bg=t.surface_dark, fg=t.text_dim,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=3, cursor="hand2", state="disabled",
        )
        action_btn.pack(side="right")

        self._rows[key] = {
            "dot":           dot,
            "status_lbl":    status_lbl,
            "action_btn":    action_btn,
            "reinstall_btn": reinstall_btn,
            "uninstall_btn": uninstall_btn,
        }
        self._statuses[key] = {"state": "unknown"}

    def _update_row(self, key: str, status: dict):
        """Redraw one row's dot, label, and buttons. Safe to call from any thread."""
        def _do():
            rw = self._rows.get(key)
            if not rw:
                return
            t  = self.theme
            st = status.get("state", "unknown")

            # Dot
            rw["dot"].delete("all")
            rw["dot"].create_oval(1, 1, 11, 11, fill=_DOT.get(st, _DOT["unknown"]), outline="")

            # Status text — append method hint for non-Docker installs
            method = status.get("method", "")
            base_label = _LABEL.get(st, st)
            if st == "running" and method in ("service", "port", "process"):
                method_hint = {"service": " (service)", "port": " (port)", "process": " (process)"}.get(method, "")
                label_text = base_label + method_hint
            else:
                label_text = base_label
            lbl_fg = _DOT.get(st, t.text_dim) if st not in ("unknown", "not_installed", "checking") else t.text_dim
            rw["status_lbl"].config(text=label_text, fg=lbl_fg)

            # Buttons
            ab = rw["action_btn"]
            rb = rw["reinstall_btn"]
            ub = rw["uninstall_btn"]

            if st in ("unknown", "checking"):
                ab.config(text="—",       state="disabled", bg=t.surface_dark, fg=t.text_dim)
                rb.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
                ub.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
            elif st == "not_installed":
                ab.config(text="Install", state="normal",   bg=t.blue,          fg="#ffffff")
                rb.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
                ub.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
            elif st == "stopped":
                ab.config(text="Start",   state="normal",   bg=t.status_running, fg="#ffffff")
                rb.config(state="normal",  bg=t.surface_light, fg=t.text)
                ub.config(state="normal",  bg=t.status_stopped, fg="#ffffff")
            elif st == "running":
                ab.config(text="Restart", state="normal",   bg=t.surface_light, fg=t.text)
                rb.config(state="normal",  bg=t.surface_light, fg=t.text)
                ub.config(state="normal",  bg=t.status_stopped, fg="#ffffff")
            elif st == "unhealthy":
                ab.config(text="Fix",     state="normal",   bg=t.yellow,        fg="#000000")
                rb.config(state="normal",  bg=t.surface_light, fg=t.text)
                ub.config(state="normal",  bg=t.status_stopped, fg="#ffffff")
            else:  # error
                ab.config(text="Retry",   state="normal",   bg=t.status_stopped, fg="#ffffff")
                rb.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)
                ub.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)

            self._statuses[key] = status
        self.after(0, _do)

    # ──────────────────────────────────────────────────────────────────────
    # CONSOLE
    # ──────────────────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str = None):
        def _do():
            self._console.configure(state="normal")
            if tag:
                self._console.insert("end", text, tag)
            else:
                self._console.insert("end", text)
            self._console.see("end")
            self._console.configure(state="disabled")
        self.after(0, _do)

    def _clear_console(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")

    # ──────────────────────────────────────────────────────────────────────
    # SCAN
    # ──────────────────────────────────────────────────────────────────────

    def _scan_all(self):
        if not self.controller.ssh.connected:
            self._log("✗  Not connected to server.\n", "error")
            return
        if self._busy:
            self._log("⚠  Operation already in progress.\n", "warn")
            return

        self._busy = True
        self._scan_btn.config(state="disabled", text="Scanning…")
        self._log("\n── Scan started ──────────────────────────────────────\n", "section")
        self._im = InstallManager(self.controller.ssh, self.controller.config_manager)

        def _worker():
            # Pre-flight: is Docker available?
            docker_ok = self._im.check_docker_available()
            if not docker_ok:
                self.after(0, lambda: self._log(
                    "  ⚠  Docker daemon not reachable — "
                    "install Docker Engine first.\n", "warn"))

            for app in APP_REGISTRY:
                key  = app["key"]
                name = app["name"]
                self._log(f"  {name}… ")
                self._update_row(key, {"state": "checking"})
                try:
                    status = self._im.check_app(app)
                except Exception as ex:
                    status = {"state": "error", "version": "", "message": str(ex)}
                self._update_row(key, status)
                state  = status.get("state", "unknown")
                method = status.get("method", "")
                tag    = ("ok"   if state == "running"
                          else "warn" if state in ("stopped", "unhealthy")
                          else None)
                method_str = f" [{method}]" if method and method not in ("none",) else ""
                msg_str = f"  —  {status['message']}" if state == "error" and status.get("message") else ""
                self._log(state + method_str + msg_str + "\n", tag or ("error" if state == "error" else None))

            self._log("── Scan complete ─────────────────────────────────────\n", "section")
            self.after(0, lambda: self._scan_btn.config(
                state="normal", text="⟳  Scan All"))
            self._busy = False

        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # PER-APP ACTIONS
    # ──────────────────────────────────────────────────────────────────────

    def _do_action(self, app):
        state = self._statuses.get(app["key"], {}).get("state", "unknown")
        if state == "not_installed":
            self._run_op(app, "install")
        elif state == "stopped":
            self._run_op(app, "start")
        elif state == "running":
            if not messagebox.askyesno(
                    "Restart", f"Restart {app['name']}?", parent=self):
                return
            self._run_op(app, "restart")
        elif state == "unhealthy":
            self._run_op(app, "fix")
        else:
            self._log(f"\n  Run Scan first to determine the action for {app['name']}.\n", "warn")

    def _do_reinstall(self, app):
        if not messagebox.askyesno(
                "Reinstall",
                f"Recreate the {app['name']} container from the latest image?\n\n"
                "Your config in /opt/{}/config/ is NOT deleted — "
                "the container is replaced but data is preserved.".format(app["key"]),
                parent=self):
            return
        self._run_op(app, "reinstall")

    def _do_uninstall(self, app):
        status = self._statuses.get(app["key"], {})
        method = status.get("method", "")
        if method == "service":
            msg = (
                f"Disable the {app['name']} systemd service?\n\n"
                "This stops and disables the native service. "
                "Config files on disk will NOT be deleted."
            )
        else:
            msg = (
                f"Remove the {app['name']} container?\n\n"
                f"Config data in $HOME/docker/{app['key']}/config/ will NOT be deleted. "
                "You can reinstall later without losing settings."
            )
        if not messagebox.askyesno("Confirm Uninstall", msg, parent=self):
            return
        self._run_op(app, "uninstall")

    def _run_op(self, app, op: str):
        if not self.controller.ssh.connected:
            self._log("✗  Not connected.\n", "error")
            return
        def _worker():
            self._run_single(app, op)
        threading.Thread(target=_worker, daemon=True).start()

    def _run_single(self, app: dict, op: str):
        """Execute one operation for one app (background thread)."""
        key  = app["key"]
        name = app["name"]
        if self._im is None:
            self._im = InstallManager(self.controller.ssh, self.controller.config_manager)
        im = self._im

        self._log(f"\n── {op.title()}: {name} ───────────────────────────────\n", "section")
        self._update_row(key, {"state": "checking"})

        ok = False
        if op == "install":
            ok = im.install(app, self._log)
        elif op == "start":
            ok = im.start(app, self._log)
        elif op == "restart":
            container = app.get("container")
            if container:
                self._log(f"  $ docker restart {container}\n", "cmd")
                out, _, code = self.controller.ssh.run(f"docker restart {shlex.quote(container)} 2>&1")
                if (out or "").strip():
                    self._log(out.strip() + "\n")
                ok = (code == 0)
        elif op == "fix":
            ok = im.fix(app, self._log)
        elif op == "reinstall":
            ok = im.reinstall(app, self._log)
        elif op == "uninstall":
            ok = im.uninstall(app, self._log)

        self.controller.audit_log(
            "install.{}".format(op), name,
            result="ok" if ok else "fail")

        # Re-check status after a short settle time
        settle = 8 if op in ("install", "fix", "reinstall") else 4
        time.sleep(settle)
        try:
            new_status = im.check_app(app)
        except Exception:
            new_status = {"state": "error"}
        self._update_row(key, new_status)

        final = new_status.get("state", "unknown")
        tag   = "ok" if final == "running" else "error"
        self._log(f"\n  → {name}: {final}\n", tag)

    # ──────────────────────────────────────────────────────────────────────
    # BATCH OPERATIONS
    # ──────────────────────────────────────────────────────────────────────

    def _install_selected(self):
        """Install all checked apps that are currently not_installed."""
        targets = [
            app for app in APP_REGISTRY
            if (self._checks[app["key"]].get() and
                self._statuses.get(app["key"], {}).get("state") == "not_installed")
        ]
        if not targets:
            self._log(
                "\n  No checked apps are uninstalled. "
                "Run Scan, then tick the apps you want.\n", "warn")
            return
        if not self.controller.ssh.connected:
            self._log("✗  Not connected.\n", "error")
            return

        self._log(
            f"\n── Batch install: {len(targets)} app(s) ─────────────────────\n",
            "section")

        def _worker():
            for app in targets:
                self._run_single(app, "install")
        threading.Thread(target=_worker, daemon=True).start()

    def _fix_all_broken(self):
        """Fix all apps currently in stopped or unhealthy state."""
        targets = [
            app for app in APP_REGISTRY
            if self._statuses.get(app["key"], {}).get("state") in ("stopped", "unhealthy")
        ]
        if not targets:
            self._log(
                "\n  No broken apps found. Run Scan first.\n", "warn")
            return
        if not self.controller.ssh.connected:
            self._log("✗  Not connected.\n", "error")
            return

        self._log(
            f"\n── Fix all broken: {len(targets)} app(s) ────────────────────\n",
            "section")

        def _worker():
            for app in targets:
                op = ("start" if self._statuses.get(app["key"], {}).get("state") == "stopped"
                      else "fix")
                self._run_single(app, op)
        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ──────────────────────────────────────────────────────────────────────

    def on_show(self):
        """Called when the tab is selected via _trigger_tab_refresh."""
        connect_args = getattr(self.controller.ssh, "_connect_args", None) or {}
        host = connect_args.get("host")
        if self.controller.ssh.connected and host != self._scanned_host:
            self._scanned_host = host
            self._scan_all()
