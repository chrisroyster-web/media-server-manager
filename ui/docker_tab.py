# ui/docker_tab.py

import tkinter as tk
import threading
import webbrowser

from ui.base_tab import CardConsoleTab


class DockerTab(CardConsoleTab):
    """
    Docker container cards with embedded output console.
    Inherits layout, mousewheel scrolling, and console from CardConsoleTab.
    Container config is loaded from ConfigManager so the Config tab can update it live.
    """

    TITLE = "DOCKER CONTAINERS"

    # Class-level fallback (kept for backward compat; overridden per-instance from config)
    DOCKER_CONTAINERS = {
        "Tracearr":    {"container": "tracearr",    "port": 3000},
        "Homarr":      {"container": "homarr",      "port": 7575},
        "Uptime Kuma": {"container": "uptime-kuma", "port": 3001},
        "Watchtower":  {"container": "watchtower",  "port": None},
    }

    def __init__(self, parent, controller):
        # Load from config BEFORE super().__init__() which calls _populate_cards()
        self.docker_containers = controller.config_manager.get_docker()
        DockerTab.DOCKER_CONTAINERS = self.docker_containers  # keep class var in sync
        super().__init__(parent, controller)

    def _host(self):
        return self.controller.config_manager.last_host or "localhost"

    def _url(self, port):
        return "http://{0}:{1}".format(self._host(), port) if port else None

    # ---------------------------------------------------------
    # POPULATE CARDS
    # ---------------------------------------------------------
    def _populate_cards(self):
        for name, data in self.docker_containers.items():
            self.cards[name] = self._create_card(name, data)

    def _create_card(self, name, data):
        frame = tk.Frame(
            self.inner,
            bg=self.theme.card_bg,
            highlightbackground=self.theme.card_border,
            highlightthickness=1,
        )
        frame.pack(fill="x", padx=10, pady=6)
        self._bind_mousewheel(frame)

        header = tk.Frame(frame, bg=self.theme.card_bg)
        header.pack(fill="x", pady=(6, 2))
        self._bind_mousewheel(header)

        dot = tk.Canvas(header, width=14, height=14,
                        bg=self.theme.card_bg, highlightthickness=0)
        dot.pack(side="left", padx=(6, 10))
        self._bind_mousewheel(dot)

        tk.Label(header, text=name, bg=self.theme.card_bg,
                 fg=self.theme.text, font=self.theme.font_title).pack(side="left")

        status_lbl = tk.Label(header, text="unknown", bg=self.theme.card_bg,
                               fg=self.theme.text_muted, font=self.theme.font_small)
        status_lbl.pack(side="right", padx=10)

        port = data.get("port")
        url_lbl = None
        if port:
            url_lbl = tk.Label(
                frame, text=self._url(port),
                bg=self.theme.card_bg, fg=self.theme.cyan,
                font=self.theme.font_small, cursor="hand2",
            )
            url_lbl.pack(anchor="w", padx=10)
            url_lbl.bind("<Button-1>", lambda e, p=port: webbrowser.open(self._url(p)))
            self._bind_mousewheel(url_lbl)

        btn_row = tk.Frame(frame, bg=self.theme.card_bg)
        btn_row.pack(fill="x", pady=6)
        self._bind_mousewheel(btn_row)

        for label, action in [
            ("Start", "start"), ("Stop", "stop"), ("Restart", "restart"),
            ("Logs", "logs"), ("Inspect", "inspect"),
        ]:
            btn = tk.Button(btn_row, text=label,
                            command=lambda a=action, n=name: self._action(n, a))
            self.theme.style_button(btn)
            btn.pack(side="left", padx=4)

        # Stats row: CPU % / RAM % / Uptime (populated on refresh)
        stats_lbl = tk.Label(frame, text="", bg=self.theme.card_bg,
                             fg=self.theme.text_dim, font=("Segoe UI", 9))
        stats_lbl.pack(anchor="w", padx=8, pady=(0, 4))
        self._bind_mousewheel(stats_lbl)

        return {"frame": frame, "dot": dot, "status_lbl": status_lbl,
                "stats_lbl": stats_lbl,
                "url_lbl": url_lbl, "container": data["container"], "port": port}

    # ---------------------------------------------------------
    # ACTIONS
    # ---------------------------------------------------------
    def _action(self, name, action):
        container = self.cards[name]["container"]
        self._log("{0} {1}".format(action.upper(), container), "cmd")

        def worker():
            dm = self.controller.docker_manager
            if   action == "start":   result = dm.start(container)
            elif action == "stop":    result = dm.stop(container)
            elif action == "restart": result = dm.restart(container)
            elif action == "logs":    result = dm.logs(container)
            elif action == "inspect": result = dm.inspect(container)
            else: return
            out, err, code = result
            self._log_output("{0} {1}".format(name, action), out, err, code)
            self.refresh_all()

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # REFRESH
    # ---------------------------------------------------------
    def refresh_all(self):
        for card in self.cards.values():
            if card["url_lbl"] and card["port"]:
                card["url_lbl"].config(text=self._url(card["port"]))

        def worker():
            ssh = self.controller.ssh
            dm  = self.controller.docker_manager

            # Fetch docker stats for all containers in one call
            stats_map = {}
            if ssh.connected:
                names = " ".join(c["container"] for c in self.cards.values())
                out, _, code = ssh.run(
                    "docker stats --no-stream --format "
                    "'{{{{.Name}}}}|{{{{.CPUPerc}}}}|{{{{.MemPerc}}}}|{{{{.RunningFor}}}}'"
                    " {} 2>/dev/null".format(names)
                )
                if code == 0:
                    for line in out.strip().splitlines():
                        parts = line.split("|")
                        if len(parts) == 4:
                            stats_map[parts[0].strip()] = {
                                "cpu": parts[1].strip(),
                                "mem": parts[2].strip(),
                                "uptime": parts[3].strip(),
                            }

            for name, card in self.cards.items():
                status = dm.get_status(card["container"])
                st = stats_map.get(card["container"], {})
                self.after(0, lambda n=name, s=status, st=st: self._update_card(n, s, st))

        threading.Thread(target=worker, daemon=True).start()

    def _update_card(self, name, status, stats=None):
        card = self.cards[name]
        t    = self.theme

        # Status dot + label
        card["status_lbl"].config(text=status)
        dot = card["dot"]
        dot.delete("all")
        if   status == "running":   color = t.status_running
        elif status == "stopped":   color = t.status_stopped
        elif status == "paused":    color = t.yellow
        elif status == "scheduled": color = t.cyan
        else:                       color = t.status_unknown
        dot.create_oval(2, 2, 12, 12, fill=color, outline=color)

        # Stats row
        if stats and status == "running":
            cpu    = stats.get("cpu", "--")
            mem    = stats.get("mem", "--")
            uptime = stats.get("uptime", "")
            up_lower = uptime.lower()
            if any(w in up_lower for w in ("day", "hour", "week")):
                up_color = t.status_running
            elif "minute" in up_lower:
                up_color = t.yellow
            else:
                up_color = t.status_stopped
            stats_text = "CPU {}  MEM {}  Up: {}".format(cpu, mem, uptime)
            card["stats_lbl"].config(text=stats_text, fg=up_color)
        elif status in ("stopped", "unknown"):
            card["stats_lbl"].config(text="", fg=t.text_dim)
        elif status == "scheduled":
            card["stats_lbl"].config(text="runs on schedule", fg=t.cyan)
        else:
            card["stats_lbl"].config(text="", fg=t.text_dim)
