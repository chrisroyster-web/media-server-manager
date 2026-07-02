# ui/emby_users_tab.py
"""
Emby User Management tab.
Lists all users, allows enable/disable, bitrate cap, and deletion.
Supports creating new users.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import urllib.request
import json


def _emby_request(host, port, apikey, method, path, body=None):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url  = "http://{}:{}/emby/{}".format(host, port, path.lstrip("/"))
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "X-Emby-Token": apikey,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}


def _fmt_date(iso):
    if not iso:
        return "Never"
    try:
        return iso[:10] + "  " + iso[11:16]
    except Exception:
        return iso[:16]


def _fmt_bitrate(bps):
    if not bps:
        return "Unlimited"
    return "{:.1f} Mbps".format(bps / 1_000_000)


class EmbyUsersTab(tk.Frame):
    """Manage Emby users — list, enable/disable, bitrate cap, create, delete."""

    PLAYER_COLOR = "#52b54b"   # Emby green

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._users     = []
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 6))

        tk.Frame(hdr, bg=self.PLAYER_COLOR, width=4).pack(side="left", fill="y", padx=(0, 10))
        tk.Label(hdr, text="EMBY  —  USERS",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._fetch)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right", padx=(0, 8))

        new_btn = tk.Button(hdr, text="+ New User", command=self._new_user_dialog)
        t.style_button(new_btn)
        new_btn.pack(side="right", padx=(0, 8))

        self._status_lbl = tk.Label(self, text="",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w", padx=8)
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 6))

        cols = ("name", "role", "enabled", "last_active", "bitrate")
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("EmbyUsers.Treeview",
                        background=t.card_bg,
                        foreground=t.text,
                        fieldbackground=t.card_bg,
                        rowheight=28,
                        font=("Segoe UI", 10))
        style.configure("EmbyUsers.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        font=("Segoe UI", 9, "bold"))
        style.map("EmbyUsers.Treeview",
                  background=[("selected", t.blue)],
                  foreground=[("selected", "#fff")])

        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                   style="EmbyUsers.Treeview", selectmode="browse")
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.heading("name",        text="Username")
        self._tree.heading("role",        text="Role")
        self._tree.heading("enabled",     text="Status")
        self._tree.heading("last_active", text="Last Active")
        self._tree.heading("bitrate",     text="Bitrate Limit")

        self._tree.column("name",        width=180, anchor="w")
        self._tree.column("role",        width=90,  anchor="center")
        self._tree.column("enabled",     width=90,  anchor="center")
        self._tree.column("last_active", width=160, anchor="center")
        self._tree.column("bitrate",     width=120, anchor="center")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._action_frame = tk.Frame(self, bg=t.surface_dark)
        self._action_frame.pack(fill="x", padx=16, pady=(0, 12))

        self._sel_lbl = tk.Label(self._action_frame, text="",
                                  bg=t.surface_dark, fg=t.blue,
                                  font=("Segoe UI Semibold", 10), padx=12, pady=8)
        self._sel_lbl.pack(side="left")

        self._toggle_btn = tk.Button(self._action_frame, text="Enable / Disable",
                                      command=self._toggle_enabled,
                                      bg=t.surface_light, fg=t.text,
                                      bd=0, relief="flat", font=t.font_small,
                                      padx=12, pady=4, cursor="hand2")
        self._toggle_btn.pack(side="left", padx=(0, 6), pady=6)

        self._bitrate_btn = tk.Button(self._action_frame, text="Set Bitrate Limit…",
                                       command=self._set_bitrate_dialog,
                                       bg=t.surface_light, fg=t.text,
                                       bd=0, relief="flat", font=t.font_small,
                                       padx=12, pady=4, cursor="hand2")
        self._bitrate_btn.pack(side="left", padx=(0, 6), pady=6)

        self._delete_btn = tk.Button(self._action_frame, text="Delete User",
                                      command=self._delete_user,
                                      bg=t.status_stopped, fg="#ffffff",
                                      bd=0, relief="flat", font=t.font_small,
                                      padx=12, pady=4, cursor="hand2")
        self._delete_btn.pack(side="left", pady=6)

        self._set_actions_enabled(False)
        self._fetch()

    def _set_actions_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in (self._toggle_btn, self._bitrate_btn, self._delete_btn):
            btn.config(state=state)

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------
    def _fetch(self):
        self._refresh_btn.config(state="disabled", text="Loading…")
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        cfg    = self.controller.config_manager
        host   = cfg.emby_host
        port   = cfg.emby_port
        apikey = cfg.emby_apikey
        if not apikey:
            self.after(0, lambda: self._show_status(
                "No Emby API key configured.", self.theme.status_stopped))
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳ Refresh"))
            return
        try:
            users = _emby_request(host, port, apikey, "GET", "/Users")
            if not isinstance(users, list):
                users = []
            self.after(0, lambda u=users: self._populate(u))
        except Exception as e:
            self.after(0, lambda err=str(e): self._show_status(
                "Fetch failed: " + err[:80], self.theme.status_stopped))
        finally:
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳ Refresh"))

    def _populate(self, users):
        self._users = users
        self._tree.delete(*self._tree.get_children())
        self._set_actions_enabled(False)
        self._sel_lbl.config(text="")

        for u in users:
            policy   = u.get("Policy", {}) or {}
            name     = u.get("Name", "Unknown")
            is_admin = policy.get("IsAdministrator", False)
            disabled = policy.get("IsDisabled", False)
            role     = "Admin" if is_admin else "User"
            status   = "Disabled" if disabled else "Active"
            last     = _fmt_date(u.get("LastActivityDate", ""))
            bitrate  = _fmt_bitrate(policy.get("RemoteClientBitrateLimit", 0))
            iid      = u.get("Id", name)
            self._tree.insert("", "end", iid=iid,
                              values=(name, role, status, last, bitrate))

        self._show_status("{} user{} loaded.".format(
            len(users), "s" if len(users) != 1 else ""))

    # ------------------------------------------------------------------
    # SELECTION
    # ------------------------------------------------------------------
    def _on_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            self._set_actions_enabled(False)
            self._sel_lbl.config(text="")
            return
        uid  = sel[0]
        user = next((u for u in self._users if u.get("Id") == uid), None)
        if user:
            self._set_actions_enabled(True)
            policy   = user.get("Policy", {}) or {}
            disabled = policy.get("IsDisabled", False)
            self._sel_lbl.config(text="  Selected: {}".format(user.get("Name", uid)))
            self._toggle_btn.config(
                text="Enable" if disabled else "Disable",
                bg=self.theme.status_running if disabled else self.theme.surface_light,
                fg="#fff" if disabled else self.theme.text)

    def _selected_user(self):
        sel = self._tree.selection()
        if not sel:
            return None
        uid = sel[0]
        return next((u for u in self._users if u.get("Id") == uid), None)

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _toggle_enabled(self):
        user = self._selected_user()
        if not user:
            return
        policy   = dict(user.get("Policy", {}) or {})
        disabled = policy.get("IsDisabled", False)
        if not disabled and not messagebox.askyesno(
                "Disable User", "Disable {}? They won't be able to sign in.".format(
                    user.get("Name", "this user")), parent=self):
            return
        policy["IsDisabled"] = not disabled

        def worker():
            try:
                cfg = self.controller.config_manager
                _emby_request(cfg.emby_host, cfg.emby_port, cfg.emby_apikey,
                              "POST", "/Users/{}/Policy".format(user["Id"]), policy)
                action = "enabled" if disabled else "disabled"
                self.after(0, lambda: self._show_status(
                    "{} {}.".format(user["Name"], action), self.theme.status_running))
                self.after(0, self._fetch)
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Failed: " + err[:60], self.theme.status_stopped))
        threading.Thread(target=worker, daemon=True).start()

    def _set_bitrate_dialog(self):
        user = self._selected_user()
        if not user:
            return
        t       = self.theme
        policy  = user.get("Policy", {}) or {}
        current = policy.get("RemoteClientBitrateLimit", 0) or 0
        current_mbps = current / 1_000_000 if current else 0

        dlg = tk.Toplevel(self)
        dlg.title("Set Bitrate Limit")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)

        tk.Label(dlg, text="Bitrate limit for {}:".format(user.get("Name")),
                 bg=t.bg, fg=t.text, font=("Segoe UI Semibold", 11),
                 padx=20, pady=12).pack()

        frm = tk.Frame(dlg, bg=t.bg, padx=20)
        frm.pack(fill="x")
        tk.Label(frm, text="Mbps  (0 = unlimited):",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(side="left")
        var = tk.StringVar(value=str(round(current_mbps, 1)) if current_mbps else "0")
        entry = tk.Entry(frm, textvariable=var, width=8,
                         bg=t.surface_dark, fg=t.text, relief="flat",
                         insertbackground=t.blue, font=t.font_regular)
        entry.pack(side="left", padx=8)
        entry.focus_set()

        presets_frame = tk.Frame(dlg, bg=t.bg, padx=20)
        presets_frame.pack(fill="x", pady=4)
        tk.Label(presets_frame, text="Quick:", bg=t.bg, fg=t.text_dim,
                 font=t.font_small).pack(side="left")
        for label, val in [("Unlimited", "0"), ("4 Mbps", "4"), ("10 Mbps", "10"),
                           ("20 Mbps", "20"), ("40 Mbps", "40")]:
            tk.Button(presets_frame, text=label,
                      command=lambda v=val: var.set(v),
                      bg=t.surface_dark, fg=t.blue, bd=0, relief="flat",
                      font=t.font_small, padx=8, pady=2, cursor="hand2"
                      ).pack(side="left", padx=2)

        status_lbl = tk.Label(dlg, text="", bg=t.bg, fg=t.text_muted, font=t.font_small)
        status_lbl.pack(pady=4)

        def _apply():
            try:
                mbps = float(var.get())
                bps  = int(mbps * 1_000_000) if mbps > 0 else 0
            except ValueError:
                status_lbl.config(text="Enter a valid number.", fg=t.yellow)
                return
            new_policy = dict(policy)
            new_policy["RemoteClientBitrateLimit"] = bps
            apply_btn.config(state="disabled")
            def worker():
                try:
                    cfg = self.controller.config_manager
                    _emby_request(cfg.emby_host, cfg.emby_port, cfg.emby_apikey,
                                  "POST", "/Users/{}/Policy".format(user["Id"]), new_policy)
                    self.after(0, lambda: self._show_status(
                        "Bitrate limit set for {}.".format(user["Name"]),
                        self.theme.status_running))
                    self.after(0, self._fetch)
                    self.after(0, dlg.destroy)
                except Exception as e:
                    self.after(0, lambda err=str(e): status_lbl.config(
                        text="Failed: " + err[:60], fg=t.status_stopped))
                    self.after(0, lambda: apply_btn.config(state="normal"))
            threading.Thread(target=worker, daemon=True).start()

        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=12)
        apply_btn = tk.Button(btn_row, text="Apply", command=_apply)
        t.style_button(apply_btn)
        apply_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat", bd=0,
                  cursor="hand2").pack(side="left")

        entry.bind("<Return>", lambda e: _apply())

    def _delete_user(self):
        user = self._selected_user()
        if not user:
            return
        name = user.get("Name", "this user")
        if not messagebox.askyesno(
                "Delete User",
                "Permanently delete '{}'?\nThis cannot be undone.".format(name),
                parent=self):
            return
        def worker():
            try:
                cfg = self.controller.config_manager
                _emby_request(cfg.emby_host, cfg.emby_port, cfg.emby_apikey,
                              "DELETE", "/Users/{}".format(user["Id"]))
                self.after(0, lambda: self._show_status(
                    "User '{}' deleted.".format(name), self.theme.status_running))
                self.after(0, self._fetch)
            except Exception as e:
                self.after(0, lambda err=str(e): self._show_status(
                    "Delete failed: " + err[:60], self.theme.status_stopped))
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # NEW USER
    # ------------------------------------------------------------------
    def _new_user_dialog(self):
        t   = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("Create Emby User")
        dlg.configure(bg=t.bg)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)

        tk.Label(dlg, text="New Emby User",
                 bg=t.bg, fg=t.text, font=("Segoe UI Semibold", 12),
                 padx=20, pady=12).pack()

        frm = tk.Frame(dlg, bg=t.bg, padx=20)
        frm.pack(fill="x")

        tk.Label(frm, text="Username:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=0, column=0, sticky="w", pady=6)
        name_var = tk.StringVar()
        name_entry = tk.Entry(frm, textvariable=name_var, width=28,
                               bg=t.surface_dark, fg=t.text, relief="flat",
                               insertbackground=t.blue, font=t.font_regular)
        name_entry.grid(row=0, column=1, padx=8, pady=6)
        name_entry.focus_set()

        tk.Label(frm, text="Password:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).grid(row=1, column=0, sticky="w", pady=6)
        pw_var = tk.StringVar()
        tk.Entry(frm, textvariable=pw_var, show="•", width=28,
                 bg=t.surface_dark, fg=t.text, relief="flat",
                 insertbackground=t.blue, font=t.font_regular).grid(
                     row=1, column=1, padx=8, pady=6)

        status_lbl = tk.Label(dlg, text="", bg=t.bg, fg=t.text_muted, font=t.font_small)
        status_lbl.pack(pady=4)

        def _create():
            name = name_var.get().strip()
            pw   = pw_var.get()
            if not name:
                status_lbl.config(text="Username is required.", fg=t.yellow)
                return
            create_btn.config(state="disabled")
            def worker():
                try:
                    cfg = self.controller.config_manager
                    _emby_request(cfg.emby_host, cfg.emby_port, cfg.emby_apikey,
                                  "POST", "/Users/New", {"Name": name, "Password": pw})
                    self.after(0, lambda: self._show_status(
                        "User '{}' created.".format(name), self.theme.status_running))
                    self.after(0, self._fetch)
                    self.after(0, dlg.destroy)
                except Exception as e:
                    self.after(0, lambda err=str(e): status_lbl.config(
                        text="Failed: " + err[:70], fg=t.status_stopped))
                    self.after(0, lambda: create_btn.config(state="normal"))
            threading.Thread(target=worker, daemon=True).start()

        btn_row = tk.Frame(dlg, bg=t.bg)
        btn_row.pack(pady=12)
        create_btn = tk.Button(btn_row, text="Create", command=_create)
        t.style_button(create_btn)
        create_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  bg=t.surface_dark, fg=t.text, relief="flat", bd=0,
                  cursor="hand2").pack(side="left")

        name_entry.bind("<Return>", lambda e: _create())

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _show_status(self, msg, color=None):
        t = self.theme
        if msg.endswith("…") or msg.endswith("..."):
            self._status_lbl.config(text=msg, bg=t.blue, fg="#ffffff")
            return
        self._status_lbl.config(text=msg, bg=t.surface_dark, fg=color or t.text_muted)
