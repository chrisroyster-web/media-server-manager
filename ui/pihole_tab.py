# ui/pihole_tab.py
"""
Pi-hole / AdGuard Home DNS blocker management tab.

Supports both Pi-hole v5/v6 and AdGuard Home via their respective HTTP APIs.
The backend is selected by cfg.pihole_type ("pihole" or "adguard").
No SSH — all requests go directly from the desktop client to the blocker host.
"""

import base64
import json
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import urllib.error
import urllib.request

from ui.refresh_control import RefreshControl


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def _clean_host(host: str) -> str:
    """Strip scheme and trailing slashes from a host string."""
    return host.removeprefix("https://").removeprefix("http://").strip("/").strip()


# ---- Pi-hole ---------------------------------------------------------------

def _pihole_url(host: str, port: str, path: str) -> str:
    return "http://{}:{}/{}".format(_clean_host(host), port, path.lstrip("/"))


def _pihole_get(host: str, port: str, apikey: str, params: str):
    """GET /admin/api.php?<params>&auth=<key> → parsed JSON."""
    url = _pihole_url(host, port, "admin/api.php") + "?{}&auth={}".format(params, apikey)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _pihole_post(host: str, port: str, apikey: str, params: str):
    """POST /admin/api.php?<params>&auth=<key> (empty body) → parsed JSON."""
    url = _pihole_url(host, port, "admin/api.php") + "?{}&auth={}".format(params, apikey)
    req = urllib.request.Request(url, data=b"", method="POST",
                                  headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ---- AdGuard Home ----------------------------------------------------------

def _adguard_headers(username: str, password: str) -> dict:
    token = base64.b64encode("{}:{}".format(username, password).encode()).decode()
    return {
        "Authorization": "Basic {}".format(token),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _adguard_get(host: str, port: str, username: str, password: str, path: str):
    """GET <path> with Basic auth → parsed JSON."""
    url = _pihole_url(host, port, path)
    req = urllib.request.Request(url, headers=_adguard_headers(username, password))
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _adguard_post(host: str, port: str, username: str, password: str,
                  path: str, body: dict):
    """POST <path> with Basic auth and JSON body → parsed JSON."""
    url = _pihole_url(host, port, path)
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers=_adguard_headers(username, password))
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw.strip() else {}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_count(n) -> str:
    try:
        n = int(n)
        if n >= 1_000_000:
            return "{:.1f}M".format(n / 1_000_000)
        if n >= 1_000:
            return "{:,.0f}".format(n)
        return str(n)
    except Exception:
        return "--"


def _fmt_pct(v) -> str:
    try:
        return "{:.1f}%".format(float(v))
    except Exception:
        return "--"


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(int(ts)))
    except Exception:
        return str(ts)


# ---------------------------------------------------------------------------
# Status codes used by Pi-hole recent queries
# ---------------------------------------------------------------------------
_PIHOLE_STATUS = {
    "1":  "OK (cache)",
    "2":  "OK (forward)",
    "3":  "Blocked (gravity)",
    "4":  "Blocked (regex)",
    "5":  "Blocked (blacklist)",
    "6":  "Blocked (NXDOMAIN)",
    "7":  "Blocked (CNAME)",
    "8":  "Blocked (upstream)",
    "9":  "Cached",
    "10": "Blocked (regex/CNAME)",
    "11": "Blocked (denylist/CNAME)",
    "12": "Retried",
    "13": "Retried (ignored)",
    "14": "In-memory cached",
}


# ===========================================================================
# Tab
# ===========================================================================

