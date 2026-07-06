# ui/netdata_tab.py
"""
Netdata real-time metrics tab.
API: http://HOST:19999/api/v1/
No auth required by default.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import json
import time

from ui.refresh_control import RefreshControl


def _get(host, port, path):
    url = "http://{}:{}/api/v1/{}".format(host, port, path.lstrip("/"))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def _all_metrics(host, port):
    """
    One request for the latest value of EVERY chart on the server — replaces
    what used to be 50+ separate /api/v1/data and /api/v1/chart round trips
    every single refresh (one probe each for CPU/RAM, plus up to a dozen
    each of disk-space, disk-io, and network charts, discovered via a
    separate /api/v1/charts call). allmetrics already includes every chart
    ID as a top-level key, so chart discovery comes for free too.
    """
    return _get(host, port, "allmetrics?format=json")


def _chart_dims(all_metrics, chart_id):
    """{dim_name: value} for one chart, sliced out of an allmetrics response."""
    dims = (all_metrics.get(chart_id) or {}).get("dimensions") or {}
    return {name: (d.get("value") or 0) for name, d in dims.items()}


# Docker creates a virtual net.* chart per bridge network/veth pair, which
# drowns out the physical interfaces that actually matter on this tab.
_VIRTUAL_IFACE_PREFIXES = ("net.docker", "net.br-", "net.veth", "net.lo")


class MiniBar(tk.Canvas):
    """Tiny horizontal bar showing a percentage."""
    def __init__(self, parent, theme, width=120, height=12):
        super().__init__(parent, bg=theme.card_bg, width=width, height=height,
                         highlightthickness=0, bd=0)
        self._t = theme
        self._w = width
        self._h = height

    def set(self, pct, color=None):
        self.delete("all")
        pct = max(0.0, min(1.0, pct or 0.0))
        t = self._t
        c = color or (t.status_stopped if pct > 0.9 else
                      t.yellow          if pct > 0.7 else
                      t.status_running)
        self.create_rectangle(0, 0, self._w, self._h,
                              fill=t.surface_dark, outline="")
        self.create_rectangle(0, 0, int(self._w * pct), self._h,
                              fill=c, outline="")


class NetdataTab(tk.Frame):

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
        tk.Label(hdr, text="NETDATA", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "netdata",
                                  default=10, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards row
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._c_cpu  = self._stat_card(cards, "CPU",     "--", t.cyan)
        self._c_ram  = self._stat_card(cards, "RAM",     "--", t.status_running)
        self._c_disk = self._stat_card(cards, "Disk I/O","--", t.yellow)
        self._c_net  = self._stat_card(cards, "Network", "--", t.magenta if hasattr(t, "magenta") else t.cyan)

        # Sub-tabs
        nb_style = ttk.Style()
        nb_style.configure("ND.TNotebook",
                           background=t.bg, borderwidth=0)
        nb_style.configure("ND.TNotebook.Tab",
                           background=t.surface_dark, foreground=t.text_muted,
                           padding=(12, 5), font=t.font_small)
        nb_style.map("ND.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="ND.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._tab_system  = tk.Frame(self._nb, bg=t.bg)
        self._tab_disk    = tk.Frame(self._nb, bg=t.bg)
        self._tab_network = tk.Frame(self._nb, bg=t.bg)
        self._nb.add(self._tab_system,  text="  System  ")
        self._nb.add(self._tab_disk,    text="  Disks  ")
        self._nb.add(self._tab_network, text="  Network  ")

        self._build_system_tab()
        self._build_disk_tab()
        self._build_network_tab()

        # Status bar
        self._status = tk.Label(
            self, text="Configure Netdata in Settings to get started",
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

    # ---- System tab ----
    def _build_system_tab(self):
        f = self._tab_system

        cols = [
            ("metric",  200, "Metric",   "w"),
            ("value",   140, "Value",    "e"),
            ("bar",     160, "Usage",    "w"),
            ("detail",  300, "Detail",   "w"),
        ]
        self._sys_tree = self._make_tree(f, cols, "ND.System")

    # ---- Disk tab ----
    def _build_disk_tab(self):
        f = self._tab_disk

        cols = [
            ("disk",    120, "Disk",     "w"),
            ("reads",   110, "Reads/s",  "e"),
            ("writes",  110, "Writes/s", "e"),
            ("util",    100, "Util%",    "e"),
            ("space",   120, "Space",    "e"),
            ("mnt",     200, "Mount",    "w"),
        ]
        self._disk_tree = self._make_tree(f, cols, "ND.Disk")

    # ---- Network tab ----
    def _build_network_tab(self):
        f = self._tab_network

        cols = [
            ("iface",   160, "Interface","w"),
            ("rx",      160, "RX/s",     "e"),
            ("tx",      160, "TX/s",     "e"),
        ]
        self._net_tree = self._make_tree(f, cols, "ND.Net")

    def _make_tree(self, parent, cols, style_name):
        t = self.theme
        style = ttk.Style()
        style.configure("{}.Treeview".format(style_name),
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
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

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.netdata_host:
            self._status.config(
                text="No host configured — add it in Settings > Netdata",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        cfg  = self.controller.config_manager
        host = cfg.netdata_host.removeprefix("https://").removeprefix("http://").strip("/")
        port = cfg.netdata_port or "19999"

        try:
            info    = _get(host, port, "info")
            metrics = _all_metrics(host, port)

            # CPU
            cpu_vals = _chart_dims(metrics, "system.cpu")
            cpu_pct  = 100.0 - cpu_vals.get("idle", 100.0)

            # RAM
            ram_vals  = _chart_dims(metrics, "system.ram")
            ram_used  = ram_vals.get("used", 0) + ram_vals.get("buffers", 0) + ram_vals.get("cached", 0)
            ram_total = sum(v for v in ram_vals.values() if isinstance(v, (int, float)))
            ram_pct   = (ram_used / ram_total * 100) if ram_total else 0

            # Every disk-space / disk-io / network chart, sliced straight out
            # of the one allmetrics response instead of one request each.
            disk_spaces = {k: _chart_dims(metrics, k) for k in metrics
                           if k.startswith("disk_space.")}
            disk_ios    = {k: _chart_dims(metrics, k) for k in metrics
                           if k.startswith("disk.")}
            net_ifaces  = {k: {"current": _chart_dims(metrics, k)} for k in metrics
                           if k.startswith("net.")
                           and not k.startswith(_VIRTUAL_IFACE_PREFIXES)}

            # Disk I/O (aggregate summary card) — first physical disk found
            if disk_ios:
                dio_vals = next(iter(disk_ios.values()))
                dio_str  = "R:{:.0f}  W:{:.0f} KiB/s".format(
                    abs(dio_vals.get("reads", 0)), abs(dio_vals.get("writes", 0)))
            else:
                dio_str = "--"

            # Network summary card — prefer a real ethernet/wifi interface
            net_key = next((k for k in net_ifaces
                            if k.split(".", 1)[-1].startswith(("eth", "en", "wl"))),
                           next(iter(net_ifaces), None))
            if net_key:
                nv = net_ifaces[net_key]["current"]
                rx = abs(nv.get("received", nv.get("InOctets", 0)) or 0)
                tx = abs(nv.get("sent",     nv.get("OutOctets", 0)) or 0)
                net_str = "↓{:.0f}  ↑{:.0f} kb/s".format(rx, tx)
            else:
                net_str = "--"

            payload = {
                "info":        info,
                "cpu_pct":     cpu_pct,
                "cpu_vals":    cpu_vals,
                "ram_pct":     ram_pct,
                "ram_vals":    ram_vals,
                "ram_total":   ram_total,
                "dio_str":     dio_str,
                "net_str":     net_str,
                "disk_spaces": dict(list(disk_spaces.items())[:12]),
                "disk_ios":    dict(list(disk_ios.items())[:12]),
                "net_ifaces":  dict(list(net_ifaces.items())[:12]),
            }
        except Exception as e:
            self.after(0, lambda err=str(e): self._status.config(
                text="Cannot reach Netdata: {}".format(err),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            return
        finally:
            self._fetching = False
            self.after(0, self._rc.schedule)

        self.after(0, lambda: self._populate(payload))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M:%S"))))

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, p):
        t = self.theme

        cpu_pct  = p["cpu_pct"]
        ram_pct  = p["ram_pct"]

        # Cards
        self._c_cpu.config(text="{:.1f}%".format(cpu_pct),
                           fg=t.status_stopped if cpu_pct > 90 else
                              t.yellow         if cpu_pct > 70 else t.status_running)
        self._c_ram.config(text="{:.1f}%".format(ram_pct),
                           fg=t.status_stopped if ram_pct > 90 else
                              t.yellow         if ram_pct > 70 else t.status_running)
        self._c_disk.config(text=p["dio_str"])
        self._c_net.config( text=p["net_str"])

        # System tab
        self._sys_tree.delete(*self._sys_tree.get_children())
        info     = p["info"]
        cv       = p["cpu_vals"]
        rv       = p["ram_vals"]
        ram_gb   = p["ram_total"] / 1024 / 1024

        def _row(metric, value, detail=""):
            self._sys_tree.insert("", "end", values=(metric, value, "", detail))

        _row("CPU Total",  "{:.1f}%".format(cpu_pct),
             "usr:{:.1f}  sys:{:.1f}  nice:{:.1f}".format(
                 cv.get("user", cv.get("usr", 0)),
                 cv.get("system", cv.get("sys", 0)),
                 cv.get("nice", 0)))
        _row("CPU IOWait", "{:.1f}%".format(cv.get("iowait", cv.get("iowait", 0))),
             "softirq:{:.1f}  irq:{:.1f}".format(
                 cv.get("softirq", 0), cv.get("irq", 0)))
        _row("RAM Used",   "{:.1f}%".format(ram_pct),
             "{:.1f} / {:.1f} GB".format(
                 (rv.get("used", 0) + rv.get("buffers", 0) + rv.get("cached", 0)) / 1024 / 1024,
                 ram_gb))
        _row("RAM Free",   "{:.1f} GB".format(rv.get("free", 0) / 1024 / 1024))
        _row("RAM Cached", "{:.1f} GB".format(rv.get("cached", 0) / 1024 / 1024),
             "buffers:{:.1f} GB".format(rv.get("buffers", 0) / 1024 / 1024))

        os_name  = info.get("os_name",  "")
        kernel   = info.get("kernel_name", "")
        hostname = info.get("hostname",    "")
        ver      = info.get("version",     "")
        _row("Host",    hostname, "{} {}".format(os_name, kernel))
        _row("Netdata", "v{}".format(ver) if ver else "--")

        # Disk tab
        self._disk_tree.delete(*self._disk_tree.get_children())
        for sc, sv in p["disk_spaces"].items():
            mnt   = sc.replace("disk_space.", "").replace("_", "/")
            used  = sv.get("used",   0)
            avail = sv.get("avail",  sv.get("free", 0))
            total = used + avail
            pct   = "{:.1f}%".format(used / total * 100) if total else "--"

            # Match disk I/O
            disk_name = mnt.strip("/") or "root"
            ios  = p["disk_ios"]
            dkey = next((k for k in ios if disk_name in k), None)
            dv   = ios.get(dkey, {}) if dkey else {}
            reads  = "{:.0f}".format(abs(dv.get("reads",  0))) if dv else "--"
            writes = "{:.0f}".format(abs(dv.get("writes", 0))) if dv else "--"

            self._disk_tree.insert("", "end", values=(
                disk_name, reads, writes, pct,
                "{:.1f}/{:.1f} GB".format(used / 1024, total / 1024),
                "/" if mnt == "" else "/" + mnt,
            ))

        # Network tab
        self._net_tree.delete(*self._net_tree.get_children())
        for nc, entry in p["net_ifaces"].items():
            iface = nc.replace("net.", "")
            nv    = entry.get("current", {})

            rx    = abs(nv.get("received", nv.get("InOctets",  0)) or 0)
            tx    = abs(nv.get("sent",     nv.get("OutOctets", 0)) or 0)

            self._net_tree.insert("", "end", values=(
                iface,
                "{:.1f} kb/s".format(rx),
                "{:.1f} kb/s".format(tx),
            ))

        ver_str = info.get("version", "?")
        self._status.config(
            text="Netdata v{}  ·  {}  ·  CPU {:.1f}%  RAM {:.1f}%".format(
                ver_str, info.get("hostname", ""), cpu_pct, ram_pct),
            bg=t.surface_dark, fg=t.text_muted)
