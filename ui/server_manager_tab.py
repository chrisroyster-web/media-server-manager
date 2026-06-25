# ui/server_manager_tab.py
"""
Server profile manager.
Lists saved SSH server profiles; allows add / edit / delete.
Switching servers (connect) is handled by main.py's switch_server().
"""

import tkinter as tk


class ServerManagerTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._selected  = None   # index of selected profile
        self._build_ui()
        self._load()

    # =========================================================
    # BUILD
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="SERVER PROFILES",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        add_btn = tk.Button(hdr, text="+ Add Server", command=self._add)
        t.style_button(add_btn)
        add_btn.pack(side="right")

        # Two-column layout: profile list  |  detail/edit form
        body = tk.Frame(self, bg=t.bg)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # ---- Left: profile list ----
        list_outer = tk.Frame(body, bg=t.card_bg,
                              highlightbackground=t.card_border,
                              highlightthickness=1, width=220)
        list_outer.pack(side="left", fill="y", padx=(0, 12))
        list_outer.pack_propagate(False)

        tk.Label(list_outer, text="Servers", bg=t.card_bg,
                 fg=t.text_muted, font=t.font_small,
                 anchor="w", padx=10).pack(fill="x", pady=(8, 4))
        tk.Frame(list_outer, bg=t.card_border, height=1).pack(fill="x")

        self._list_frame = tk.Frame(list_outer, bg=t.card_bg)
        self._list_frame.pack(fill="both", expand=True)

        # ---- Right: edit form ----
        self._form_outer = tk.Frame(body, bg=t.bg)
        self._form_outer.pack(side="left", fill="both", expand=True)

        self._form_frame = None
        self._show_empty_state()

    def _show_empty_state(self):
        if self._form_frame:
            self._form_frame.destroy()
        self._form_frame = tk.Frame(self._form_outer, bg=self.theme.bg)
        self._form_frame.pack(fill="both", expand=True)
        tk.Label(self._form_frame,
                 text="Select a server to edit, or click + Add Server",
                 bg=self.theme.bg, fg=self.theme.text_muted,
                 font=("Segoe UI", 12)).pack(pady=60)

    # =========================================================
    # LOAD / RENDER LIST
    # =========================================================
    def _load(self):
        """Reload profile list from config and redraw."""
        for w in self._list_frame.winfo_children():
            w.destroy()

        servers = self.controller.config_manager.get_servers()
        active  = self.controller.config_manager.get_active_server_index()

        if not servers:
            tk.Label(self._list_frame, text="No servers yet.",
                     bg=self.theme.card_bg, fg=self.theme.text_muted,
                     font=self.theme.font_small).pack(pady=12)
            return

        for i, srv in enumerate(servers):
            self._build_list_row(i, srv, active)

        # Update sidebar
        self.controller._update_server_sidebar()

    def _build_list_row(self, idx, srv, active_idx):
        t    = self.theme
        is_a = (idx == active_idx)
        row  = tk.Frame(self._list_frame,
                        bg=t.blue if is_a else t.card_bg)
        row.pack(fill="x", pady=1)

        indicator = tk.Canvas(row, width=6, height=30,
                               bg=t.blue if is_a else t.card_bg,
                               highlightthickness=0)
        if is_a:
            indicator.create_rectangle(0, 0, 6, 30, fill=t.status_running, outline="")
        indicator.pack(side="left")

        lbl = tk.Label(row,
                       text=srv.get("name") or srv.get("host", "Unnamed"),
                       bg=t.blue if is_a else t.card_bg,
                       fg="#fff" if is_a else t.text,
                       font=t.font_regular, anchor="w", padx=10, pady=6,
                       cursor="hand2")
        lbl.pack(side="left", fill="x", expand=True)

        host_lbl = tk.Label(row,
                            text=srv.get("host", ""),
                            bg=t.blue if is_a else t.card_bg,
                            fg="#dde" if is_a else t.text_muted,
                            font=t.font_small, padx=6)
        host_lbl.pack(side="right")

        for w in (row, lbl, host_lbl, indicator):
            w.bind("<Button-1>", lambda e, i=idx: self._select(i))

    def _select(self, idx):
        self._selected = idx
        servers = self.controller.config_manager.get_servers()
        if 0 <= idx < len(servers):
            self._show_edit_form(idx, servers[idx])

    # =========================================================
    # EDIT FORM
    # =========================================================
    def _show_edit_form(self, idx, srv):
        if self._form_frame:
            self._form_frame.destroy()

        t = self.theme
        self._form_frame = tk.Frame(self._form_outer, bg=t.bg)
        self._form_frame.pack(fill="both", expand=True)

        # Form fields
        fields = [
            ("name",     "Display Name",   False),
            ("host",     "Host / IP",      False),
            ("port",     "SSH Port",       False),
            ("username", "Username",       False),
            ("password", "Password",       True),
            ("key_path", "SSH Key Path",   False),
            ("notes",    "Notes",          False),
        ]

        self._edit_vars = {}
        frm = tk.Frame(self._form_frame, bg=t.surface, padx=16, pady=12)
        frm.pack(fill="x")
        frm.columnconfigure(1, weight=1)

        for row_i, (key, label, secret) in enumerate(fields):
            tk.Label(frm, text=label + ":", bg=t.surface, fg=t.text,
                     font=t.font_regular).grid(
                         row=row_i, column=0, sticky="w", pady=5, padx=(0, 12))
            var = tk.StringVar(value=srv.get(key, ""))
            self._edit_vars[key] = var
            e = tk.Entry(frm, textvariable=var, show="*" if secret else "",
                         font=t.font_regular)
            t.style_entry(e)
            e.grid(row=row_i, column=1, sticky="ew", pady=5)

        # Buttons
        btn_row = tk.Frame(self._form_frame, bg=t.bg)
        btn_row.pack(fill="x", pady=(12, 0))

        save_btn = tk.Button(btn_row, text="Save", command=lambda: self._save(idx))
        t.style_button(save_btn)
        save_btn.pack(side="left", padx=(0, 8))

        connect_btn = tk.Button(btn_row, text="⚡ Connect",
                                command=lambda: self._connect(idx),
                                bg=t.status_running, fg="#fff",
                                bd=0, relief="flat", font=t.font_regular,
                                padx=12, pady=5, cursor="hand2")
        connect_btn.pack(side="left", padx=(0, 8))

        del_btn = tk.Button(btn_row, text="Delete",
                            command=lambda: self._delete(idx),
                            bg=t.status_stopped, fg="#fff",
                            bd=0, relief="flat", font=t.font_regular,
                            padx=12, pady=5, cursor="hand2")
        del_btn.pack(side="right")

        self._status_lbl = tk.Label(self._form_frame, text="",
                                     bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._status_lbl.pack(anchor="w", pady=(8, 0))

    # =========================================================
    # CRUD
    # =========================================================
    def _add(self):
        cfg     = self.controller.config_manager
        servers = cfg.get_servers()
        new     = {"name": "New Server", "host": "", "port": "22",
                   "username": "", "password": "", "key_path": "", "notes": ""}
        servers.append(new)
        cfg.set_servers(servers)
        self._load()
        self._select(len(servers) - 1)

    def _save(self, idx):
        cfg     = self.controller.config_manager
        servers = cfg.get_servers()
        if 0 <= idx < len(servers):
            for key, var in self._edit_vars.items():
                servers[idx][key] = var.get().strip()
            cfg.set_servers(servers)
            self._load()
            self._select(idx)
            self._status_lbl.config(text="Saved.", fg=self.theme.status_running)
            self.after(2000, lambda: self._status_lbl.config(text=""))

    def _delete(self, idx):
        import tkinter.messagebox as mb
        cfg     = self.controller.config_manager
        servers = cfg.get_servers()
        if not (0 <= idx < len(servers)):
            return
        name = servers[idx].get("name") or servers[idx].get("host", "this server")
        if not mb.askyesno("Delete Server",
                            "Delete profile for '{}'?".format(name)):
            return
        servers.pop(idx)
        # Clamp active index
        active = cfg.get_active_server_index()
        if active >= len(servers):
            cfg.set_active_server_index(max(0, len(servers) - 1))
        cfg.set_servers(servers)
        self._selected = None
        self._show_empty_state()
        self._load()

    def _connect(self, idx):
        cfg     = self.controller.config_manager
        servers = cfg.get_servers()
        if not (0 <= idx < len(servers)):
            return
        # Save any pending edits first
        for key, var in self._edit_vars.items():
            servers[idx][key] = var.get().strip()
        cfg.set_servers(servers)
        cfg.set_active_server_index(idx)
        self.controller.switch_server(servers[idx])
        self._load()
