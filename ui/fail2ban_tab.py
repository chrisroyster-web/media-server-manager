# ui/fail2ban_tab.py

import re
import threading
import shlex
import tkinter as tk
from tkinter import ttk


class Fail2banTab(tk.Frame):
    """Fail2ban jail monitor — shows banned IPs per jail with one-click unban."""

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme = t
        self._jails = {}
        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔒  Fail2ban",
                 bg=t.surface_dark, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", padx=18, pady=14)

        self._refresh_btn = tk.Button(
            hdr, text="⟳  Refresh",
            command=self._fetch,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat", font=t.font_small,
            padx=14, pady=4, cursor="hand2",
        )
        self._refresh_btn.pack(side="right", padx=(0, 14), pady=10)

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Paned window: content (top) + console (bottom)
        pane = tk.PanedWindow(self, orient="vertical",
                              bg=t.card_border, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        # ── Content pane ──────────────────────────────────────────────────
        content = tk.Frame(pane, bg=t.bg)
        pane.add(content, minsize=300, stretch="always")

        # Jails section
        jails_outer = tk.Frame(content, bg=t.bg, padx=16, pady=12)
        jails_outer.pack(fill="x")

        jlbl_row = tk.Frame(jails_outer, bg=t.bg)
        jlbl_row.pack(fill="x", pady=(0, 6))
        tk.Label(jlbl_row, text="JAILS",
                 bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        tree_wrap = tk.Frame(jails_outer, bg=t.card_border, padx=1, pady=1)
        tree_wrap.pack(fill="x")

        self._jail_tree = ttk.Treeview(
            tree_wrap,
            columns=("jail", "banned", "total_banned", "failed"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        for col, txt, w, anc in [
            ("jail",         "Jail Name",        220, "w"),
            ("banned",       "Currently Banned", 150, "center"),
            ("total_banned", "Total Banned",     130, "center"),
            ("failed",       "Currently Failed", 140, "center"),
        ]:
            self._jail_tree.heading(col, text=txt)
            self._jail_tree.column(col, width=w, anchor=anc)
        self._jail_tree.pack(fill="x")
        self._jail_tree.bind("<<TreeviewSelect>>", self._on_jail_select)

        tk.Frame(content, bg=t.card_border, height=1).pack(fill="x", padx=16, pady=(8, 0))

        # Banned IPs section
        ips_outer = tk.Frame(content, bg=t.bg, padx=16, pady=12)
        ips_outer.pack(fill="both", expand=True)

        ip_hdr = tk.Frame(ips_outer, bg=t.bg)
        ip_hdr.pack(fill="x", pady=(0, 6))

        self._ip_title = tk.Label(ip_hdr, text="BANNED IPs",
                                  bg=t.bg, fg=t.text_muted,
                                  font=("Segoe UI", 8, "bold"))
        self._ip_title.pack(side="left")

        self._unban_btn = tk.Button(
            ip_hdr, text="↩  Unban Selected",
            command=self._unban_selected,
            bg=t.surface_dark, fg=t.text_dim,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=3, cursor="hand2", state="disabled",
        )
        self._unban_btn.pack(side="right")

        ip_wrap = tk.Frame(ips_outer, bg=t.card_border, padx=1, pady=1)
        ip_wrap.pack(fill="both", expand=True)

        ip_sb = ttk.Scrollbar(ip_wrap, orient="vertical")
        self._ip_tree = ttk.Treeview(
            ip_wrap,
            columns=("ip", "jail"),
            show="headings",
            selectmode="browse",
            yscrollcommand=ip_sb.set,
        )
        ip_sb.configure(command=self._ip_tree.yview)
        for col, txt, w in [("ip", "Banned IP Address", 320), ("jail", "Jail", 200)]:
            self._ip_tree.heading(col, text=txt)
            self._ip_tree.column(col, width=w, anchor="w")
        ip_sb.pack(side="right", fill="y")
        self._ip_tree.pack(fill="both", expand=True)
        self._ip_tree.bind("<<TreeviewSelect>>", self._on_ip_select)

        # ── Console pane ──────────────────────────────────────────────────
        con_outer = tk.Frame(pane, bg=t.surface_dark)
        pane.add(con_outer, minsize=120, stretch="never")

        con_hdr = tk.Frame(con_outer, bg=t.surface_dark, padx=14, pady=5)
        con_hdr.pack(fill="x")
        tk.Label(con_hdr, text="OUTPUT",
                 bg=t.surface_dark, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(con_hdr, text="Clear",
                  command=self._clear_log,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small,
                  cursor="hand2").pack(side="right")

        con_sb = ttk.Scrollbar(con_outer, orient="vertical")
        self._console = tk.Text(
            con_outer,
            bg=t.surface_dark, fg=t.text,
            font=t.font_mono, bd=0, relief="flat",
            state="disabled", wrap="word",
            yscrollcommand=con_sb.set,
        )
        con_sb.configure(command=self._console.yview)
        con_sb.pack(side="right", fill="y")
        self._console.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        self._console.tag_configure("cmd",   foreground=t.cyan)
        self._console.tag_configure("ok",    foreground=t.status_running)
        self._console.tag_configure("error", foreground=t.status_stopped_text)
        self._console.tag_configure("warn",  foreground=t.yellow)

    # ──────────────────────────────────────────────────────────────────────
    # DATA FETCHING
    # ──────────────────────────────────────────────────────────────────────

    def _fetch(self):
        if getattr(self, "_fetching", False): return
        if not self.controller.ssh.connected:
            self._log("✗  Not connected.\n", "error")
            return
        self._refresh_btn.config(state="disabled", text="Refreshing…")
        self._fetching = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            ssh = self.controller.ssh

            _, _, code = ssh.run("which fail2ban-client 2>/dev/null")
            if code != 0:
                self.after(0, lambda: self._log(
                    "✗  fail2ban-client not found — install fail2ban first.\n", "error"))
                self.after(0, lambda: self._refresh_btn.config(
                    state="normal", text="⟳  Refresh"))
                return

            self._log("  $ fail2ban-client status\n", "cmd")
            out, err, code = ssh.run_sudo("fail2ban-client status")
            if code != 0:
                self.after(0, lambda: self._log(
                    f"✗  {err or out}\n", "error"))
                self.after(0, lambda: self._refresh_btn.config(
                    state="normal", text="⟳  Refresh"))
                return

            jail_names = self._parse_jail_list(out)
            self._log(f"  Jails: {', '.join(jail_names) or 'none'}\n")

            jails = {}
            for jail in jail_names:
                self._log(f"  $ fail2ban-client status {jail}\n", "cmd")
                out2, _, code2 = ssh.run_sudo(f"fail2ban-client status {shlex.quote(jail)}")
                if code2 == 0:
                    jails[jail] = self._parse_jail_detail(out2)

            self._jails = jails
            self.after(0, self._populate_jails)
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳  Refresh"))
        finally:
            self._fetching = False

    def _parse_jail_list(self, output):
        for line in output.splitlines():
            if "Jail list" in line or "Jails list" in line:
                _, _, rest = line.partition(":")
                return [j.strip() for j in rest.split(",") if j.strip()]
        return []

    def _parse_jail_detail(self, output):
        result = {"failed": 0, "banned": 0, "total_banned": 0, "ips": []}
        for line in output.splitlines():
            clean = re.sub(r"[|`\-\\]", "", line).strip()
            if "Currently failed:" in clean:
                m = re.search(r"\d+", clean)
                if m:
                    result["failed"] = int(m.group())
            elif "Currently banned:" in clean:
                m = re.search(r"\d+", clean)
                if m:
                    result["banned"] = int(m.group())
            elif "Total banned:" in clean:
                m = re.search(r"\d+", clean)
                if m:
                    result["total_banned"] = int(m.group())
            elif "Banned IP list:" in clean:
                _, _, rest = clean.partition(":")
                result["ips"] = [ip.strip() for ip in rest.split() if ip.strip()]
        return result

    # ──────────────────────────────────────────────────────────────────────
    # UI POPULATION
    # ──────────────────────────────────────────────────────────────────────

    def _populate_jails(self):
        for row in self._jail_tree.get_children():
            self._jail_tree.delete(row)
        for row in self._ip_tree.get_children():
            self._ip_tree.delete(row)
        self._unban_btn.config(state="disabled", bg=self.theme.surface_dark,
                               fg=self.theme.text_dim)
        self._ip_title.config(text="BANNED IPs")

        t = self.theme
        self._jail_tree.tag_configure("active",   foreground=t.status_stopped_text)
        self._jail_tree.tag_configure("inactive", foreground=t.text_muted)

        for jail, data in sorted(self._jails.items()):
            tag = "active" if data["banned"] > 0 else "inactive"
            self._jail_tree.insert("", "end", iid=jail, values=(
                jail,
                data["banned"],
                data["total_banned"],
                data["failed"],
            ), tags=(tag,))

    def _on_jail_select(self, _event):
        sel = self._jail_tree.selection()
        if not sel:
            return
        jail = sel[0]
        data = self._jails.get(jail, {})

        self._ip_title.config(text=f"BANNED IPs — {jail}")
        for row in self._ip_tree.get_children():
            self._ip_tree.delete(row)
        for ip in data.get("ips", []):
            self._ip_tree.insert("", "end", values=(ip, jail))
        self._unban_btn.config(state="disabled", bg=self.theme.surface_dark,
                               fg=self.theme.text_dim)

    def _on_ip_select(self, _event):
        sel = self._ip_tree.selection()
        if sel:
            self._unban_btn.config(state="normal",
                                   bg=self.theme.status_stopped, fg="#ffffff")
        else:
            self._unban_btn.config(state="disabled",
                                   bg=self.theme.surface_dark, fg=self.theme.text_dim)

    # ──────────────────────────────────────────────────────────────────────
    # UNBAN
    # ──────────────────────────────────────────────────────────────────────

    def _unban_selected(self):
        sel = self._ip_tree.selection()
        if not sel:
            return
        item = self._ip_tree.item(sel[0])
        ip, jail = item["values"][0], item["values"][1]

        self._unban_btn.config(state="disabled", text="Unbanning…")

        def _worker():
            self._log(f"  $ fail2ban-client set {jail} unbanip {ip}\n", "cmd")
            out, err, code = self.controller.ssh.run_sudo(
                f"fail2ban-client set {shlex.quote(jail)} unbanip {shlex.quote(ip)}")
            self.controller.audit_log(
                "fail2ban.unban", ip, detail=f"jail={jail}",
                result="ok" if code == 0 else "fail")
            if code == 0:
                self._log(f"  ✓  {ip} unbanned from {jail}\n", "ok")
            else:
                self._log(f"  ✗  {err or out}\n", "error")
            self.after(0, lambda: self._unban_btn.config(text="↩  Unban Selected"))
            self.after(0, self._fetch)

        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # CONSOLE
    # ──────────────────────────────────────────────────────────────────────

    def _log(self, text, tag=None):
        def _do():
            self._console.configure(state="normal")
            if tag:
                self._console.insert("end", text, tag)
            else:
                self._console.insert("end", text)
            self._console.see("end")
            self._console.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")

    # ──────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ──────────────────────────────────────────────────────────────────────

    def on_show(self):
        # Always call _fetch() — see docker_stats_tab.py for why gating
        # this on connection state hid the "Not connected" message too.
        self._fetch()