class PiholeTab(tk.Frame):
    """Pi-hole / AdGuard Home DNS blocker management tab."""

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._fetching  = False
        self._build_ui()

    # -----------------------------------------------------------------------
    # BUILD UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        t = self.theme

        # ---- Header row ----------------------------------------------------
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        self._title_lbl = tk.Label(
            hdr, text="PI-HOLE",
            bg=t.bg, fg=t.text, font=t.font_title,
        )
        self._title_lbl.pack(side="left")

        self._ts_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                 font=t.font_small)
        self._ts_lbl.pack(side="right", padx=12)

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))

        self._rc = RefreshControl(hdr, self.controller, "pihole",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right", padx=(0, 12))

        # ---- Toggle row ----------------------------------------------------
        toggle_row = tk.Frame(self, bg=t.bg)
        toggle_row.pack(fill="x", padx=16, pady=(0, 8))

        tk.Label(toggle_row, text="Status:", bg=t.bg, fg=t.text_muted,
                 font=t.font_regular).pack(side="left")

        self._enabled_lbl = tk.Label(
            toggle_row, text="Unknown",
            bg=t.bg, fg=t.text_muted, font=t.font_regular,
        )
        self._enabled_lbl.pack(side="left", padx=(6, 18))

        self._disable_btn = tk.Button(
            toggle_row, text="⏸ Disable",
            command=self._on_disable,
        )
        t.style_button(self._disable_btn)
        self._disable_btn.pack(side="left", padx=(0, 6))

        self._enable_btn = tk.Button(
            toggle_row, text="▶ Enable",
            command=self._on_enable,
        )
        t.style_button(self._enable_btn)
        self._enable_btn.pack(side="left")

        # ---- Summary cards -------------------------------------------------
        self._cards_row = tk.Frame(self, bg=t.bg)
        self._cards_row.pack(fill="x", padx=16, pady=(0, 10))

        self._card_pct       = self._make_card("Blocked %",       "--", accent=t.status_stopped)
        self._card_queries   = self._make_card("Queries Today",    "--")
        self._card_blocked   = self._make_card("Blocked Today",    "--")
        self._card_domains   = self._make_card("Domains on List",  "--")
        self._card_cached    = self._make_card("Cached",           "--")
        self._card_forwarded = self._make_card("Forwarded",        "--")

        # ---- Sub-tabs (Notebook) -------------------------------------------
        nb_style = ttk.Style()
        nb_style.configure("Pihole.TNotebook",
                           background=t.bg, borderwidth=0)
        nb_style.configure("Pihole.TNotebook.Tab",
                           background=t.surface_dark,
                           foreground=t.text_muted,
                           padding=[14, 6],
                           font=t.font_small)
        nb_style.map("Pihole.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="Pihole.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._tab_blocked = tk.Frame(self._nb, bg=t.bg)
        self._tab_clients = tk.Frame(self._nb, bg=t.bg)
        self._tab_queries = tk.Frame(self._nb, bg=t.bg)

        self._nb.add(self._tab_blocked, text="  Top Blocked  ")
        self._nb.add(self._tab_clients, text="  Top Clients  ")
        self._nb.add(self._tab_queries, text="  Recent Queries  ")

        self._tree_blocked = self._make_tree(
            self._tab_blocked,
            cols=("domain", "count"),
            headings=[
                ("domain", "Domain",    420, "w"),
                ("count",  "Count",     100, "e"),
            ],
        )

        self._tree_clients = self._make_tree(
            self._tab_clients,
            cols=("client", "queries"),
            headings=[
                ("client",  "Client",   280, "w"),
                ("queries", "Queries",  100, "e"),
            ],
        )

        # Recent queries — Pi-hole only; AdGuard shows a note
        self._queries_note = tk.Label(
            self._tab_queries,
            text="Recent query log is not available through the AdGuard Home stats API.",
            bg=t.bg, fg=t.text_muted, font=t.font_regular,
            wraplength=500, justify="center",
        )

        self._tree_queries = self._make_tree(
            self._tab_queries,
            cols=("time", "type", "domain", "client", "status"),
            headings=[
                ("time",   "Time",    80,  "center"),
                ("type",   "Type",    60,  "center"),
                ("domain", "Domain", 340,  "w"),
                ("client", "Client", 140,  "w"),
                ("status", "Status", 180,  "w"),
            ],
        )

        # ---- Status bar ----------------------------------------------------
        self._status = tk.Label(
            self, text="Configure Pi-hole / AdGuard in the Config tab.",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, anchor="w", padx=8, pady=4,
        )
        self._status.pack(fill="x", side="bottom")

    # -----------------------------------------------------------------------
    # CARD / TREE HELPERS
    # -----------------------------------------------------------------------

    def _make_card(self, label: str, value: str, accent=None) -> dict:
        """Create a summary stat card and return a dict with value labels."""
        t = self.theme
        card = tk.Frame(self._cards_row, bg=t.card_bg,
                        padx=14, pady=10,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 10))

        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")

        fg = accent if accent else t.text
        val_lbl = tk.Label(card, text=value, bg=t.card_bg, fg=fg,
                           font=(t.font_title[0], 20, "bold"))
        val_lbl.pack(anchor="w")

        return {"frame": card, "val": val_lbl, "default_fg": fg}

    def _set_card(self, card: dict, value: str, highlight: bool = False):
        t = self.theme
        fg = card["default_fg"] if not highlight else t.status_stopped
        if value == "--" or not value:
            fg = t.text_muted
        card["val"].config(text=value, fg=fg)

    def _make_tree(self, parent, cols, headings) -> ttk.Treeview:
        t = self.theme
        sid = "Pihole{}.Treeview".format(id(parent))
        style = ttk.Style()
        style.configure(sid,
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg,
                        borderwidth=0, rowheight=26,
                        font=t.font_mono)
        style.configure(sid + ".Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map(sid,
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=sid, selectmode="browse")
        for col, text, width, anchor in headings:
            tree.heading(col, text=text, anchor=anchor)
            tree.column(col, width=width, minwidth=40,
                        anchor=anchor, stretch=(col in ("domain", "client", "status")))

        tree.tag_configure("odd",     background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",    background=t.card_bg,      foreground=t.text)
        tree.tag_configure("blocked", foreground=t.status_stopped_text)
        tree.tag_configure("cached",  foreground=t.cyan)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _clear_tree(self, tree: ttk.Treeview):
        for row in tree.get_children():
            tree.delete(row)

    # -----------------------------------------------------------------------
    # PUBLIC ENTRY POINTS
    # -----------------------------------------------------------------------

    def on_show(self):
        cfg = self.controller.config_manager
        if cfg.pihole_host:
            self.refresh()

    def refresh(self):
        if self._fetching:
            return
        self._fetching = True
        self._rc.cancel()
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        threading.Thread(target=self._fetch, daemon=True).start()

    # -----------------------------------------------------------------------
    # BACKGROUND FETCH
    # -----------------------------------------------------------------------

    def _fetch(self):
        try:
            cfg  = self.controller.config_manager
            kind = (cfg.pihole_type or "pihole").lower()
            if kind == "adguard":
                self._fetch_adguard(cfg)
            else:
                self._fetch_pihole(cfg)
        except urllib.error.URLError as exc:
            msg = "Connection error: {}".format(exc.reason)
            self.after(0, lambda m=msg: self._show_error(m))
        except urllib.error.HTTPError as exc:
            msg = "HTTP {}: {}".format(exc.code, exc.reason)
            self.after(0, lambda m=msg: self._show_error(m))
        except Exception as exc:
            msg = "Error: {}".format(exc)
            self.after(0, lambda m=msg: self._show_error(m))
        finally:
            self._fetching = False

    # ---- Pi-hole -----------------------------------------------------------

    def _fetch_pihole(self, cfg):
        host   = cfg.pihole_host
        port   = cfg.pihole_port or "80"
        apikey = cfg.pihole_apikey

        if not host:
            self.after(0, lambda: self._show_error(
                "No Pi-hole host configured. Go to Config to set it up."))
            return

        summary   = _pihole_get(host, port, apikey, "summaryRaw")
        top_items = _pihole_get(host, port, apikey, "topItems=10")
        queries   = _pihole_get(host, port, apikey, "getAllQueries=20")

        data = {
            "kind":    "pihole",
            "enabled": summary.get("status", "disabled") == "enabled",
            "pct":     summary.get("ads_percentage_today", 0),
            "queries": summary.get("dns_queries_today",    0),
            "blocked": summary.get("ads_blocked_today",    0),
            "domains": summary.get("domains_being_blocked", 0),
            "cached":  summary.get("queries_cached",       0),
            "fwd":     summary.get("queries_forwarded",    0),
            "top_ads":     top_items.get("top_ads",     {}),
            "top_queries": top_items.get("top_queries", {}),
            "recent":  queries.get("data", []),
        }
        self.after(0, lambda d=data: self._update_ui(d))

    # ---- AdGuard Home ------------------------------------------------------

    def _fetch_adguard(self, cfg):
        host     = cfg.pihole_host
        port     = cfg.pihole_port or "80"
        username = cfg.adguard_username or "admin"
        password = cfg.pihole_apikey

        if not host:
            self.after(0, lambda: self._show_error(
                "No AdGuard host configured. Go to Config to set it up."))
            return

        status = _adguard_get(host, port, username, password, "/control/status")
        stats  = _adguard_get(host, port, username, password, "/control/stats")

        blocked_ratio = stats.get("blocked_filtering_ratio", 0.0)
        num_queries   = stats.get("num_dns_queries", 0)
        num_blocked   = stats.get("num_blocked_filtering", 0)

        # top_blocked_domains: list of {name, count}
        top_blocked_raw = stats.get("top_blocked_domains", []) or []
        top_blocked = {
            item.get("name", ""): item.get("count", 0)
            for item in top_blocked_raw
        }

        # top_clients: list of {name, count}
        top_clients_raw = stats.get("top_clients", []) or []
        top_clients = {
            item.get("name", ""): item.get("count", 0)
            for item in top_clients_raw
        }

        data = {
            "kind":    "adguard",
            "enabled": bool(status.get("protection_enabled", False)),
            "pct":     blocked_ratio * 100,
            "queries": num_queries,
            "blocked": num_blocked,
            "domains": "--",   # not in stats API
            "cached":  stats.get("num_replaced_safebrowsing", 0),
            "fwd":     "--",
            "top_ads":     top_blocked,
            "top_queries": top_clients,
            "recent":  None,   # not available in stats API
        }
        self.after(0, lambda d=data: self._update_ui(d))

    # -----------------------------------------------------------------------
    # UI UPDATE  (runs on main thread)
    # -----------------------------------------------------------------------

    def _update_ui(self, data: dict):
        t    = self.theme
        kind = data["kind"]

        # Title
        title = "ADGUARD HOME" if kind == "adguard" else "PI-HOLE"
        self._title_lbl.config(text=title)

        # Timestamp
        ts = time.strftime("%H:%M:%S")
        self._ts_lbl.config(text="Updated {}".format(ts))

        # Enabled state
        enabled = data["enabled"]
        if enabled:
            self._enabled_lbl.config(text="Enabled", fg=t.status_running)
        else:
            self._enabled_lbl.config(text="Disabled", fg=t.status_stopped_text)

        # Summary cards
        pct_val = _fmt_pct(data["pct"])
        self._set_card(self._card_pct, pct_val,
                       highlight=(float(data["pct"]) > 0))
        self._set_card(self._card_queries,   _fmt_count(data["queries"]))
        self._set_card(self._card_blocked,   _fmt_count(data["blocked"]))
        self._set_card(self._card_domains,
                       _fmt_count(data["domains"]) if data["domains"] != "--" else "--")
        self._set_card(self._card_cached,
                       _fmt_count(data["cached"]) if data["cached"] != "--" else "--")
        self._set_card(self._card_forwarded,
                       _fmt_count(data["fwd"]) if data["fwd"] != "--" else "--")

        # Top blocked domains
        self._clear_tree(self._tree_blocked)
        top_ads = data.get("top_ads", {})
        sorted_ads = sorted(top_ads.items(), key=lambda x: x[1], reverse=True)
        for i, (domain, count) in enumerate(sorted_ads):
            tag = ("odd" if i % 2 else "even",)
            self._tree_blocked.insert("", "end",
                                      values=(domain, _fmt_count(count)),
                                      tags=tag)

        # Top clients (AdGuard) / top queries (Pi-hole used as clients proxy)
        self._clear_tree(self._tree_clients)
        top_q = data.get("top_queries", {})
        sorted_q = sorted(top_q.items(), key=lambda x: x[1], reverse=True)
        for i, (client, count) in enumerate(sorted_q):
            tag = ("odd" if i % 2 else "even",)
            self._tree_clients.insert("", "end",
                                      values=(client, _fmt_count(count)),
                                      tags=tag)

        # Recent queries tab
        self._queries_note.pack_forget()
        self._tree_queries.pack_forget()

        if kind == "adguard" or data.get("recent") is None:
            self._tree_queries.pack_forget()
            self._queries_note.pack(expand=True)
        else:
            self._queries_note.pack_forget()
            self._clear_tree(self._tree_queries)
            recent = data.get("recent") or []
            for i, row in enumerate(recent):
                # row: [timestamp, type, domain, client, status_code]
                try:
                    ts_val  = _fmt_ts(row[0])
                    qtype   = str(row[1])
                    domain  = str(row[2])
                    client  = str(row[3])
                    scode   = str(row[4])
                    status  = _PIHOLE_STATUS.get(scode, "Status {}".format(scode))
                except Exception:
                    continue

                tag = "odd" if i % 2 else "even"
                if "Blocked" in status:
                    extra_tag = "blocked"
                elif "cache" in status.lower():
                    extra_tag = "cached"
                else:
                    extra_tag = tag

                self._tree_queries.insert(
                    "", "end",
                    values=(ts_val, qtype, domain, client, status),
                    tags=(tag, extra_tag),
                )
            self._tree_queries.pack(fill="both", expand=True)

        # Status bar
        self._status.config(
            text="Last refreshed {}  |  {}".format(ts, title),
            bg=t.surface_dark, fg=t.text_muted,
        )
        self._rc.schedule()

    def _show_error(self, msg: str):
        t = self.theme
        self._status.config(text=msg, bg=t.surface_dark, fg=t.status_stopped_text)
        self._rc.schedule()

    # -----------------------------------------------------------------------
    # ENABLE / DISABLE ACTIONS
    # -----------------------------------------------------------------------

    def _on_enable(self):
        self._enable_btn.config(state="disabled", text="Enabling…")
        self._disable_btn.config(state="disabled")
        threading.Thread(target=self._toggle, args=(True,), daemon=True).start()

    def _on_disable(self):
        if not messagebox.askyesno(
                "Disable Pi-hole",
                "Disable ad-blocking protection network-wide?",
                parent=self):
            return
        self._enable_btn.config(state="disabled")
        self._disable_btn.config(state="disabled", text="Disabling…")
        threading.Thread(target=self._toggle, args=(False,), daemon=True).start()

    def _reset_toggle_buttons(self):
        self._enable_btn.config(state="normal", text="▶ Enable")
        self._disable_btn.config(state="normal", text="⏸ Disable")

    def _toggle(self, enable: bool):
        cfg  = self.controller.config_manager
        kind = (cfg.pihole_type or "pihole").lower()
        try:
            if kind == "adguard":
                _adguard_post(cfg.pihole_host, cfg.pihole_port or "80",
                              cfg.adguard_username or "admin", cfg.pihole_apikey,
                              "/control/protection", {"enabled": enable})
            else:
                param = "enable" if enable else "disable"
                _pihole_post(cfg.pihole_host, cfg.pihole_port or "80",
                             cfg.pihole_apikey, param)

            # Refresh after toggling to pick up the new state
            self.after(500, self.refresh)
        except urllib.error.HTTPError as exc:
            msg = "Toggle failed: HTTP {} {}".format(exc.code, exc.reason)
            self.after(0, lambda m=msg: self._show_error(m))
        except urllib.error.URLError as exc:
            msg = "Toggle failed: {}".format(exc.reason)
            self.after(0, lambda m=msg: self._show_error(m))
        except Exception as exc:
            msg = "Toggle failed: {}".format(exc)
            self.after(0, lambda m=msg: self._show_error(m))
        finally:
            self.after(0, self._reset_toggle_buttons)
