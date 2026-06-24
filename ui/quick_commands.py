# ui/quick_commands.py

import tkinter as tk
import threading
import time


class QuickCommandsPanel(tk.Frame):
    """
    Quick Commands panel.
    - Each category in a styled card box
    - Cards flow and wrap with window width
    - Mousewheel scrolling on the card canvas
    - Embedded output console below
    """

    GROUPED_COMMANDS = {
        "System Health": [
            ("Full Health Check",   "sudo /usr/local/bin/healthcheck"),
            ("System Resources",    "top -b -n 1"),
            ("Disk Space (All)",    "df -h"),
            ("Downloads SSD Space", "df -h /opt/media/downloads"),
            ("Recent System Logs",  "journalctl -n 50 --no-pager"),
            ("CPU Temperature",     "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{print $1/1000\"C\"}'"),
        ],
        "NAS & Storage": [
            ("NAS Mount Status",    "mount | grep nas"),
            ("NAS Share Space",     "df -h /mnt/nas/wsbackup"),
            ("Remount NAS Shares",  "sudo mount -a"),
            ("List NAS Mounts",     "ls /mnt/nas/"),
        ],
        "UPS": [
            ("UPS Status",          "upsc apcups@localhost"),
            ("UPS Battery Level",   "upsc apcups@localhost battery.charge"),
            ("UPS Load",            "upsc apcups@localhost ups.load"),
            ("UPS Runtime Left",    "upsc apcups@localhost battery.runtime | grep -v SSL | awk '{s=$1; printf \"%dh %dm\\n\", s/3600, (s%3600)/60}'"),
        ],
        "Backup & Cleanup": [
            ("Run Backup Now",      "sudo /opt/media/backup.sh"),
            ("View Backup Log",     "tail -50 /var/log/media-backup.log"),
            ("List Backups",        "ls -lh /mnt/nas/wsbackup/mediaserver/"),
            ("Run Cleanup Now",     "sudo /opt/media/cleanup.sh"),
            ("View Cleanup Log",    "tail -50 /var/log/mediaserver-cleanup.log"),
        ],
        "Services": [
            ("Restart All Services","sudo systemctl restart emby-server sonarr radarr prowlarr bazarr sabnzbdplus"),
            ("Docker Status",       "docker ps"),
            ("Restart Docker",      "sudo systemctl restart docker"),
            ("Docker Logs",         "docker ps -q | xargs -I{} docker logs --tail=20 {}"),
        ],
        "Security": [
            ("Firewall Status",     "sudo ufw status verbose"),
            ("Active Connections",  "ss -tuln"),
            ("Failed Logins",       "journalctl _SYSTEMD_UNIT=ssh.service | grep Failed | tail -20"),
            ("Last Logins",         "last -n 10"),
        ],
        "Downloads": [
            ("Downloads Disk Use",  "du -sh /opt/media/downloads/*"),
            ("Incomplete Downloads","ls -lh /opt/media/downloads/incomplete/"),
            ("Complete Downloads",  "ls -lh /opt/media/downloads/complete/"),
            ("SABnzbd Status",      "systemctl status sabnzbdplus --no-pager"),
        ],
    }

    CATEGORY_COLORS = {
        "System Health":    "blue",
        "NAS & Storage":    "cyan",
        "UPS":              "yellow",
        "Backup & Cleanup": "orange",
        "Services":         "purple",
        "Security":         "red",
        "Downloads":        "blue",
    }

    CARD_MIN_WIDTH = 280

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)

        self.controller = controller
        self.theme = controller.theme

        self._cards = []
        self._flow_job = None

        self._build_ui()

    # ---------------------------------------------------------
    # BUILD UI
    # ---------------------------------------------------------
    def _build_ui(self):
        tk.Label(
            self,
            text="QUICK COMMANDS",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(anchor="w", padx=12, pady=(12, 6))

        top = tk.Frame(self, bg=self.theme.bg)
        top.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(top, bg=self.theme.bg, highlightthickness=0)
        scrollbar = tk.Scrollbar(top, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._flow = tk.Frame(self._canvas, bg=self.theme.bg)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._flow, anchor="nw"
        )

        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # Mousewheel scrolling
        for w in (self._canvas, self._flow):
            w.bind("<MouseWheel>", self._on_mousewheel)
            w.bind("<Button-4>",   self._on_mousewheel)
            w.bind("<Button-5>",   self._on_mousewheel)

        for category, commands in self.GROUPED_COMMANDS.items():
            card = self._build_card(category, commands)
            self._bind_scroll(card)
            self._cards.append(card)

        # Output console
        console_header = tk.Frame(self, bg=self.theme.bg)
        console_header.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(
            console_header,
            text="Output",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.theme.font_title,
        ).pack(side="left")

        clear_btn = tk.Button(
            console_header,
            text="Clear",
            command=self._clear_output,
        )
        self.theme.style_button(clear_btn)
        clear_btn.pack(side="right")

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
            height=10,
        )
        self.output.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(console_frame, command=self.output.yview)
        sb.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=sb.set)

        self._configure_tags()

    # ---------------------------------------------------------
    # BUILD A SINGLE CATEGORY CARD
    # ---------------------------------------------------------
    def _build_card(self, category, commands):
        color_attr = self.CATEGORY_COLORS.get(category, "text")
        accent = getattr(self.theme, color_attr, self.theme.text)

        card = tk.Frame(
            self._flow,
            bg=self.theme.card_bg,
            highlightbackground=self.theme.card_border,
            highlightthickness=1,
        )

        tk.Frame(card, bg=accent, height=3).pack(fill="x")

        tk.Label(
            card,
            text=category,
            bg=self.theme.card_bg,
            fg=accent,
            font=self.theme.font_title,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 6))

        tk.Frame(card, bg=self.theme.card_border, height=1).pack(fill="x", padx=8)

        btn_area = tk.Frame(card, bg=self.theme.card_bg)
        btn_area.pack(fill="x", padx=8, pady=6)

        for label, cmd in commands:
            btn = tk.Button(
                btn_area,
                text=label,
                anchor="w",
                command=lambda l=label, c=cmd: self._run_command(l, c),
            )
            self.theme.style_button(btn)
            btn.pack(fill="x", pady=2)

        return card

    # ---------------------------------------------------------
    # MOUSEWHEEL
    # ---------------------------------------------------------
    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_scroll(self, widget):
        """Recursively bind mousewheel on widget and all descendants."""
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>",   self._on_mousewheel)
        widget.bind("<Button-5>",   self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    # ---------------------------------------------------------
    # FLOW LAYOUT
    # ---------------------------------------------------------
    def _on_canvas_resize(self, event):
        if self._flow_job:
            self.after_cancel(self._flow_job)
        self._flow_job = self.after(50, lambda: self._reflow(event.width))

    def _reflow(self, available_width):
        if not self._cards:
            return

        pad = 10
        gap = 10

        cols = max(1, (available_width + gap) // (self.CARD_MIN_WIDTH + gap))
        card_width = (available_width - pad * 2 - gap * (cols - 1)) // cols

        self._canvas.itemconfig(self._canvas_window, width=available_width)

        col_heights = [pad] * cols

        for i, card in enumerate(self._cards):
            col = i % cols
            x = pad + col * (card_width + gap)
            y = col_heights[col]

            card.place(x=x, y=y, width=card_width)
            card.update_idletasks()
            h = card.winfo_reqheight()
            col_heights[col] += h + gap

        total_height = max(col_heights) + pad
        self._flow.config(height=total_height)
        self._canvas.configure(scrollregion=(0, 0, available_width, total_height))

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
    # RUN COMMAND (THREADED)
    # ---------------------------------------------------------
    def _run_command(self, label, cmd):
        self._log("$ " + cmd, "cmd")

        def worker():
            out, err, code = self.controller.ssh.run(cmd)

            self._append("exit code: " + str(code) + "\n", "info")

            if out.strip():
                for line in out.splitlines():
                    self._append(line + "\n", "output")

            if err.strip():
                for line in err.splitlines():
                    self._append(line + "\n", "error")

            self._append("\n", None)

            if "systemctl" in cmd or "docker" in cmd:
                self.controller.services_tab.refresh_all()

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
        self._append(timestamp + "  " + text + "\n", tag, timestamp_prefix=True)

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
