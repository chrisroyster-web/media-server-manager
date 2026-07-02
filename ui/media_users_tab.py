# ui/media_users_tab.py
"""
Unified Media Users tab — Emby and Jellyfin share near-identical APIs
(Emby adds /emby/ prefix). A single tab with a server picker replaces
the two separate EmbyUsersTab / JellyfinUsersTab.
"""

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import threading
import urllib.request
import json
import time

from ui.refresh_control import RefreshControl
from ui.empty_state import EmptyState

_SERVER_JELLYFIN = "Jellyfin"
_SERVER_EMBY     = "Emby"

_JF_COLOR   = "#00a4dc"
_EMBY_COLOR = "#52b54b"

_BITRATE_PRESETS = [
    ("Unlimited",  0),
    ("4 Mbps",     4_000_000),
    ("10 Mbps",   10_000_000),
    ("20 Mbps",   20_000_000),
    ("40 Mbps",   40_000_000),
]


def _request(host, port, apikey, method, path, body=None, is_emby=False):
    host    = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    prefix  = "/emby" if is_emby else ""
    url     = "http://{}:{}{}{}".format(host, port, prefix, path)
    data    = json.dumps(body).encode() if body is not None else None
    headers = {
        "X-Emby-Token"   if is_emby else "X-MediaBrowser-Token": apikey,
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as r:
        raw = r.read()
        return json.loads(raw.decode()) if raw else {}


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


class MediaUsersTab(tk.Frame):
    """Unified Emby / Jellyfin user management."""

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._users     = []
        self._selected  = None
        self._build_ui()

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="MEDIA USERS",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._rc = RefreshControl(hdr, self.controller, "media_users",
                                  default=120, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Server picker
        picker = tk.Frame(self, bg=t.surface_dark)
        picker.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(picker, text="Server:", bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(12, 6), pady=8)
        self._server_var = tk.StringVar()
        self._server_menu = ttk.Combobox(picker, textvariable=self._server_var,
                                          state="readonly", width=12,
                                          font=t.font_small)
        self._server_menu.pack(side="left", pady=6)
        self._server_var.trace_add("write", lambda *_: self._on_server_change())

        # New user button
        self._new_btn = tk.Button(picker, text="+ New User",
                                   command=self._new_user)
        t.style_button(self._new_btn)
        self._new_btn.pack(side="right", padx=12, pady=6)

        # Treeview
        tv_frame = tk.Frame(self, bg=t.bg)
        tv_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("MU.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("MU.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("MU.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("name", "role", "status", "last_active", "bitrate")
        self._tree = ttk.Treeview(tv_frame, columns=cols,
                                   show="headings", style="MU.Treeview")
        for col, w, lbl, anch in [
            ("name",        200, "Username",    "w"),
            ("role",         80, "Role",        "w"),
            ("status",       90, "Status",      "w"),
            ("last_active", 170, "Last Active", "w"),
            ("bitrate",     110, "Bitrate Limit","w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anch)
            self._tree.column(col, width=w, minwidth=40,
                              anchor=anch, stretch=(col == "name"))

        self._tree.tag_configure("disabled", foreground=t.text_muted)
        self._tree.tag_configure("admin",    foreground=t.yellow)
        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Button-3>", self._on_right_click)

        # Action panel (shown when a row is selected)
        self._action_frame = tk.Frame(self, bg=t.surface_dark)
        self._action_frame.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(self._action_frame, text="Selected user:",
                 bg=t.surface_dark, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(12, 4), pady=8)
        self._sel_lbl = tk.Label(self._action_frame, text="—",
                                  bg=t.surface_dark, fg=t.text,
                                  font=t.font_small)
        self._sel_lbl.pack(side="left", padx=(0, 16))
        self._toggle_btn = tk.Button(self._action_frame, text="Disable",
                                      command=self._toggle_user, width=10)
        t.style_button(self._toggle_btn)
        self._toggle_btn.pack(side="left", padx=(0, 6))
        self._bitrate_btn = tk.Button(self._action_frame, text="Set Bitrate",
                                       command=self._set_bitrate, width=10)
        t.style_button(self._bitrate_btn)
        self._bitrate_btn.pack(side="left", padx=(0, 6))
        self._del_btn = tk.Button(self._action_frame, text="Delete",
                                   command=self._delete_user, width=8)
        t.style_button(self._del_btn, "danger")
        self._del_btn.pack(side="left")

        self._status = tk.Label(self, text="Select a server to load users.",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        # Empty state overlay — shown when no media server API keys are configured
        self._empty = EmptyState(
            self, t,
            icon="👥",
            title="No media server configured",
            subtitle="Add a Jellyfin or Emby API key in Settings to manage users.",
            action_text="⚙ Open Settings",
            action_cmd=lambda: self.controller.tabs.select(8),
        )
        self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._empty.place_forget()
        self._populate_server_menu()

    def _populate_server_menu(self):
        cfg     = self.controller.config_manager
        servers = []
        if cfg.jellyfin_apikey:  servers.append(_SERVER_JELLYFIN)
        if cfg.emby_apikey:      servers.append(_SERVER_EMBY)
        self._server_menu["values"] = servers
        if servers:
            if not self._server_var.get():
                self._server_var.set(servers[0])
            self._empty.place_forget()
        else:
            self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._empty.lift()

    def _on_server_change(self):
        self._selected = None
        if hasattr(self, "_sel_lbl"):
            self._sel_lbl.config(text="—")
        if hasattr(self, "_toggle_btn"):
            self._toggle_btn.config(text="Disable")
        self.refresh()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _is_emby(self):
        return self._server_var.get() == _SERVER_EMBY

    def _creds(self):
        cfg = self.controller.config_manager
        if self._is_emby():
            return cfg.emby_host, cfg.emby_port, cfg.emby_apikey
        return cfg.jellyfin_host, cfg.jellyfin_port, cfg.jellyfin_apikey

    def _api(self, method, path, body=None):
        host, port, key = self._creds()
        return _request(host, port, key, method, path, body, self._is_emby())

    def _accent_color(self):
        return _EMBY_COLOR if self._is_emby() else _JF_COLOR

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def on_show(self):
        self._populate_server_menu()
        self.refresh()

    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        server = self._server_var.get()
        if not server:
            return
        host, port, key = self._creds()
        if not key:
            self._status.config(
                text="No API key configured for {}.  →  Add it in Settings (Config tab).".format(server),
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        server = self._server_var.get()
        try:
            users = self._api("GET", "/Users")
            if isinstance(users, dict):
                users = users.get("Items", []) or []
        except Exception as e:
            self.after(0, lambda: self._status.config(
                text="Cannot reach {}: {}".format(server, e),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped))
            return
        finally:
            self._fetching = False
        self.after(0, lambda: self._populate(server, users))
        self.after(0, lambda: self._last_lbl.config(
            text="{} · {}".format(server, time.strftime("%H:%M"))))
        self.after(0, self._rc.schedule)

    # ------------------------------------------------------------------
    # POPULATE
    # ------------------------------------------------------------------
    def _populate(self, server, users):
        self._users = users
        self._tree.delete(*self._tree.get_children())
        for u in users:
            policy   = u.get("Policy", {}) or {}
            disabled = policy.get("IsDisabled", False)
            is_admin = policy.get("IsAdministrator", False)
            role     = "Admin" if is_admin else "User"
            status   = "Disabled" if disabled else "Active"
            last_raw = u.get("LastActivityDate") or u.get("LastLoginDate")
            tag      = "disabled" if disabled else ("admin" if is_admin else "")
            bitrate  = _fmt_bitrate(policy.get("RemoteClientBitrateLimit", 0))
            self._tree.insert("", "end", iid=u["Id"],
                              tags=(tag,) if tag else (),
                              values=(u.get("Name", ""), role, status,
                                      _fmt_date(last_raw), bitrate))
        self._status.config(
            text="{} user(s) on {}".format(len(users), server),
            bg=self.theme.surface_dark, fg=self._accent_color())

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            self._selected = None
            return
        uid  = sel[0]
        user = next((u for u in self._users if u["Id"] == uid), None)
        if not user:
            return
        self._selected = user
        disabled = (user.get("Policy") or {}).get("IsDisabled", False)
        self._sel_lbl.config(text=user.get("Name", uid))
        self._toggle_btn.config(
            text="Enable" if disabled else "Disable",
            fg=self.theme.status_running if disabled else self.theme.yellow)

    def _on_right_click(self, event):
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._on_select()

        t = self.theme
        menu = tk.Menu(self, tearoff=0,
                       bg=t.surface, fg=t.text,
                       activebackground=t.blue, activeforeground="#ffffff",
                       bd=0, relief="flat", font=t.font_small)

        if self._selected:
            disabled = (self._selected.get("Policy") or {}).get("IsDisabled", False)
            menu.add_command(
                label="Enable User" if disabled else "Disable User",
                command=self._toggle_user)
            menu.add_command(label="Set Bitrate Limit…", command=self._set_bitrate)
            menu.add_separator()
            menu.add_command(label="Delete User", command=self._delete_user)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _toggle_user(self):
        if not self._selected:
            return
        user     = self._selected
        policy   = dict(user.get("Policy") or {})
        disabled = policy.get("IsDisabled", False)
        if not disabled and not messagebox.askyesno(
                "Disable User", "Disable {}? They won't be able to sign in.".format(
                    user.get("Name", "this user")), parent=self):
            return
        policy["IsDisabled"] = not disabled
        uid = user["Id"]

        def do():
            try:
                self._api("POST", "/Users/{}/Policy".format(uid), policy)
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Error", "Could not update user policy:\n{}".format(e)))
        threading.Thread(target=do, daemon=True).start()

    def _set_bitrate(self):
        if not self._selected:
            return
        user   = self._selected
        policy = dict(user.get("Policy") or {})
        uid    = user["Id"]

        dlg = tk.Toplevel(self)
        dlg.title("Set Bitrate Limit — {}".format(user.get("Name", "")))
        dlg.configure(bg=self.theme.bg)
        dlg.resizable(False, False)
        dlg.grab_set()

        t = self.theme
        tk.Label(dlg, text="Choose a bitrate limit:",
                 bg=t.bg, fg=t.text, font=t.font_small).pack(padx=24, pady=(16, 8))

        selected_bps = tk.IntVar(value=policy.get("RemoteClientBitrateLimit", 0))
        for label, bps in _BITRATE_PRESETS:
            rb = tk.Radiobutton(dlg, text=label, variable=selected_bps, value=bps,
                                bg=t.bg, fg=t.text, selectcolor=t.surface,
                                font=t.font_small, activebackground=t.bg)
            rb.pack(anchor="w", padx=32)

        def apply():
            policy["RemoteClientBitrateLimit"] = selected_bps.get()
            dlg.destroy()
            def do():
                try:
                    self._api("POST", "/Users/{}/Policy".format(uid), policy)
                    self.after(0, self.refresh)
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror(
                        "Error", "Could not set bitrate:\n{}".format(e)))
            threading.Thread(target=do, daemon=True).start()

        btns = tk.Frame(dlg, bg=t.bg)
        btns.pack(pady=16, padx=24)
        ok = tk.Button(btns, text="Apply", command=apply)
        t.style_button(ok)
        ok.pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Cancel", command=dlg.destroy,
                  bg=t.surface, fg=t.text, relief="flat",
                  activebackground=t.surface_light, bd=0).pack(side="left")

    def _delete_user(self):
        if not self._selected:
            return
        user = self._selected
        name = user.get("Name", user["Id"])
        if not messagebox.askyesno("Delete User",
                                   "Permanently delete \"{}\"?\nThis cannot be undone.".format(name),
                                   icon="warning"):
            return
        uid = user["Id"]
        def do():
            try:
                self._api("DELETE", "/Users/{}".format(uid))
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Error", "Could not delete user:\n{}".format(e)))
        threading.Thread(target=do, daemon=True).start()

    def _new_user(self):
        server = self._server_var.get()
        if not server:
            return
        name = simpledialog.askstring("New User",
                                      "Username for new {} user:".format(server),
                                      parent=self)
        if not name:
            return
        pw = simpledialog.askstring("New User",
                                    "Password (leave blank for none):",
                                    parent=self, show="*")
        def do():
            try:
                body = {"Name": name, "Password": pw or ""}
                self._api("POST", "/Users/New", body)
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Error", "Could not create user:\n{}".format(e)))
        threading.Thread(target=do, daemon=True).start()
