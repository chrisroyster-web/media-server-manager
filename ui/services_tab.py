# ui/services_tab.py

import tkinter as tk
from tkinter import messagebox
import threading
import webbrowser
import shlex

from ui.base_tab import CardConsoleTab
from ui.log_tail_window import LogTailWindow


class ServicesTab(CardConsoleTab):
    """
    Systemd service cards with embedded output console.
    Inherits layout, mousewheel scrolling, and console from CardConsoleTab.
    Service config is loaded from ConfigManager so the Config tab can update it live.
    """

    TITLE = "SERVICES"

    # Class-level fallback (kept for backward compat; overridden per-instance from config)
    SYSTEMD_SERVICES = {
        "Emby":     {"service": "emby-server",  "port": 8096},
        "Sonarr":   {"service": "sonarr",        "port": 8989},
        "Radarr":   {"service": "radarr",        "port": 7878},
        "Prowlarr": {"service": "prowlarr",      "port": 9797},
        "Bazarr":   {"service": "bazarr",        "port": 6767},
        "SABnzbd":  {"service": "sabnzbdplus",   "port": 8080},
    }

    def __init__(self, parent, controller):
        # Load from config BEFORE super().__init__() which calls _populate_cards()
        self.services = controller.config_manager.get_services()
        ServicesTab.SYSTEMD_SERVICES = self.services  # keep class var in sync
        super().__init__(parent, controller)

    def _host(self):
        return self.controller.config_manager.last_host or "localhost"

    def _url(self, port):
        return "http://{0}:{1}".format(self._host(), port)

    # ---------------------------------------------------------
    # POPULATE CARDS  (2-column grid)
    # ---------------------------------------------------------
    COLS = 2

    def _populate_cards(self):
        for c in range(self.COLS):
            self.inner.columnconfigure(c, weight=1, uniform="svc")
        for i, (name, data) in enumerate(self.services.items()):
            row, col = divmod(i, self.COLS)
            self.cards[name] = self._create_card(name, data, row, col)

    def _create_card(self, name, data, grid_row=0, grid_col=0):
        frame = tk.Frame(
            self.inner,
            bg=self.theme.card_bg,
            highlightbackground=self.theme.card_border,
            highlightthickness=1,
        )
        frame.grid(row=grid_row, column=grid_col, padx=8, pady=6, sticky="nsew")
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

        port = data["port"]
        url_lbl = tk.Label(
            frame, text=self._url(port) if port else "--",
            bg=self.theme.card_bg, fg=self.theme.blue,
            font=self.theme.font_small, cursor="hand2" if port else "",
        )
        url_lbl.pack(anchor="w", padx=10)
        if port:
            url_lbl.bind("<Button-1>", lambda e, p=port: webbrowser.open(self._url(p)))
        self._bind_mousewheel(url_lbl)

        btn_row = tk.Frame(frame, bg=self.theme.card_bg)
        btn_row.pack(fill="x", pady=6)
        self._bind_mousewheel(btn_row)

        for label, action in [
            ("Start", "start"), ("Stop", "stop"), ("Restart", "restart"),
            ("Logs", "logs"), ("Tail", "tail"), ("Status", "status"),
        ]:
            btn = tk.Button(btn_row, text=label,
                            command=lambda a=action, n=name: self._action(n, a))
            self.theme.style_button(btn)
            btn.pack(side="left", padx=4)

        return {"frame": frame, "dot": dot, "status_lbl": status_lbl,
                "url_lbl": url_lbl, "service": data["service"], "port": port}

    # ---------------------------------------------------------
    # ACTIONS
    # ---------------------------------------------------------
    def _action(self, name, action):
        svc = self.cards[name]["service"]
        if action in ("stop", "restart"):
            verb = "Stop" if action == "stop" else "Restart"
            if not messagebox.askyesno(
                    "{} Service".format(verb),
                    "{} '{}' ({})?".format(verb, name, svc),
                    parent=self):
                return
        self._log("{0} {1}".format(action.upper(), svc), "cmd")

        def worker():
            sm = self.controller.service_manager
            if action == "tail":
                cmd = "journalctl -fu {} --no-pager".format(shlex.quote(svc))
                self.after(0, lambda: LogTailWindow(
                    self.controller,
                    title="journalctl -fu {}".format(svc),
                    cmd=cmd,
                ))
                return
            if   action == "start":   result = sm.start(svc)
            elif action == "stop":    result = sm.stop(svc)
            elif action == "restart": result = sm.restart(svc)
            elif action == "logs":    result = sm.logs(svc)
            elif action == "status":  result = sm.full_status(svc)
            else: return
            out, err, code = result
            if action in ("start", "stop", "restart"):
                self.controller.audit_log(
                    "service.{}".format(action), svc,
                    detail=(err or out or "").strip()[:200],
                    result="ok" if code == 0 else "fail")
            self._log_output("{0} {1}".format(name, action), out, err, code)
            if code != 0:
                self.after(0, lambda n=name, a=action, c=code: (
                    self.controller.show_toast(
                        f"{a.title()} failed — {n}",
                        (err or out or "").strip().splitlines()[-1] if (err or out or "").strip() else f"exit {c}",
                        level="error",
                    )
                ))
            self.after(0, self.refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------
    # REFRESH
    # ---------------------------------------------------------
    def refresh_all(self):
        for card in self.cards.values():
            if card["port"]:
                card["url_lbl"].config(text=self._url(card["port"]))

        def worker():
            sm = self.controller.service_manager
            names = {name: card["service"] for name, card in self.cards.items()}
            statuses = sm.get_statuses(list(names.values()))
            for name, service in names.items():
                status = statuses.get(service, "unknown")
                self.after(0, lambda n=name, s=status: self._update_card(n, s))

        threading.Thread(target=worker, daemon=True).start()

    def _update_card(self, name, status):
        card = self.cards[name]
        card["status_lbl"].config(text=status)
        dot = card["dot"]
        dot.delete("all")
        if   status == "running":             color = self.theme.status_running
        elif status in ("stopped", "failed"): color = self.theme.status_stopped
        else:                                 color = self.theme.status_unknown
        dot.create_oval(2, 2, 12, 12, fill=color, outline=color)
