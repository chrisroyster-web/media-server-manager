# ui/server_dialog.py
"""
Modal dialog for adding or editing a server profile.
Opens from the sidebar "+" button or server right-click menu.
"""
import tkinter as tk
from tkinter import messagebox


class ServerDialog(tk.Toplevel):
    """
    Compact Add / Edit Server modal.
    - Add mode  (profile=None): blank form, "Save & Connect" + "Save Only"
    - Edit mode (profile=dict): pre-filled, adds a "Delete" button
    """

    def __init__(self, parent, controller, profile=None):
        super().__init__(parent)
        self.controller = controller
        self.theme      = controller.theme
        self._profile   = profile or {}
        self._editing   = bool(self._profile.get("host"))

        t = self.theme
        self.configure(bg=t.bg)
        self.title("Edit Server" if self._editing else "Add Server")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._center()
        self.wait_window(self)

    # ------------------------------------------------------------------
    def _build(self):
        t = self.theme
        outer = tk.Frame(self, bg=t.bg, padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        tk.Label(outer,
                 text="Edit Server" if self._editing else "Add Server",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(anchor="w", pady=(0, 16))

        frm = tk.Frame(outer, bg=t.surface, padx=16, pady=12)
        frm.pack(fill="x")
        frm.columnconfigure(1, weight=1)

        def _row(r, label, key, secret=False, default=""):
            tk.Label(frm, text=label + ":", bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(row=r, column=0, sticky="w",
                                               pady=6, padx=(0, 12))
            var = tk.StringVar(value=self._profile.get(key, default))
            e = tk.Entry(frm, textvariable=var,
                         show="*" if secret else "",
                         font=t.font_regular)
            t.style_entry(e)
            e.grid(row=r, column=1, sticky="ew", pady=6)
            if r == 1:
                e.focus_set()
            return var

        self._name_var = _row(0, "Display Name",  "name")
        self._host_var = _row(1, "Host / IP",      "host")
        self._port_var = _row(2, "SSH Port",       "port",     default="22")
        self._user_var = _row(3, "Username",       "username")
        self._pass_var = _row(4, "Password",       "password", secret=True)
        self._key_var  = _row(5, "SSH Key Path",   "key_path")

        tk.Label(frm,
                 text="Leave password blank to use an SSH key. "
                      "Leave key path blank to auto-use ~/.ssh/id_rsa.",
                 bg=t.surface, fg=t.text_muted,
                 font=("Segoe UI", 8),
                 wraplength=340, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 2))

        # ---- Status label ----
        self._status = tk.Label(outer, text="", bg=t.bg,
                                fg=t.text_muted, font=t.font_small)
        self._status.pack(anchor="w", pady=(12, 0))

        # ---- Button row ----
        btn_row = tk.Frame(outer, bg=t.bg)
        btn_row.pack(fill="x", pady=(8, 0))

        conn_btn = tk.Button(btn_row,
                             text="Save & Connect",
                             command=self._save_and_connect,
                             bg=t.blue, fg="#fff",
                             bd=0, relief="flat",
                             font=t.font_regular, padx=14, pady=6,
                             cursor="hand2")
        conn_btn.pack(side="left", padx=(0, 8))

        save_btn = tk.Button(btn_row, text="Save Only",
                             command=self._save_only)
        t.style_button(save_btn)
        save_btn.pack(side="left", padx=(0, 8))

        cancel_btn = tk.Button(btn_row, text="Cancel",
                               command=self.destroy)
        t.style_button(cancel_btn)
        cancel_btn.pack(side="left")

        if self._editing:
            del_btn = tk.Button(btn_row, text="Delete Profile",
                                command=self._delete,
                                bg=t.status_stopped, fg="#fff",
                                bd=0, relief="flat",
                                font=t.font_regular, padx=14, pady=6,
                                cursor="hand2")
            del_btn.pack(side="right")

        # Allow Enter key to trigger Save & Connect
        self.bind("<Return>", lambda e: self._save_and_connect())
        self.bind("<Escape>", lambda e: self.destroy())

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry("+{}+{}".format(pw - w // 2, ph - h // 2))

    # ------------------------------------------------------------------
    def _collect(self):
        host = self._host_var.get().strip()
        if not host:
            self._status.config(text="Host is required.",
                                fg=self.theme.status_stopped)
            return None
        return {
            "name":     self._name_var.get().strip() or host,
            "host":     host,
            "port":     self._port_var.get().strip() or "22",
            "username": self._user_var.get().strip(),
            "password": self._pass_var.get().strip(),
            "key_path": self._key_var.get().strip(),
            "notes":    self._profile.get("notes", ""),
        }

    def _persist(self, data):
        cfg = self.controller.config_manager
        cfg.upsert_server(data["host"],
                          username=data["username"],
                          port=data["port"],
                          password=data["password"],
                          key_path=data["key_path"])
        # upsert_server doesn't write name/notes — patch them here
        servers = cfg.get_servers()
        for srv in servers:
            if srv.get("host") == data["host"]:
                srv["name"]  = data["name"]
                srv["notes"] = data["notes"]
                break
        cfg.set_servers(servers)
        self.controller._update_server_sidebar()
        if hasattr(self.controller, "server_tab"):
            self.controller.server_tab._load()

    def _save_only(self):
        data = self._collect()
        if data is None:
            return
        self._persist(data)
        self._status.config(text="Saved.", fg=self.theme.status_running)
        self.after(1000, self.destroy)

    def _save_and_connect(self):
        data = self._collect()
        if data is None:
            return
        self._persist(data)
        cfg     = self.controller.config_manager
        servers = cfg.get_servers()
        profile = next((s for s in servers if s.get("host") == data["host"]), None)
        if profile:
            idx = servers.index(profile)
            cfg.set_active_server_index(idx)
            self.controller._update_server_sidebar()
            self.controller.switch_server(profile)
        self.destroy()

    def _delete(self):
        name = self._profile.get("name") or self._profile.get("host", "this server")
        if not messagebox.askyesno("Delete Server",
                                   "Delete profile for '{}'?".format(name),
                                   parent=self):
            return
        cfg         = self.controller.config_manager
        all_servers = cfg.get_servers()
        del_idx     = next((i for i, s in enumerate(all_servers)
                            if s.get("host") == self._profile.get("host")), None)
        servers = [s for s in all_servers
                   if s.get("host") != self._profile.get("host")]
        cfg.set_servers(servers)
        active = cfg.get_active_server_index()
        if del_idx is not None and del_idx < active:
            active -= 1
        if active >= len(servers):
            active = max(0, len(servers) - 1)
        cfg.set_active_server_index(active)
        self.controller._update_server_sidebar()
        if hasattr(self.controller, "server_tab"):
            self.controller.server_tab._load()
        self.destroy()
