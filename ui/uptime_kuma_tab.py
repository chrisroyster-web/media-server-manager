# ui/uptime_kuma_tab.py
"""
Uptime Kuma monitor status tab.
Uses the public status-page API — no authentication required if the
status page is public, or pass an API key for private instances.
"""

import tkinter as tk
from tkinter import ttk
import threading
import urllib.request
import urllib.error
import json
import time

from ui.refresh_control import RefreshControl

# Monitor status codes
_STATUS_TEXT = {0: "DOWN", 1: "UP", 2: "PENDING", 3: "MAINTENANCE"}
_STATUS_TAG  = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}


def _get(url, apikey=""):
    headers = {"Accept": "application/json"}
    if apikey:
        headers["Authorization"] = "Bearer {}".format(apikey)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())

def _api(host, port, slug, apikey=""):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    base = "http://{}:{}".format(host, port)
    page = _get("{}/api/status-page/{}".format(base, slug), apikey)
    hb_err = None
    try:
        hb = _get("{}/api/status-page/heartbeat/{}".format(base, slug), apikey)
    except Exception as e:
        hb     = {}
        hb_err = str(e)
    return page, hb, hb_err


class UptimeKumaTab(tk.Frame):

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
        tk.Label(hdr, text="UPTIME KUMA", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "uptime_kuma",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        cards = tk.Frame(self, bg=t.bg)
        cards.pack(fill="x", padx=16, pady=(0, 8))
        self._card_total       = self._stat_card(cards, "Total",       "--", t.cyan)
        self._card_up          = self._stat_card(cards, "Up",          "--", t.status_running)
        self._card_down        = self._stat_card(cards, "Down",        "--", t.status_stopped)
        self._card_maintenance = self._stat_card(cards, "Maintenance", "--", t.yellow)

        # Monitor tree
        style = ttk.Style()
        style.configure("UK.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=28, font=t.font_mono)
        style.configure("UK.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("UK.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        cols = ("status", "name", "type", "url", "uptime_24h", "uptime_7d", "ping", "last_check")
        self._tree = ttk.Treeview(tree_frame, columns=cols,
                                   show="headings", style="UK.Treeview")
        for col, w, lbl, anch in [
            ("status",     80,  "Status",    "center"),
            ("name",      200,  "Monitor",   "w"),
            ("type",       70,  "Type",      "w"),
            ("url",       260,  "Target",    "w"),
            ("uptime_24h", 80,  "24h Up%",   "e"),
            ("uptime_7d",  80,  "30d Up%",   "e"),
            ("ping",       70,  "Ping",      "e"),
            ("last_check",130,  "Last Check","w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anch)
            self._tree.column(col, width=w, minwidth=40,
                              anchor=anch, stretch=(col == "url"))

        self._tree.tag_configure("up",          foreground=t.status_running)
        self._tree.tag_configure("down",        foreground=t.status_stopped)
        self._tree.tag_configure("pending",     foreground=t.yellow)
        self._tree.tag_configure("maintenance", foreground=t.cyan)
        self._tree.tag_configure("group",
                                  background=t.surface_dark,
                                  foreground=t.text_muted,
                                  font=t.font_small)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status bar
        self._status = tk.Label(
            self, text="Configure Uptime Kuma in Settings to get started",
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

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.uptime_kuma_host:
            self._status.config(
                text="No host configured — add it in Settings > Uptime Kuma",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        self._refresh_btn.config(state="disabled")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        cfg  = self.controller.config_manager
        host = cfg.uptime_kuma_host
        port = cfg.uptime_kuma_port
        slug = cfg.uptime_kuma_slug or "default"
        key  = cfg.uptime_kuma_apikey

        try:
            page, hb, hb_err = _api(host, port, slug, key)
        except Exception as e:
            self.after(0, lambda err=str(e): self._status.config(
                text="Cannot reach Uptime Kuma: {}".format(err),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            return
        finally:
            self._fetching = False
            self.after(0, lambda: self._refresh_btn.config(state="normal"))

        self.after(0, lambda: self._populate(page, hb, hb_err))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M"))))
        self.after(0, self._rc.schedule)

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, data, hb_data, hb_err=None):
        t = self.theme

        groups     = data.get("publicGroupList", [])
        page_title = (data.get("config") or {}).get("title", "Status Page")

        # Heartbeat data: {monitor_id: [list of heartbeats]}
        hb_map     = hb_data.get("heartbeatList", {})
        # Uptime data: {"id_24": ratio, "id_720": ratio}
        uptime_map = hb_data.get("uptimeList", {})

        all_monitors = []
        for group in groups:
            for m in group.get("monitorList", []):
                all_monitors.append((group.get("name", ""), m))

        n_total = len(all_monitors)
        n_up    = 0
        n_down  = 0
        n_maint = 0

        self._tree.delete(*self._tree.get_children())

        current_group = None
        for group_name, m in all_monitors:
            if group_name != current_group:
                current_group = group_name
                if group_name:
                    self._tree.insert("", "end", tags=("group",), values=(
                        "", "▸ " + group_name, "", "", "", "", "", ""))

            mid = str(m.get("id", ""))

            # Status from heartbeat list
            hb_list     = hb_map.get(mid, [])
            latest      = hb_list[-1] if hb_list else {}
            status_code = latest.get("status", 2)

            if status_code == 1:
                n_up += 1
            elif status_code == 0:
                n_down += 1
            elif status_code == 3:
                n_maint += 1

            tag    = _STATUS_TAG.get(status_code, "pending")
            status = _STATUS_TEXT.get(status_code, "?")

            # Uptime %: keys are "{id}_24" (24 h) and "{id}_720" (720 h = 30 days)
            up_24h = uptime_map.get("{}_24".format(mid))
            up_30d = uptime_map.get("{}_720".format(mid))
            up_24h_str = "{:.1f}%".format(up_24h * 100) if up_24h is not None else "--"
            up_7d_str  = "{:.1f}%".format(up_30d * 100) if up_30d is not None else "--"

            # Ping from latest heartbeat
            ping = latest.get("ping")
            ping_str = "{} ms".format(int(ping)) if ping is not None else "--"

            # Last check time
            last_time = latest.get("time", "")
            try:
                ts = last_time[:19].replace("T", " ") if last_time else "--"
            except Exception:
                ts = "--"

            url   = m.get("url") or m.get("hostname") or (
                "(URL hidden — enable in Uptime Kuma monitor settings)"
                if not m.get("sendUrl") else "--"
            )
            mtype = (m.get("type") or "").upper()

            self._tree.insert("", "end", tags=(tag,), values=(
                status,
                m.get("name", "--"),
                mtype,
                url,
                up_24h_str,
                up_7d_str,
                ping_str,
                ts,
            ))

        # Cards
        self._card_total.config(text=str(n_total))
        self._card_up.config(
            text=str(n_up),
            fg=t.status_running if n_up else t.text_muted)
        self._card_down.config(
            text=str(n_down),
            fg=t.status_stopped if n_down else t.text_muted)
        self._card_maintenance.config(
            text=str(n_maint),
            fg=t.yellow if n_maint else t.text_muted)

        status_color = t.status_stopped if n_down else t.status_running
        status_text  = "{} — {} up  |  {} down  |  {} maintenance".format(
            page_title, n_up, n_down, n_maint)
        if hb_err:
            status_text += "  ·  Heartbeat API failed ({}): uptime unavailable".format(hb_err)
            status_color = t.yellow
        self._status.config(text=status_text, bg=t.surface_dark, fg=status_color)
