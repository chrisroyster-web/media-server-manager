# ui/config_tab.py

import tkinter as tk
from tkinter import messagebox


class ConfigTab(tk.Frame):
    """
    Configuration tab for editing service ports, docker containers,
    storage mounts, dashboard settings, and SABnzbd credentials.
    Changes are saved to config.json and applied live without restarting.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme

        self._service_rows = []  # list of dicts: {name, unit, port, frame}
        self._docker_rows  = []  # list of dicts: {name, container, port, frame}
        self._mount_rows   = []  # list of dicts: {path, frame}

        self._build_ui()
        self._populate_from_config()

    # =========================================================
    # BUILD UI SKELETON
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # ---- Header ----
        header = tk.Frame(self, bg=t.bg)
        header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(header, text="CONFIGURATION", bg=t.bg,
                 fg=t.text, font=t.font_title).pack(side="left")

        self.save_btn = tk.Button(header, text="Save & Apply", command=self._save)
        t.style_button(self.save_btn)
        self.save_btn.pack(side="right")

        # Export / Import buttons
        import_btn = tk.Button(header, text="Import Config", command=self._import_config,
                               bg=t.surface_light, fg=t.text,
                               bd=0, relief="flat", font=t.font_small, padx=10, pady=5,
                               cursor="hand2")
        import_btn.pack(side="right", padx=(0, 6))

        export_btn = tk.Button(header, text="Export Config", command=self._export_config,
                               bg=t.surface_light, fg=t.text,
                               bd=0, relief="flat", font=t.font_small, padx=10, pady=5,
                               cursor="hand2")
        export_btn.pack(side="right", padx=(0, 6))

        self.status_lbl = tk.Label(header, text="", bg=t.bg,
                                    fg=t.text_secondary, font=t.font_small)
        self.status_lbl.pack(side="right", padx=12)

        # ---- Scrollable body ----
        self._canvas = tk.Canvas(self, bg=t.bg, highlightthickness=0)
        sb = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self._canvas, bg=t.bg)
        self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self._canvas.configure(
                           scrollregion=self._canvas.bbox("all")))

        def _mw(e):
            if e.num == 4:   self._canvas.yview_scroll(-1, "units")
            elif e.num == 5: self._canvas.yview_scroll(1,  "units")
            else:            self._canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        for w in (self._canvas, self.body):
            w.bind("<MouseWheel>", _mw)
            w.bind("<Button-4>",   _mw)
            w.bind("<Button-5>",   _mw)

        # ---- Systemd Services ----
        self._section_header("Systemd Services",
                             "Control which services are managed on the Services tab")
        self._col_header(["Name", "Systemd Unit", "Port"], [2, 3, 1])
        self.svc_body = tk.Frame(self.body, bg=t.bg)
        self.svc_body.pack(fill="x", padx=16, pady=(0, 2))
        self._add_btn("+ Add Service", self._add_service_row)

        # ---- Docker Containers ----
        self._section_header("Docker Containers",
                             "Control which containers are managed on the Docker tab")
        self._col_header(["Name", "Container", "Port"], [2, 3, 1])
        self.docker_body = tk.Frame(self.body, bg=t.bg)
        self.docker_body.pack(fill="x", padx=16, pady=(0, 2))
        self._add_btn("+ Add Container", self._add_docker_row)

        # ---- Storage Mounts ----
        self._section_header("Storage Mounts",
                             "Mount paths shown in the Dashboard storage table")
        self.mount_body = tk.Frame(self.body, bg=t.bg)
        self.mount_body.pack(fill="x", padx=16, pady=(0, 2))
        self._add_btn("+ Add Mount", self._add_mount_row)

        # ---- Dashboard ----
        self._section_header("Dashboard", "Auto-refresh interval")
        dash_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        dash_frame.pack(fill="x", padx=16, pady=(0, 8))

        tk.Label(dash_frame, text="Refresh interval (seconds):",
                 bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=4)
        self.refresh_var = tk.StringVar(value="30")
        e = tk.Entry(dash_frame, textvariable=self.refresh_var,
                     width=8, font=t.font_regular)
        t.style_entry(e)
        e.grid(row=0, column=1, sticky="w", padx=12, pady=4)

        # ---- Alert Thresholds ----
        self._section_header("Alert Thresholds",
                             "Flash a warning in the status bar when any value exceeds its limit")
        thresh_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        thresh_frame.pack(fill="x", padx=16, pady=(0, 8))

        self._thresh_vars = {}
        for row_i, (key, label, unit, default) in enumerate([
            ("cpu",  "CPU usage",    "%",  "80"),
            ("ram",  "RAM usage",    "%",  "85"),
            ("disk", "Disk usage",   "%",  "90"),
            ("temp", "CPU temp",     "°C", "85"),
        ]):
            tk.Label(thresh_frame, text=label + " alert above:",
                     bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=default)
            self._thresh_vars[key] = var
            e = tk.Entry(thresh_frame, textvariable=var, width=6, font=t.font_regular)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="w", padx=8, pady=3)
            tk.Label(thresh_frame, text=unit, bg=t.surface, fg=t.text_muted,
                     font=t.font_small).grid(row=row_i, column=2, sticky="w", pady=3)

        # ---- SABnzbd ----
        self._section_header("SABnzbd", "HTTP API credentials for the SABnzbd tab")
        sab_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        sab_frame.pack(fill="x", padx=16, pady=(0, 8))
        sab_frame.columnconfigure(1, weight=1)

        tk.Label(sab_frame, text="Port:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=4)
        self.sab_port_var = tk.StringVar()
        e_port = tk.Entry(sab_frame, textvariable=self.sab_port_var,
                          width=10, font=t.font_regular)
        t.style_entry(e_port)
        e_port.grid(row=0, column=1, sticky="w", padx=12, pady=4)

        tk.Label(sab_frame, text="API Key:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.sab_key_var = tk.StringVar()
        self._sab_key_entry = tk.Entry(sab_frame, textvariable=self.sab_key_var,
                                        show="*", font=t.font_mono)
        t.style_entry(self._sab_key_entry)
        self._sab_key_entry.grid(row=1, column=1, sticky="ew", padx=12, pady=4)

        self._show_key = False
        self._show_btn = tk.Button(
            sab_frame, text="Show",
            command=self._toggle_key,
            bg=t.surface, fg=t.blue,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.text,
        )
        self._show_btn.grid(row=1, column=2, padx=4, pady=4)

        self._sab_test_lbl = self._test_button(sab_frame, 2,
            lambda: self._test_sabnzbd())

        # ---- Emby ----
        self._section_header("Emby", "API connection for the Now Playing tab")
        emby_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        emby_frame.pack(fill="x", padx=16, pady=(0, 8))
        emby_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "emby_host_var"),
            ("Port:", "emby_port_var"),
            ("API Key:", "emby_key_var"),
        ]):
            tk.Label(emby_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "emby_key_var" else ""
            e = tk.Entry(emby_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._emby_test_lbl = self._test_button(emby_frame, 3,
            lambda: self._test_emby())

        # ---- Plex ----
        self._section_header("Plex", "API connection for the Plex Now Playing tab")
        plex_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        plex_frame.pack(fill="x", padx=16, pady=(0, 8))
        plex_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",  "plex_host_var"),
            ("Port:",  "plex_port_var"),
            ("Token:", "plex_token_var"),
        ]):
            tk.Label(plex_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "plex_token_var" else ""
            e = tk.Entry(plex_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._plex_test_lbl = self._test_button(plex_frame, 3,
            lambda: self._test_plex())

        # ---- Jellyfin ----
        self._section_header("Jellyfin", "API connection for the Jellyfin Now Playing tab")
        jf_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        jf_frame.pack(fill="x", padx=16, pady=(0, 8))
        jf_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",    "jf_host_var"),
            ("Port:",    "jf_port_var"),
            ("API Key:", "jf_key_var"),
        ]):
            tk.Label(jf_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "jf_key_var" else ""
            e = tk.Entry(jf_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._jf_test_lbl = self._test_button(jf_frame, 3,
            lambda: self._test_jellyfin())

        # ---- Sonarr ----
        self._section_header("Sonarr", "API connection for the Arr queue tab")
        sonarr_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        sonarr_frame.pack(fill="x", padx=16, pady=(0, 8))
        sonarr_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "sonarr_host_var"),
            ("Port:", "sonarr_port_var"),
            ("API Key:", "sonarr_key_var"),
        ]):
            tk.Label(sonarr_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "sonarr_key_var" else ""
            e = tk.Entry(sonarr_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._sonarr_test_lbl = self._test_button(sonarr_frame, 3,
            lambda: self._test_arr("sonarr"))

        # ---- Radarr ----
        self._section_header("Radarr", "API connection for the Arr queue tab")
        radarr_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        radarr_frame.pack(fill="x", padx=16, pady=(0, 8))
        radarr_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "radarr_host_var"),
            ("Port:", "radarr_port_var"),
            ("API Key:", "radarr_key_var"),
        ]):
            tk.Label(radarr_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "radarr_key_var" else ""
            e = tk.Entry(radarr_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._radarr_test_lbl = self._test_button(radarr_frame, 3,
            lambda: self._test_arr("radarr"))

        # ---- Notifications ----
        self._section_header("Notifications", "Alert delivery via ntfy.sh push or SMTP email")
        notif_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        notif_frame.pack(fill="x", padx=16, pady=(0, 8))
        notif_frame.columnconfigure(1, weight=1)

        # ntfy.sh
        tk.Label(notif_frame, text="ntfy.sh", bg=t.surface, fg=t.cyan,
                 font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.ntfy_enabled_var = tk.BooleanVar()
        tk.Checkbutton(notif_frame, text="Enable ntfy.sh push",
                       variable=self.ntfy_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface, font=t.font_regular).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=2)

        for row_i, (label, attr) in enumerate([
            ("Topic:",  "ntfy_topic_var"),
            ("Server:", "ntfy_server_var"),
            ("Token:",  "ntfy_token_var"),
        ], start=2):
            tk.Label(notif_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "ntfy_token_var" else ""
            e = tk.Entry(notif_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=3)

        # Divider
        tk.Frame(notif_frame, bg=t.card_border, height=1).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=8)

        # Email
        tk.Label(notif_frame, text="Email (SMTP)", bg=t.surface, fg=t.cyan,
                 font=("Segoe UI", 10, "bold")).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.email_enabled_var = tk.BooleanVar()
        tk.Checkbutton(notif_frame, text="Enable email alerts",
                       variable=self.email_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface, font=t.font_regular).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=2)

        for row_i, (label, attr) in enumerate([
            ("To:",          "email_to_var"),
            ("SMTP Host:",   "smtp_host_var"),
            ("SMTP Port:",   "smtp_port_var"),
            ("SMTP User:",   "smtp_user_var"),
            ("SMTP Pass:",   "smtp_pass_var"),
        ], start=8):
            tk.Label(notif_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "smtp_pass_var" else ""
            e = tk.Entry(notif_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=3)

        # Bottom spacer
        tk.Frame(self.body, bg=t.bg, height=40).pack()

    # =========================================================
    # SECTION / COLUMN HELPERS
    # =========================================================
    def _section_header(self, title, subtitle=""):
        t = self.theme
        wrap = tk.Frame(self.body, bg=t.bg)
        wrap.pack(fill="x", padx=16, pady=(20, 4))
        tk.Frame(wrap, bg=t.blue, height=2).pack(fill="x")
        tk.Label(wrap, text=title, bg=t.bg, fg=t.text,
                 font=t.font_title).pack(anchor="w", pady=(4, 0))
        if subtitle:
            tk.Label(wrap, text=subtitle, bg=t.bg, fg=t.text_muted,
                     font=t.font_small).pack(anchor="w")

    def _col_header(self, cols, weights):
        t = self.theme
        hdr = tk.Frame(self.body, bg=t.surface_dark)
        hdr.pack(fill="x", padx=16)
        for i, (col, w) in enumerate(zip(cols, weights)):
            tk.Label(hdr, text=col, bg=t.surface_dark, fg=t.text_muted,
                     font=t.font_small, anchor="w").grid(
                row=0, column=i, sticky="ew", padx=10, pady=4)
            hdr.columnconfigure(i, weight=w)

    def _add_btn(self, text, cmd):
        t = self.theme
        tk.Button(
            self.body, text=text, command=cmd,
            bg=t.bg, fg=t.blue,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.blue,
            cursor="hand2",
        ).pack(anchor="w", padx=16, pady=(2, 6))

    # =========================================================
    # POPULATE FROM CONFIG
    # =========================================================
    def _populate_from_config(self):
        cfg = self.controller.config_manager

        # Services
        for name, data in cfg.get_services().items():
            self._add_service_row(name, data["service"], data.get("port", ""))

        # Docker
        for name, data in cfg.get_docker().items():
            self._add_docker_row(name, data["container"], data.get("port", ""))

        # Storage mounts
        for mount in cfg.get_storage_mounts():
            self._add_mount_row(mount)

        # Dashboard
        self.refresh_var.set(str(cfg.dashboard_refresh_interval))

        # Alert thresholds
        thresholds = cfg.get_thresholds()
        for key, var in self._thresh_vars.items():
            var.set(str(thresholds.get(key, 80)))

        # SABnzbd
        self.sab_port_var.set(cfg.sabnzbd_port)
        self.sab_key_var.set(cfg.sabnzbd_apikey)

        # Emby
        self.emby_host_var.set(cfg.emby_host)
        self.emby_port_var.set(cfg.emby_port)
        self.emby_key_var.set(cfg.emby_apikey)

        # Plex
        self.plex_host_var.set(cfg.plex_host)
        self.plex_port_var.set(cfg.plex_port)
        self.plex_token_var.set(cfg.plex_token)

        # Jellyfin
        self.jf_host_var.set(cfg.jellyfin_host)
        self.jf_port_var.set(cfg.jellyfin_port)
        self.jf_key_var.set(cfg.jellyfin_apikey)

        # Sonarr
        self.sonarr_host_var.set(cfg.sonarr_host)
        self.sonarr_port_var.set(cfg.sonarr_port)
        self.sonarr_key_var.set(cfg.sonarr_apikey)

        # Radarr
        self.radarr_host_var.set(cfg.radarr_host)
        self.radarr_port_var.set(cfg.radarr_port)
        self.radarr_key_var.set(cfg.radarr_apikey)

        # Notifications
        self.ntfy_enabled_var.set(cfg.notify_ntfy_enabled)
        self.ntfy_topic_var.set(cfg.notify_ntfy_topic)
        self.ntfy_server_var.set(cfg.notify_ntfy_server)
        self.ntfy_token_var.set(cfg.notify_ntfy_token)
        self.email_enabled_var.set(cfg.notify_email_enabled)
        self.email_to_var.set(cfg.notify_email_to)
        self.smtp_host_var.set(cfg.notify_smtp_host)
        self.smtp_port_var.set(cfg.notify_smtp_port)
        self.smtp_user_var.set(cfg.notify_smtp_user)
        self.smtp_pass_var.set(cfg.notify_smtp_pass)

    # =========================================================
    # ROW BUILDERS
    # =========================================================
    def _add_service_row(self, name="", unit="", port=""):
        t = self.theme
        row = {
            "name": tk.StringVar(value=name),
            "unit": tk.StringVar(value=unit),
            "port": tk.StringVar(value=str(port) if port else ""),
        }
        frame = tk.Frame(self.svc_body, bg=t.card_bg,
                         highlightbackground=t.card_border, highlightthickness=1)
        frame.pack(fill="x", pady=1)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(2, weight=1)

        e_name = tk.Entry(frame, textvariable=row["name"], font=t.font_regular)
        t.style_entry(e_name)
        e_name.grid(row=0, column=0, sticky="ew", padx=(6, 3), pady=4)

        e_unit = tk.Entry(frame, textvariable=row["unit"], font=t.font_mono)
        t.style_entry(e_unit)
        e_unit.grid(row=0, column=1, sticky="ew", padx=3, pady=4)

        e_port = tk.Entry(frame, textvariable=row["port"], font=t.font_regular, width=8)
        t.style_entry(e_port)
        e_port.grid(row=0, column=2, sticky="ew", padx=3, pady=4)

        tk.Button(
            frame, text="✕",
            command=lambda r=row: self._del_row(r, self._service_rows),
            bg=t.card_bg, fg=t.status_stopped,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.status_stopped,
            cursor="hand2",
        ).grid(row=0, column=3, padx=(3, 6), pady=4)

        row["frame"] = frame
        self._service_rows.append(row)
        self._scroll_bottom()

    def _add_docker_row(self, name="", container="", port=""):
        t = self.theme
        row = {
            "name":      tk.StringVar(value=name),
            "container": tk.StringVar(value=container),
            "port":      tk.StringVar(value=str(port) if port else ""),
        }
        frame = tk.Frame(self.docker_body, bg=t.card_bg,
                         highlightbackground=t.card_border, highlightthickness=1)
        frame.pack(fill="x", pady=1)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(2, weight=1)

        e_name = tk.Entry(frame, textvariable=row["name"], font=t.font_regular)
        t.style_entry(e_name)
        e_name.grid(row=0, column=0, sticky="ew", padx=(6, 3), pady=4)

        e_ctr = tk.Entry(frame, textvariable=row["container"], font=t.font_mono)
        t.style_entry(e_ctr)
        e_ctr.grid(row=0, column=1, sticky="ew", padx=3, pady=4)

        e_port = tk.Entry(frame, textvariable=row["port"], font=t.font_regular, width=8)
        t.style_entry(e_port)
        e_port.grid(row=0, column=2, sticky="ew", padx=3, pady=4)

        tk.Button(
            frame, text="✕",
            command=lambda r=row: self._del_row(r, self._docker_rows),
            bg=t.card_bg, fg=t.status_stopped,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.status_stopped,
            cursor="hand2",
        ).grid(row=0, column=3, padx=(3, 6), pady=4)

        row["frame"] = frame
        self._docker_rows.append(row)
        self._scroll_bottom()

    def _add_mount_row(self, path=""):
        t = self.theme
        row = {"path": tk.StringVar(value=path)}
        frame = tk.Frame(self.mount_body, bg=t.card_bg,
                         highlightbackground=t.card_border, highlightthickness=1)
        frame.pack(fill="x", pady=1)
        frame.columnconfigure(0, weight=1)

        e_path = tk.Entry(frame, textvariable=row["path"], font=t.font_mono)
        t.style_entry(e_path)
        e_path.grid(row=0, column=0, sticky="ew", padx=(6, 3), pady=4)

        tk.Button(
            frame, text="✕",
            command=lambda r=row: self._del_row(r, self._mount_rows),
            bg=t.card_bg, fg=t.status_stopped,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.status_stopped,
            cursor="hand2",
        ).grid(row=0, column=1, padx=(3, 6), pady=4)

        row["frame"] = frame
        self._mount_rows.append(row)
        self._scroll_bottom()

    def _del_row(self, row, row_list):
        row["frame"].destroy()
        if row in row_list:
            row_list.remove(row)

    def _scroll_bottom(self):
        self.body.update_idletasks()
        self._canvas.yview_moveto(1.0)

    # =========================================================
    # API KEY TOGGLE
    # =========================================================
    def _toggle_key(self):
        self._show_key = not self._show_key
        self._sab_key_entry.config(show="" if self._show_key else "*")
        self._show_btn.config(text="Hide" if self._show_key else "Show")

    # =========================================================
    # SAVE
    # =========================================================
    def _save(self):
        self.save_btn.config(state="disabled", text="Saving...")

        # --- Collect services ---
        services = {}
        for row in self._service_rows:
            name = row["name"].get().strip()
            unit = row["unit"].get().strip()
            port = row["port"].get().strip()
            if name and unit:
                try:
                    port_val = int(port) if port else None
                except ValueError:
                    port_val = None
                services[name] = {"service": unit, "port": port_val}

        # --- Collect docker ---
        docker = {}
        for row in self._docker_rows:
            name      = row["name"].get().strip()
            container = row["container"].get().strip()
            port      = row["port"].get().strip()
            if name and container:
                try:
                    port_val = int(port) if port else None
                except ValueError:
                    port_val = None
                docker[name] = {"container": container, "port": port_val}

        # --- Collect mounts ---
        mounts = [r["path"].get().strip() for r in self._mount_rows
                  if r["path"].get().strip()]

        # --- Dashboard refresh ---
        try:
            refresh = int(self.refresh_var.get())
            if refresh < 5:
                refresh = 5
        except ValueError:
            refresh = 30

        # --- Alert thresholds ---
        thresholds = {}
        defaults = {"cpu": 80, "ram": 85, "disk": 90, "temp": 85}
        for key, var in self._thresh_vars.items():
            try:
                thresholds[key] = int(var.get())
            except ValueError:
                thresholds[key] = defaults.get(key, 80)

        # --- SABnzbd ---
        sab_port = self.sab_port_var.get().strip() or "8080"
        sab_key  = self.sab_key_var.get().strip()

        # --- Emby ---
        emby_host = self.emby_host_var.get().strip() or "localhost"
        emby_port = self.emby_port_var.get().strip() or "8096"
        emby_key  = self.emby_key_var.get().strip()

        # --- Plex ---
        plex_host  = self.plex_host_var.get().strip() or "localhost"
        plex_port  = self.plex_port_var.get().strip() or "32400"
        plex_token = self.plex_token_var.get().strip()

        # --- Jellyfin ---
        jf_host = self.jf_host_var.get().strip() or "localhost"
        jf_port = self.jf_port_var.get().strip() or "8096"
        jf_key  = self.jf_key_var.get().strip()

        # --- Sonarr ---
        sonarr_host = self.sonarr_host_var.get().strip() or "localhost"
        sonarr_port = self.sonarr_port_var.get().strip() or "8989"
        sonarr_key  = self.sonarr_key_var.get().strip()


        # --- Radarr ---
        radarr_host = self.radarr_host_var.get().strip() or "localhost"
        radarr_port = self.radarr_port_var.get().strip() or "7878"
        radarr_key  = self.radarr_key_var.get().strip()

        # --- Notifications ---
        notify_ntfy_enabled  = self.ntfy_enabled_var.get()
        notify_ntfy_topic    = self.ntfy_topic_var.get().strip()
        notify_ntfy_server   = self.ntfy_server_var.get().strip() or "https://ntfy.sh"
        notify_ntfy_token    = self.ntfy_token_var.get().strip()
        notify_email_enabled = self.email_enabled_var.get()
        notify_email_to      = self.email_to_var.get().strip()
        notify_smtp_host     = self.smtp_host_var.get().strip()
        notify_smtp_port     = self.smtp_port_var.get().strip() or "587"
        notify_smtp_user     = self.smtp_user_var.get().strip()
        notify_smtp_pass     = self.smtp_pass_var.get().strip()

        # --- Persist ---
        cfg = self.controller.config_manager
        # Batch all updates into the in-memory config, then write once
        cfg.config["services"]                  = services
        cfg.config["docker"]                    = docker
        cfg.config["storage_mounts"]            = mounts
        cfg.config["thresholds"]                = thresholds
        cfg.config["dashboard_refresh_interval"] = refresh
        cfg.config["sabnzbd_port"]              = sab_port
        cfg.config["sabnzbd_apikey"]            = sab_key
        cfg.config["emby_host"]                 = emby_host
        cfg.config["emby_port"]                 = emby_port
        cfg.config["emby_apikey"]               = emby_key
        cfg.config["plex_host"]                 = plex_host
        cfg.config["plex_port"]                 = plex_port
        cfg.config["plex_token"]                = plex_token
        cfg.config["jellyfin_host"]             = jf_host
        cfg.config["jellyfin_port"]             = jf_port
        cfg.config["jellyfin_apikey"]           = jf_key
        cfg.config["sonarr_host"]               = sonarr_host
        cfg.config["sonarr_port"]               = sonarr_port
        cfg.config["sonarr_apikey"]             = sonarr_key
        cfg.config["radarr_host"]               = radarr_host
        cfg.config["radarr_port"]               = radarr_port
        cfg.config["radarr_apikey"]             = radarr_key
        cfg.config["notify_ntfy_enabled"]       = notify_ntfy_enabled
        cfg.config["notify_ntfy_topic"]         = notify_ntfy_topic
        cfg.config["notify_ntfy_server"]        = notify_ntfy_server
        cfg.config["notify_ntfy_token"]         = notify_ntfy_token
        cfg.config["notify_email_enabled"]      = notify_email_enabled
        cfg.config["notify_email_to"]           = notify_email_to
        cfg.config["notify_smtp_host"]          = notify_smtp_host
        cfg.config["notify_smtp_port"]          = notify_smtp_port
        cfg.config["notify_smtp_user"]          = notify_smtp_user
        cfg.config["notify_smtp_pass"]          = notify_smtp_pass
        cfg.save()   # single write to disk

        self.controller.apply_config()
        self.save_btn.config(state="normal", text="Save & Apply")
        self._show_saved_banner()

    def _show_saved_banner(self):
        t = self.controller.theme
        banner = tk.Label(
            self, text="✓  Settings saved",
            bg=t.status_running, fg="#000000",
            font=t.font_small, padx=12, pady=4,
        )
        banner.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=48)
        self.after(2500, banner.destroy)

    # ------------------------------------------------------------------
    # TEST CONNECTION HELPERS
    # ------------------------------------------------------------------
    def _test_button(self, parent, row, command):
        """Add a Test Connection button + result label at given grid row."""
        t = self.controller.theme
        btn = tk.Button(
            parent,
            text="Test Connection",
            command=command,
            bg=t.surface_light, fg=t.blue,
            bd=0, relief="flat",
            font=t.font_small, padx=10, pady=4,
            cursor="hand2",
        )
        btn.grid(row=row, column=0, sticky="w", pady=(8, 2))
        btn.bind("<Enter>", lambda e: btn.configure(fg=t.blue_bright))
        btn.bind("<Leave>", lambda e: btn.configure(fg=t.blue))

        result_lbl = tk.Label(
            parent, text="",
            bg=t.surface, fg=t.text_muted,
            font=t.font_small,
        )
        result_lbl.grid(row=row, column=1, sticky="w", padx=12, pady=(8, 2))
        return result_lbl

    def _set_test_result(self, lbl, ok, msg):
        t = self.controller.theme
        lbl.configure(
            text=("✓  " if ok else "✗  ") + msg,
            fg=t.status_running if ok else t.status_stopped,
        )

    def _test_arr(self, app):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._sonarr_test_lbl if app == "sonarr" else self._radarr_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = (self.sonarr_host_var if app == "sonarr" else self.radarr_host_var).get().strip()
        port = (self.sonarr_port_var if app == "sonarr" else self.radarr_port_var).get().strip()
        key  = (self.sonarr_key_var  if app == "sonarr" else self.radarr_key_var).get().strip()
        host = host.removeprefix("https://").removeprefix("http://").strip("/")

        def _run():
            try:
                url = "http://{}:{}/api/v3/system/status".format(host, port)
                req = urllib.request.Request(url, headers={"X-Api-Key": key})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_sabnzbd(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._sab_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        cfg = self.controller.config_manager
        host = cfg.last_host or "localhost"
        port = self.sab_port_var.get().strip() or "8080"
        key  = self.sab_key_var.get().strip()

        def _run():
            try:
                url = "http://{}:{}/sabnzbd/api?mode=version&apikey={}&output=json".format(
                    host, port, key)
                with urllib.request.urlopen(url, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_emby(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._emby_test_lbl
        lbl.configure(text="Testing...", fg=self.controller.theme.text_muted)
        host = self.emby_host_var.get().strip() or "localhost"
        port = self.emby_port_var.get().strip() or "8096"
        key  = self.emby_key_var.get().strip()
        result = [None]  # thread writes here; main thread polls

        def _run():
            try:
                # /System/Ping needs no auth - confirms host:port is reachable
                ping = "http://{}:{}/emby/System/Ping".format(host, port)
                urllib.request.urlopen(ping, timeout=8)
                # Now validate the API key
                info = "http://{}:{}/emby/System/Info".format(host, port)
                req = urllib.request.Request(
                    info,
                    headers={"X-Emby-Token": key, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                ver = data.get("Version", "?")
                result[0] = ("ok", "Connected  \xc2\xb7  v{}".format(ver))
            except Exception as e:
                result[0] = ("err", str(e)[:70])

        def _poll():
            if result[0] is None:
                lbl.after(200, _poll)
                return
            status, msg = result[0]
            if status == "ok":
                self._set_test_result(lbl, True, msg)
            else:
                self._set_test_result(lbl, False, msg)

        import threading
        threading.Thread(target=_run, daemon=True).start()
        lbl.after(200, _poll)


    def _test_plex(self):
        import threading, urllib.request, json as _json
        lbl = self._plex_test_lbl
        lbl.configure(text="Testing...", fg=self.controller.theme.text_muted)
        host  = self.plex_host_var.get().strip() or "localhost"
        port  = self.plex_port_var.get().strip() or "32400"
        token = self.plex_token_var.get().strip()
        result = [None]

        def _run():
            try:
                url = "http://{}:{}/".format(host, port)
                req = urllib.request.Request(url, headers={
                    "X-Plex-Token": token, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                ver = (data.get("MediaContainer") or {}).get("version", "?")
                result[0] = ("ok", "Connected  \xb7  v{}".format(ver))
            except Exception as e:
                result[0] = ("err", str(e)[:70])

        def _poll():
            if result[0] is None:
                lbl.after(200, _poll)
                return
            status, msg = result[0]
            self._set_test_result(lbl, status == "ok", msg)

        threading.Thread(target=_run, daemon=True).start()
        lbl.after(200, _poll)

    def _test_jellyfin(self):
        import threading, urllib.request, json as _json
        lbl = self._jf_test_lbl
        lbl.configure(text="Testing...", fg=self.controller.theme.text_muted)
        host = self.jf_host_var.get().strip() or "localhost"
        port = self.jf_port_var.get().strip() or "8096"
        key  = self.jf_key_var.get().strip()
        result = [None]

        def _run():
            try:
                ping = "http://{}:{}/health".format(host, port)
                urllib.request.urlopen(ping, timeout=8)
                info = "http://{}:{}/System/Info".format(host, port)
                req = urllib.request.Request(
                    info, headers={"X-Emby-Token": key, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                ver = data.get("Version", "?")
                result[0] = ("ok", "Connected  \xb7  v{}".format(ver))
            except Exception as e:
                result[0] = ("err", str(e)[:70])

        def _poll():
            if result[0] is None:
                lbl.after(200, _poll)
                return
            status, msg = result[0]
            self._set_test_result(lbl, status == "ok", msg)

        threading.Thread(target=_run, daemon=True).start()
        lbl.after(200, _poll)

    def _export_config(self):
        import json, tkinter.filedialog as fd
        path = fd.asksaveasfilename(
            title="Export Config",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="media_server_manager_config.json",
        )
        if not path:
            return
        try:
            cfg = self.controller.config_manager
            data = dict(cfg.config)
            with open(path, "w", encoding="utf-8") as f:
                import json as _j
                _j.dump(data, f, indent=2)
            self.status_lbl.config(
                text="Config exported to {}".format(path.split("/")[-1].split("\\")[-1]),
                fg=self.controller.theme.status_running)
        except Exception as e:
            self.status_lbl.config(
                text="Export failed: {}".format(str(e)[:60]),
                fg=self.controller.theme.status_stopped)

    def _import_config(self):
        import json, tkinter.filedialog as fd, tkinter.messagebox as mb
        path = fd.askopenfilename(
            title="Import Config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json as _j
                data = _j.load(f)
            if not isinstance(data, dict):
                raise ValueError("File does not contain a JSON object.")
            ok = mb.askyesno(
                "Import Config",
                "This will overwrite your current configuration.\nContinue?",
            )
            if not ok:
                return
            cfg = self.controller.config_manager
            cfg.config.update(data)
            cfg.save()
            self._load_values()
            self.status_lbl.config(
                text="Config imported - review and click Save & Apply",
                fg=self.controller.theme.yellow)
        except Exception as e:
            self.status_lbl.config(
                text="Import failed: {}".format(str(e)[:60]),
                fg=self.controller.theme.status_stopped)
