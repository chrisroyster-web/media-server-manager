# ui/bandwidth_tab.py
"""
vnstat bandwidth history tab.
Shows daily/monthly traffic totals per interface with a canvas bar chart.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import re

from ui.refresh_control import RefreshControl


class BandwidthTab(tk.Frame):

    BAR_H   = 18
    BAR_GAP = 4
    BAR_PAD = 48

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._ifaces    = []
        self._selected  = tk.StringVar()
        self._mode      = tk.StringVar(value="daily")
        self._entries   = []
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="BANDWIDTH", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "bandwidth",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Controls row
        ctrl = tk.Frame(self, bg=t.bg)
        ctrl.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(ctrl, text="Interface:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._iface_cb = ttk.Combobox(ctrl, textvariable=self._selected,
                                       state="readonly", width=14)
        self._iface_cb.pack(side="left", padx=(6, 16))
        self._iface_cb.bind("<<ComboboxSelected>>", lambda _: self._draw())

        for label, val in [("Daily", "daily"), ("Monthly", "monthly")]:
            rb = tk.Radiobutton(ctrl, text=label, variable=self._mode, value=val,
                                command=self._draw,
                                bg=t.bg, fg=t.text, selectcolor=t.bg,
                                activebackground=t.bg, activeforeground=t.cyan,
                                font=t.font_small)
            rb.pack(side="left", padx=4)

        # Summary cards
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_rx    = self._stat_card(s_row, "Total RX",    "--", t.cyan)
        self._card_tx    = self._stat_card(s_row, "Total TX",    "--", t.purple)
        self._card_total = self._stat_card(s_row, "Combined",    "--", t.status_running)
        self._card_avg   = self._stat_card(s_row, "Daily Avg",   "--", t.text_muted)

        # Bar chart canvas
        chart_outer = tk.Frame(self, bg=t.bg)
        chart_outer.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._canvas = tk.Canvas(chart_outer, bg=t.surface_dark,
                                 highlightthickness=0)
        vsb = tk.Scrollbar(chart_outer, orient="vertical",
                           command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda _: self._draw())
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(
                              int(-1 * (e.delta / 120)), "units"))
        self._canvas.bind("<Button-4>",
                          lambda e: self._canvas.yview_scroll(-1, "units"))
        self._canvas.bind("<Button-5>",
                          lambda e: self._canvas.yview_scroll(1, "units"))

        # Status bar
        self._status = tk.Label(self, text="Press 'Refresh' to load bandwidth data",
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
                       font=("Segoe UI Semibold", 18))
        lbl.pack(anchor="w")
        return lbl

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected", fg=self.theme.status_stopped)
            return
        self._status.config(text="Loading bandwidth data…", fg=self.theme.text_muted)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        ssh = self.controller.ssh
        out, _, _ = ssh.run("command -v vnstat 2>/dev/null && echo FOUND")
        has_vnstat = "FOUND" in (out or "")

        if has_vnstat:
            self._fetch_vnstat(ssh)
        else:
            self._fetch_procnet(ssh)

    def _fetch_vnstat(self, ssh):
        iface_out, _, _ = ssh.run("vnstat --iflist 2>/dev/null")
        ifaces = re.findall(r'\b([a-z][a-z0-9]+(?:\.[0-9]+)?)\b', iface_out or "")
        ifaces = [i for i in ifaces if i not in ("Available", "interfaces", "and") and len(i) > 1]
        if not ifaces:
            proc, _, _ = ssh.run("awk 'NR>2{print $1}' /proc/net/dev | tr -d ':'")
            ifaces = [i.strip() for i in (proc or "").splitlines()
                      if i.strip() and i.strip() not in ("lo", "")]

        results = {}
        for iface in ifaces[:8]:
            import json
            j_out, _, j_code = ssh.run("vnstat -i {} --json 2>/dev/null".format(iface))
            if j_code == 0 and j_out and j_out.strip():
                try:
                    results[iface] = json.loads(j_out)
                except Exception:
                    pass

        if not results:
            plain, _, _ = ssh.run("vnstat 2>/dev/null")
            self.after(0, lambda t=(plain or "No vnstat data"):
                self._status.config(text=t[:200], fg=self.theme.text_muted))
            return

        self.after(0, lambda: self._populate(results, list(results.keys())))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M"))))
        self.after(0, self._rc.schedule)

    def _fetch_procnet(self, ssh):
        """Fallback when vnstat isn't installed: read /proc/net/dev cumulative totals."""
        raw, _, _ = ssh.run("cat /proc/net/dev 2>/dev/null")
        if not raw:
            self.after(0, lambda: self._status.config(
                text="vnstat not installed. Install with: sudo apt install vnstat",
                fg=self.theme.status_stopped))
            return

        # /proc/net/dev columns: iface rx_bytes ... tx_bytes ...
        # Header is 2 lines; field order: bytes packets errs drop fifo frame compressed multicast
        skip = {"lo"}
        ifaces = []
        results = {}  # iface -> synthetic vnstat-like structure for _populate
        for line in raw.splitlines()[2:]:
            if ":" not in line:
                continue
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if iface in skip:
                continue
            fields = rest.split()
            if len(fields) < 9:
                continue
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])
            ifaces.append(iface)
            # Build a single synthetic "today" entry so _draw() works
            import datetime
            today = datetime.date.today()
            results[iface] = {
                "traffic": {
                    "day": [{
                        "date": {"year": today.year, "month": today.month, "day": today.day},
                        "rx": rx_bytes,
                        "tx": tx_bytes,
                    }],
                    "month": [{
                        "date": {"year": today.year, "month": today.month},
                        "rx": rx_bytes,
                        "tx": tx_bytes,
                    }],
                }
            }

        if not results:
            self.after(0, lambda: self._status.config(
                text="No interface data found",
                fg=self.theme.status_stopped))
            return

        def _show():
            self._populate(results, ifaces)
            self._status.config(
                text="Live totals since boot (install vnstat for history)  |  "
                     "sudo apt install vnstat",
                fg=self.theme.yellow)
            self._last_lbl.config(text="Updated {}".format(time.strftime("%H:%M")))

        self.after(0, _show)
        self.after(0, self._rc.schedule)

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, results, ifaces):
        self._data = results
        self._ifaces = list(results.keys())
        self._iface_cb["values"] = self._ifaces
        if self._ifaces and self._selected.get() not in self._ifaces:
            self._selected.set(self._ifaces[0])
        self._draw()
        self._status.config(
            text="vnstat data for: {}".format(", ".join(self._ifaces)),
            fg=self.theme.text_muted)

    def _draw(self):
        t = self.theme
        iface = self._selected.get()
        mode  = self._mode.get()
        if not hasattr(self, "_data") or iface not in self._data:
            return

        idata = self._data[iface]
        # Extract entries from JSON
        import json
        entries = []
        if mode == "daily":
            days = idata.get("traffic", {}).get("day", [])
            for d in days[-30:]:
                date_d = d.get("date", {})
                label  = "{}-{:02d}-{:02d}".format(
                    date_d.get("year", ""), date_d.get("month", 0),
                    date_d.get("day", 0))
                rx = d.get("rx", 0)
                tx = d.get("tx", 0)
                entries.append((label, rx, tx))
        else:
            months = idata.get("traffic", {}).get("month", [])
            for m in months[-12:]:
                date_m = m.get("date", {})
                label  = "{}-{:02d}".format(date_m.get("year", ""), date_m.get("month", 0))
                rx = m.get("rx", 0)
                tx = m.get("tx", 0)
                entries.append((label, rx, tx))

        entries.reverse()  # newest first
        self._entries = entries

        # Summary cards
        total_rx    = sum(e[1] for e in entries)
        total_tx    = sum(e[2] for e in entries)
        total_both  = total_rx + total_tx
        avg_daily   = total_both / len(entries) if entries else 0

        self._card_rx.config(text=self._fmt(total_rx))
        self._card_tx.config(text=self._fmt(total_tx))
        self._card_total.config(text=self._fmt(total_both))
        self._card_avg.config(text=self._fmt(avg_daily))

        # Draw chart
        self._canvas.delete("all")
        if not entries:
            self._canvas.create_text(200, 30, text="No data",
                                     fill=t.text_muted, font=t.font_small)
            return

        cw = self._canvas.winfo_width() or 600
        max_val = max((e[1] + e[2]) for e in entries) or 1
        bar_h   = self.BAR_H
        gap     = self.BAR_GAP
        pad_l   = self.BAR_PAD
        row_h   = bar_h * 2 + gap * 3

        for i, (label, rx, tx) in enumerate(entries):
            y0 = i * row_h + gap
            self._canvas.create_text(pad_l - 4, y0 + row_h // 2,
                                     text=label, fill=t.text_muted,
                                     font=t.font_small, anchor="e")
            avail = cw - pad_l - 60
            rx_w = int(avail * rx / max_val)
            self._canvas.create_rectangle(pad_l, y0, pad_l + rx_w, y0 + bar_h,
                                          fill=t.cyan, outline="")
            self._canvas.create_text(pad_l + rx_w + 4, y0 + bar_h // 2,
                                     text=self._fmt(rx), fill=t.cyan,
                                     font=t.font_small, anchor="w")
            y1 = y0 + bar_h + gap
            tx_w = int(avail * tx / max_val)
            self._canvas.create_rectangle(pad_l, y1, pad_l + tx_w, y1 + bar_h,
                                          fill=t.purple, outline="")
            self._canvas.create_text(pad_l + tx_w + 4, y1 + bar_h // 2,
                                     text=self._fmt(tx), fill=t.purple,
                                     font=t.font_small, anchor="w")

        total_h = len(entries) * row_h + gap
        self._canvas.configure(scrollregion=(0, 0, cw, total_h))

    # =========================================================
    # HELPERS
    # =========================================================
    @staticmethod
    def _fmt(b):
        """Format bytes."""
        if b is None:
            return "--"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return "{:.1f} {}".format(b, unit)
            b /= 1024
        return "{:.1f} PB".format(b)
