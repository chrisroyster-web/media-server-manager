# ui/compose_tab.py
"""
Docker Compose tab.
Lists all compose stacks found on the server, shows per-service status,
and lets you run up/down/pull/restart per stack.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import shlex

from ui.empty_state import EmptyState


class ComposeTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._stack_frames = []
        self._build_ui()
        self.after(600, self.refresh)

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")

        tk.Label(
            hdr, text="🐙  Docker Compose",
            bg=t.surface_dark, fg=t.text,
            font=t.font_title, anchor="w",
        ).pack(side="left", padx=18, pady=14)

        self._status_lbl = tk.Label(
            hdr, text="",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small,
        )
        self._status_lbl.pack(side="right", padx=18)

        tk.Button(
            hdr, text="⟳  Refresh",
            command=self.refresh,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat",
            font=t.font_small, padx=12, pady=4,
        ).pack(side="right", padx=(0, 10), pady=10)

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Scrollable area
        outer = tk.Frame(self, bg=t.bg)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        canvas = tk.Canvas(outer, bg=t.bg, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(canvas, bg=t.bg)
        self._win  = canvas.create_window((0, 0), window=self._body, anchor="nw")

        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._win, width=e.width))
        self._body.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._canvas = canvas

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._status_lbl.config(text="Scanning…", bg=self.theme.blue, fg="#ffffff")
        for f in self._stack_frames:
            f.destroy()
        self._stack_frames.clear()
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            if not ssh.connected:
                self.after(0, lambda: self._show_msg("Not connected to server.", disconnected=True))
                return

            # Find compose stacks via docker compose ls
            out, err, code = ssh.run("docker compose ls --format json 2>/dev/null || docker compose ls 2>/dev/null")
            if code != 0 or not out.strip():
                self.after(0, lambda: self._show_msg(
                    "No compose stacks found.\n\nMake sure Docker Compose v2 is installed\nand stacks are running or stopped.",
                    error=False))
                return

            stacks = self._parse_stacks(out.strip())
            if not stacks:
                self.after(0, lambda: self._show_msg("No compose stacks found.", error=False))
                return

            # For each stack, get per-service status
            stack_data = []
            for name, config_file, status in stacks:
                services = self._fetch_services(ssh, name, config_file)
                stack_data.append((name, config_file, status, services))

            self.after(0, lambda d=stack_data: self._render(d))
        finally:
            self._fetching = False

    def _parse_stacks(self, raw):
        """Parse `docker compose ls` output (JSON or table)."""
        import json as _json
        stacks = []
        # Try JSON first
        try:
            data = _json.loads(raw)
            for item in data:
                name   = item.get("Name", "")
                cfg    = item.get("ConfigFiles", "")
                status = item.get("Status", "")
                if name:
                    stacks.append((name, cfg, status))
            return stacks
        except Exception:
            pass

        # Table fallback: NAME   STATUS   CONFIG FILES
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() != "name":
                stacks.append((parts[0], parts[-1] if len(parts) >= 3 else "", parts[1]))
        return stacks

    def _compose_file_flags(self, config_file):
        """
        Build -f flags from docker compose ls's ConfigFiles field (comma-separated
        when a stack uses an override file). -p <project> alone is not reliably
        enough for `pull`/`up` on every Compose version -- those need to actually
        read the compose file, and not all versions can recover its location from
        existing containers' labels ("No configuration file provided: not found").
        """
        if not config_file:
            return ""
        files = [f.strip() for f in config_file.split(",") if f.strip()]
        return " ".join("-f {}".format(shlex.quote(f)) for f in files)

    def _fetch_services(self, ssh, stack_name, config_file):
        """Return list of (service_name, status, image) for a stack."""
        # Use -p (project name) to scope to the stack
        q  = shlex.quote(stack_name)
        ff = self._compose_file_flags(config_file)
        cmd = "docker compose {ff} -p {q} ps --format json 2>/dev/null || docker compose {ff} -p {q} ps 2>/dev/null".format(
            ff=ff, q=q)
        out, _, code = ssh.run(cmd)
        services = []
        if code != 0 or not out.strip():
            return services

        import json as _json
        # JSON output (compose v2.17+)
        try:
            # May be one JSON object per line
            for line in out.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = _json.loads(line)
                    services.append((
                        item.get("Service", item.get("Name", "?")),
                        item.get("State", item.get("Status", "?")),
                        item.get("Image", ""),
                    ))
                except Exception:
                    pass
            if services:
                return services
        except Exception:
            pass

        # Table fallback
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].lower() not in ("name", "service"):
                services.append((parts[0], parts[3] if len(parts) > 3 else parts[1], ""))
        return services

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def _render(self, stack_data):
        for f in self._stack_frames:
            f.destroy()
        self._stack_frames.clear()

        ts = time.strftime("%H:%M:%S")
        self._status_lbl.config(text="Updated {}".format(ts),
                               bg=self.theme.surface_dark, fg=self.theme.text_muted)

        for name, config_file, status, services in stack_data:
            frame = self._build_stack_card(name, config_file, status, services)
            self._stack_frames.append(frame)

    def _build_stack_card(self, name, config_file, status, services):
        t = self.theme

        card = tk.Frame(self._body, bg=t.surface,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))

        # ── Stack header ─────────────────────────────────────────────
        hdr = tk.Frame(card, bg=t.surface_dark, padx=14, pady=10)
        hdr.pack(fill="x")

        # Status dot
        is_up = "running" in status.lower() or "up" in status.lower()
        dot_color = t.status_running if is_up else t.status_stopped
        dot = tk.Canvas(hdr, width=10, height=10,
                        bg=t.surface_dark, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=dot_color, outline="")
        dot.pack(side="left", padx=(0, 8), pady=5)

        tk.Label(hdr, text=name,
                 bg=t.surface_dark, fg=t.text,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        tk.Label(hdr, text=status,
                 bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=12)

        if config_file:
            tk.Label(hdr, text=config_file,
                     bg=t.surface_dark, fg=t.text_muted,
                     font=t.font_small).pack(side="left")

        # Action buttons
        btn_cfg = [
            ("▲ Up",      t.status_running,   lambda n=name, c=config_file: self._run_action(n, c, "up -d")),
            ("▼ Down",    t.status_stopped,     lambda n=name, c=config_file: self._run_action(n, c, "down")),
            ("⟳ Restart", t.yellow,  lambda n=name, c=config_file: self._run_action(n, c, "restart")),
            ("⬇ Pull",    t.blue,    lambda n=name, c=config_file: self._run_action(n, c, "pull")),
        ]
        for btn_txt, btn_col, cmd in reversed(btn_cfg):
            fg = "#000000" if btn_col == t.yellow else "#ffffff"
            tk.Button(
                hdr, text=btn_txt,
                command=cmd,
                bg=btn_col, fg=fg,
                bd=0, relief="flat",
                font=t.font_small, padx=10, pady=3,
            ).pack(side="right", padx=(0, 6))

        # Edit button — opens compose file in an in-app editor
        if config_file:
            first_cfg = config_file.split(",")[0].strip()
            tk.Button(
                hdr, text="✏ Edit",
                command=lambda n=name, f=first_cfg: self._edit_compose(n, f),
                bg=t.surface_light, fg=t.text,
                bd=0, relief="flat",
                font=t.font_small, padx=10, pady=3,
                cursor="hand2",
            ).pack(side="right", padx=(0, 6))

        # ── Service list ─────────────────────────────────────────────
        if services:
            svc_frame = tk.Frame(card, bg=t.surface, padx=14, pady=8)
            svc_frame.pack(fill="x")

            # Column headers
            cols = [("Service", 200), ("Status", 120), ("Image", 0)]
            for col_i, (col_lbl, col_w) in enumerate(cols):
                anchor = "w"
                tk.Label(svc_frame, text=col_lbl,
                         bg=t.surface, fg=t.text_muted,
                         font=t.font_small, width=col_w//8, anchor=anchor,
                         ).grid(row=0, column=col_i, sticky="w", padx=(0, 20), pady=(0, 4))

            tk.Frame(svc_frame, bg=t.card_border, height=1).grid(
                row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))

            for row_i, (svc_name, svc_status, image) in enumerate(services):
                row = row_i + 2
                svc_up = "running" in svc_status.lower() or "up" in svc_status.lower()
                svc_col = t.status_running if svc_up else t.status_stopped

                tk.Label(svc_frame, text=svc_name,
                         bg=t.surface, fg=t.text,
                         font=t.font_regular, anchor="w",
                         ).grid(row=row, column=0, sticky="w", padx=(0, 20))
                tk.Label(svc_frame, text=svc_status,
                         bg=t.surface, fg=svc_col,
                         font=t.font_small, anchor="w",
                         ).grid(row=row, column=1, sticky="w", padx=(0, 20))
                tk.Label(svc_frame, text=image,
                         bg=t.surface, fg=t.text_muted,
                         font=t.font_small, anchor="w",
                         ).grid(row=row, column=2, sticky="w")
        else:
            tk.Label(card, text="No service info available",
                     bg=t.surface, fg=t.text_muted,
                     font=t.font_small).pack(anchor="w", padx=14, pady=6)

        # ── Action output console ────────────────────────────────────
        console_frame = tk.Frame(card, bg=t.surface)
        console_frame.pack(fill="x")
        console = tk.Text(
            console_frame,
            height=0,   # hidden until an action runs
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_mono, bd=0, relief="flat",
            state="disabled", wrap="word",
        )
        console.pack(fill="x", padx=14, pady=(0, 10))
        card._console = console

        return card

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _run_action(self, stack_name, config_file, action):
        if action in ("down", "restart"):
            verb = "Stop" if action == "down" else "Restart"
            if not messagebox.askyesno(
                    "{} Stack".format(verb),
                    "{} every service in the '{}' stack?".format(verb, stack_name),
                    parent=self):
                return
        # Find the card for this stack
        card = None
        for f in self._stack_frames:
            # identify by stack name stored in its header label
            for child in f.winfo_children():
                for lbl in child.winfo_children():
                    if isinstance(lbl, tk.Label) and lbl.cget("text") == stack_name:
                        card = f
                        break

        def _stream():
            ssh = self.controller.ssh
            if not ssh.connected:
                self._append_console(card, "Not connected.\n")
                return

            ff  = self._compose_file_flags(config_file)
            cmd = "docker compose {} -p {} {} 2>&1".format(ff, shlex.quote(stack_name), action)
            self._append_console(card, "$ {}\n".format(cmd))
            out, _, code = ssh.run(cmd)
            self.controller.audit_log(
                "compose.{}".format(action), stack_name,
                detail=(out or "").strip()[:200],
                result="ok" if code == 0 else "fail")
            self._append_console(card, out + "\n")
            self.after(1000, self.refresh)

        threading.Thread(target=_stream, daemon=True).start()

    def _append_console(self, card, text):
        if card is None:
            return
        console = getattr(card, "_console", None)
        if console is None:
            return
        def _do():
            console.configure(state="normal", height=8)
            console.insert("end", text)
            console.see("end")
            console.configure(state="disabled")
        self.after(0, _do)

    # ------------------------------------------------------------------
    # COMPOSE FILE EDITOR
    # ------------------------------------------------------------------
    def _edit_compose(self, stack_name, config_file):
        """Fetch the compose file via SSH and open it in an in-app text editor."""
        if not self.controller.ssh.connected:
            messagebox.showerror("Edit Compose", "Not connected to server.", parent=self)
            return

        def _fetch():
            out, err, code = self.controller.ssh.run(
                "cat {} 2>&1".format(shlex.quote(config_file)))
            if code != 0:
                self.after(0, lambda e=err: messagebox.showerror(
                    "Edit Compose",
                    "Could not read {}:\n{}".format(config_file, e[:300]),
                    parent=self))
                return
            self.after(0, lambda content=out:
                       self._open_compose_editor(stack_name, config_file, content))

        threading.Thread(target=_fetch, daemon=True).start()

    def _open_compose_editor(self, stack_name, config_file, content):
        t = self.theme
        win = tk.Toplevel(self)
        win.title("Edit — {}".format(config_file))
        win.geometry("920x680")
        win.configure(bg=t.bg)
        win.transient(self.winfo_toplevel())

        # Header
        hdr = tk.Frame(win, bg=t.surface_dark, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✏  {}".format(stack_name),
                 bg=t.surface_dark, fg=t.text,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(hdr, text=config_file,
                 bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=14)

        tk.Frame(win, bg=t.card_border, height=1).pack(fill="x")

        # Editor
        editor_frame = tk.Frame(win, bg=t.surface_dark)
        editor_frame.pack(fill="both", expand=True)

        hsb = tk.Scrollbar(editor_frame, orient="horizontal")
        vsb = tk.Scrollbar(editor_frame, orient="vertical")
        editor = tk.Text(
            editor_frame,
            bg=t.surface_dark, fg=t.text,
            font=t.font_mono,
            wrap="none",
            insertbackground=t.blue,
            selectbackground=t.surface_light,
            relief="flat", bd=0,
            padx=14, pady=10,
            xscrollcommand=hsb.set,
            yscrollcommand=vsb.set,
        )
        hsb.configure(command=editor.xview)
        vsb.configure(command=editor.yview)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", content)
        editor.focus_set()

        tk.Frame(win, bg=t.card_border, height=1).pack(fill="x")

        # Footer
        footer = tk.Frame(win, bg=t.surface_dark, padx=16, pady=10)
        footer.pack(fill="x")
        status_lbl = tk.Label(footer, text="", bg=t.surface_dark,
                               fg=t.text_muted, font=t.font_small)
        status_lbl.pack(side="left")

        def _save():
            new_content = editor.get("1.0", "end-1c")
            save_btn.config(state="disabled", text="Saving…")
            status_lbl.config(text="Saving…", fg=t.text_muted)

            def _worker():
                import base64
                b64 = base64.b64encode(new_content.encode("utf-8")).decode("ascii")
                cmd = "echo {} | base64 -d | sudo tee {} > /dev/null 2>&1".format(
                    shlex.quote(b64), shlex.quote(config_file))
                _, err, code = self.controller.ssh.run(cmd)

                def _done():
                    save_btn.config(state="normal", text="Save")
                    if code == 0:
                        status_lbl.config(text="Saved successfully.", fg=t.status_running)
                        win.after(3000, lambda: status_lbl.config(text=""))
                    else:
                        status_lbl.config(
                            text="Save failed: {}".format((err or "unknown error")[:120]),
                            fg=t.status_stopped_text)
                self.after(0, _done)

            threading.Thread(target=_worker, daemon=True).start()

        save_btn = tk.Button(footer, text="Save", command=_save,
                              bg=t.blue, fg="#ffffff",
                              bd=0, relief="flat", font=t.font_regular,
                              padx=16, pady=5, cursor="hand2")
        save_btn.pack(side="right", padx=(6, 0))

        tk.Button(footer, text="Close", command=win.destroy,
                  bg=t.surface_light, fg=t.text,
                  bd=0, relief="flat", font=t.font_regular,
                  padx=12, pady=5, cursor="hand2").pack(side="right")

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _show_msg(self, msg, error=True, disconnected=False):
        for f in self._stack_frames:
            f.destroy()
        self._stack_frames.clear()
        if disconnected:
            state = EmptyState(
                self._body, self.theme,
                icon="🔌", title="Not connected",
                subtitle="Connect to a server to view Compose stacks.",
                action_text="⚡ Connect",
                action_cmd=lambda: self.controller.tabs.select(0),
            )
        else:
            title, _, subtitle = msg.partition("\n\n")
            state = EmptyState(
                self._body, self.theme,
                icon="⚠" if error else "🐙",
                title=title, subtitle=subtitle,
            )
        state.pack(fill="both", expand=True)
        self._stack_frames.append(state)
        self._status_lbl.config(text="", bg=self.theme.surface_dark)
