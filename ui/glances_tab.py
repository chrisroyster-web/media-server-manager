# ui/glances_tab.py
"""
Glances real-time metrics tab.
API: http://HOST:61208/api/3/
Optional basic auth via username:password.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import base64
import json
import time

from ui.refresh_control import RefreshControl


def _make_headers(username="", password=""):
    headers = {"Accept": "application/json"}
    if username:
        creds = base64.b64encode("{}:{}".format(username, password).encode()).decode()
        headers["Authorization"] = "Basic {}".format(creds)
    return headers


def _get(host, port, path, username="", password="", api_ver=None):
    """Fetch from Glances API, auto-detecting v4 vs v3 if api_ver not given."""
    path = path.lstrip("/")
    headers = _make_headers(username, password)
    # Try caller-specified version first, then v4, then v3
    versions = [api_ver] if api_ver else [4, 3]
    last_err = None
    for v in versions:
        url = "http://{}:{}/api/{}/{}".format(host, port, v, path)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode()), v
        except urllib.error.HTTPError as e:
            if e.code == 404:
                last_err = e
                continue
            raise
    raise last_err


def _fmt_bytes(b, suffix="B/s"):
    for unit in ("", "K", "M", "G", "T"):
        if abs(b) < 1024.0:
            return "{:.1f} {}{}".format(b, unit, suffix)
        b /= 1024.0
    return "{:.1f} P{}".format(b, suffix)


def _fmt_size(b):
    return _fmt_bytes(b, suffix="B")


class GlancesTab(tk.Frame):

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
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="GLANCES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "glances",
                                  default=10, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._c_cpu   = self._stat_card(cards, "CPU",      "--", t.cyan)
        self._c_ram   = self._stat_card(cards, "RAM",      "--", t.status_running)
        self._c_swap  = self._stat_card(cards, "Swap",     "--", t.yellow)
        self._c_load  = self._stat_card(cards, "Load 1m",  "--", t.text_muted)
        self._c_procs = self._stat_card(cards, "Processes","--", t.text_muted)

        # Sub-tabs
        nb_style = ttk.Style()
        nb_style.configure("GL.TNotebook",
                           background=t.bg, borderwidth=0)
        nb_style.configure("GL.TNotebook.Tab",
                           background=t.surface_dark, foreground=t.text_muted,
                           padding=(12, 5), font=t.font_small)
        nb_style.map("GL.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="GL.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._tab_procs = tk.Frame(self._nb, bg=t.bg)
        self._tab_fs    = tk.Frame(self._nb, bg=t.bg)
        self._tab_net   = tk.Frame(self._nb, bg=t.bg)
        self._tab_diskio= tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._tab_procs,  text="  Processes  ")
        self._nb.add(self._tab_fs,     text="  Filesystems  ")
        self._nb.add(self._tab_net,    text="  Network  ")
        self._nb.add(self._tab_diskio, text="  Disk I/O  ")

        self._build_procs_tab()
        self._build_fs_tab()
        self._build_net_tab()
        self._build_diskio_tab()

        # Status bar
        self._status = tk.Label(
            self, text="Configure Glances in Settings to get started",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    def _stat_card(self, parent, label, value, color):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    def _make_tree(self, parent, cols, style_name):
        t = self.theme
        style = ttk.Style()
        style.configure("{}.Treeview".format(style_name),
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=24, font=t.font_mono)
        style.configure("{}.Treeview.Heading".format(style_name),
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("{}.Treeview".format(style_name),
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])
        col_ids = [c[0] for c in cols]
        tree = ttk.Treeview(parent, columns=col_ids, show="headings",
                            style="{}.Treeview".format(style_name))
        for cid, w, lbl, anch in cols:
            tree.heading(cid, text=lbl, anchor=anch)
            tree.column(cid, width=w, minwidth=40, anchor=anch,
                        stretch=(cid == col_ids[-1]))
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _build_procs_tab(self):
        cols = [
            ("pid",    55,  "PID",      "e"),
            ("name",  180,  "Name",     "w"),
            ("user",   90,  "User",     "w"),
            ("cpu",    70,  "CPU%",     "e"),
            ("mem",    70,  "MEM%",     "e"),
            ("virt",   90,  "VIRT",     "e"),
            ("res",    90,  "RES",      "e"),
            ("status", 70,  "Status",   "w"),
            ("cmd",   240,  "Command",  "w"),
        ]
        self._proc_tree = self._make_tree(self._tab_procs, cols, "GL.Proc")
        t = self.theme
        self._proc_tree.tag_configure("high_cpu", foreground=t.status_stopped_text)
        self._proc_tree.tag_configure("mid_cpu",  foreground=t.yellow)

    def _build_fs_tab(self):
        cols = [
            ("mnt",    160, "Mount",    "w"),
            ("fs",     100, "FS Type",  "w"),
            ("used",   100, "Used",     "e"),
            ("free",   100, "Free",     "e"),
            ("total",  100, "Total",    "e"),
            ("pct",     80, "Use%",     "e"),
        ]
        self._fs_tree = self._make_tree(self._tab_fs, cols, "GL.FS")
        t = self.theme
        self._fs_tree.tag_configure("warn",  foreground=t.yellow)
        self._fs_tree.tag_configure("crit",  foreground=t.status_stopped_text)

    def _build_net_tab(self):
        cols = [
            ("iface",  120, "Interface","w"),
            ("rx",     120, "RX/s",     "e"),
            ("tx",     120, "TX/s",     "e"),
            ("rx_cum", 130, "RX Total", "e"),
            ("tx_cum", 130, "TX Total", "e"),
            ("speed",  100, "Speed",    "e"),
        ]
        self._net_tree = self._make_tree(self._tab_net, cols, "GL.Net")

    def _build_diskio_tab(self):
        cols = [
            ("disk",   120, "Disk",     "w"),
            ("read",   130, "Read/s",   "e"),
            ("write",  130, "Write/s",  "e"),
            ("r_count", 90, "Reads",    "e"),
            ("w_count", 90, "Writes",   "e"),
        ]
        self._diskio_tree = self._make_tree(self._tab_diskio, cols, "GL.DIO")

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.glances_host:
            self._status.config(
                text="No host configured — add it in Settings > Glances",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        cfg  = self.controller.config_manager
        host = cfg.glances_host.removeprefix("https://").removeprefix("http://").strip("/")
        port = cfg.glances_port or "61208"
        user = cfg.glances_username
        pwd  = cfg.glances_password

        try:
            # Auto-detect API version on first call, then reuse
            cpu,    v = _get(host, port, "cpu",         user, pwd)
            mem,    _ = _get(host, port, "mem",         user, pwd, v)
            swap,   _ = _get(host, port, "memswap",     user, pwd, v)
            load,   _ = _get(host, port, "load",        user, pwd, v)
            procs,  _ = _get(host, port, "processlist", user, pwd, v)
            fs,     _ = _get(host, port, "fs",          user, pwd, v)
            net,    _ = _get(host, port, "network",     user, pwd, v)
            diskio, _ = _get(host, port, "diskio",      user, pwd, v)
            sysinfo = {}
            for ep in ("system", "core"):
                try:
                    sysinfo, _ = _get(host, port, ep, user, pwd, v)
                    if isinstance(sysinfo, dict) and sysinfo:
                        break
                except Exception:
                    pass
        except Exception as e:
            self.after(0, lambda err=str(e): self._status.config(
                text="Cannot reach Glances: {}".format(err),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
            return
        finally:
            self._fetching = False

        payload = dict(cpu=cpu, mem=mem, swap=swap, load=load,
                       procs=procs, fs=fs, net=net, diskio=diskio,
                       sysinfo=sysinfo)
        self.after(0, lambda: self._populate(payload))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M:%S"))))
        self.after(0, self._rc.schedule)

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, p):
        t = self.theme

        cpu  = p["cpu"]
        mem  = p["mem"]
        swap = p["swap"]
        load = p["load"]

        cpu_pct  = cpu.get("total", 0)
        ram_pct  = mem.get("percent", 0)
        swap_pct = swap.get("percent", 0)
        load_1   = load.get("min1", 0)

        def _pct_color(pct):
            return (t.status_stopped if pct > 90 else
                    t.yellow         if pct > 70 else
                    t.status_running)

        self._c_cpu.config(text="{:.1f}%".format(cpu_pct),
                           fg=_pct_color(cpu_pct))
        self._c_ram.config(text="{:.1f}%".format(ram_pct),
                           fg=_pct_color(ram_pct))
        self._c_swap.config(text="{:.1f}%".format(swap_pct),
                            fg=_pct_color(swap_pct))
        self._c_load.config(text="{:.2f}".format(load_1))
        self._c_procs.config(text=str(len(p["procs"])))

        # Processes
        self._proc_tree.delete(*self._proc_tree.get_children())
        procs_sorted = sorted(p["procs"],
                              key=lambda x: x.get("cpu_percent", 0),
                              reverse=True)[:60]
        for pr in procs_sorted:
            cpu_p = pr.get("cpu_percent", 0)
            tag   = ("high_cpu" if cpu_p > 50 else
                     "mid_cpu"  if cpu_p > 20 else "")
            name  = pr.get("name", "--")
            cmd   = " ".join(pr.get("cmdline", [name]) or [name])[:80]
            self._proc_tree.insert("", "end", tags=(tag,), values=(
                pr.get("pid", "--"),
                name,
                pr.get("username", "--"),
                "{:.1f}".format(cpu_p),
                "{:.1f}".format(pr.get("memory_percent", 0)),
                _fmt_size(pr.get("memory_info", {}).get("vms", 0)),
                _fmt_size(pr.get("memory_info", {}).get("rss", 0)),
                pr.get("status", "--"),
                cmd,
            ))

        # Filesystems
        self._fs_tree.delete(*self._fs_tree.get_children())
        for fs in p["fs"]:
            pct  = fs.get("percent", 0)
            tag  = ("crit" if pct > 90 else "warn" if pct > 75 else "")
            self._fs_tree.insert("", "end", tags=(tag,), values=(
                fs.get("mnt_point", "--"),
                fs.get("fs_type", "--"),
                _fmt_size(fs.get("used", 0)),
                _fmt_size(fs.get("free", 0)),
                _fmt_size(fs.get("size", 0)),
                "{:.1f}%".format(pct),
            ))

        # Network
        self._net_tree.delete(*self._net_tree.get_children())
        for iface in p["net"]:
            if iface.get("is_up") is False:
                continue
            speed = iface.get("speed", 0)
            speed_str = "{} Mb/s".format(speed) if speed else "--"
            self._net_tree.insert("", "end", values=(
                iface.get("interface_name", "--"),
                _fmt_bytes(iface.get("bytes_recv_rate", iface.get("rx", 0))),
                _fmt_bytes(iface.get("bytes_sent_rate", iface.get("tx", 0))),
                _fmt_size(iface.get("bytes_recv", 0)),
                _fmt_size(iface.get("bytes_sent", 0)),
                speed_str,
            ))

        # Disk I/O
        self._diskio_tree.delete(*self._diskio_tree.get_children())
        for disk in p["diskio"]:
            dname = disk.get("disk_name", "--")
            if dname.startswith("loop"):
                continue
            self._diskio_tree.insert("", "end", values=(
                dname,
                _fmt_bytes(disk.get("read_bytes_rate",  disk.get("read_bytes",  0))),
                _fmt_bytes(disk.get("write_bytes_rate", disk.get("write_bytes", 0))),
                disk.get("read_count",  "--"),
                disk.get("write_count", "--"),
            ))

        si  = p["sysinfo"]
        host_str = si.get("hostname", "") if isinstance(si, dict) else ""
        self._status.config(
            text="{}  ·  CPU {:.1f}%  ·  RAM {:.1f}%  ·  Load {:.2f}".format(
                host_str, cpu_pct, ram_pct, load_1),
            bg=t.surface_dark, fg=t.text_muted)
