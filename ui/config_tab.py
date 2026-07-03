# ui/config_tab.py

import tkinter as tk
from tkinter import messagebox, ttk
import time


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
        self._alert_rules  = []  # list of rule dicts (in-memory, saved on Save)

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
                             "Status cards shown on the Dashboard and checked on the Updates tab")
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

        tk.Label(dash_frame, text="Metrics retention (days):",
                 bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.retention_var = tk.StringVar(value="30")
        e2 = tk.Entry(dash_frame, textvariable=self.retention_var,
                      width=8, font=t.font_regular)
        t.style_entry(e2)
        e2.grid(row=1, column=1, sticky="w", padx=12, pady=4)
        tk.Label(dash_frame, text="(SQLite history for charts and notifications)",
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small).grid(row=1, column=2, sticky="w", padx=4)

        # ---- Alert Rules ----
        self._section_header("Alert Rules",
                             "Fire notifications when server metrics cross thresholds")
        rules_outer = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        rules_outer.pack(fill="x", padx=16, pady=(0, 8))

        # "+ Add Rule" button row
        add_row = tk.Frame(rules_outer, bg=t.surface)
        add_row.pack(fill="x", pady=(0, 8))
        add_btn = tk.Button(add_row, text="+ Add Rule",
                            command=self._add_rule,
                            bg=t.blue, fg="#ffffff",
                            bd=0, relief="flat",
                            font=t.font_small, padx=12, pady=4, cursor="hand2")
        add_btn.pack(side="left")

        # Container for rule rows (rebuilt by _redraw_rule_rows)
        self._rules_container = tk.Frame(rules_outer, bg=t.surface)
        self._rules_container.pack(fill="x")

        # ---- SABnzbd ----
        self._section_header("SABnzbd", "HTTP API credentials for the SABnzbd tab")
        sab_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        sab_frame.pack(fill="x", padx=16, pady=(0, 8))
        sab_frame.columnconfigure(1, weight=1)

        tk.Label(sab_frame, text="Host:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=4)
        self.sab_host_var = tk.StringVar()
        e_host = tk.Entry(sab_frame, textvariable=self.sab_host_var, font=t.font_regular)
        t.style_entry(e_host)
        e_host.grid(row=0, column=1, sticky="ew", padx=12, pady=4)

        tk.Label(sab_frame, text="Port:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.sab_port_var = tk.StringVar()
        e_port = tk.Entry(sab_frame, textvariable=self.sab_port_var,
                          width=10, font=t.font_regular)
        t.style_entry(e_port)
        e_port.grid(row=1, column=1, sticky="w", padx=12, pady=4)

        tk.Label(sab_frame, text="API Key:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=2, column=0, sticky="w", pady=4)
        self.sab_key_var = tk.StringVar()
        self._sab_key_entry = tk.Entry(sab_frame, textvariable=self.sab_key_var,
                                        show="*", font=t.font_mono)
        t.style_entry(self._sab_key_entry)
        self._sab_key_entry.grid(row=2, column=1, sticky="ew", padx=12, pady=4)

        self._show_key = False
        self._show_btn = tk.Button(
            sab_frame, text="Show",
            command=self._toggle_key,
            bg=t.surface, fg=t.blue,
            font=t.font_small, bd=0, relief="flat",
            activebackground=t.surface, activeforeground=t.text,
        )
        self._show_btn.grid(row=2, column=2, padx=4, pady=4)

        self._sab_test_lbl = self._test_button(sab_frame, 3,
            lambda: self._test_sabnzbd())

        # ---- qBittorrent ----
        self._section_header("qBittorrent", "HTTP credentials for the qBittorrent tab (Web API v2)")
        qb_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        qb_frame.pack(fill="x", padx=16, pady=(0, 8))
        qb_frame.columnconfigure(1, weight=1)

        tk.Label(qb_frame, text="Host:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=4)
        self.qb_host_var = tk.StringVar()
        e_qb_host = tk.Entry(qb_frame, textvariable=self.qb_host_var, font=t.font_regular)
        t.style_entry(e_qb_host)
        e_qb_host.grid(row=0, column=1, sticky="ew", padx=12, pady=4)

        tk.Label(qb_frame, text="Port:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.qb_port_var = tk.StringVar()
        e_qb_port = tk.Entry(qb_frame, textvariable=self.qb_port_var,
                             width=10, font=t.font_regular)
        t.style_entry(e_qb_port)
        e_qb_port.grid(row=1, column=1, sticky="w", padx=12, pady=4)

        tk.Label(qb_frame, text="Username:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=2, column=0, sticky="w", pady=4)
        self.qb_user_var = tk.StringVar()
        e_qb_user = tk.Entry(qb_frame, textvariable=self.qb_user_var, font=t.font_regular)
        t.style_entry(e_qb_user)
        e_qb_user.grid(row=2, column=1, sticky="ew", padx=12, pady=4)

        tk.Label(qb_frame, text="Password:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=3, column=0, sticky="w", pady=4)
        self.qb_pass_var = tk.StringVar()
        e_qb_pass = tk.Entry(qb_frame, textvariable=self.qb_pass_var,
                             show="*", font=t.font_regular)
        t.style_entry(e_qb_pass)
        e_qb_pass.grid(row=3, column=1, sticky="ew", padx=12, pady=4)

        self._qb_test_lbl = self._test_button(qb_frame, 4,
            lambda: self._test_qbittorrent())

        # ---- Pi-hole / AdGuard Home ----
        self._section_header("Pi-hole / AdGuard Home",
                             "DNS ad-blocking dashboard — choose type below")
        ph_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        ph_frame.pack(fill="x", padx=16, pady=(0, 8))
        ph_frame.columnconfigure(1, weight=1)

        tk.Label(ph_frame, text="Type:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=4)
        self.ph_type_var = tk.StringVar(value="pihole")
        type_menu = tk.OptionMenu(ph_frame, self.ph_type_var, "pihole", "adguard")
        type_menu.config(bg=t.surface, fg=t.text, relief="flat",
                         font=t.font_regular, bd=0, highlightthickness=0,
                         activebackground=t.surface_light, activeforeground=t.text)
        type_menu["menu"].config(bg=t.surface, fg=t.text, font=t.font_regular)
        type_menu.grid(row=0, column=1, sticky="w", padx=12, pady=4)

        tk.Label(ph_frame, text="Host:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.ph_host_var = tk.StringVar()
        e_ph_host = tk.Entry(ph_frame, textvariable=self.ph_host_var, font=t.font_regular)
        t.style_entry(e_ph_host)
        e_ph_host.grid(row=1, column=1, sticky="ew", padx=12, pady=4)

        tk.Label(ph_frame, text="Port:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=2, column=0, sticky="w", pady=4)
        self.ph_port_var = tk.StringVar(value="80")
        e_ph_port = tk.Entry(ph_frame, textvariable=self.ph_port_var,
                             width=10, font=t.font_regular)
        t.style_entry(e_ph_port)
        e_ph_port.grid(row=2, column=1, sticky="w", padx=12, pady=4)

        tk.Label(ph_frame, text="API Key / Password:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=3, column=0, sticky="w", pady=4)
        self.ph_apikey_var = tk.StringVar()
        e_ph_key = tk.Entry(ph_frame, textvariable=self.ph_apikey_var,
                            show="*", font=t.font_regular)
        t.style_entry(e_ph_key)
        e_ph_key.grid(row=3, column=1, sticky="ew", padx=12, pady=4)
        tk.Label(ph_frame, text="(Pi-hole: API key  /  AdGuard: password)",
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small).grid(row=3, column=2, sticky="w", padx=4)

        tk.Label(ph_frame, text="Username:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=4, column=0, sticky="w", pady=4)
        self.ph_pass_var = tk.StringVar()
        e_ph_pass = tk.Entry(ph_frame, textvariable=self.ph_pass_var,
                             font=t.font_regular)
        t.style_entry(e_ph_pass)
        e_ph_pass.grid(row=4, column=1, sticky="ew", padx=12, pady=4)
        tk.Label(ph_frame, text="(AdGuard only, default: admin)", bg=t.surface, fg=t.text_muted,
                 font=t.font_small).grid(row=4, column=2, sticky="w", padx=4)

        self._ph_test_lbl = self._test_button(ph_frame, 5,
            lambda: self._test_pihole())

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
            if show == "*":
                self._eye_btn(emby_frame, e, row_i)

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
            if show == "*":
                self._eye_btn(plex_frame, e, row_i)

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
            if show == "*":
                self._eye_btn(jf_frame, e, row_i)

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
            if show == "*":
                self._eye_btn(sonarr_frame, e, row_i)

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
            if show == "*":
                self._eye_btn(radarr_frame, e, row_i)

        self._radarr_test_lbl = self._test_button(radarr_frame, 3,
            lambda: self._test_arr("radarr"))

        # ---- Prowlarr ----
        self._section_header("Prowlarr", "API connection for the Prowlarr indexer tab")
        prowlarr_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        prowlarr_frame.pack(fill="x", padx=16, pady=(0, 8))
        prowlarr_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",    "prowlarr_host_var"),
            ("Port:",    "prowlarr_port_var"),
            ("API Key:", "prowlarr_key_var"),
        ]):
            tk.Label(prowlarr_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "prowlarr_key_var" else ""
            e = tk.Entry(prowlarr_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(prowlarr_frame, e, row_i)

        self._prowlarr_test_lbl = self._test_button(prowlarr_frame, 3,
            lambda: self._test_arr("prowlarr"))

        # ---- Overseerr ----
        self._section_header("Overseerr", "API connection for the Overseerr requests tab")
        overseerr_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        overseerr_frame.pack(fill="x", padx=16, pady=(0, 8))
        overseerr_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",    "overseerr_host_var"),
            ("Port:",    "overseerr_port_var"),
            ("API Key:", "overseerr_key_var"),
        ]):
            tk.Label(overseerr_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "overseerr_key_var" else ""
            e = tk.Entry(overseerr_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(overseerr_frame, e, row_i)

        self._overseerr_test_lbl = self._test_button(overseerr_frame, 3,
            lambda: self._test_seerr("overseerr"))

        # ---- Jellyseerr ----
        self._section_header("Jellyseerr", "API connection for the Jellyseerr requests tab")
        jellyseerr_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        jellyseerr_frame.pack(fill="x", padx=16, pady=(0, 8))
        jellyseerr_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",    "jellyseerr_host_var"),
            ("Port:",    "jellyseerr_port_var"),
            ("API Key:", "jellyseerr_key_var"),
        ]):
            tk.Label(jellyseerr_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "jellyseerr_key_var" else ""
            e = tk.Entry(jellyseerr_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(jellyseerr_frame, e, row_i)

        self._jellyseerr_test_lbl = self._test_button(jellyseerr_frame, 3,
            lambda: self._test_seerr("jellyseerr"))

        # ---- Tautulli ----
        self._section_header("Tautulli", "API connection for the Tautulli statistics tab")
        tautulli_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        tautulli_frame.pack(fill="x", padx=16, pady=(0, 8))
        tautulli_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",    "tautulli_host_var"),
            ("Port:",    "tautulli_port_var"),
            ("API Key:", "tautulli_key_var"),
        ]):
            tk.Label(tautulli_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "tautulli_key_var" else ""
            e = tk.Entry(tautulli_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(tautulli_frame, e, row_i)

        self._tautulli_test_lbl = self._test_button(tautulli_frame, 3,
            lambda: self._test_tautulli())

        # ---- Uptime Kuma ----
        self._section_header("Uptime Kuma", "Show monitor statuses from your Uptime Kuma status page")
        uk_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        uk_frame.pack(fill="x", padx=16, pady=(0, 8))
        uk_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",       "uptime_kuma_host_var"),
            ("Port:",       "uptime_kuma_port_var"),
            ("Slug:",       "uptime_kuma_slug_var"),
            ("API Key:",    "uptime_kuma_key_var"),
        ]):
            tk.Label(uk_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "uptime_kuma_key_var" else ""
            e = tk.Entry(uk_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(uk_frame, e, row_i)

        self._uk_test_lbl = self._test_button(uk_frame, 4,
            lambda: self._test_uptime_kuma())

        # ---- Netdata ----
        self._section_header("Netdata", "Real-time server metrics via the Netdata API (port 19999)")
        nd_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        nd_frame.pack(fill="x", padx=16, pady=(0, 8))
        nd_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "netdata_host_var"),
            ("Port:", "netdata_port_var"),
        ]):
            tk.Label(nd_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            e = tk.Entry(nd_frame, textvariable=var, font=t.font_regular)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._nd_test_lbl = self._test_button(nd_frame, 2,
            lambda: self._test_netdata())

        # ---- Glances ----
        self._section_header("Glances", "Real-time server metrics via the Glances REST API (port 61208)")
        gl_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        gl_frame.pack(fill="x", padx=16, pady=(0, 8))
        gl_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:",     "glances_host_var"),
            ("Port:",     "glances_port_var"),
            ("Username:", "glances_user_var"),
            ("Password:", "glances_pass_var"),
        ]):
            tk.Label(gl_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "glances_pass_var" else ""
            e = tk.Entry(gl_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(gl_frame, e, row_i)

        self._gl_test_lbl = self._test_button(gl_frame, 4,
            lambda: self._test_glances())

        # ---- WUD (What's Up Docker) ----
        self._section_header("What's Up Docker (WUD)",
                             "Poll WUD for container updates and alert when one is available")
        wud_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        wud_frame.pack(fill="x", padx=16, pady=(0, 8))
        wud_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "wud_host_var"),
            ("Port:", "wud_port_var"),
        ]):
            tk.Label(wud_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            e = tk.Entry(wud_frame, textvariable=var, font=t.font_regular)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._wud_test_lbl = self._test_button(wud_frame, 2,
            lambda: self._test_wud())

        # ---- Watchstate ----
        self._section_header("Watchstate",
                             "Syncs watched/play state between Plex, Emby, and Jellyfin")
        ws_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        ws_frame.pack(fill="x", padx=16, pady=(0, 8))
        ws_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("Host:", "watchstate_host_var"),
            ("Port:", "watchstate_port_var"),
        ]):
            tk.Label(ws_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            e = tk.Entry(ws_frame, textvariable=var, font=t.font_regular)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)

        self._ws_test_lbl = self._test_button(ws_frame, 2,
            lambda: self._test_watchstate())

        # ---- Cloudflare ----
        cf_hdr_wrap = tk.Frame(self.body, bg=t.bg)
        cf_hdr_wrap.pack(fill="x", padx=16, pady=(20, 4))
        tk.Frame(cf_hdr_wrap, bg=t.blue, height=2).pack(fill="x")
        cf_title_row = tk.Frame(cf_hdr_wrap, bg=t.bg)
        cf_title_row.pack(fill="x", pady=(4, 0))
        tk.Label(cf_title_row, text="Cloudflare", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        cf_help_btn = tk.Button(cf_title_row, text="?",
                                 command=self._show_cloudflare_help,
                                 bg=t.surface_light, fg=t.blue,
                                 bd=0, relief="flat", font=("Segoe UI", 9, "bold"),
                                 width=2, cursor="hand2")
        cf_help_btn.pack(side="left", padx=(8, 0))
        tk.Label(cf_hdr_wrap,
                 text="DNS records, dynamic-IP sync, WAF events, cache purge, and Tunnel status",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(anchor="w")

        cf_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        cf_frame.pack(fill="x", padx=16, pady=(0, 8))
        cf_frame.columnconfigure(1, weight=1)

        for row_i, (label, attr) in enumerate([
            ("API Token:", "cf_token_var"),
            ("Zone ID:",   "cf_zone_var"),
            ("Account ID:", "cf_account_var"),
        ]):
            tk.Label(cf_frame, text=label, bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=row_i, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr, var)
            show = "*" if attr == "cf_token_var" else ""
            e = tk.Entry(cf_frame, textvariable=var, font=t.font_regular, show=show)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", padx=12, pady=4)
            if show == "*":
                self._eye_btn(cf_frame, e, row_i)
        tk.Label(cf_frame, text="Account ID is only needed for Tunnel status — leave blank otherwise.",
                 bg=t.surface, fg=t.text_muted, font=t.font_small).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self._cf_test_lbl = self._test_button(cf_frame, 4,
            lambda: self._test_cloudflare())

        # ---- VPN ----
        self._section_header("VPN",
                             "Enable to show the VPN Status tab in the sidebar")
        vpn_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        vpn_frame.pack(fill="x", padx=16, pady=(0, 8))
        vpn_frame.columnconfigure(1, weight=1)

        self.vpn_enabled_var = tk.BooleanVar()
        tk.Checkbutton(vpn_frame, text="I have a VPN on this server",
                       variable=self.vpn_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface,
                       font=t.font_regular).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        tk.Label(vpn_frame, text="VPN Type:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.vpn_type_var = tk.StringVar(value="ProtonVPN")
        vpn_menu = tk.OptionMenu(vpn_frame, self.vpn_type_var,
                                 "ProtonVPN", "WireGuard", "OpenVPN")
        vpn_menu.configure(bg=t.surface, fg=t.text, relief="flat",
                           font=t.font_regular, highlightthickness=0,
                           activebackground=t.surface_light)
        vpn_menu["menu"].configure(bg=t.surface, fg=t.text)
        vpn_menu.grid(row=1, column=1, sticky="w", padx=12, pady=4)

        # ---- Reverse Proxy ----
        self._section_header("Reverse Proxy",
                             "Enable to show the Reverse Proxy tab in the sidebar")
        proxy_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        proxy_frame.pack(fill="x", padx=16, pady=(0, 8))
        proxy_frame.columnconfigure(1, weight=1)

        self.proxy_enabled_var = tk.BooleanVar()
        tk.Checkbutton(proxy_frame, text="I have a reverse proxy on this server",
                       variable=self.proxy_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface,
                       font=t.font_regular).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        tk.Label(proxy_frame, text="Proxy Type:", bg=t.surface, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=4)
        self.proxy_type_var = tk.StringVar(value="Auto-detect")
        proxy_menu = tk.OptionMenu(proxy_frame, self.proxy_type_var,
                                   "Auto-detect", "Nginx", "Caddy", "Traefik")
        proxy_menu.configure(bg=t.surface, fg=t.text, relief="flat",
                             font=t.font_regular, highlightthickness=0,
                             activebackground=t.surface_light)
        proxy_menu["menu"].configure(bg=t.surface, fg=t.text)
        proxy_menu.grid(row=1, column=1, sticky="w", padx=12, pady=4)

        # ---- Tailscale ----
        self._section_header("Tailscale",
                             "Enable to show the Tailscale tab in the sidebar")
        ts_frame = tk.Frame(self.body, bg=t.surface, padx=12, pady=10)
        ts_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.tailscale_enabled_var = tk.BooleanVar()
        tk.Checkbutton(ts_frame, text="Tailscale is installed on this server",
                       variable=self.tailscale_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface,
                       font=t.font_regular).pack(anchor="w")

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
            if show == "*":
                self._eye_btn(notif_frame, e, row_i)

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
            if show == "*":
                self._eye_btn(notif_frame, e, row_i)

        # Divider
        tk.Frame(notif_frame, bg=t.card_border, height=1).grid(
            row=13, column=0, columnspan=3, sticky="ew", pady=8)

        # Apprise
        tk.Label(notif_frame, text="Apprise", bg=t.surface, fg=t.cyan,
                 font=("Segoe UI", 10, "bold")).grid(
            row=14, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.apprise_enabled_var = tk.BooleanVar()
        tk.Checkbutton(notif_frame, text="Enable Apprise (Discord, Slack, Telegram, Pushover, etc.)",
                       variable=self.apprise_enabled_var,
                       bg=t.surface, fg=t.text, selectcolor=t.surface_dark,
                       activebackground=t.surface, font=t.font_regular).grid(
            row=15, column=0, columnspan=3, sticky="w", pady=2)

        tk.Label(notif_frame,
                 text="One service URL per line — see github.com/caronc/apprise#popular-notification-services",
                 bg=t.surface, fg=t.text_muted, font=t.font_small).grid(
            row=16, column=0, columnspan=3, sticky="w", pady=(0, 4))

        apprise_text_frame = tk.Frame(notif_frame, bg=t.surface)
        apprise_text_frame.grid(row=17, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self.apprise_urls_text = tk.Text(
            apprise_text_frame, height=4, bg=t.surface_dark, fg=t.text,
            font=t.font_mono, insertbackground=t.blue,
            selectbackground=t.surface_light, relief="flat", bd=0,
            padx=8, pady=6, wrap="none")
        self.apprise_urls_text.pack(fill="x")

        # Bottom spacer
        tk.Frame(self.body, bg=t.bg, height=40).pack()

    # =========================================================
    # SECTION / COLUMN HELPERS
    # =========================================================
    # =========================================================
    # ALERT RULES BUILDER
    # =========================================================

    _METRICS = [
        ("cpu",     "CPU",         "%"),
        ("ram",     "RAM",         "%"),
        ("disk",    "Disk",        "%"),
        ("temp",    "CPU Temp",    "°C"),
        ("rx_mbps", "Network In",  " MB/s"),
        ("tx_mbps", "Network Out", " MB/s"),
    ]
    _OPERATORS   = [">=", ">", "<=", "<"]
    _OP_LABELS   = {">=": "≥", ">": ">", "<=": "≤", "<": "<"}
    _CH_LABELS   = [("toast", "In-App Toast"), ("ntfy", "Push (ntfy)"), ("email", "Email"), ("apprise", "Apprise")]

    def _redraw_rule_rows(self):
        """Rebuild the rule list UI from self._alert_rules."""
        t = self.theme
        for w in self._rules_container.winfo_children():
            w.destroy()

        if not self._alert_rules:
            tk.Label(self._rules_container,
                     text="No alert rules defined. Click '+ Add Rule' to create one.",
                     bg=t.surface, fg=t.text_muted, font=t.font_small).pack(
                anchor="w", pady=6)
            return

        for idx, rule in enumerate(self._alert_rules):
            self._build_rule_row(idx, rule)

    def _build_rule_row(self, idx, rule):
        t   = self.theme
        row = tk.Frame(self._rules_container, bg=t.surface_dark,
                       highlightbackground=t.card_border, highlightthickness=1)
        row.pack(fill="x", pady=(0, 4))

        # Enabled toggle
        enabled_var = tk.BooleanVar(value=rule.get("enabled", True))
        def _toggle(i=idx, v=enabled_var):
            self._alert_rules[i]["enabled"] = v.get()
        chk = tk.Checkbutton(row, variable=enabled_var, command=_toggle,
                              bg=t.surface_dark, activebackground=t.surface_dark,
                              bd=0, highlightthickness=0)
        chk.pack(side="left", padx=(8, 4))

        # Rule summary text
        metric_lbl = next((lbl for k, lbl, _ in self._METRICS if k == rule.get("metric", "cpu")), "CPU")
        unit       = next((u   for k, _,   u in self._METRICS if k == rule.get("metric", "cpu")), "%")
        op_sym     = self._OP_LABELS.get(rule.get("operator", ">="), "≥")
        thresh     = rule.get("threshold", 80)
        dur        = rule.get("duration_minutes", 0)
        dur_str    = " for {}m".format(int(dur)) if dur else ""

        summary = "{name}   {metric} {op} {thresh}{unit}{dur}".format(
            name=rule.get("name", "?"),
            metric=metric_lbl, op=op_sym,
            thresh=thresh, unit=unit, dur=dur_str)
        tk.Label(row, text=summary, bg=t.surface_dark, fg=t.text,
                 font=t.font_regular, anchor="w").pack(side="left", padx=8, expand=True, fill="x")

        # Channel badges
        ch_colors = {"toast": t.cyan, "ntfy": t.blue, "email": t.status_running, "apprise": t.purple}
        ch_names  = {"toast": "toast", "ntfy": "ntfy", "email": "email", "apprise": "apprise"}
        for ch_key in ("toast", "ntfy", "email", "apprise"):
            if ch_key in rule.get("channels", []):
                tk.Label(row, text=ch_names[ch_key],
                         bg=ch_colors[ch_key], fg="#ffffff",
                         font=("Segoe UI", 9), padx=6, pady=1).pack(
                    side="left", padx=(0, 4))

        # Edit button
        tk.Button(row, text="Edit",
                  command=lambda i=idx: self._edit_rule(i),
                  bg=t.surface_light, fg=t.text,
                  bd=0, relief="flat", font=t.font_small,
                  padx=8, pady=3, cursor="hand2").pack(side="left", padx=(4, 2))

        # Delete button
        tk.Button(row, text="×",
                  command=lambda i=idx: self._delete_rule(i),
                  bg=t.status_stopped, fg="#ffffff",
                  bd=0, relief="flat", font=t.font_small,
                  padx=8, pady=3, cursor="hand2").pack(side="left", padx=(0, 8), pady=4)

    def _add_rule(self):
        new_rule = {
            "id":               "rule_{}".format(int(time.time())),
            "name":             "New Rule",
            "metric":           "cpu",
            "operator":         ">=",
            "threshold":        80,
            "duration_minutes": 0,
            "cooldown_minutes": 60,
            "channels":         ["toast", "ntfy", "email", "apprise"],
            "enabled":          True,
        }
        self._open_rule_dialog(new_rule, is_new=True)

    def _edit_rule(self, idx):
        self._open_rule_dialog(dict(self._alert_rules[idx]), is_new=False, idx=idx)

    def _delete_rule(self, idx):
        rule_name = self._alert_rules[idx].get("name", "this rule")
        if messagebox.askyesno("Delete Rule",
                               "Delete the rule '{}'?".format(rule_name),
                               parent=self):
            del self._alert_rules[idx]
            self._redraw_rule_rows()

    def _open_rule_dialog(self, rule: dict, is_new: bool, idx: int = -1):
        t   = self.theme
        win = tk.Toplevel(self)
        win.title("Add Alert Rule" if is_new else "Edit Alert Rule")
        win.geometry("500x460")
        win.configure(bg=t.bg)
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        # Header
        hdr = tk.Frame(win, bg=t.surface_dark, padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Add Alert Rule" if is_new else "Edit Alert Rule",
                 bg=t.surface_dark, fg=t.text,
                 font=("Segoe UI Semibold", 13)).pack(side="left")

        tk.Frame(win, bg=t.card_border, height=1).pack(fill="x")

        # Body
        body = tk.Frame(win, bg=t.bg, padx=24, pady=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        def _lbl(text, row):
            tk.Label(body, text=text, bg=t.bg, fg=t.text,
                     font=t.font_regular, anchor="w").grid(
                row=row, column=0, sticky="w", pady=6, padx=(0, 16))

        # Rule name
        _lbl("Rule name:", 0)
        name_var = tk.StringVar(value=rule.get("name", "New Rule"))
        e_name = tk.Entry(body, textvariable=name_var, font=t.font_regular)
        t.style_entry(e_name)
        e_name.grid(row=0, column=1, sticky="ew", pady=6)

        # Metric
        _lbl("Metric:", 1)
        metric_labels = ["{} ({})".format(lbl, u.strip()) for _, lbl, u in self._METRICS]
        metric_keys   = [k for k, _, _ in self._METRICS]
        metric_idx    = metric_keys.index(rule.get("metric", "cpu")) if rule.get("metric", "cpu") in metric_keys else 0
        metric_var    = tk.StringVar(value=metric_labels[metric_idx])
        om_metric = ttk.Combobox(body, textvariable=metric_var,
                                  values=metric_labels, state="readonly",
                                  font=t.font_regular, width=22)
        om_metric.grid(row=1, column=1, sticky="w", pady=6)

        # Condition row: operator + threshold + unit
        _lbl("Condition:", 2)
        cond_frame = tk.Frame(body, bg=t.bg)
        cond_frame.grid(row=2, column=1, sticky="w", pady=6)

        op_labels = [self._OP_LABELS[o] for o in self._OPERATORS]
        op_idx    = self._OPERATORS.index(rule.get("operator", ">=")) if rule.get("operator", ">=") in self._OPERATORS else 0
        op_var    = tk.StringVar(value=op_labels[op_idx])
        om_op = ttk.Combobox(cond_frame, textvariable=op_var,
                              values=op_labels, state="readonly",
                              font=t.font_regular, width=5)
        om_op.pack(side="left")

        thresh_var = tk.StringVar(value=str(rule.get("threshold", 80)))
        e_thresh = tk.Entry(cond_frame, textvariable=thresh_var,
                            width=7, font=t.font_regular)
        t.style_entry(e_thresh)
        e_thresh.pack(side="left", padx=(8, 4))

        unit_lbl = tk.Label(cond_frame, text="%", bg=t.bg, fg=t.text_muted,
                             font=t.font_small)
        unit_lbl.pack(side="left")

        def _update_unit(*_):
            sel_idx = metric_labels.index(metric_var.get()) if metric_var.get() in metric_labels else 0
            unit_lbl.config(text=self._METRICS[sel_idx][2].strip())
        metric_var.trace_add("write", _update_unit)
        _update_unit()

        # Duration
        _lbl("Duration:", 3)
        dur_frame = tk.Frame(body, bg=t.bg)
        dur_frame.grid(row=3, column=1, sticky="w", pady=6)
        dur_var = tk.StringVar(value=str(int(rule.get("duration_minutes", 0))))
        sp_dur = tk.Spinbox(dur_frame, from_=0, to=60, textvariable=dur_var,
                             width=5, font=t.font_regular,
                             bg=t.card_bg, fg=t.text, bd=1,
                             buttonbackground=t.surface_light)
        sp_dur.pack(side="left")
        tk.Label(dur_frame, text="minutes  (0 = fire immediately)",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(side="left", padx=8)

        # Cooldown
        _lbl("Cooldown:", 4)
        cd_frame = tk.Frame(body, bg=t.bg)
        cd_frame.grid(row=4, column=1, sticky="w", pady=6)
        cd_var = tk.StringVar(value=str(int(rule.get("cooldown_minutes", 60))))
        sp_cd = tk.Spinbox(cd_frame, from_=0, to=1440, textvariable=cd_var,
                            width=5, font=t.font_regular,
                            bg=t.card_bg, fg=t.text, bd=1,
                            buttonbackground=t.surface_light)
        sp_cd.pack(side="left")
        tk.Label(cd_frame, text="minutes before re-firing",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(side="left", padx=8)

        # Channels
        _lbl("Channels:", 5)
        ch_frame = tk.Frame(body, bg=t.bg)
        ch_frame.grid(row=5, column=1, sticky="w", pady=6)
        ch_vars = {}
        for ch_key, ch_label in self._CH_LABELS:
            v = tk.BooleanVar(value=ch_key in rule.get("channels", ["toast", "ntfy", "email"]))
            ch_vars[ch_key] = v
            tk.Checkbutton(ch_frame, text=ch_label, variable=v,
                            bg=t.bg, fg=t.text,
                            activebackground=t.bg, activeforeground=t.text,
                            selectcolor=t.card_bg, font=t.font_regular,
                            bd=0, highlightthickness=0).pack(side="left", padx=(0, 16))

        tk.Frame(win, bg=t.card_border, height=1).pack(fill="x")

        # Footer
        footer = tk.Frame(win, bg=t.surface_dark, padx=16, pady=12)
        footer.pack(fill="x")

        err_lbl = tk.Label(footer, text="", bg=t.surface_dark,
                            fg=t.status_stopped, font=t.font_small)
        err_lbl.pack(side="left")

        def _save():
            name = name_var.get().strip()
            if not name:
                err_lbl.config(text="Rule name is required.")
                return
            try:
                thresh = float(thresh_var.get())
            except ValueError:
                err_lbl.config(text="Threshold must be a number.")
                return
            try:
                dur_min = max(0, int(dur_var.get()))
                cd_min  = max(0, int(cd_var.get()))
            except ValueError:
                err_lbl.config(text="Duration and cooldown must be whole numbers.")
                return

            sel_idx    = metric_labels.index(metric_var.get()) if metric_var.get() in metric_labels else 0
            sel_metric = metric_keys[sel_idx]
            sel_op_sym = op_var.get()
            sel_op     = next(o for o in self._OPERATORS if self._OP_LABELS[o] == sel_op_sym)
            channels   = [k for k in ch_vars if ch_vars[k].get()]

            updated = dict(rule)
            updated.update({
                "name":             name,
                "metric":           sel_metric,
                "operator":         sel_op,
                "threshold":        thresh,
                "duration_minutes": dur_min,
                "cooldown_minutes": cd_min,
                "channels":         channels,
            })

            if is_new:
                self._alert_rules.append(updated)
            else:
                self._alert_rules[idx] = updated

            self._redraw_rule_rows()
            win.destroy()

        tk.Button(footer, text="Save Rule", command=_save,
                  bg=t.blue, fg="#ffffff",
                  bd=0, relief="flat", font=t.font_regular,
                  padx=16, pady=5, cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(footer, text="Cancel", command=win.destroy,
                  bg=t.surface_light, fg=t.text,
                  bd=0, relief="flat", font=t.font_regular,
                  padx=12, pady=5, cursor="hand2").pack(side="right")

        e_name.focus_set()

    # =========================================================
    # SECTION HELPERS
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
    # RELOAD (called on server switch)
    # =========================================================
    def reload(self):
        """Clear dynamic rows and re-populate every field from the active server."""
        for row in self._service_rows:
            row["frame"].destroy()
        self._service_rows.clear()

        for row in self._docker_rows:
            row["frame"].destroy()
        self._docker_rows.clear()

        for row in self._mount_rows:
            row["frame"].destroy()
        self._mount_rows.clear()

        for lbl in (
            self._sab_test_lbl, self._qb_test_lbl, self._ph_test_lbl,
            self._emby_test_lbl, self._plex_test_lbl,
            self._jf_test_lbl, self._sonarr_test_lbl, self._radarr_test_lbl,
            self._prowlarr_test_lbl, self._overseerr_test_lbl,
            self._jellyseerr_test_lbl, self._tautulli_test_lbl,
            self._uk_test_lbl, self._nd_test_lbl, self._gl_test_lbl,
            self._wud_test_lbl, self._ws_test_lbl, self._cf_test_lbl,
        ):
            lbl.config(text="", fg=self.theme.text_muted)

        self._populate_from_config()

    # =========================================================
    # POPULATE FROM CONFIG
    # =========================================================
    def _populate_from_config(self):
        cfg = self.controller.config_manager

        # Services
        for name, data in cfg.get_services().items():
            self._add_service_row(name, data["service"], data.get("port", ""))

        # Docker containers
        for name, data in cfg.get_docker().items():
            self._add_docker_row(name, data.get("container", ""), data.get("port", ""))

        # Storage mounts
        for mount in cfg.get_storage_mounts():
            self._add_mount_row(mount)

        # Dashboard
        self.refresh_var.set(str(cfg.dashboard_refresh_interval))
        self.retention_var.set(str(cfg.metrics_retention_days))

        # Alert rules
        self._alert_rules = [dict(r) for r in cfg.get_alert_rules()]
        self._redraw_rule_rows()

        # SABnzbd
        self.sab_host_var.set(cfg.sabnzbd_host)
        self.sab_port_var.set(cfg.sabnzbd_port)
        self.sab_key_var.set(cfg.sabnzbd_apikey)

        # qBittorrent
        self.qb_host_var.set(cfg.qbittorrent_host)
        self.qb_port_var.set(cfg.qbittorrent_port)
        self.qb_user_var.set(cfg.qbittorrent_username)
        self.qb_pass_var.set(cfg.qbittorrent_password)

        # Pi-hole / AdGuard
        self.ph_type_var.set(cfg.pihole_type)
        self.ph_host_var.set(cfg.pihole_host)
        self.ph_port_var.set(cfg.pihole_port)
        self.ph_apikey_var.set(cfg.pihole_apikey)
        self.ph_pass_var.set(cfg.adguard_username)

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

        # Prowlarr
        self.prowlarr_host_var.set(cfg.prowlarr_host)
        self.prowlarr_port_var.set(cfg.prowlarr_port)
        self.prowlarr_key_var.set(cfg.prowlarr_apikey)

        # Overseerr
        self.overseerr_host_var.set(cfg.overseerr_host)
        self.overseerr_port_var.set(cfg.overseerr_port)
        self.overseerr_key_var.set(cfg.overseerr_apikey)

        # Jellyseerr
        self.jellyseerr_host_var.set(cfg.jellyseerr_host)
        self.jellyseerr_port_var.set(cfg.jellyseerr_port)
        self.jellyseerr_key_var.set(cfg.jellyseerr_apikey)

        # Tautulli
        self.tautulli_host_var.set(cfg.tautulli_host)
        self.tautulli_port_var.set(cfg.tautulli_port)
        self.tautulli_key_var.set(cfg.tautulli_apikey)

        # Uptime Kuma
        self.uptime_kuma_host_var.set(cfg.uptime_kuma_host)
        self.uptime_kuma_port_var.set(cfg.uptime_kuma_port)
        self.uptime_kuma_slug_var.set(cfg.uptime_kuma_slug)
        self.uptime_kuma_key_var.set(cfg.uptime_kuma_apikey)

        # Netdata
        self.netdata_host_var.set(cfg.netdata_host)
        self.netdata_port_var.set(cfg.netdata_port)

        # Glances
        self.glances_host_var.set(cfg.glances_host)
        self.glances_port_var.set(cfg.glances_port)
        self.glances_user_var.set(cfg.glances_username)
        self.glances_pass_var.set(cfg.glances_password)

        # WUD
        self.wud_host_var.set(cfg.wud_host)
        self.wud_port_var.set(cfg.wud_port)

        # Watchstate
        self.watchstate_host_var.set(cfg.watchstate_host)
        self.watchstate_port_var.set(cfg.watchstate_port)

        # Cloudflare
        self.cf_token_var.set(cfg.cloudflare_api_token)
        self.cf_zone_var.set(cfg.cloudflare_zone_id)
        self.cf_account_var.set(cfg.cloudflare_account_id)

        # VPN
        self.vpn_enabled_var.set(cfg.vpn_enabled)
        self.vpn_type_var.set(cfg.vpn_type)

        # Reverse Proxy
        self.proxy_enabled_var.set(cfg.proxy_enabled)
        self.proxy_type_var.set(cfg.proxy_type)

        # Tailscale
        self.tailscale_enabled_var.set(cfg.tailscale_enabled)

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
        self.apprise_enabled_var.set(cfg.notify_apprise_enabled)
        self.apprise_urls_text.delete("1.0", "end")
        self.apprise_urls_text.insert("1.0", cfg.notify_apprise_urls)

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

        e_container = tk.Entry(frame, textvariable=row["container"], font=t.font_mono)
        t.style_entry(e_container)
        e_container.grid(row=0, column=1, sticky="ew", padx=3, pady=4)

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

    def _eye_btn(self, frame, entry, row):
        """Add a Show/Hide toggle button in column 2 next to a masked entry."""
        t = self.theme
        state = {"visible": False}
        btn = tk.Button(frame, text="Show", bd=0, relief="flat",
                        bg=t.surface, fg=t.blue,
                        font=t.font_small, cursor="hand2",
                        activebackground=t.surface, activeforeground=t.text)
        def _toggle():
            state["visible"] = not state["visible"]
            entry.configure(show="" if state["visible"] else "*")
            btn.configure(text="Hide" if state["visible"] else "Show")
        btn.configure(command=_toggle)
        btn.grid(row=row, column=2, padx=4, pady=4)

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

        # --- Collect docker containers ---
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

        # --- Alert rules are already maintained in self._alert_rules ---

        # --- SABnzbd ---
        sab_host = self.sab_host_var.get().strip() or "localhost"
        sab_port = self.sab_port_var.get().strip() or "8080"
        sab_key  = self.sab_key_var.get().strip()

        # --- qBittorrent ---
        qb_host = self.qb_host_var.get().strip()
        qb_port = self.qb_port_var.get().strip() or "8080"
        qb_user = self.qb_user_var.get().strip() or "admin"
        qb_pass = self.qb_pass_var.get().strip()

        # --- Pi-hole / AdGuard ---
        ph_type   = self.ph_type_var.get().strip() or "pihole"
        ph_host   = self.ph_host_var.get().strip()
        ph_port   = self.ph_port_var.get().strip() or "80"
        ph_apikey = self.ph_apikey_var.get().strip()
        ph_pass   = self.ph_pass_var.get().strip()

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

        # --- Prowlarr ---
        prowlarr_host = self.prowlarr_host_var.get().strip() or "localhost"
        prowlarr_port = self.prowlarr_port_var.get().strip() or "9797"
        prowlarr_key  = self.prowlarr_key_var.get().strip()

        # --- Overseerr ---
        overseerr_host = self.overseerr_host_var.get().strip() or "localhost"
        overseerr_port = self.overseerr_port_var.get().strip() or "5055"
        overseerr_key  = self.overseerr_key_var.get().strip()

        # --- Jellyseerr ---
        jellyseerr_host = self.jellyseerr_host_var.get().strip() or "localhost"
        jellyseerr_port = self.jellyseerr_port_var.get().strip() or "5055"
        jellyseerr_key  = self.jellyseerr_key_var.get().strip()

        # --- Tautulli ---
        tautulli_host = self.tautulli_host_var.get().strip() or "localhost"
        tautulli_port = self.tautulli_port_var.get().strip() or "8181"
        tautulli_key  = self.tautulli_key_var.get().strip()

        # --- VPN ---
        vpn_enabled = self.vpn_enabled_var.get()
        vpn_type    = self.vpn_type_var.get()

        # --- Reverse Proxy ---
        proxy_enabled = self.proxy_enabled_var.get()
        proxy_type    = self.proxy_type_var.get()

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
        notify_apprise_enabled = self.apprise_enabled_var.get()
        notify_apprise_urls     = self.apprise_urls_text.get("1.0", "end").strip()

        # --- Persist ---
        cfg = self.controller.config_manager

        try:
            retention = int(self.retention_var.get())
            if retention < 1:
                retention = 1
        except ValueError:
            retention = 30

        # Per-server settings — written into the active server's settings dict
        cfg.update_server_settings({
            "services":                  services,
            "docker":                    docker,
            "storage_mounts":            mounts,
            "alert_rules":               self._alert_rules,
            "dashboard_refresh_interval": refresh,
            "sabnzbd_host":              sab_host,
            "sabnzbd_port":              sab_port,
            "sabnzbd_apikey":            sab_key,
            "qbittorrent_host":          qb_host,
            "qbittorrent_port":          qb_port,
            "qbittorrent_username":      qb_user,
            "qbittorrent_password":      qb_pass,
            "pihole_type":               ph_type,
            "pihole_host":               ph_host,
            "pihole_port":               ph_port,
            "pihole_apikey":             ph_apikey,
            "adguard_username":          ph_pass,
            "emby_host":                 emby_host,
            "emby_port":                 emby_port,
            "emby_apikey":               emby_key,
            "plex_host":                 plex_host,
            "plex_port":                 plex_port,
            "plex_token":                plex_token,
            "jellyfin_host":             jf_host,
            "jellyfin_port":             jf_port,
            "jellyfin_apikey":           jf_key,
            "sonarr_host":               sonarr_host,
            "sonarr_port":               sonarr_port,
            "sonarr_apikey":             sonarr_key,
            "radarr_host":               radarr_host,
            "radarr_port":               radarr_port,
            "radarr_apikey":             radarr_key,
            "prowlarr_host":             prowlarr_host,
            "prowlarr_port":             prowlarr_port,
            "prowlarr_apikey":           prowlarr_key,
            "overseerr_host":            overseerr_host,
            "overseerr_port":            overseerr_port,
            "overseerr_apikey":          overseerr_key,
            "jellyseerr_host":           jellyseerr_host,
            "jellyseerr_port":           jellyseerr_port,
            "jellyseerr_apikey":         jellyseerr_key,
            "tautulli_host":             tautulli_host,
            "tautulli_port":             tautulli_port,
            "tautulli_apikey":           tautulli_key,
            "uptime_kuma_host":          self.uptime_kuma_host_var.get().strip(),
            "uptime_kuma_port":          self.uptime_kuma_port_var.get().strip() or "3001",
            "uptime_kuma_slug":          self.uptime_kuma_slug_var.get().strip() or "default",
            "uptime_kuma_apikey":        self.uptime_kuma_key_var.get().strip(),
            "netdata_host":              self.netdata_host_var.get().strip(),
            "netdata_port":              self.netdata_port_var.get().strip() or "19999",
            "glances_host":              self.glances_host_var.get().strip(),
            "glances_port":              self.glances_port_var.get().strip() or "61208",
            "glances_username":          self.glances_user_var.get().strip(),
            "glances_password":          self.glances_pass_var.get().strip(),
            "wud_host":                  self.wud_host_var.get().strip(),
            "wud_port":                  self.wud_port_var.get().strip() or "3002",
            "watchstate_host":           self.watchstate_host_var.get().strip(),
            "watchstate_port":           self.watchstate_port_var.get().strip() or "8090",
            "cloudflare_api_token":      self.cf_token_var.get().strip(),
            "cloudflare_zone_id":        self.cf_zone_var.get().strip(),
            "cloudflare_account_id":     self.cf_account_var.get().strip(),
            "vpn_enabled":               vpn_enabled,
            "vpn_type":                  vpn_type,
            "proxy_enabled":             proxy_enabled,
            "proxy_type":                proxy_type,
            "tailscale_enabled":         self.tailscale_enabled_var.get(),
        })

        # Global settings — shared across all servers
        cfg.config["metrics_retention_days"] = retention
        cfg.config["notify_ntfy_enabled"]    = notify_ntfy_enabled
        cfg.config["notify_ntfy_topic"]      = notify_ntfy_topic
        cfg.config["notify_ntfy_server"]     = notify_ntfy_server
        cfg.config["notify_ntfy_token"]      = notify_ntfy_token
        cfg.config["notify_email_enabled"]   = notify_email_enabled
        cfg.config["notify_email_to"]        = notify_email_to
        cfg.config["notify_smtp_host"]       = notify_smtp_host
        cfg.config["notify_smtp_port"]       = notify_smtp_port
        cfg.config["notify_smtp_user"]       = notify_smtp_user
        cfg.config["notify_smtp_pass"]       = notify_smtp_pass
        cfg.config["notify_apprise_enabled"] = notify_apprise_enabled
        cfg.config["notify_apprise_urls"]    = notify_apprise_urls
        cfg.save()

        self.controller.apply_config()
        self.save_btn.config(state="normal", text="Save & Apply")
        self._show_saved_banner()

    def _show_saved_banner(self):
        t = self.controller.theme
        banner = tk.Label(
            self, text="✓  Settings saved",
            bg=t.status_running, fg="#ffffff",
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

    def _resolve_host(self, host):
        """Replace localhost/127.0.0.1 with the active server's SSH host.
        All test connections run from this Windows machine, so 'localhost'
        would hit Windows itself rather than the remote server."""
        if host in ("", "localhost", "127.0.0.1"):
            active = self.controller.config_manager.get_active_server()
            if active:
                return active.get("host", host)
        return host

    def _set_test_result(self, lbl, ok, msg):
        t = self.controller.theme
        lbl.configure(
            text=("✓  " if ok else "✗  ") + msg,
            fg=t.status_running if ok else t.status_stopped,
        )

    def _test_arr(self, app):
        import threading, urllib.request, urllib.error, json as _json
        if app == "sonarr":
            lbl = self._sonarr_test_lbl
            host = self.sonarr_host_var.get().strip()
            port = self.sonarr_port_var.get().strip()
            key  = self.sonarr_key_var.get().strip()
        elif app == "radarr":
            lbl = self._radarr_test_lbl
            host = self.radarr_host_var.get().strip()
            port = self.radarr_port_var.get().strip()
            key  = self.radarr_key_var.get().strip()
        else:  # prowlarr
            lbl = self._prowlarr_test_lbl
            host = self.prowlarr_host_var.get().strip()
            port = self.prowlarr_port_var.get().strip()
            key  = self.prowlarr_key_var.get().strip()

        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))
        api_ver = "v1" if app == "prowlarr" else "v3"

        def _run():
            try:
                url = "http://{}:{}/api/{}/system/status".format(host, port, api_ver)
                req = urllib.request.Request(url, headers={"X-Api-Key": key})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()


    def _test_seerr(self, app):
        import threading, urllib.request, urllib.error, json as _json
        if app == "overseerr":
            lbl  = self._overseerr_test_lbl
            host = self.overseerr_host_var.get().strip()
            port = self.overseerr_port_var.get().strip() or "5055"
            key  = self.overseerr_key_var.get().strip()
        else:
            lbl  = self._jellyseerr_test_lbl
            host = self.jellyseerr_host_var.get().strip()
            port = self.jellyseerr_port_var.get().strip() or "5055"
            key  = self.jellyseerr_key_var.get().strip()

        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/api/v1/status".format(host, port)
                req = urllib.request.Request(url, headers={"X-Api-Key": key})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_tautulli(self):
        import threading, urllib.request, urllib.error, json as _json, urllib.parse as _parse
        lbl  = self._tautulli_test_lbl
        host = self.tautulli_host_var.get().strip()
        port = self.tautulli_port_var.get().strip() or "8181"
        key  = self.tautulli_key_var.get().strip()
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/api/v2?apikey={}&cmd=get_server_info".format(
                    host, port, _parse.quote(key))
                with urllib.request.urlopen(url, timeout=6) as r:
                    data = _json.loads(r.read())
                resp = data.get("response", {})
                if resp.get("result") != "success":
                    raise RuntimeError(resp.get("message", "API error"))
                info = resp.get("data", {})
                ver = info.get("pms_version", info.get("version", "?"))
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_sabnzbd(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._sab_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.sab_host_var.get().strip() or "localhost"
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

    def _test_wud(self):
        import threading, urllib.request, json as _json
        lbl  = self._wud_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.wud_host_var.get().strip() or "localhost"
        port = self.wud_port_var.get().strip() or "3002"
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/api/containers".format(host, port)
                with urllib.request.urlopen(url, timeout=6) as r:
                    containers = _json.loads(r.read())
                updates = sum(1 for c in containers if c.get("updateAvailable"))
                self.after(0, lambda: self._set_test_result(
                    lbl, True,
                    "Connected  ·  {} container(s)  ·  {} update(s) available".format(
                        len(containers), updates)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_emby(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._emby_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.emby_host_var.get().strip() or "localhost"
        port = self.emby_port_var.get().strip() or "8096"
        key  = self.emby_key_var.get().strip()
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/emby/System/Info".format(host, port)
                req = urllib.request.Request(
                    url, headers={"X-Emby-Token": key, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("Version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_plex(self):
        import threading, urllib.request, urllib.error
        lbl = self._plex_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host  = self.plex_host_var.get().strip() or "localhost"
        port  = self.plex_port_var.get().strip() or "32400"
        token = self.plex_token_var.get().strip()
        host  = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/identity".format(host, port)
                req = urllib.request.Request(
                    url, headers={"X-Plex-Token": token, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    import json as _json
                    data = _json.loads(r.read())
                ver = (data.get("MediaContainer") or {}).get("version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_jellyfin(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl = self._jf_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.jf_host_var.get().strip() or "localhost"
        port = self.jf_port_var.get().strip() or "8096"
        key  = self.jf_key_var.get().strip()
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/System/Info".format(host, port)
                req = urllib.request.Request(
                    url, headers={"X-Emby-Token": key, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver = data.get("Version", "?")
                self.after(0, lambda: self._set_test_result(lbl, True, "Connected  ·  v{}".format(ver)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_uptime_kuma(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl  = self._uk_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.uptime_kuma_host_var.get().strip() or "localhost"
        port = self.uptime_kuma_port_var.get().strip() or "3001"
        slug = self.uptime_kuma_slug_var.get().strip()
        key  = self.uptime_kuma_key_var.get().strip()
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            base = "http://{}:{}".format(host, port)
            # Step 1: basic reachability check against the root URL.
            # Any HTTP response (even 4xx) means the server is up.
            try:
                try:
                    urllib.request.urlopen(base + "/", timeout=6)
                except urllib.error.HTTPError:
                    pass  # Server responded — it's up
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
                return

            # Step 2: if a slug is configured, fetch the status page for detail.
            if slug:
                try:
                    headers = {"Accept": "application/json"}
                    if key:
                        headers["Authorization"] = "Bearer {}".format(key)
                    req = urllib.request.Request(
                        "{}/api/status-page/{}".format(base, slug), headers=headers)
                    with urllib.request.urlopen(req, timeout=6) as r:
                        data = _json.loads(r.read())
                    title  = (data.get("config") or {}).get("title", slug)
                    groups = data.get("publicGroupList", [])
                    total  = sum(len(g.get("monitorList", [])) for g in groups)
                    self.after(0, lambda: self._set_test_result(
                        lbl, True, "Connected  ·  {}  ·  {} monitors".format(title, total)))
                    return
                except Exception:
                    pass  # Slug not found or API error — server is still up

            self.after(0, lambda: self._set_test_result(lbl, True, "Connected"))
        threading.Thread(target=_run, daemon=True).start()


    def _test_watchstate(self):
        import threading, urllib.request, urllib.error
        lbl  = self._ws_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.watchstate_host_var.get().strip() or "localhost"
        port = self.watchstate_port_var.get().strip() or "8090"
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/v1/api/system/healthcheck".format(host, port)
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    code = r.status
                self.after(0, lambda: self._set_test_result(
                    lbl, True, "Connected  ·  HTTP {}".format(code)))
            except urllib.error.HTTPError as e:
                # Something answered on this host:port, but not with a healthy
                # response from Watchstate's own endpoint -- e.g. a 404 usually
                # means a different service (or a proxy's default page) is
                # sitting on that port, not Watchstate.
                self.after(0, lambda err=e: self._set_test_result(
                    lbl, False, "No Watchstate here — HTTP {}".format(err.code)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_cloudflare(self):
        import threading
        from core import cloudflare_manager as cf
        lbl   = self._cf_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        token = self.cf_token_var.get().strip()
        zone  = self.cf_zone_var.get().strip()

        def _run():
            if not token or not zone:
                self.after(0, lambda: self._set_test_result(
                    lbl, False, "API Token and Zone ID are required"))
                return
            try:
                zone_info = cf.test_connection(token, zone)
                self.after(0, lambda: self._set_test_result(
                    lbl, True, "Connected  ·  {}  ·  {}".format(
                        zone_info["name"], zone_info["status"])))
            except cf.CloudflareError as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:80]))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:80]))
        threading.Thread(target=_run, daemon=True).start()

    def _show_cloudflare_help(self):
        if getattr(self, "_cf_help_win", None) and self._cf_help_win.winfo_exists():
            self._cf_help_win.lift()
            return
        t = self.controller.theme
        win = tk.Toplevel(self)
        win.title("Cloudflare Setup")
        win.configure(bg=t.bg)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._cf_help_win = win

        hdr = tk.Frame(win, bg=t.surface, padx=20, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="☁  Cloudflare Setup",
                 bg=t.surface, fg=t.text, font=t.font_title).pack(side="left")
        tk.Button(hdr, text="✕", command=win.destroy,
                  bg=t.surface, fg=t.text_muted, bd=0, relief="flat",
                  font=("Segoe UI", 14), cursor="hand2").pack(side="right")

        body = tk.Frame(win, bg=t.bg, padx=24, pady=16)
        body.pack(fill="both")

        tk.Label(body,
                 text="Create a Custom Token at dash.cloudflare.com/profile/api-tokens\n"
                      "with these permissions:",
                 bg=t.bg, fg=t.text, font=t.font_regular, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        PERMISSIONS = [
            ("Zone → Zone",                  "Read",  "Test Connection"),
            ("Zone → DNS",                   "Edit",  "View + edit records, Sync Dynamic IP"),
            ("Zone → Cache Purge",           "Purge", "Purge Cache button"),
            ("Zone → Analytics",             "Read",  "Security events  (optional)"),
            ("Account → Cloudflare Tunnel",  "Read",  "Tunnel status  (optional)"),
        ]
        row_i = 1
        for perm, level, used_for in PERMISSIONS:
            tk.Label(body, text=perm, bg=t.bg, fg=t.text,
                     font=t.font_small).grid(row=row_i, column=0, sticky="w", pady=2)
            level_lbl = tk.Label(body, text=level,
                                 bg=t.surface, fg=t.blue,
                                 font=t.font_mono, padx=6, pady=2,
                                 highlightbackground=t.card_border, highlightthickness=1)
            level_lbl.grid(row=row_i, column=1, sticky="w", padx=(10, 10), pady=2)
            tk.Label(body, text=used_for, bg=t.bg, fg=t.text_muted,
                     font=t.font_small).grid(row=row_i, column=2, sticky="w", pady=2)
            row_i += 1

        tk.Label(body,
                 text="Skip the last two rows if you don't need those sections — the tab\n"
                      "degrades gracefully and just shows them as unavailable.",
                 bg=t.bg, fg=t.text_muted, font=t.font_small, justify="left").grid(
            row=row_i, column=0, columnspan=3, sticky="w", pady=(6, 14))
        row_i += 1

        tk.Label(body, text="RESOURCE SCOPING", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).grid(
            row=row_i, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row_i += 1
        tk.Label(body,
                 text="Zone Resources → Specific zone → your domain\n"
                      "Account Resources → Specific account → your account  (only if adding Tunnel Read)",
                 bg=t.bg, fg=t.text, font=t.font_small, justify="left").grid(
            row=row_i, column=0, columnspan=3, sticky="w", pady=(0, 14))
        row_i += 1

        tk.Label(body, text="FINDING YOUR ZONE ID / ACCOUNT ID", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).grid(
            row=row_i, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row_i += 1
        tk.Label(body,
                 text="Cloudflare dashboard → select your domain → Overview page →\n"
                      "right-hand sidebar, under “API”. Both Zone ID and Account ID\n"
                      "are listed there with a copy icon next to each.",
                 bg=t.bg, fg=t.text, font=t.font_small, justify="left").grid(
            row=row_i, column=0, columnspan=3, sticky="w")

        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 2
        win.geometry("+{}+{}".format(max(x, 0), max(y, 0)))

    def _test_netdata(self):
        import threading, urllib.request, urllib.error, json as _json
        lbl  = self._nd_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.netdata_host_var.get().strip() or "localhost"
        port = self.netdata_port_var.get().strip() or "19999"
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/api/v1/info".format(host, port)
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read())
                ver      = data.get("version", "?")
                hostname = data.get("hostname", "")
                self.after(0, lambda: self._set_test_result(
                    lbl, True, "Connected  ·  v{}  ·  {}".format(ver, hostname)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_glances(self):
        import threading, urllib.request, urllib.error, json as _json, base64
        lbl  = self._gl_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.glances_host_var.get().strip() or "localhost"
        port = self.glances_port_var.get().strip() or "61208"
        user = self.glances_user_var.get().strip()
        pwd  = self.glances_pass_var.get().strip()
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                headers = {"Accept": "application/json"}
                if user:
                    creds = base64.b64encode("{}:{}".format(user, pwd).encode()).decode()
                    headers["Authorization"] = "Basic {}".format(creds)
                data = None
                api_ver = None
                for v in (4, 3):
                    try:
                        url = "http://{}:{}/api/{}/cpu".format(host, port, v)
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, timeout=6) as r:
                            data = _json.loads(r.read())
                        api_ver = v
                        break
                    except urllib.error.HTTPError as e:
                        if e.code == 404:
                            continue
                        raise
                if data is None:
                    raise RuntimeError("No Glances API found on v3 or v4")
                cpu_total = data.get("total", "?")
                self.after(0, lambda: self._set_test_result(
                    lbl, True, "Connected  ·  API v{}  ·  CPU {:.1f}%".format(
                        api_ver, float(cpu_total))))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_qbittorrent(self):
        import threading, urllib.request, urllib.parse as _up
        lbl  = self._qb_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.qb_host_var.get().strip() or "localhost"
        port = self.qb_port_var.get().strip() or "8080"
        user = self.qb_user_var.get().strip() or "admin"
        pwd  = self.qb_pass_var.get().strip()

        def _run():
            try:
                url  = "http://{}:{}/api/v2/auth/login".format(host, port)
                body = _up.urlencode({"username": user, "password": pwd}).encode()
                req  = urllib.request.Request(url, data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    resp   = r.read().decode()
                    cookie = ""
                    for k, v in r.headers.items():
                        if k.lower() == "set-cookie" and "SID=" in v:
                            cookie = "SID=" + v.split("SID=")[1].split(";")[0]
                if resp.strip() == "Ok.":
                    vreq = urllib.request.Request(
                        "http://{}:{}/api/v2/app/version".format(host, port),
                        headers={"Cookie": cookie} if cookie else {})
                    with urllib.request.urlopen(vreq, timeout=4) as vr:
                        ver = vr.read().decode().strip()
                    self.after(0, lambda: self._set_test_result(
                        lbl, True, "Connected  ·  v{}".format(ver)))
                else:
                    self.after(0, lambda: self._set_test_result(
                        lbl, False, "Auth failed — check username/password"))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_pihole(self):
        import threading, urllib.request, json as _json, base64
        lbl     = self._ph_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        ph_type = self.ph_type_var.get().strip() or "pihole"
        host    = self.ph_host_var.get().strip() or "localhost"
        port    = self.ph_port_var.get().strip() or "80"
        apikey  = self.ph_apikey_var.get().strip()
        passwd  = self.ph_pass_var.get().strip()

        def _run():
            try:
                if ph_type == "pihole":
                    url = "http://{}:{}/admin/api.php?summaryRaw&auth={}".format(
                        host, port, apikey)
                    with urllib.request.urlopen(url, timeout=6) as r:
                        data = _json.loads(r.read())
                    blocked = data.get("ads_blocked_today", "?")
                    pct     = data.get("ads_percentage_today", 0)
                    status  = data.get("status", "?")
                    self.after(0, lambda: self._set_test_result(
                        lbl, True,
                        "Pi-hole {}  ·  {}% blocked  ·  {} ads today".format(
                            status, round(pct, 1), blocked)))
                else:
                    # AdGuard: apikey field = password, ph_pass field = username
                    username = passwd or "admin"
                    creds = base64.b64encode(
                        "{}:{}".format(username, apikey).encode()).decode()
                    req = urllib.request.Request(
                        "http://{}:{}/control/status".format(host, port),
                        headers={"Authorization": "Basic {}".format(creds)})
                    with urllib.request.urlopen(req, timeout=6) as r:
                        data = _json.loads(r.read())
                    version    = data.get("version", "?")
                    protection = data.get("protection_enabled", "?")
                    self.after(0, lambda: self._set_test_result(
                        lbl, True,
                        "AdGuard v{}  ·  protection={}".format(version, protection)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _test_wud(self):
        import threading, urllib.request, json as _json
        lbl  = self._wud_test_lbl
        lbl.configure(text="Testing…", fg=self.controller.theme.text_muted)
        host = self.wud_host_var.get().strip() or "localhost"
        port = self.wud_port_var.get().strip() or "3002"
        host = self._resolve_host(host.removeprefix("https://").removeprefix("http://").strip("/"))

        def _run():
            try:
                url = "http://{}:{}/api/containers".format(host, port)
                with urllib.request.urlopen(url, timeout=6) as r:
                    containers = _json.loads(r.read())
                updates = sum(1 for c in containers if c.get("updateAvailable"))
                self.after(0, lambda: self._set_test_result(
                    lbl, True,
                    "Connected  ·  {} container(s)  ·  {} update(s) available".format(
                        len(containers), updates)))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_test_result(lbl, False, err[:60]))
        threading.Thread(target=_run, daemon=True).start()

    def _export_config(self):
        from tkinter import filedialog
        import json, shutil
        path = filedialog.asksaveasfilename(
            title="Export Config",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="media-server-config.json",
        )
        if not path:
            return
        try:
            cfg_path = self.controller.config_manager.config_path
            shutil.copy2(cfg_path, path)
            self._show_save_toast("Config exported to {}".format(path))
        except Exception as e:
            self._show_save_toast("Export failed: {}".format(e))

    def _import_config(self):
        from tkinter import filedialog
        import json, shutil
        path = filedialog.askopenfilename(
            title="Import Config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
            cfg_path = self.controller.config_manager.config_path
            shutil.copy2(path, cfg_path)
            self.controller.config_manager.load()
            self.reload()
            self._show_save_toast("Config imported — restart recommended")
        except Exception as e:
            self._show_save_toast("Import failed: {}".format(e))

    def _show_save_toast(self, msg="Settings saved"):
        try:
            self.controller.show_toast("Config", msg)
        except Exception:
            pass
