# ui/cloudflare_tab.py
"""
Cloudflare tab — DNS records (with dynamic-IP sync), recent WAF/security
events, cache purge, and Cloudflare Tunnel status. All via the Cloudflare
API v4 (core/cloudflare_manager.py), not SSH.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from ui.refresh_control import RefreshControl
from core import cloudflare_manager as cf


class CloudflareTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._records   = []
        self._events    = []
        self._tunnels   = []
        self._fetching  = False
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="CLOUDFLARE", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "cloudflare",
                                  default=120, on_refresh=self.refresh)
        self._rc.pack(side="right")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        self._status = tk.Label(self, text="Not configured",
                                 bg=t.surface_dark, fg=t.text_muted,
                                 font=t.font_small, anchor="w", padx=10, pady=4)
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        paned = tk.PanedWindow(self, orient="vertical",
                               bg=t.card_border, sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self._style = ttk.Style()
        for name in ("CFDns", "CFEvt", "CFTun"):
            sid = "{}.Treeview".format(name)
            self._style.configure(sid,
                background=t.card_bg, foreground=t.text,
                fieldbackground=t.card_bg, borderwidth=0,
                rowheight=24, font=t.font_mono)
            self._style.configure(sid + ".Heading",
                background=t.surface_dark, foreground=t.text_muted,
                font=t.font_small, relief="flat")
            self._style.map(sid,
                background=[("selected", t.surface_light)],
                foreground=[("selected", t.text)])

        # ── DNS RECORDS ──────────────────────────────────────────────────
        dns_fr = tk.Frame(paned, bg=t.bg)
        paned.add(dns_fr, minsize=140, stretch="always")

        dns_hdr = tk.Frame(dns_fr, bg=t.bg)
        dns_hdr.pack(fill="x", pady=(6, 4))
        tk.Label(dns_hdr, text="DNS RECORDS", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        self._purge_btn = tk.Button(dns_hdr, text="🗑 Purge Cache",
                                     command=self._purge_cache, state="disabled")
        t.style_button(self._purge_btn, "danger")
        self._purge_btn.pack(side="right", padx=(4, 0))
        self._sync_btn = tk.Button(dns_hdr, text="🔄 Sync Dynamic IP",
                                    command=self._sync_dynamic_ip, state="disabled")
        t.style_button(self._sync_btn)
        self._sync_btn.pack(side="right", padx=(4, 0))
        self._edit_btn = tk.Button(dns_hdr, text="✎ Edit Record",
                                    command=self._edit_record, state="disabled")
        t.style_button(self._edit_btn)
        self._edit_btn.pack(side="right", padx=(4, 0))

        dns_cols = ("type", "name", "content", "proxied", "ttl")
        dns_tree_fr = tk.Frame(dns_fr, bg=t.bg)
        dns_tree_fr.pack(fill="both", expand=True)
        self._dns_tree = ttk.Treeview(dns_tree_fr, columns=dns_cols,
                                       show="headings", style="CFDns.Treeview",
                                       selectmode="browse")
        for col, hdr_txt, w in [
            ("type",    "Type",    60),
            ("name",    "Name",    260),
            ("content", "Content", 220),
            ("proxied", "Proxied", 70),
            ("ttl",     "TTL",     70),
        ]:
            self._dns_tree.heading(col, text=hdr_txt, anchor="w")
            self._dns_tree.column(col, width=w, minwidth=40, anchor="w",
                                  stretch=(col in ("name", "content")))
        self._dns_tree.bind("<<TreeviewSelect>>", self._on_dns_select)
        self._dns_tree.bind("<Double-1>", lambda e: self._edit_record())
        dvsb = ttk.Scrollbar(dns_tree_fr, orient="vertical", command=self._dns_tree.yview)
        self._dns_tree.configure(yscrollcommand=dvsb.set)
        dvsb.pack(side="right", fill="y")
        self._dns_tree.pack(fill="both", expand=True)

        # ── SECURITY EVENTS ──────────────────────────────────────────────
        evt_fr = tk.Frame(paned, bg=t.bg)
        paned.add(evt_fr, minsize=140, stretch="always")

        evt_hdr = tk.Frame(evt_fr, bg=t.bg)
        evt_hdr.pack(fill="x", pady=(6, 4))
        tk.Label(evt_hdr, text="SECURITY EVENTS  (last 24h, WAF/firewall blocks)",
                 bg=t.bg, fg=t.text_muted, font=("Segoe UI", 8, "bold")).pack(side="left")

        evt_cols = ("time", "action", "ip", "country", "path", "source")
        evt_tree_fr = tk.Frame(evt_fr, bg=t.bg)
        evt_tree_fr.pack(fill="both", expand=True)
        self._evt_tree = ttk.Treeview(evt_tree_fr, columns=evt_cols,
                                       show="headings", style="CFEvt.Treeview",
                                       selectmode="browse")
        for col, hdr_txt, w in [
            ("time",    "Time",    150),
            ("action",  "Action",  80),
            ("ip",      "Client IP", 130),
            ("country", "Country", 80),
            ("path",    "Path",    260),
            ("source",  "Source",  100),
        ]:
            self._evt_tree.heading(col, text=hdr_txt, anchor="w")
            self._evt_tree.column(col, width=w, minwidth=40, anchor="w",
                                  stretch=(col == "path"))
        self._evt_tree.tag_configure("block",     foreground=t.status_stopped_text)
        self._evt_tree.tag_configure("challenge", foreground=t.yellow)
        self._evt_tree.tag_configure("other",     foreground=t.text_muted)
        evsb = ttk.Scrollbar(evt_tree_fr, orient="vertical", command=self._evt_tree.yview)
        self._evt_tree.configure(yscrollcommand=evsb.set)
        evsb.pack(side="right", fill="y")
        self._evt_tree.pack(fill="both", expand=True)

        # ── TUNNELS ───────────────────────────────────────────────────────
        tun_fr = tk.Frame(paned, bg=t.bg)
        paned.add(tun_fr, minsize=100, stretch="always")

        tun_hdr = tk.Frame(tun_fr, bg=t.bg)
        tun_hdr.pack(fill="x", pady=(6, 4))
        tk.Label(tun_hdr, text="CLOUDFLARE TUNNELS", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        tun_cols = ("name", "status", "connections")
        tun_tree_fr = tk.Frame(tun_fr, bg=t.bg)
        tun_tree_fr.pack(fill="both", expand=True)
        self._tun_tree = ttk.Treeview(tun_tree_fr, columns=tun_cols,
                                       show="headings", style="CFTun.Treeview",
                                       selectmode="browse", height=4)
        for col, hdr_txt, w in [
            ("name",        "Tunnel",      220),
            ("status",      "Status",      120),
            ("connections", "Connections", 100),
        ]:
            self._tun_tree.heading(col, text=hdr_txt, anchor="w")
            self._tun_tree.column(col, width=w, minwidth=40, anchor="w",
                                  stretch=(col == "name"))
        self._tun_tree.tag_configure("healthy",  foreground=t.status_running)
        self._tun_tree.tag_configure("down",     foreground=t.status_stopped_text)
        self._tun_tree.tag_configure("degraded", foreground=t.yellow)
        tusb = ttk.Scrollbar(tun_tree_fr, orient="vertical", command=self._tun_tree.yview)
        self._tun_tree.configure(yscrollcommand=tusb.set)
        tusb.pack(side="right", fill="y")
        self._tun_tree.pack(fill="both", expand=True)

    # -----------------------------------------------------------------------
    # LIFECYCLE
    # -----------------------------------------------------------------------
    def on_show(self):
        self.refresh()

    def _on_dns_select(self, _event=None):
        state = "normal" if self._dns_tree.selection() else "disabled"
        self._edit_btn.config(state=state)

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if self._fetching:
            return
        self._rc.cancel()
        cfg   = self.controller.config_manager
        token = cfg.cloudflare_api_token
        zone  = cfg.cloudflare_zone_id
        if not token or not zone:
            self._status.config(
                text="Not configured — add your API Token and Zone ID in Config → Monitoring",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        self._refresh_btn.config(state="disabled")
        self._sync_btn.config(state="disabled")
        self._purge_btn.config(state="disabled")
        threading.Thread(target=self._fetch, args=(token, zone, cfg.cloudflare_account_id),
                          daemon=True).start()

    def _fetch(self, token, zone, account_id):
        try:
            try:
                records = cf.list_dns_records(token, zone)
            except cf.CloudflareError as e:
                self.after(0, lambda err=str(e): self._fail("DNS records: {}".format(err)))
                return
            except Exception as e:
                self.after(0, lambda err=str(e): self._fail("DNS records: {}".format(err)))
                return

            try:
                events = cf.list_security_events(token, zone)
            except Exception:
                events = None  # token may lack Analytics scope — not fatal

            tunnels = []
            if account_id:
                try:
                    tunnels = cf.list_tunnels(token, account_id)
                except Exception:
                    tunnels = None  # token may lack Tunnel scope — not fatal

            self._records = records
            self._events  = events or []
            self._tunnels = tunnels or []
            self.after(0, lambda: self._populate(events is None, tunnels is None and bool(account_id)))
        finally:
            # Must always clear no matter what fails above -- refresh() no-ops
            # while this is True, so an unreset flag permanently wedges the
            # tab. _fail()/_populate() also clear it on their own paths;
            # this is the backstop for anything that escapes both.
            self._fetching = False

    def _fail(self, msg):
        self._fetching = False
        self._refresh_btn.config(state="normal")
        self._status.config(text=msg, bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)

    def _populate(self, events_unavailable, tunnels_unavailable):
        t = self.theme

        self._dns_tree.delete(*self._dns_tree.get_children())
        for r in self._records:
            self._dns_tree.insert("", "end", iid=r["id"], values=(
                r["type"], r["name"], r["content"],
                "yes" if r["proxied"] else "no", r["ttl"]))

        self._evt_tree.delete(*self._evt_tree.get_children())
        for e in self._events:
            action = (e.get("action") or "").lower()
            tag = "block" if action == "block" else "challenge" if "challenge" in action else "other"
            self._evt_tree.insert("", "end", values=(
                e["datetime"], e["action"], e["client_ip"],
                e["country"], e["path"], e["source"]), tags=(tag,))

        self._tun_tree.delete(*self._tun_tree.get_children())
        for tun in self._tunnels:
            status = (tun.get("status") or "").lower()
            tag = "healthy" if status == "healthy" else "down" if status in ("down", "inactive") else "degraded"
            self._tun_tree.insert("", "end", values=(
                tun["name"], tun["status"], tun["connections"]), tags=(tag,))

        self._fetching = False
        self._refresh_btn.config(state="normal")
        self._sync_btn.config(state="normal" if self._records else "disabled")
        self._purge_btn.config(state="normal")
        self._last_lbl.config(text="Updated {}".format(time.strftime("%H:%M")))
        self._rc.schedule()

        notes = []
        if events_unavailable:
            notes.append("security events unavailable (token needs Analytics Read)")
        if tunnels_unavailable:
            notes.append("tunnels unavailable (token needs Tunnel Read)")
        if notes:
            self._status.config(text="Loaded — " + "; ".join(notes),
                                bg=t.surface_dark, fg=t.yellow)
        else:
            self._status.config(
                text="{} DNS record(s)  ·  {} event(s)  ·  {} tunnel(s)".format(
                    len(self._records), len(self._events), len(self._tunnels)),
                bg=t.surface_dark, fg=t.text_muted)

    # -----------------------------------------------------------------------
    # DNS ACTIONS
    # -----------------------------------------------------------------------
    def _selected_record(self):
        sel = self._dns_tree.selection()
        if not sel:
            return None
        rid = sel[0]
        return next((r for r in self._records if r["id"] == rid), None)

    def _edit_record(self):
        rec = self._selected_record()
        if not rec:
            return
        new_content = simpledialog.askstring(
            "Edit DNS Record",
            "{} record for {}\n\nNew content:".format(rec["type"], rec["name"]),
            initialvalue=rec["content"], parent=self)
        if not new_content or new_content.strip() == rec["content"]:
            return
        new_content = new_content.strip()
        if not messagebox.askyesno(
                "Update DNS Record",
                "Change {} {} from\n  {}\nto\n  {} ?".format(
                    rec["type"], rec["name"], rec["content"], new_content),
                parent=self):
            return
        self._apply_dns_update([(rec, new_content)])

    def _sync_dynamic_ip(self):
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected to server — can't detect current IP",
                                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text)
            return
        self._sync_btn.config(state="disabled", text="Checking…")
        threading.Thread(target=self._do_sync_check, daemon=True).start()

    def _do_sync_check(self):
        out, _, code = self.controller.ssh.run(
            "curl -s --max-time 5 https://api.ipify.org")
        current_ip = out.strip()
        self.after(0, lambda: self._sync_btn.config(state="normal", text="🔄 Sync Dynamic IP"))
        if code != 0 or not current_ip:
            self.after(0, lambda: self._status.config(
                text="Could not detect the server's current public IP",
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
            return

        stale = [(r, current_ip) for r in self._records
                 if r["type"] == "A" and r["content"] != current_ip]
        if not stale:
            self.after(0, lambda: self._status.config(
                text="All A records already point to {}".format(current_ip),
                bg=self.theme.surface_dark, fg=self.theme.status_running))
            return

        def _confirm():
            lines = "\n".join(
                "  {}:  {}  →  {}".format(r["name"], r["content"], ip) for r, ip in stale)
            if messagebox.askyesno(
                    "Sync Dynamic IP",
                    "The server's current public IP is {}.\n\n"
                    "These A record(s) point elsewhere and will be updated:\n\n{}\n\nContinue?"
                    .format(current_ip, lines),
                    parent=self):
                self._apply_dns_update(stale)
        self.after(0, _confirm)

    def _apply_dns_update(self, changes):
        """changes: list of (record_dict, new_content) to PATCH."""
        cfg   = self.controller.config_manager
        token = cfg.cloudflare_api_token
        zone  = cfg.cloudflare_zone_id

        def worker():
            errors = []
            for rec, new_content in changes:
                try:
                    cf.update_dns_record_content(token, zone, rec["id"], new_content)
                except Exception as e:
                    errors.append("{}: {}".format(rec["name"], e))
            if errors:
                self.after(0, lambda: self._status.config(
                    text="Some updates failed — " + "; ".join(errors)[:150],
                    bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
            else:
                self.after(0, lambda: self._status.config(
                    text="Updated {} record(s)".format(len(changes)),
                    bg=self.theme.surface_dark, fg=self.theme.status_running))
            self.after(500, self.refresh)

        threading.Thread(target=worker, daemon=True).start()

    def _purge_cache(self):
        if not messagebox.askyesno(
                "Purge Cache",
                "Purge everything cached for this zone?\n\n"
                "This is safe but causes a temporary traffic spike to your "
                "origin server while the cache repopulates.",
                parent=self):
            return
        cfg   = self.controller.config_manager
        token = cfg.cloudflare_api_token
        zone  = cfg.cloudflare_zone_id
        self._purge_btn.config(state="disabled", text="Purging…")

        def worker():
            try:
                cf.purge_cache(token, zone)
                self.after(0, lambda: self._status.config(
                    text="Cache purge requested", bg=self.theme.surface_dark,
                    fg=self.theme.status_running))
            except Exception as e:
                self.after(0, lambda err=str(e): self._status.config(
                    text="Purge failed: {}".format(err), bg=self.theme.surface_dark,
                    fg=self.theme.status_stopped_text))
            finally:
                self.after(0, lambda: self._purge_btn.config(state="normal", text="🗑 Purge Cache"))

        threading.Thread(target=worker, daemon=True).start()
