# ui/ports_tab.py
"""
Port & Socket viewer.
Uses `ss -tlnup` to show all TCP/UDP listening sockets with the owning process.
"""

import re
import threading
import tkinter as tk
from tkinter import ttk

from ui.refresh_control import RefreshControl


class PortsTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._all_rows  = []
        self._sort_col  = "port"
        self._sort_rev  = False
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="PORTS & SOCKETS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "ports",
                                  default=30, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Filter row
        filter_row = tk.Frame(self, bg=t.bg)
        filter_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(filter_row, text="Filter:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        fe = tk.Entry(filter_row, textvariable=self._filter_var,
                      font=t.font_regular, width=24)
        t.style_entry(fe)
        fe.pack(side="left", padx=(6, 8))
        tk.Label(filter_row, text="(port number, process name, or address)",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(side="left")

        # Protocol toggle
        self._show_tcp = tk.BooleanVar(value=True)
        self._show_udp = tk.BooleanVar(value=True)
        for var, lbl in [(self._show_tcp, "TCP"), (self._show_udp, "UDP")]:
            cb = tk.Checkbutton(filter_row, text=lbl, variable=var,
                                command=self._apply_filter,
                                bg=t.bg, fg=t.text,
                                selectcolor=t.bg, activebackground=t.bg,
                                font=t.font_small)
            cb.pack(side="right", padx=(0, 8))

        # Treeview
        cols   = ("proto", "port", "local_addr", "process", "pid")
        hdgs   = ("Proto", "Port", "Local Address", "Process", "PID")
        widths = (60, 70, 220, 260, 70)
        stretches = {"local_addr", "process"}

        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Ports.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("Ports.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("Ports.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings",
                                   style="Ports.Treeview", selectmode="browse")
        for col, hdr_txt, w in zip(cols, hdgs, widths):
            self._tree.heading(col, text=hdr_txt, anchor="w",
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, minwidth=30, anchor="w",
                              stretch=(col in stretches))

        self._tree.tag_configure("tcp",  foreground=t.cyan)
        self._tree.tag_configure("udp",  foreground=t.purple)
        self._tree.tag_configure("sys",  foreground=t.text_muted)
        self._tree.tag_configure("priv", foreground=t.yellow)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status bar
        self._status = tk.Label(self, text="Connect to server to view open ports",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            return
        self._status.config(text="Scanning ports…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            # TCP and UDP listening sockets with process info
            cmd = "ss -tlnup 2>/dev/null"
            out, _, _ = ssh.run(cmd)
            rows = self._parse(out)
            import time
            self.after(0, lambda: self._show(rows))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Error: {}".format(msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # PARSE
    # -----------------------------------------------------------------------
    def _parse(self, output):
        rows = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Netid"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            proto = parts[0].lower()   # tcp, udp, tcp6, udp6
            local = parts[4] if len(parts) > 4 else ""

            # Extract port from local address (last :port)
            port_str = ""
            if ":" in local:
                port_str = local.rsplit(":", 1)[-1]
            try:
                port_num = int(port_str)
            except ValueError:
                port_num = 0

            # Process info: users:(("name",pid=N,...))
            proc_name = ""
            pid_str   = ""
            proc_field = parts[-1] if parts[-1].startswith("users:") else ""
            if proc_field:
                m = re.search(r'"([^"]+)"', proc_field)
                if m:
                    proc_name = m.group(1)
                m2 = re.search(r'pid=(\d+)', proc_field)
                if m2:
                    pid_str = m2.group(1)

            # Normalise protocol label
            proto_short = "tcp" if "tcp" in proto else "udp"

            rows.append({
                "proto":      proto_short,
                "port":       port_num,
                "port_str":   port_str,
                "local_addr": local,
                "process":    proc_name,
                "pid":        pid_str,
            })
        return rows

    # -----------------------------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------------------------
    def _show(self, rows):
        self._all_rows = rows
        self._apply_filter()
        t = self.theme
        n_tcp = sum(1 for r in rows if r["proto"] == "tcp")
        n_udp = sum(1 for r in rows if r["proto"] == "udp")
        self._status.config(
            text="{} listening sockets  |  TCP: {}  UDP: {}".format(
                len(rows), n_tcp, n_udp),
            bg=t.surface_dark, fg=t.text_muted)

    def _apply_filter(self):
        flt   = self._filter_var.get().lower().strip()
        show_tcp = self._show_tcp.get()
        show_udp = self._show_udp.get()
        rows  = [r for r in self._all_rows
                 if (r["proto"] == "tcp" and show_tcp)
                 or (r["proto"] == "udp" and show_udp)]
        if flt:
            rows = [r for r in rows
                    if flt in r["port_str"]
                    or flt in r["process"].lower()
                    or flt in r["local_addr"].lower()]
        self._redraw(rows)

    def _redraw(self, rows=None):
        if rows is None:
            rows = self._all_rows
        key = self._sort_col
        rev = self._sort_rev
        if key == "port":
            rows = sorted(rows, key=lambda r: r["port"], reverse=rev)
        else:
            rows = sorted(rows, key=lambda r: str(r.get(key, "")), reverse=rev)

        self._tree.delete(*self._tree.get_children())
        for r in rows:
            # Tag: protocol colour, plus priv (<1024) or sys (no process)
            tags = [r["proto"]]
            if r["port"] < 1024:
                tags.append("priv")
            if not r["process"]:
                tags.append("sys")
            self._tree.insert("", "end", tags=tags, values=(
                r["proto"].upper(),
                r["port_str"],
                r["local_addr"],
                r["process"] or "—",
                r["pid"] or "—",
            ))

    def _sort(self, col):
        self._sort_rev = not self._sort_rev if self._sort_col == col else False
        self._sort_col = col
        self._apply_filter()

    def on_show(self):
        if self.controller.ssh.connected:
            self.refresh()
