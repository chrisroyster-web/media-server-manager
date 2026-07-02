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


def _chart(host, port, chart, after=-60, points=60):
    path = "data?chart={}&after={}&points={}&format=json&options=absolute".format(
        chart, after, points)
    return _get(host, port, path)


def _chart_latest(host, port, chart):
    """Return {dim: value} for the most recent reading using the chart metadata
    endpoint, which always carries current latest_values without null rows."""
    info = _get(host, port, "chart?chart={}".format(chart))
    dims = info.get("dimension_names", [])
    vals = info.get("latest_values", [])
    return {d: (v if v is not None else 0) for d, v in zip(dims, vals)}


def _latest(data):
    """Return the most recent non-null data point from a Netdata data response.

    /api/v1/chart has dimension_names + latest_values at the top level.
    /api/v1/data only has labels (["time", dim1, dim2, ...]) + data rows.
    Both formats are handled here.
    """
    try:
        dims = data.get("dimension_names")
        lv   = data.get("latest_values")
        if dims is None:
            # /api/v1/data format — skip the leading "time" label
            dims = [l for l in data.get("labels", []) if l != "time"]
        if not dims:
            return {}
        if lv is not None:
            return {d: (v if v is not None else 0) for d, v in zip(dims, lv)}
        for row in reversed(data.get("data", [])):
            vals = row[1:]
            if any(v is not None for v in vals):
                return {d: (v if v is not None else 0) for d, v in zip(dims, vals)}
        return {}
    except Exception:
        return {}


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
        t = self.theme
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
        t = self.theme
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
        t = self.theme
        f = self._tab_network

        cols = [
            ("iface",   120, "Interface","w"),
            ("rx",      120, "RX/s",     "e"),
            ("tx",      120, "TX/s",     "e"),
            ("rx_total",130, "RX Total", "e"),
            ("tx_total",130, "TX Total", "e"),
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
            info = _get(host, port, "info")

            # CPU
            cpu_data  = _chart(host, port, "system.cpu")
            cpu_vals  = _latest(cpu_data)
            cpu_pct   = 100.0 - cpu_vals.get("idle", 100.0)

            # RAM
            ram_data  = _chart(host, port, "system.ram")
            ram_vals  = _latest(ram_data)
            ram_used  = ram_vals.get("used", 0) + ram_vals.get("buffers", 0) + ram_vals.get("cached", 0)
            ram_total = sum(v for v in ram_vals.values() if isinstance(v, (int, float)))
            ram_pct   = (ram_used / ram_total * 100) if ram_total else 0

            # Disk I/O (aggregate)
            try:
                dio_data = _chart(host, port, "disk.sda")
                dio_vals = _latest(dio_data)
                dio_str  = "R:{:.0f}  W:{:.0f} KiB/s".format(
                    abs(dio_vals.get("reads", 0)),
                    abs(dio_vals.get("writes", 0)))
            except Exception:
                dio_str = "--"

            # Network summary (eth0 fallback)
            try:
                net_vals = _chart_latest(host, port, "net.eth0")
                rx = abs(net_vals.get("received", net_vals.get("InOctets", 0)) or 0)
                tx = abs(net_vals.get("sent",     net_vals.get("OutOctets", 0)) or 0)
                net_str = "↓{:.0f}  ↑{:.0f} kb/s".format(rx, tx)
            except Exception:
                net_str = "--"

            # All disk space charts
            try:
                charts   = _get(host, port, "charts")
                space_charts = [k for k in charts.get("charts", {})
                                if k.startswith("disk_space.")]
                disk_spaces = {}
                for sc in space_charts[:12]:
                    try:
                        sd = _chart(host, port, sc)
                        sv = _latest(sd)
                        disk_spaces[sc] = sv
                    except Exception:
                        pass

                disk_io_charts = [k for k in charts.get("charts", {})
                                  if k.startswith("disk.")]
                disk_ios = {}
                for dc in disk_io_charts[:12]:
                    try:
                        dd = _chart(host, port, dc)
                        dv = _latest(dd)
                        disk_ios[dc] = dv
                    except Exception:
                        pass

                net_charts = [k for k in charts.get("charts", {})
                              if k.startswith("net.")]
                net_ifaces = {}
                for nc in net_charts[:12]:
                    try:
                        # Use chart metadata for latest_values — avoids null rows
                        nv = _chart_latest(host, port, nc)
                        # Fetch 24-hour totals (group=sum gives a single summed point)
                        tot = _latest(_get(host, port,
                            "data?chart={}&after=-86400&points=1"
                            "&format=json&group=sum".format(nc)))
                        net_ifaces[nc] = {"current": nv, "total": tot}
                    except Exception:
                        pass
            except Exception:
                charts       = {}
                disk_spaces  = {}
                disk_ios     = {}
                net_ifaces   = {}

            payload = {
                "info":        info,
                "cpu_pct":     cpu_pct,
                "cpu_vals":    cpu_vals,
                "ram_pct":     ram_pct,
                "ram_vals":    ram_vals,
                "ram_total":   ram_total,
                "dio_str":     dio_str,
                "net_str":     net_str,
                "disk_spaces": disk_spaces,
                "disk_ios":    disk_ios,
                "net_ifaces":  net_ifaces,
            }
        except Exception as e:
            self.after(0, lambda: self._status.config(
                text="Cannot reach Netdata: {}".format(e),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            return
        finally:
            self._fetching = False

        self.after(0, lambda: self._populate(payload))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M:%S"))))
        self.after(0, self._rc.schedule)

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
            tot   = entry.get("total",   {})

            rx    = abs(nv.get("received", nv.get("InOctets",  0)) or 0)
            tx    = abs(nv.get("sent",     nv.get("OutOctets", 0)) or 0)

            # 24 h totals are in kilobits; convert to MiB for readability
            rx_t_kb = abs(tot.get("received", tot.get("InOctets",  0)) or 0)
            tx_t_kb = abs(tot.get("sent",     tot.get("OutOctets", 0)) or 0)
            rx_t_str = "{:.1f} MiB".format(rx_t_kb * 125 / 1_000_000) if rx_t_kb else "--"
            tx_t_str = "{:.1f} MiB".format(tx_t_kb * 125 / 1_000_000) if tx_t_kb else "--"

            self._net_tree.insert("", "end", values=(
                iface,
                "{:.1f} kb/s".format(rx),
                "{:.1f} kb/s".format(tx),
                rx_t_str,
                tx_t_str,
            ))

        ver_str = info.get("version", "?")
        self._status.config(
            text="Netdata v{}  ·  {}  ·  CPU {:.1f}%  RAM {:.1f}%".format(
                ver_str, info.get("hostname", ""), cpu_pct, ram_pct),
            bg=t.surface_dark, fg=t.text_muted)
