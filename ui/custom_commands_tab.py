# ui/custom_commands_tab.py

import tkinter as tk
import threading
import time


class CustomCommandsTab(tk.Frame):
    """
    Custom Commands tab — free-form SSH command runner with history shortcuts.
    Type any shell command and run it, or click a shortcut to load and execute it.
    Unlike Quick Commands (which has grouped, categorised buttons), these shortcuts
    are one-off or diagnostic commands that don't fit neatly into a category.
    """

    SAVED_COMMANDS = [
        ("Who's Logged In",          "who"),
        ("Open Ports",               "ss -tuln"),
        ("Top Processes (snapshot)", "ps aux --sort=-%cpu | head -20"),
        ("Failed Services",          "systemctl --failed --no-pager"),
        ("Disk Inodes",              "df -i"),
        ("Last 20 Auth Events",      "journalctl _SYSTEMD_UNIT=ssh.service -n 20 --no-pager"),
        ("Docker Stats (snapshot)",  "docker stats --no-stream"),
    ]

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)

        self.controller = controller
        self.theme = controller.theme

        self._build_ui()

    # ---------------------------------------------------------
    # BUILD UI
    # ---------------------------------------------------------
    def _build_ui(self):
        # ── Title ────────────────────────────────────────────
        tk.Label(
            self,
            text="CUSTOM COMMANDS",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(anchor="w", padx=12, pady=(12, 2))

        tk.Label(
            self,
            text="Type any shell command and run it on the server.",
            bg=self.theme.bg,
            fg=self.theme.text_muted,
            font=self.theme.font_small,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # ── Command entry row ─────────────────────────────────
        entry_row = tk.Frame(self, bg=self.theme.bg)
        entry_row.pack(fill="x", padx=12)

        self.cmd_var = tk.StringVar()

        self.entry = tk.Entry(
            entry_row,
            textvariable=self.cmd_var,
            font=self.theme.font_mono,
        )
        self.theme.style_entry(self.entry)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._run_command())

        self.run_btn = tk.Button(
            entry_row,
            text="Run",
            command=self._run_command,
        )
        self.theme.style_button(self.run_btn)
        self.run_btn.pack(side="left", padx=(8, 0))

        # ── Saved commands grid ───────────────────────────────
        tk.Label(
            self,
            text="Saved Commands",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(anchor="w", padx=12, pady=(16, 4))

        grid = tk.Frame(self, bg=self.theme.bg)
        grid.pack(fill="x", padx=12)

        for i, (label, cmd) in enumerate(self.SAVED_COMMANDS):
            btn = tk.Button(
                grid,
                text=label,
                anchor="w",
                command=lambda c=cmd: self._load_and_run(c),
            )
            self.theme.style_button(btn)
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)

        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        # ── Output console ────────────────────────────────────
        output_header = tk.Frame(self, bg=self.theme.bg)
        output_header.pack(fill="x", padx=12, pady=(16, 4))

        tk.Label(
            output_header,
            text="Output",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(side="left")

        clear_btn = tk.Button(
            output_header,
            text="Clear",
            command=self._clear_output,
        )
        self.theme.style_button(clear_btn)
        clear_btn.pack(side="right")

        # Text widget + scrollbar
        console_frame = tk.Frame(self, bg=self.theme.bg)
        console_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.output = tk.Text(
            console_frame,
            bg=self.theme.surface_dark,
            fg=self.theme.text,
            font=self.theme.font_mono,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.output.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(console_frame, command=self.output.yview)
        scrollbar.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scrollbar.set)

        self._configure_tags()

    # ---------------------------------------------------------
    # OUTPUT TAGS
    # ---------------------------------------------------------
    def _configure_tags(self):
        self.output.tag_config("cmd",       foreground=self.theme.console_cmd)
        self.output.tag_config("info",      foreground=self.theme.console_info)
        self.output.tag_config("success",   foreground=self.theme.console_success)
        self.output.tag_config("error",     foreground=self.theme.console_error)
        self.output.tag_config("timestamp", foreground=self.theme.console_timestamp)
        self.output.tag_config("output",    foreground=self.theme.console_output)

    # ---------------------------------------------------------
    # LOAD A SAVED COMMAND AND RUN IT IMMEDIATELY
    # ---------------------------------------------------------
    def _load_and_run(self, cmd):
        self.cmd_var.set(cmd)
        self._run_command()

    # ---------------------------------------------------------
    # RUN COMMAND (THREADED)
    # ---------------------------------------------------------
    def _run_command(self):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return

        self._log(f"$ {cmd}", "cmd")
        self.run_btn.config(text="Running…", state="disabled")

        def worker():
            out, err, code = self.controller.ssh.run(cmd)

            self._append(f"exit code: {code}\n", "info")

            if out.strip():
                for line in out.splitlines():
                    self._append(f"{line}\n", "output")

            if err.strip():
                for line in err.splitlines():
                    self._append(f"{line}\n", "error")

            self._append("\n", None)
            self.after(0, lambda: self.run_btn.config(text="Run", state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # CLEAR OUTPUT
    # ---------------------------------------------------------
    def _clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    # ---------------------------------------------------------
    # LOG / APPEND (THREAD-SAFE)
    # ---------------------------------------------------------
    def _log(self, text, tag):
        timestamp = time.strftime("%H:%M:%S")
        self._append(f"{timestamp}  {text}\n", tag, timestamp_prefix=True)

    def _append(self, text, tag, timestamp_prefix=False):
        self.after(0, lambda: self._append_safe(text, tag, timestamp_prefix))

    def _append_safe(self, text, tag, timestamp_prefix=False):
        autoscroll = self.output.yview()[1] >= 0.99

        self.output.configure(state="normal")

        if timestamp_prefix and len(text) > 8:
            self.output.insert("end", text[:8], "timestamp")
            self.output.insert("end", text[8:], tag)
        else:
            self.output.insert("end", text, tag or "")

        self.output.configure(state="disabled")

        if autoscroll:
            self.output.see("end")
