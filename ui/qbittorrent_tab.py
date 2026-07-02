# ui/qbittorrent_tab.py
"""
qBittorrent download manager tab.
Uses the qBittorrent Web API v2 (HTTP) — no SSH required.
"""

import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from ui.refresh_control import RefreshControl


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api(host, port, path, method="GET", data=None, cookies=None, timeout=10):
    url = "http://{}:{}/api/v2/{}".format(host, port, path)
    headers = {}
    if cookies:
        headers["Cookie"] = "; ".join("{}={}".format(k, v)
                                       for k, v in cookies.items())
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        # Collect Set-Cookie headers
        set_cookies = {}
        for k, v in r.headers.items():
            if k.lower() == "set-cookie" and "SID=" in v:
                sid = v.split("SID=")[1].split(";")[0]
                set_cookies["SID"] = sid
        return raw, set_cookies


def _fmt_speed(bps):
    if not bps:
        return "0 B/s"
    if bps < 1024:
        return "{} B/s".format(int(bps))
    if bps < 1024 ** 2:
        return "{:.1f} KB/s".format(bps / 1024)
    return "{:.1f} MB/s".format(bps / 1024 ** 2)


def _fmt_size(b):
    if not b:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return "{:.1f} {}".format(b, unit)
        b /= 1024
    return "{:.1f} PB".format(b)


def _fmt_eta(s):
    if s is None or s < 0 or s > 8_640_000:
        return "∞"
    h, r = divmod(int(s), 3600)
    m, s = divmod(r, 60)
    if h:
        return "{}h {}m".format(h, m)
    if m:
        return "{}m {}s".format(m, s)
    return "{}s".format(s)


_STATE_LABEL = {
    "downloading":  "↓ Downloading",
    "uploading":    "↑ Seeding",
    "stalledDL":    "↓ Stalled",
    "stalledUP":    "↑ Seeding",
    "pausedDL":     "⏸ Paused",
    "pausedUP":     "⏸ Paused",
    "queuedDL":     "⏳ Queued",
    "queuedUP":     "⏳ Queued",
    "checkingDL":   "⟳ Checking",
    "checkingUP":   "⟳ Checking",
    "forcedDL":     "↓ Forced",
    "forcedUP":     "↑ Forced",
    "moving":       "→ Moving",
    "error":        "✗ Error",
    "missingFiles": "✗ Missing",
    "unknown":      "? Unknown",
}

_STATE_TAG = {
    "downloading": "dl",
    "forcedDL":    "dl",
    "uploading":   "seed",
    "stalledUP":   "seed",
    "forcedUP":    "seed",
    "stalledDL":   "stall",
    "pausedDL":    "paused",
    "pausedUP":    "paused",
    "error":       "err",
    "missingFiles":"err",
}


# ---------------------------------------------------------------------------
# Tab
# ---------------------------------------------------------------------------

class QBittorrentTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller  = controller
        self.theme       = t
        self._cookies    = {}
        self._all_torrents = []
        self._torrents   = []
        self._sort_col   = "dlspeed"
        self._sort_rev   = True
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="QBITTORRENT", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "qbittorrent",
                                  default=10, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        card_row = tk.Frame(self, bg=t.bg)
        card_row.pack(fill="x", padx=16, pady=(0, 8))
        self._c_dl    = self._card(card_row, "Downloading", "--", t.cyan)
        self._c_seed  = self._card(card_row, "Seeding",     "--", t.status_running)
        self._c_pause = self._card(card_row, "Paused",      "--", t.text_muted)
        self._c_total = self._card(card_row, "Total",       "--", t.text)
        self._c_dlsp  = self._card(card_row, "↓ Speed",     "--", t.cyan)
        self._c_ulsp  = self._card(card_row, "↑ Speed",     "--", t.purple)

        # Toolbar
        toolbar = tk.Frame(self, bg=t.bg)
        toolbar.pack(fill="x", padx=16, pady=(0, 6))

        add_btn = tk.Button(toolbar, text="＋ Add URL / Magnet",
                            command=self._add_torrent)
        t.style_button(add_btn)
        add_btn.pack(side="left", padx=(0, 10))

        tk.Label(toolbar, text="Filter:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._filter_var = tk.StringVar(value="all")
        for val, lbl in [("all", "All"), ("downloading", "↓ DL"),
                          ("seeding", "↑ Seeding"), ("paused", "⏸ Paused"),
                          ("error", "✗ Error")]:
            rb = tk.Radiobutton(
                toolbar, text=lbl, variable=self._filter_var, value=val,
                command=self._apply_filter,
                bg=t.bg, fg=t.text, selectcolor=t.bg,
                activebackground=t.bg, activeforeground=t.cyan,
                font=t.font_small)
            rb.pack(side="left", padx=(6, 0))

        self._del_btn = tk.Button(toolbar, text="✕ Delete",
                                   command=self._delete_selected, state="disabled")
        t.style_button(self._del_btn)
        self._del_btn.pack(side="right", padx=(4, 0))

        self._resume_btn = tk.Button(toolbar, text="▶ Resume",
                                      command=lambda: self._torrent_action("resume"),
                                      state="disabled")
        t.style_button(self._resume_btn)
        self._resume_btn.pack(side="right", padx=(4, 0))

        self._pause_btn = tk.Button(toolbar, text="⏸ Pause",
                                     command=lambda: self._torrent_action("pause"),
                                     state="disabled")
        t.style_button(self._pause_btn)
        self._pause_btn.pack(side="right", padx=(4, 0))

        # Treeview
        cols   = ("name", "size", "progress", "status", "dlspeed", "upspeed",
                  "eta", "ratio", "category")
        hdgs   = ("Name", "Size", "Progress", "Status",
                  "↓ Speed", "↑ Speed", "ETA", "Ratio", "Category")
        widths = (320, 80, 72, 115, 90, 90, 72, 58, 100)
        stretches = {"name"}

        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("QB.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("QB.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("QB.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings",
                                   style="QB.Treeview", selectmode="extended")
        for col, hdr_txt, w in zip(cols, hdgs, widths):
            self._tree.heading(col, text=hdr_txt, anchor="w",
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, minwidth=40, anchor="w",
                              stretch=(col in stretches))

        self._tree.tag_configure("dl",     foreground=t.cyan)
        self._tree.tag_configure("seed",   foreground=t.status_running)
        self._tree.tag_configure("stall",  foreground=t.yellow)
        self._tree.tag_configure("paused", foreground=t.text_muted)
        self._tree.tag_configure("err",    foreground=t.status_stopped)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-Button-1>",  self._on_double_click)

        # Status bar
        self._status = tk.Label(self, text="Configure host in Config → qBittorrent",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    def _card(self, parent, label, value, color):
        t = self.theme
        c = tk.Frame(parent, bg=t.card_bg,
                     highlightbackground=t.card_border, highlightthickness=1)
        c.pack(side="left", padx=(0, 8), pady=4, ipadx=14, ipady=8)
        tk.Label(c, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(c, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 15))
        lbl.pack(anchor="w")
        return lbl

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.qbittorrent_host:
            self._status.config(
                text="No host configured — add it in Config → qBittorrent",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            cfg  = self.controller.config_manager
            host = cfg.qbittorrent_host
            port = cfg.qbittorrent_port

            # Re-login if session lost
            if not self._cookies:
                _, sc = _api(host, port, "auth/login", "POST", {
                    "username": cfg.qbittorrent_username or "admin",
                    "password": cfg.qbittorrent_password,
                })
                if sc:
                    self._cookies = sc

            torrents_raw, _ = _api(host, port, "torrents/info",
                                   cookies=self._cookies)
            info_raw,     _ = _api(host, port, "transfer/info",
                                   cookies=self._cookies)

            torrents = json.loads(torrents_raw)
            info     = json.loads(info_raw)

            self.after(0, lambda: self._populate(torrents, info))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        except Exception as e:
            self._cookies = {}
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Cannot reach qBittorrent: {}".format(msg),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped))
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # POPULATE
    # -----------------------------------------------------------------------
    def _populate(self, torrents, info):
        self._all_torrents = torrents
        self._apply_filter()

        n_dl   = sum(1 for t in torrents
                     if t.get("state", "") in ("downloading", "forcedDL", "stalledDL"))
        n_seed = sum(1 for t in torrents
                     if t.get("state", "") in ("uploading", "forcedUP", "stalledUP"))
        n_pause= sum(1 for t in torrents
                     if "paused" in t.get("state", ""))
        t = self.theme
        self._c_dl.config(text=str(n_dl),
                          fg=t.cyan if n_dl else t.text_muted)
        self._c_seed.config(text=str(n_seed),
                            fg=t.status_running if n_seed else t.text_muted)
        self._c_pause.config(text=str(n_pause),
                             fg=t.yellow if n_pause else t.text_muted)
        self._c_total.config(text=str(len(torrents)))
        self._c_dlsp.config(text=_fmt_speed(info.get("dl_info_speed", 0)))
        self._c_ulsp.config(text=_fmt_speed(info.get("up_info_speed", 0)))

        self._status.config(
            text="{} torrents  |  ↓ {}  |  ↑ {}".format(
                len(torrents),
                _fmt_speed(info.get("dl_info_speed", 0)),
                _fmt_speed(info.get("up_info_speed", 0))),
            bg=t.surface_dark, fg=t.text_muted)

    def _apply_filter(self):
        flt = self._filter_var.get()
        ts  = self._all_torrents
        if flt == "downloading":
            ts = [t for t in ts if "download" in t.get("state", "").lower()
                  or t.get("state", "") == "forcedDL"]
        elif flt == "seeding":
            ts = [t for t in ts if "upload" in t.get("state", "").lower()
                  or t.get("state", "") in ("stalledUP", "forcedUP")]
        elif flt == "paused":
            ts = [t for t in ts if "paused" in t.get("state", "").lower()]
        elif flt == "error":
            ts = [t for t in ts if t.get("state", "") in ("error", "missingFiles")]
        self._torrents = ts
        self._redraw()

    def _redraw(self):
        prev_sel = set(self._tree.selection())
        self._tree.delete(*self._tree.get_children())

        key = self._sort_col
        rev = self._sort_rev
        try:
            ts = sorted(self._torrents, key=lambda t: t.get(key, 0) or 0, reverse=rev)
        except TypeError:
            ts = sorted(self._torrents, key=lambda t: str(t.get(key, "")), reverse=rev)

        for t in ts:
            state = t.get("state", "unknown")
            tag   = _STATE_TAG.get(state, "")
            prog  = t.get("progress", 0) * 100
            self._tree.insert("", "end", iid=t.get("hash", ""), tags=(tag,), values=(
                t.get("name", "--"),
                _fmt_size(t.get("size", 0)),
                "{:.1f}%".format(prog),
                _STATE_LABEL.get(state, state),
                _fmt_speed(t.get("dlspeed", 0)),
                _fmt_speed(t.get("upspeed", 0)),
                _fmt_eta(t.get("eta")),
                "{:.2f}".format(t.get("ratio", 0)),
                t.get("category", "") or "—",
            ))

        for h in prev_sel:
            try:
                self._tree.selection_add(h)
            except Exception:
                pass

    def _sort(self, col):
        self._sort_rev = not self._sort_rev if self._sort_col == col else False
        self._sort_col = col
        self._redraw()

    # -----------------------------------------------------------------------
    # SELECTION & ACTIONS
    # -----------------------------------------------------------------------
    def _on_select(self, _=None):
        has = bool(self._tree.selection())
        state = "normal" if has else "disabled"
        for btn in (self._pause_btn, self._resume_btn, self._del_btn):
            btn.config(state=state)

    def _on_double_click(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        h = sel[0]
        t = next((t for t in self._torrents if t.get("hash") == h), None)
        if not t:
            return
        lines = [
            "Name:      {}".format(t.get("name", "")),
            "Size:      {}".format(_fmt_size(t.get("size", 0))),
            "Progress:  {:.1f}%".format(t.get("progress", 0) * 100),
            "State:     {}".format(_STATE_LABEL.get(t.get("state", ""), t.get("state", ""))),
            "Save path: {}".format(t.get("save_path", "")),
            "Tracker:   {}".format(t.get("tracker", "") or "—"),
            "Ratio:     {:.3f}".format(t.get("ratio", 0)),
            "Uploaded:  {}".format(_fmt_size(t.get("uploaded", 0))),
            "Seeds:     {}  |  Peers: {}".format(
                t.get("num_seeds", 0), t.get("num_leechs", 0)),
            "Category:  {}".format(t.get("category", "") or "None"),
            "Tags:      {}".format(t.get("tags", "") or "None"),
        ]
        messagebox.showinfo("Torrent Details", "\n".join(lines), parent=self)

    def _torrent_action(self, action):
        hashes = "|".join(self._tree.selection())
        if not hashes:
            return
        cfg = self.controller.config_manager
        def _run():
            try:
                _api(cfg.qbittorrent_host, cfg.qbittorrent_port,
                     "torrents/{}".format(action), "POST",
                     {"hashes": hashes}, self._cookies)
                self.after(800, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Action Failed", str(e), parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _delete_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        n = len(sel)
        answer = messagebox.askyesnocancel(
            "Delete Torrent{}".format("s" if n > 1 else ""),
            "Remove {} torrent{}?\n\n"
            "Yes = delete torrent AND downloaded files\n"
            "No  = remove torrent only (keep files)".format(
                n, "s" if n > 1 else ""),
            parent=self)
        if answer is None:
            return
        hashes = "|".join(sel)
        cfg = self.controller.config_manager
        def _run():
            try:
                _api(cfg.qbittorrent_host, cfg.qbittorrent_port,
                     "torrents/delete", "POST",
                     {"hashes": hashes,
                      "deleteFiles": "true" if answer else "false"},
                     self._cookies)
                self.after(800, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Delete Failed", str(e), parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _add_torrent(self):
        url = simpledialog.askstring(
            "Add Torrent",
            "Paste a magnet link or HTTP/S torrent URL:",
            parent=self)
        if not url or not url.strip():
            return
        cfg = self.controller.config_manager
        def _run():
            try:
                _api(cfg.qbittorrent_host, cfg.qbittorrent_port,
                     "torrents/add", "POST",
                     {"urls": url.strip()}, self._cookies)
                self.after(1500, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Add Failed", str(e), parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def on_show(self):
        if self.controller.config_manager.qbittorrent_host:
            self.refresh()
