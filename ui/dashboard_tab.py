# ui/dashboard_tab.py

import collections
import shlex
import tkinter as tk
from tkinter import ttk
import threading
import time
from ui.refresh_control import RefreshControl
from ui.empty_state import EmptyState
from ui.loading_spinner import LoadingSpinner


class DashboardTab(tk.Frame):
    """
    Live system dashboard.
    Sections: system metrics, history chart, network I/O, UPS, downloads,
    storage, docker, services, top processes, recent errors, last backup.
    All configurable data is read from ConfigManager.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._net_prev    = None   # (rx_bytes, tx_bytes, timestamp)
        self._history     = collections.deque(maxlen=30)  # {cpu, ram} dicts
        self._net_history = collections.deque(maxlen=30)  # {rx_bps, tx_bps} dicts
        self._build_ui()
        self._seed_history_from_db()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        # ---- Header ----
        header = tk.Frame(self, bg=self.theme.bg)
        header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(header, text="DASHBOARD", bg=self.theme.bg,
                 fg=self.theme.text, font=self.theme.font_title).pack(side="left")

        self.refresh_btn = tk.Button(header, text="⟳ Refresh", command=self.refresh)
        self.theme.style_button(self.refresh_btn)
        self.refresh_btn.pack(side="right")
        self._spinner = LoadingSpinner(header, self.theme)
        self._spinner.pack(side="right", padx=(0, 6))

        cfg_default = self.controller.config_manager.dashboard_refresh_interval
        self._rc = RefreshControl(header, self.controller, "dashboard",
                                  default=cfg_default, on_refresh=self.refresh)
        self._rc.pack(side="right", padx=(0, 12))

        self.last_updated_lbl = tk.Label(header, text="", bg=self.theme.bg,
                                          fg=self.theme.text_secondary, font=self.theme.font_small)
        self.last_updated_lbl.pack(side="right", padx=12)

        # ---- Scrollable body (inside a container so the overlay can cover it) ----
        self._body_container = tk.Frame(self, bg=self.theme.bg)
        self._body_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(self._body_container, bg=self.theme.bg, highlightthickness=0)
        scrollbar = tk.Scrollbar(self._body_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(canvas, bg=self.theme.bg)
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _mw(e):
            if e.num == 4:   canvas.yview_scroll(-1, "units")
            elif e.num == 5: canvas.yview_scroll(1,  "units")
            else:            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        for w in (canvas, self.body):
            w.bind("<MouseWheel>", _mw)
            w.bind("<Button-4>",   _mw)
            w.bind("<Button-5>",   _mw)

        # ---- Disconnected overlay (shown until first successful fetch) ----
        self._disconn_overlay = EmptyState(
            self._body_container, self.theme,
            icon="🔌",
            title="Not connected",
            subtitle="Connect to a server to view live metrics.",
            action_text="⚡ Connect",
            action_cmd=lambda: self.controller.tabs.select(0),
        )
        self._disconn_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ---- Row 1: Connection / Uptime / CPU Temp ----
        r1 = tk.Frame(self.body, bg=self.theme.bg)
        r1.pack(fill="x", padx=16, pady=6)
        self.card_connection = self._stat_card(r1, "Connection",  "--", self.theme.text_muted)
        self.card_uptime     = self._stat_card(r1, "Uptime",      "--", self.theme.blue)
        self.card_temp       = self._stat_card(r1, "CPU Temp",    "--", self.theme.orange)

        # ---- Row 2: CPU / RAM / Disk ----
        r2 = tk.Frame(self.body, bg=self.theme.bg)
        r2.pack(fill="x", padx=16, pady=6)
        self.card_cpu  = self._stat_card(r2, "CPU",    "--", self.theme.orange)
        self.card_ram  = self._stat_card(r2, "RAM",    "--", self.theme.purple)
        self.card_disk = self._stat_card(r2, "Disk /", "--", self.theme.cyan)

        # ---- History Chart ----
        self._section("System History  (CPU & RAM — last 30 readings)")
        chart_wrap = tk.Frame(self.body, bg=self.theme.surface_dark,
                              highlightbackground=self.theme.card_border,
                              highlightthickness=1)
        chart_wrap.pack(fill="x", padx=16, pady=(0, 8))

        self.hist_canvas = tk.Canvas(chart_wrap, bg=self.theme.surface_dark,
                                     height=160, highlightthickness=0)
        self.hist_canvas.pack(fill="x", padx=0, pady=0)
        self.hist_canvas.bind("<Configure>", lambda e: self._redraw_chart())

        # ---- Network Bandwidth Chart ----
        self._section("Network History  (RX & TX — last 30 readings)")
        net_wrap = tk.Frame(self.body, bg=self.theme.surface_dark,
                            highlightbackground=self.theme.card_border,
                            highlightthickness=1)
        net_wrap.pack(fill="x", padx=16, pady=(0, 8))
        self.net_canvas = tk.Canvas(net_wrap, bg=self.theme.surface_dark,
                                    height=130, highlightthickness=0)
        self.net_canvas.pack(fill="x", padx=0, pady=0)
        self.net_canvas.bind("<Configure>", lambda e: self._redraw_net_chart())

        # ---- Network I/O ----
        self._section("Network I/O")
        rnet = tk.Frame(self.body, bg=self.theme.bg)
        rnet.pack(fill="x", padx=16, pady=6)
        self.card_net_rx = self._stat_card(rnet, "Download (RX)", "--", self.theme.status_running)
        self.card_net_tx = self._stat_card(rnet, "Upload (TX)",   "--", self.theme.blue)

        # ---- UPS ----
        self._section("UPS")
        rups = tk.Frame(self.body, bg=self.theme.bg)
        rups.pack(fill="x", padx=16, pady=6)
        self.card_ups_battery = self._stat_card(rups, "Battery",      "--", self.theme.status_running)
        self.card_ups_load    = self._stat_card(rups, "Load",         "--", self.theme.yellow)
        self.card_ups_runtime = self._stat_card(rups, "Runtime Left", "--", self.theme.cyan)

        # ---- GPU ----
        self._section("GPU")
        rgpu = tk.Frame(self.body, bg=self.theme.bg)
        rgpu.pack(fill="x", padx=16, pady=6)
        self.card_gpu_util  = self._stat_card(rgpu, "GPU Util",  "--", self.theme.purple)
        self.card_gpu_vram  = self._stat_card(rgpu, "VRAM",      "--", self.theme.cyan)
        self.card_gpu_temp  = self._stat_card(rgpu, "GPU Temp",  "--", self.theme.orange)

        # ---- Downloads ----
        self._section("Downloads")
        rdl = tk.Frame(self.body, bg=self.theme.bg)
        rdl.pack(fill="x", padx=16, pady=6)
        self.card_sabnzbd = self._stat_card(rdl, "SABnzbd", "--", self.theme.text_muted)

        # ---- Storage ----
        self._section("Storage")
        self.storage_frame = tk.Frame(self.body, bg=self.theme.bg)
        self.storage_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._build_storage_table()

        # ---- Docker ----
        self._section("Docker Containers")
        self.docker_row = tk.Frame(self.body, bg=self.theme.bg)
        self.docker_row.pack(fill="x", padx=16, pady=6)
        self._build_docker_row()

        # ---- Services ----
        self._section("Services")
        rsvc_counts = tk.Frame(self.body, bg=self.theme.bg)
        rsvc_counts.pack(fill="x", padx=16, pady=(0, 6))
        self.card_svc_running = self._stat_card(rsvc_counts, "Running", "--", self.theme.status_running)
        self.card_svc_stopped = self._stat_card(rsvc_counts, "Stopped", "--", self.theme.status_stopped)

        self.svc_table = tk.Frame(self.body, bg=self.theme.bg)
        self.svc_table.pack(fill="x", padx=16, pady=(0, 8))
        self._build_service_table()

        # ---- Top Processes ----
        self._section("Top Processes (by CPU)")
        self.proc_table = tk.Frame(self.body, bg=self.theme.bg)
        self.proc_table.pack(fill="x", padx=16, pady=(0, 8))
        self._build_proc_table()

        # ---- Recent Errors ----
        self._section("Recent System Errors")
        alert_wrap = tk.Frame(self.body, bg=self.theme.surface_dark)
        alert_wrap.pack(fill="x", padx=16, pady=(0, 8))
        self.alert_text = tk.Text(
            alert_wrap, bg=self.theme.surface_dark, fg=self.theme.console_error,
            font=self.theme.font_mono, height=5, state="disabled",
            relief="flat", padx=8, pady=6, wrap="none",
        )
        self.alert_text.pack(fill="x")

        # ---- Last Backup ----
        self._section("Last Backup")
        backup_wrap = tk.Frame(self.body, bg=self.theme.surface_dark)
        backup_wrap.pack(fill="x", padx=16, pady=(0, 20))

        bh = tk.Frame(backup_wrap, bg=self.theme.surface_dark)
        bh.pack(fill="x", padx=8, pady=(6, 2))
        self.backup_dot = tk.Canvas(bh, width=12, height=12,
                                     bg=self.theme.surface_dark, highlightthickness=0)
        self.backup_dot.pack(side="left", padx=(0, 6))
        self.backup_status_lbl = tk.Label(bh, text="unknown",
                                           bg=self.theme.surface_dark,
                                           fg=self.theme.text_secondary, font=self.theme.font_small)
        self.backup_status_lbl.pack(side="left")

        self.backup_text = tk.Text(
            backup_wrap, bg=self.theme.surface_dark, fg=self.theme.console_output,
            font=self.theme.font_mono, height=4, state="disabled",
            relief="flat", padx=8, pady=4, wrap="none",
        )
        self.backup_text.pack(fill="x")

    # =========================================================
    # WIDGET BUILDERS
    # =========================================================
    def _section(self, text):
        tk.Label(self.body, text=text, bg=self.theme.bg, fg=self.theme.text_secondary,
                 font=self.theme.font_title).pack(anchor="w", padx=16, pady=(16, 4))

    def _stat_card(self, parent, label, value, accent):
        frame = tk.Frame(parent, bg=self.theme.card_bg,
                         highlightbackground=self.theme.card_border, highlightthickness=1)
        frame.pack(side="left", expand=True, fill="both", padx=6, pady=4, ipadx=12, ipady=10)
        tk.Label(frame, text=label, bg=self.theme.card_bg, fg=self.theme.text_muted,
                 font=self.theme.font_small).pack(anchor="w", padx=10, pady=(8, 2))
        lbl = tk.Label(frame, text=value, bg=self.theme.card_bg, fg=accent,
                       font=("Segoe UI", 20, "bold"))
        lbl.pack(anchor="w", padx=10, pady=(0, 8))
        return lbl

    def _table_header(self, parent, headers, weights, anchors=None):
        hdr = tk.Frame(parent, bg=self.theme.surface_dark)
        hdr.pack(fill="x")
        for i, (h, w) in enumerate(zip(headers, weights)):
            a = anchors[i] if anchors else "w"
            tk.Label(hdr, text=h, bg=self.theme.surface_dark, fg=self.theme.text_muted,
                     font=self.theme.font_small, anchor=a).grid(
                row=0, column=i, sticky="ew", padx=10, pady=4)
            hdr.columnconfigure(i, weight=w)
        return hdr

    def _build_storage_table(self):
        t = self.theme
        style = ttk.Style()
        style.configure("Storage.Treeview",
                        background=t.card_bg,
                        foreground=t.text,
                        fieldbackground=t.card_bg,
                        borderwidth=0,
                        rowheight=28,
                        font=t.font_mono)
        style.configure("Storage.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map("Storage.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])
        mounts = self.controller.config_manager.get_storage_mounts()
        cols = ("mount", "used", "total", "pct")
        self.storage_tree = ttk.Treeview(self.storage_frame, columns=cols,
                                          show="headings",
                                          height=max(1, len(mounts)),
                                          style="Storage.Treeview",
                                          selectmode="none")
        self.storage_tree.heading("mount", text="Mount",  anchor="w")
        self.storage_tree.heading("used",  text="Used",   anchor="e")
        self.storage_tree.heading("total", text="Total",  anchor="e")
        self.storage_tree.heading("pct",   text="Usage",  anchor="e")
        self.storage_tree.column("mount", width=260, minwidth=120, anchor="w", stretch=True)
        self.storage_tree.column("used",  width=90,  minwidth=60,  anchor="e", stretch=False)
        self.storage_tree.column("total", width=90,  minwidth=60,  anchor="e", stretch=False)
        self.storage_tree.column("pct",   width=80,  minwidth=50,  anchor="e", stretch=False)
        self.storage_tree.tag_configure("odd",  background=t.surface_dark, foreground=t.text)
        self.storage_tree.tag_configure("even", background=t.card_bg,      foreground=t.text)
        self.storage_tree.tag_configure("ok",   foreground=t.status_running)
        self.storage_tree.tag_configure("warn", foreground=t.yellow)
        self.storage_tree.tag_configure("crit", foreground=t.status_stopped)
        self.storage_tree.pack(fill="x")
        self.storage_rows = {}   # mount -> iid
        for idx, mount in enumerate(mounts):
            tag = "even" if idx % 2 == 0 else "odd"
            iid = self.storage_tree.insert("", "end",
                                            values=(mount, "--", "--", "--"),
                                            tags=(tag,))
            self.storage_rows[mount] = iid

    def _build_docker_row(self):
        self.docker_cards = {}
        docker_cfg = self.controller.config_manager.get_docker()
        for name in docker_cfg:
            frame = tk.Frame(self.docker_row, bg=self.theme.card_bg,
                             highlightbackground=self.theme.card_border, highlightthickness=1)
            frame.pack(side="left", expand=True, fill="both", padx=6, pady=4, ipadx=8, ipady=8)
            dot = tk.Canvas(frame, width=10, height=10,
                            bg=self.theme.card_bg, highlightthickness=0)
            dot.pack(pady=(8, 2))
            dot.create_oval(1, 1, 9, 9,
                            fill=self.theme.status_unknown, outline=self.theme.status_unknown)
            tk.Label(frame, text=name, bg=self.theme.card_bg, fg=self.theme.text,
                     font=self.theme.font_small, wraplength=100).pack(pady=(2, 2))
            status_lbl = tk.Label(frame, text="unknown", bg=self.theme.card_bg,
                                   fg=self.theme.text_secondary, font=self.theme.font_small)
            status_lbl.pack(pady=(0, 8))
            self.docker_cards[name] = {"dot": dot, "status_lbl": status_lbl}

    def _build_service_table(self):
        weights = [2, 3, 2]
        self._table_header(self.svc_table, ["Service", "Unit", "Status"], weights,
                           anchors=["w", "w", "e"])
        self.svc_rows = {}
        services_cfg = self.controller.config_manager.get_services()
        for idx, (name, data) in enumerate(services_cfg.items()):
            bg = self.theme.card_bg if idx % 2 == 0 else self.theme.surface_dark
            row = tk.Frame(self.svc_table, bg=bg)
            row.pack(fill="x")
            tk.Label(row, text=name, bg=bg, fg=self.theme.text,
                     font=self.theme.font_regular, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=10, pady=5)
            tk.Label(row, text=data["service"], bg=bg, fg=self.theme.text_muted,
                     font=self.theme.font_mono, anchor="w").grid(
                row=0, column=1, sticky="ew", padx=10, pady=5)
            status_lbl = tk.Label(row, text="unknown", bg=bg,
                                   fg=self.theme.status_unknown,
                                   font=self.theme.font_regular, anchor="e")
            status_lbl.grid(row=0, column=2, sticky="ew", padx=10, pady=5)
            for i, w in enumerate(weights):
                row.columnconfigure(i, weight=w)
            self.svc_rows[name] = status_lbl

    def _build_proc_table(self):
        t = self.theme
        style = ttk.Style()
        style.configure("Proc.Treeview",
                        background=t.card_bg,
                        foreground=t.text,
                        fieldbackground=t.card_bg,
                        borderwidth=0,
                        rowheight=28,
                        font=t.font_mono)
        style.configure("Proc.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map("Proc.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])
        cols = ("user", "cpu", "mem", "cmd")
        self.proc_tree = ttk.Treeview(self.proc_table, columns=cols,
                                       show="headings", height=5,
                                       style="Proc.Treeview", selectmode="none")
        self.proc_tree.heading("user", text="User",    anchor="w")
        self.proc_tree.heading("cpu",  text="CPU %",   anchor="e")
        self.proc_tree.heading("mem",  text="MEM %",   anchor="e")
        self.proc_tree.heading("cmd",  text="Command", anchor="w")
        self.proc_tree.column("user", width=140, minwidth=80,  anchor="w", stretch=True)
        self.proc_tree.column("cpu",  width=80,  minwidth=60,  anchor="e", stretch=False)
        self.proc_tree.column("mem",  width=80,  minwidth=60,  anchor="e", stretch=False)
        self.proc_tree.column("cmd",  width=300, minwidth=100, anchor="w", stretch=True)
        self.proc_tree.tag_configure("odd",  background=t.surface_dark, foreground=t.text)
        self.proc_tree.tag_configure("even", background=t.card_bg,      foreground=t.text)
        self.proc_tree.pack(fill="x")
        # pre-populate with placeholder rows
        self.proc_iids = []
        for i in range(5):
            tag = "even" if i % 2 == 0 else "odd"
            iid = self.proc_tree.insert("", "end", values=("--", "--", "--", "--"), tags=(tag,))
            self.proc_iids.append(iid)

    # =========================================================
    # SEED HISTORY FROM SQLITE
    # =========================================================
    def _seed_history_from_db(self):
        """Pre-populate in-memory history deques from SQLite so charts
        survive app restarts.  Called once after _build_ui."""
        try:
            cfg       = self.controller.config_manager
            server_id = (cfg.get_active_server() or {}).get("name", "default")
            self._server_id = server_id
            rows = self.controller.metrics_store.query_metrics(
                server_id, limit=self._history.maxlen)
            for r in rows:
                self._history.append({"cpu": r["cpu"], "ram": r["ram"]})
                self._net_history.append(
                    {"rx_bps": r["rx_bps"], "tx_bps": r["tx_bps"]})
            if self._history:
                self.after(100, self._redraw_chart)
                self.after(100, self._redraw_net_chart)
        except Exception:
            pass

    # =========================================================
    # HISTORY CHART
    # =========================================================
    def _redraw_chart(self):
        c   = self.hist_canvas
        w   = c.winfo_width()
        h   = c.winfo_height()
        if w < 20 or h < 20:
            return

        c.delete("all")
        t = self.theme

        PAD_L = 44   # room for Y-axis labels
        PAD_R = 14
        PAD_T = 12
        PAD_B = 22   # room for X-axis labels

        plot_w = w - PAD_L - PAD_R
        plot_h = h - PAD_T - PAD_B
        maxlen = self._history.maxlen  # 30

        # ---- Grid lines and Y labels ----
        for pct in (0, 25, 50, 75, 100):
            y = PAD_T + plot_h * (1.0 - pct / 100.0)
            c.create_line(PAD_L, y, w - PAD_R, y,
                          fill=t.card_border, dash=(3, 5))
            c.create_text(PAD_L - 6, y, text="{:3d}%".format(pct),
                          anchor="e", fill=t.text_muted,
                          font=("Consolas", 10))

        # ---- X-axis tick marks every 5 readings ----
        for i in range(0, maxlen + 1, 5):
            x = PAD_L + (i / (maxlen - 1)) * plot_w
            c.create_line(x, h - PAD_B, x, h - PAD_B + 4,
                          fill=t.card_border)
            label = "-{0}".format(maxlen - i) if i < maxlen else "now"
            c.create_text(x, h - PAD_B + 6, text=label, anchor="n",
                          fill=t.text_secondary, font=("Consolas", 10))

        # ---- No data placeholder ----
        if not self._history:
            c.create_text(w // 2, h // 2, text="Waiting for data…",
                          fill=t.text_secondary, font=t.font_small)
            return

        history_list = list(self._history)
        n = len(history_list)

        def _pts(key, color):
            points = []
            for i, entry in enumerate(history_list):
                # Align to right edge: oldest on left as chart fills
                x_frac = (maxlen - n + i) / float(maxlen - 1)
                x = PAD_L + x_frac * plot_w
                val = max(0.0, min(100.0, entry.get(key, 0)))
                y = PAD_T + plot_h * (1.0 - val / 100.0)
                points.append((x, y))

            if len(points) >= 2:
                flat = [coord for p in points for coord in p]
                c.create_line(*flat, fill=color, width=2,
                              smooth=True, joinstyle="round")
            # Latest value dot
            if points:
                lx, ly = points[-1]
                c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                              fill=color, outline=t.surface_dark, width=1)

        _pts("cpu", t.orange)
        _pts("ram", t.purple)

        # ---- Legend (top-right) ----
        leg_x = w - PAD_R - 4
        leg_y = PAD_T + 4
        box_w = 100
        c.create_rectangle(leg_x - box_w, leg_y, leg_x, leg_y + 16,
                            fill=t.surface_dark, outline=t.card_border)
        c.create_line(leg_x - box_w + 6, leg_y + 8,
                      leg_x - box_w + 20, leg_y + 8,
                      fill=t.orange, width=2)
        c.create_text(leg_x - box_w + 24, leg_y + 8, text="CPU",
                      anchor="w", fill=t.text_secondary, font=("Segoe UI", 10))
        c.create_line(leg_x - 54, leg_y + 8,
                      leg_x - 40, leg_y + 8,
                      fill=t.purple, width=2)
        c.create_text(leg_x - 36, leg_y + 8, text="RAM",
                      anchor="w", fill=t.text_secondary, font=("Segoe UI", 10))

        # ---- Latest values overlay (top-left) ----
        if history_list:
            last = history_list[-1]
            cpu_val = last.get("cpu", 0)
            ram_val = last.get("ram", 0)
            c.create_text(PAD_L + 6, PAD_T + 4,
                          text="CPU {:.0f}%  RAM {:.0f}%".format(cpu_val, ram_val),
                          anchor="nw", fill=t.text_secondary,
                          font=("Segoe UI", 10, "bold"))


    def _redraw_net_chart(self):
        c = self.net_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 20:
            return

        c.delete("all")
        t = self.theme

        PAD_L = 64   # wider for byte labels
        PAD_R = 14
        PAD_T = 12
        PAD_B = 22

        plot_w = w - PAD_L - PAD_R
        plot_h = h - PAD_T - PAD_B
        maxlen = self._net_history.maxlen

        if not self._net_history:
            c.create_text(w // 2, h // 2, text="Waiting for data…",
                          fill=t.text_secondary, font=t.font_small)
            return

        history_list = list(self._net_history)
        n = len(history_list)

        # Find peak bps for dynamic Y scale
        all_bps = [v for e in history_list for v in (e.get("rx_bps", 0), e.get("tx_bps", 0))]
        peak = max(all_bps) if all_bps else 1
        # Round up to a nice scale unit
        for unit in (1024, 10*1024, 100*1024, 512*1024,
                     1024**2, 5*1024**2, 10*1024**2, 50*1024**2,
                     100*1024**2, 500*1024**2, 1024**3):
            if peak <= unit:
                y_max = unit
                break
        else:
            y_max = peak * 1.2

        def _bps_label(bps):
            if bps >= 1024**3:   return "{:.1f}G".format(bps / 1024**3)
            if bps >= 1024**2:   return "{:.1f}M".format(bps / 1024**2)
            if bps >= 1024:      return "{:.0f}K".format(bps / 1024)
            return "{:.0f}B".format(bps)

        # Grid lines and Y labels
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            y = PAD_T + plot_h * (1.0 - frac)
            c.create_line(PAD_L, y, w - PAD_R, y,
                          fill=t.card_border, dash=(3, 5))
            c.create_text(PAD_L - 6, y, text=_bps_label(y_max * frac),
                          anchor="e", fill=t.text_secondary, font=("Consolas", 10))

        # X-axis ticks
        for i in range(0, maxlen + 1, 5):
            x = PAD_L + (i / (maxlen - 1)) * plot_w
            c.create_line(x, h - PAD_B, x, h - PAD_B + 4, fill=t.card_border)
            label = "-{0}".format(maxlen - i) if i < maxlen else "now"
            c.create_text(x, h - PAD_B + 6, text=label, anchor="n",
                          fill=t.text_secondary, font=("Consolas", 10))

        def _pts(key, color):
            points = []
            for i, entry in enumerate(history_list):
                x_frac = (maxlen - n + i) / float(maxlen - 1)
                x = PAD_L + x_frac * plot_w
                val = max(0.0, entry.get(key, 0))
                y = PAD_T + plot_h * (1.0 - val / y_max)
                points.append((x, y))
            if len(points) >= 2:
                flat = [coord for p in points for coord in p]
                c.create_line(*flat, fill=color, width=2,
                              smooth=True, joinstyle="round")
            if points:
                lx, ly = points[-1]
                c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                              fill=color, outline=t.surface_dark, width=1)

        _pts("rx_bps", t.status_running)   # green = download
        _pts("tx_bps", t.blue)             # blue  = upload

        # Legend
        leg_x = w - PAD_R - 4
        leg_y = PAD_T + 4
        box_w = 110
        c.create_rectangle(leg_x - box_w, leg_y, leg_x, leg_y + 16,
                            fill=t.surface_dark, outline=t.card_border)
        c.create_line(leg_x - box_w + 6, leg_y + 8,
                      leg_x - box_w + 20, leg_y + 8,
                      fill=t.status_running, width=2)
        c.create_text(leg_x - box_w + 24, leg_y + 8, text="RX",
                      anchor="w", fill=t.text_secondary, font=("Segoe UI", 10))
        c.create_line(leg_x - 50, leg_y + 8, leg_x - 36, leg_y + 8,
                      fill=t.blue, width=2)
        c.create_text(leg_x - 32, leg_y + 8, text="TX",
                      anchor="w", fill=t.text_secondary, font=("Segoe UI", 10))

        # Latest values overlay
        if history_list:
            last = history_list[-1]
            c.create_text(PAD_L + 6, PAD_T + 4,
                          text="RX {}  TX {}".format(
                              _bps_label(last.get("rx_bps", 0)) + "/s",
                              _bps_label(last.get("tx_bps", 0)) + "/s"),
                          anchor="nw", fill=t.text_secondary,
                          font=("Segoe UI", 10, "bold"))

    # =========================================================
    # REBUILD (called after config change)
    # =========================================================
    def rebuild_tables(self):
        if hasattr(self, "storage_tree"):
            self.storage_tree.destroy()
        for w in self.storage_frame.winfo_children():
            w.destroy()
        self._build_storage_table()

        for w in self.docker_row.winfo_children():
            w.destroy()
        self._build_docker_row()

        for w in self.svc_table.winfo_children():
            w.destroy()
        self._build_service_table()

    # =========================================================
    # REFRESH
    # =========================================================
    def _set_disconnected(self):
        m = self.theme.text_muted
        self.card_connection.config(text="Not connected", fg=m)
        for card in (self.card_uptime, self.card_temp, self.card_cpu,
                     self.card_ram, self.card_disk, self.card_net_rx,
                     self.card_net_tx, self.card_ups_battery,
                     self.card_ups_load, self.card_ups_runtime,
                     self.card_gpu_util, self.card_gpu_vram, self.card_gpu_temp):
            card.config(text="--", fg=m)
        self.last_updated_lbl.config(text="")
        self.refresh_btn.config(state="normal", text="⟳ Refresh")
        self._spinner.stop()
        self._disconn_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._disconn_overlay.lift()

    def refresh(self):
        if getattr(self, "_fetching", False): return
        if not self.controller.ssh.connected:
            self._set_disconnected()
            return
        server_id = (self.controller.config_manager.get_active_server() or {}).get("name", "default")
        if getattr(self, "_server_id", None) != server_id:
            self._history.clear()
            self._net_history.clear()
            self._net_prev = None
            self._seed_history_from_db()
        self._disconn_overlay.place_forget()
        self.refresh_btn.config(state="disabled", text="Refreshing…")
        self._spinner.start()
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh  = self.controller.ssh
            host = self.controller.config_manager.last_host

            self.after(0, lambda: self.card_connection.config(
                text=host, fg=self.theme.status_running))

            # -- Uptime --
            out, _, _ = ssh.run("uptime -p")
            uptime = out.strip().replace("up ", "") or "--"
            self.after(0, lambda: self.card_uptime.config(text=uptime))

            # -- CPU % --
            cpu_pct_hist = 0
            out, _, _ = ssh.run("nproc && cat /proc/loadavg")
            lines = out.strip().splitlines()
            try:
                cores = int(lines[0])
                load1 = float(lines[1].split()[0])
                pct   = min(int(load1 / cores * 100), 100)
                cpu_pct_hist = pct
                cpu_text  = str(pct) + "%"
                cpu_color = self._usage_color(pct)
            except Exception:
                cpu_text, cpu_color = "--", self.theme.text_muted
            self.after(0, lambda t=cpu_text, c=cpu_color: self.card_cpu.config(text=t, fg=c))

            # -- CPU Temperature --
            out, _, _ = ssh.run(
                "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0")
            try:
                temp_c = int(out.strip()) // 1000
                temp_text  = str(temp_c) + "°C"
                temp_color = (self.theme.status_running if temp_c < 70 else
                              self.theme.yellow if temp_c < 85 else
                              self.theme.status_stopped)
            except Exception:
                temp_text, temp_color = "--", self.theme.text_muted
            self.after(0, lambda t=temp_text, c=temp_color: self.card_temp.config(text=t, fg=c))

            # -- RAM --
            ram_pct_hist = 0
            out, _, _ = ssh.run("free -m | awk 'NR==2{printf \"%s %s\", $3, $2}'")
            try:
                used, total = map(int, out.strip().split())
                pct = int(used / total * 100)
                ram_pct_hist = pct
                ram_text  = (str(pct) + "%  (" +
                             str(used // 1024) + "G / " + str(total // 1024) + "G)")
                ram_color = self._usage_color(pct)
            except Exception:
                ram_text, ram_color = "--", self.theme.text_muted
            self.after(0, lambda t=ram_text, c=ram_color: self.card_ram.config(text=t, fg=c))

            # -- Record history and redraw chart --
            self._history.append({"cpu": cpu_pct_hist, "ram": ram_pct_hist})
            self.after(0, self._redraw_chart)

            # -- Disk / --
            disk_pct_hist = 0
            out, _, _ = ssh.run("df -h / | awk 'NR==2{print $3\"/\"$2\" (\"$5\")\"}'")
            disk_text = out.strip() or "--"
            try:
                pct_str    = disk_text.split("(")[1].rstrip("%)") if "(" in disk_text else "0"
                disk_pct_hist = int(pct_str)
                disk_color = self._usage_color(disk_pct_hist)
            except Exception:
                disk_text, disk_color = "--", self.theme.text_muted
            self.after(0, lambda t=disk_text, c=disk_color: self.card_disk.config(text=t, fg=c))

            # -- Network I/O rate --
            out, _, _ = ssh.run("cat /proc/net/dev")
            rx_total = tx_total = 0
            for line in out.splitlines()[2:]:
                parts = line.split()
                if len(parts) >= 10 and not parts[0].startswith("lo"):
                    try:
                        rx_total += int(parts[1])
                        tx_total += int(parts[9])
                    except ValueError:
                        pass
            now = time.time()
            rx_bps = tx_bps = 0.0
            if self._net_prev is not None:
                prev_rx, prev_tx, prev_t = self._net_prev
                elapsed = max(now - prev_t, 1)
                rx_bps  = max(0.0, (rx_total - prev_rx) / elapsed)
                tx_bps  = max(0.0, (tx_total - prev_tx) / elapsed)
                rx_text = self._fmt_rate(rx_bps)
                tx_text = self._fmt_rate(tx_bps)
                self._net_history.append({"rx_bps": rx_bps, "tx_bps": tx_bps})
                self.after(0, self._redraw_net_chart)
            else:
                rx_text = tx_text = "Sampling..."
            self._net_prev = (rx_total, tx_total, now)

            # -- Persist snapshot to SQLite --
            try:
                cfg = self.controller.config_manager
                server_id = (cfg.get_active_server() or {}).get("name", "default")
                self.controller.metrics_store.insert_metric(
                    server_id=server_id,
                    cpu=float(cpu_pct_hist),
                    ram=float(ram_pct_hist),
                    disk=float(disk_pct_hist),
                    rx_bps=float(rx_bps),
                    tx_bps=float(tx_bps),
                )
            except Exception:
                pass
            self.after(0, lambda t=rx_text: self.card_net_rx.config(text=t))
            self.after(0, lambda t=tx_text: self.card_net_tx.config(text=t))

            # -- UPS --
            out, _, _ = ssh.run("upsc apcups@localhost 2>/dev/null")
            ups = {}
            for line in out.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    ups[k.strip()] = v.strip()
            battery    = ups.get("battery.charge", "--")
            load       = ups.get("ups.load",       "--")
            runtime_s  = ups.get("battery.runtime", None)
            try:
                secs = int(runtime_s) if runtime_s else 0
                runtime_text = str(secs // 3600) + "h " + str((secs % 3600) // 60) + "m"
            except Exception:
                runtime_text = "--"
            try:
                bat_pct   = int(float(battery))
                bat_color = (self.theme.status_running if bat_pct > 50 else
                             self.theme.yellow         if bat_pct > 20 else
                             self.theme.status_stopped)
            except Exception:
                bat_color = self.theme.text_muted
            bat_text  = (battery + "%") if battery != "--" else "--"
            load_text = (load    + "%") if load    != "--" else "--"
            self.after(0, lambda t=bat_text,     c=bat_color: self.card_ups_battery.config(text=t, fg=c))
            self.after(0, lambda t=load_text:                 self.card_ups_load.config(text=t))
            self.after(0, lambda t=runtime_text:              self.card_ups_runtime.config(text=t))

            # -- GPU (nvidia-smi, then rocm-smi, then lm-sensors fallback) --
            gpu_util = gpu_vram = gpu_temp = "--"
            out, _, _ = ssh.run(
                "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu "
                "--format=csv,noheader,nounits 2>/dev/null | head -1")
            if out and out.strip():
                parts = [p.strip() for p in out.strip().split(",")]
                if len(parts) == 4:
                    try:
                        gpu_util = parts[0] + "%"
                        vram_used_mb  = int(parts[1])
                        vram_total_mb = int(parts[2])
                        gpu_vram = "{}/{}G".format(
                            round(vram_used_mb  / 1024, 1),
                            round(vram_total_mb / 1024, 1))
                        gpu_temp = parts[3] + "°C"
                    except Exception:
                        pass
            if gpu_util == "--":
                # Try AMD via rocm-smi
                out, _, _ = ssh.run(
                    "rocm-smi --showuse --showmemuse --showtemp 2>/dev/null | "
                    "awk '/GPU use/{u=$NF} /GTT use/{v=$NF} /Temperature/{t=$NF} "
                    "END{print u\" \"v\" \"t}'")
                if out and out.strip() and out.strip() != "  ":
                    parts = out.strip().split()
                    if len(parts) >= 1 and parts[0] not in ("", "N/A"):
                        gpu_util = parts[0] + "%"
                    if len(parts) >= 2 and parts[1] not in ("", "N/A"):
                        gpu_vram = parts[1] + "% VRAM"
                    if len(parts) >= 3 and parts[2] not in ("", "N/A"):
                        gpu_temp = parts[2] + "°C"
            if gpu_util == "--":
                # lm-sensors — try to find a GPU chip
                out, _, _ = ssh.run(
                    "sensors 2>/dev/null | grep -A5 -i 'amdgpu\\|nouveau\\|nvidia' | "
                    "grep -i 'temp\\|junction\\|edge' | head -1 | "
                    "awk '{for(i=1;i<=NF;i++) if($i~/\\+[0-9]/) {print $i; exit}}'")
                if out and out.strip():
                    gpu_temp = out.strip().lstrip("+")
                    gpu_util = "n/a"
                    gpu_vram = "n/a"
            def _update_gpu(u=gpu_util, v=gpu_vram, t=gpu_temp):
                t_color = (self.theme.status_running if gpu_temp == "--" or gpu_temp in ("n/a",) else
                           self.theme.status_running if int(''.join(c for c in gpu_temp if c.isdigit()) or 0) < 75 else
                           self.theme.yellow         if int(''.join(c for c in gpu_temp if c.isdigit()) or 0) < 90 else
                           self.theme.status_stopped)
                self.card_gpu_util.config(text=u)
                self.card_gpu_vram.config(text=v)
                self.card_gpu_temp.config(text=t, fg=t_color)
            self.after(0, _update_gpu)

            # -- CPU Temperature (enhanced: prefer lm-sensors package temp) --
            out, _, _ = ssh.run(
                "sensors 2>/dev/null | grep -E 'Package id|Tdie|Tctl|k10temp' | "
                "head -1 | grep -oP '\\+[0-9.]+°C' | head -1 || "
                "awk '{print int($1/1000)}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
            if out and out.strip():
                raw = out.strip().lstrip("+").replace("°C", "").strip()
                try:
                    temp_c     = float(raw)
                    temp_text  = "{:.0f}°C".format(temp_c)
                    temp_color = (self.theme.status_running if temp_c < 70 else
                                  self.theme.yellow         if temp_c < 85 else
                                  self.theme.status_stopped)
                    self.after(0, lambda t=temp_text, c=temp_color: self.card_temp.config(text=t, fg=c))
                except Exception:
                    pass

            # -- SABnzbd --
            out, _, _ = ssh.run("systemctl is-active sabnzbdplus 2>/dev/null")
            sab_state = out.strip() or "unknown"
            sab_color = (self.theme.status_running if sab_state == "active" else
                         self.theme.status_stopped)
            self.after(0, lambda t=sab_state, c=sab_color: self.card_sabnzbd.config(text=t, fg=c))

            # -- Storage breakdown (per-mount df for reliable parsing) --
            mounts = self.controller.config_manager.get_storage_mounts()
            mount_args = " ".join(shlex.quote(m) for m in mounts)
            out, _, _ = ssh.run(
                'for m in {0}; do '
                'r=$(df -h "$m" 2>/dev/null | awk \'NR==2{{print $3"|"$2"|"$5}}\'); '
                '[ -n "$r" ] && echo "$m|$r"; '
                'done'.format(mount_args))
            storage_data = {}
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 4 and parts[0]:
                    storage_data[parts[0]] = (parts[1], parts[2], parts[3])
            def _update_storage(storage_data=storage_data):
                for mount, iid in self.storage_rows.items():
                    row_tag = "even" if list(self.storage_rows).index(mount) % 2 == 0 else "odd"
                    if mount in storage_data:
                        used_s, total_s, pct_s = storage_data[mount]
                        try:
                            pct_int = int(pct_s.rstrip("%"))
                            if pct_int >= 85:   clr_tag = "crit"
                            elif pct_int >= 60: clr_tag = "warn"
                            else:               clr_tag = "ok"
                        except Exception:
                            clr_tag = ""
                        self.storage_tree.item(iid,
                            values=(mount, used_s, total_s, pct_s),
                            tags=(row_tag, clr_tag))
                    else:
                        self.storage_tree.item(iid,
                            values=(mount, "N/A", "N/A", "N/A"),
                            tags=(row_tag,))
            self.after(0, _update_storage)

            # -- Docker health --
            docker_cfg = self.controller.config_manager.get_docker()
            dm = self.controller.docker_manager
            docker_names = {name: data["container"] for name, data in docker_cfg.items()
                            if name in self.docker_cards}
            docker_statuses = dm.get_statuses(list(docker_names.values()))
            for name, container in docker_names.items():
                status = docker_statuses.get(container, "unknown")
                color  = (self.theme.status_running  if status == "running"   else
                          self.theme.status_stopped  if status == "stopped"   else
                          self.theme.yellow          if status == "paused"    else
                          self.theme.cyan            if status == "scheduled" else
                          self.theme.status_unknown)
                def _upd_docker(n=name, s=status, c=color):
                    card = self.docker_cards[n]
                    card["dot"].delete("all")
                    card["dot"].create_oval(1, 1, 9, 9, fill=c, outline=c)
                    card["status_lbl"].config(text=s, fg=c)
                self.after(0, _upd_docker)

            # -- Services --
            services_cfg = self.controller.config_manager.get_services()
            sm = self.controller.service_manager
            service_units = {name: data["service"] for name, data in services_cfg.items()}
            service_statuses = sm.get_statuses(list(service_units.values()))
            running = stopped = 0
            for name, unit in service_units.items():
                status = service_statuses.get(unit, "unknown")
                if status == "running":
                    running += 1
                    color = self.theme.status_running
                elif status in ("stopped", "failed"):
                    stopped += 1
                    color = self.theme.status_stopped
                else:
                    color = self.theme.status_unknown
                def _upd_svc(n=name, s=status, c=color):
                    if n in self.svc_rows:
                        self.svc_rows[n].config(text=s, fg=c)
                self.after(0, _upd_svc)
            self.after(0, lambda: self.card_svc_running.config(text=str(running)))
            self.after(0, lambda: self.card_svc_stopped.config(
                text=str(stopped),
                fg=self.theme.status_stopped if stopped else self.theme.status_running))

            # -- Top Processes --
            out, _, _ = ssh.run(
                "ps aux --sort=-%cpu --no-header | head -5"
                " | awk '{print $1\"|\"$3\"|\"$4\"|\"$11}'")
            procs = [l.split("|") for l in out.strip().splitlines() if "|" in l]
            def _update_procs(procs=procs):
                for i, iid in enumerate(self.proc_iids):
                    if i < len(procs) and len(procs[i]) == 4:
                        u, c, m, cmd = procs[i]
                        cmd_s = cmd.split("/")[-1][:45]
                        self.proc_tree.item(iid, values=(u, c + "%", m + "%", cmd_s))
                    else:
                        self.proc_tree.item(iid, values=("--", "--", "--", "--"))
            self.after(0, _update_procs)

            # -- Recent Errors --
            out, _, _ = ssh.run(
                "journalctl -p err -n 5 --no-pager --output=short 2>/dev/null")
            alert_text = out.strip() or "No recent errors"
            def _upd_alerts(t=alert_text):
                self.alert_text.configure(state="normal")
                self.alert_text.delete("1.0", "end")
                self.alert_text.insert("end", t)
                self.alert_text.configure(state="disabled")
            self.after(0, _upd_alerts)

            # -- Last Backup --
            # Checks both backup.sh (config) and full-system-backup.sh
            # (restic) — a single "Success" dot here used to only reflect
            # the config backup, so the full-system backup could silently
            # fail for weeks without this at-a-glance widget ever noticing.
            def _classify(text):
                low = text.lower()
                if any(w in low for w in ("error", "fail", "fatal")):
                    return "Failed", self.theme.status_stopped, 0
                if any(w in low for w in ("success", "complete", "done", "finished")):
                    return "Success", self.theme.status_running, 2
                return "Unknown", self.theme.text_muted, 1

            cfg_out, _, _ = ssh.run(
                "tail -5 /var/log/media-backup.log 2>/dev/null || echo 'Log not found'")
            full_out, _, _ = ssh.run(
                "tail -5 /var/log/media-fullbackup.log 2>/dev/null || echo 'Log not found'")
            cfg_text, full_text = cfg_out.strip(), full_out.strip()
            cfg_status,  cfg_color,  cfg_rank  = _classify(cfg_text)
            full_status, full_color, full_rank = _classify(full_text)

            # Worst-of-both: Failed beats Unknown beats Success, so this
            # widget can't show green while either backup is actually broken.
            if cfg_rank <= full_rank:
                status_text, dot_color = cfg_status, cfg_color
            else:
                status_text, dot_color = full_status, full_color
            blog = "== Config Backup ({}) ==\n{}\n\n== Full System Backup ({}) ==\n{}".format(
                cfg_status, cfg_text, full_status, full_text)
            def _upd_backup(log=blog, dc=dot_color, st=status_text):
                self.backup_dot.delete("all")
                self.backup_dot.create_oval(1, 1, 11, 11, fill=dc, outline=dc)
                self.backup_status_lbl.config(text=st, fg=dc)
                self.backup_text.configure(state="normal")
                self.backup_text.delete("1.0", "end")
                self.backup_text.insert("end", log)
                self.backup_text.configure(state="disabled")
            self.after(0, _upd_backup)

            # -- Alert rule evaluation --
            _temp_c = 0.0
            try:
                _temp_c = float(self.card_temp.cget("text").rstrip("°C"))
            except Exception:
                pass

            _disk_max = float(disk_pct_hist)
            for _mount, _iid in self.storage_rows.items():
                try:
                    _pct = float(str(self.storage_tree.item(_iid, "values")[3]).rstrip("%"))
                    if _pct > _disk_max:
                        _disk_max = _pct
                except Exception:
                    pass

            _metrics = {
                "cpu":  float(cpu_pct_hist),
                "ram":  float(ram_pct_hist),
                "disk": _disk_max,
                "temp": _temp_c,
            }
            self.after(0, lambda m=_metrics: self.controller.fire_metric_alerts(m))

            # -- Timestamp --
            ts = time.strftime("%H:%M:%S")
            self.after(0, lambda: self.last_updated_lbl.config(text="Updated " + ts))
            self.after(0, lambda: self.refresh_btn.config(state="normal", text="⟳ Refresh"))
            self.after(0, self._spinner.stop)

        # =========================================================
        # HELPERS
        # =========================================================
        finally:
            self._fetching = False
    def _usage_color(self, pct):
        t = self.theme
        if pct < 70:
            return t.status_running
        if pct < 85:
            return t.yellow
        return t.status_stopped

    def _fmt_rate(self, bps):
        if bps >= 1_000_000:
            return "{:.1f} MB/s".format(bps / 1_000_000)
        if bps >= 1_000:
            return "{:.1f} KB/s".format(bps / 1_000)
        return "{:.0f} B/s".format(bps)
