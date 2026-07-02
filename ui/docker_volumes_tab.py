# ui/docker_volumes_tab.py
"""
Docker Volumes & Networks tab — inspect, prune, remove, and create
Docker volumes and networks via SSH.
"""

import json
import re
import shlex
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from ui.refresh_control import RefreshControl


class DockerVolumesTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._volumes   = []
        self._networks  = []
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="DOCKER VOLUMES & NETWORKS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "docker_volumes",
                                  default=30, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Two-pane vertical split
        paned = tk.PanedWindow(self, orient="vertical",
                               bg=t.card_border, sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        # ── TOP PANE: VOLUMES ─────────────────────────────────────────────
        vol_fr = tk.Frame(paned, bg=t.bg)
        paned.add(vol_fr, minsize=180, stretch="always")

        vol_hdr = tk.Frame(vol_fr, bg=t.bg)
        vol_hdr.pack(fill="x", pady=(6, 4))
        tk.Label(vol_hdr, text="VOLUMES", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        self._prune_btn = tk.Button(vol_hdr, text="🗑 Prune Unused",
                                     command=self._prune_volumes)
        t.style_button(self._prune_btn, "danger")
        self._prune_btn.pack(side="right", padx=(4, 0))
        self._vol_rm_btn = tk.Button(vol_hdr, text="✕ Remove",
                                      command=self._remove_volume,
                                      state="disabled")
        t.style_button(self._vol_rm_btn)
        self._vol_rm_btn.pack(side="right", padx=(4, 0))

        vol_cols   = ("name", "driver", "scope", "size", "links", "created")
        vol_hdgs   = ("Name", "Driver", "Scope", "Size", "Links", "Created")
        vol_widths = (220, 80, 70, 90, 55, 160)

        style = ttk.Style()
        style.configure("DV.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=24, font=t.font_mono)
        style.configure("DV.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("DV.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        vtree_fr = tk.Frame(vol_fr, bg=t.bg)
        vtree_fr.pack(fill="both", expand=True)
        self._vol_tree = ttk.Treeview(vtree_fr, columns=vol_cols,
                                       show="headings", style="DV.Treeview",
                                       selectmode="browse")
        for col, hdr_txt, w in zip(vol_cols, vol_hdgs, vol_widths):
            self._vol_tree.heading(col, text=hdr_txt, anchor="w")
            self._vol_tree.column(col, width=w, minwidth=40, anchor="w",
                                  stretch=(col in {"name"}))
        self._vol_tree.tag_configure("unused",  foreground=t.yellow)
        self._vol_tree.tag_configure("inuse",   foreground=t.status_running)

        vvsb = ttk.Scrollbar(vtree_fr, orient="vertical",
                             command=self._vol_tree.yview)
        self._vol_tree.configure(yscrollcommand=vvsb.set)
        vvsb.pack(side="right", fill="y")
        self._vol_tree.pack(fill="both", expand=True)
        self._vol_tree.bind("<<TreeviewSelect>>", self._on_vol_select)
        self._vol_tree.bind("<Double-Button-1>",  self._vol_inspect)

        # ── BOTTOM PANE: NETWORKS ─────────────────────────────────────────
        net_fr = tk.Frame(paned, bg=t.bg)
        paned.add(net_fr, minsize=180, stretch="always")

        net_hdr = tk.Frame(net_fr, bg=t.bg)
        net_hdr.pack(fill="x", pady=(6, 4))
        tk.Label(net_hdr, text="NETWORKS", bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        self._net_create_btn = tk.Button(net_hdr, text="＋ Create",
                                          command=self._create_network)
        t.style_button(self._net_create_btn)
        self._net_create_btn.pack(side="right", padx=(4, 0))
        self._net_rm_btn = tk.Button(net_hdr, text="✕ Remove",
                                      command=self._remove_network,
                                      state="disabled")
        t.style_button(self._net_rm_btn)
        self._net_rm_btn.pack(side="right", padx=(4, 0))

        net_cols   = ("name", "driver", "scope", "net_id", "containers", "created")
        net_hdgs   = ("Name", "Driver", "Scope", "ID", "Containers", "Created")
        net_widths = (180, 80, 70, 100, 280, 150)

        style.configure("DN.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=24, font=t.font_mono)
        style.configure("DN.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("DN.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        ntree_fr = tk.Frame(net_fr, bg=t.bg)
        ntree_fr.pack(fill="both", expand=True)
        self._net_tree = ttk.Treeview(ntree_fr, columns=net_cols,
                                       show="headings", style="DN.Treeview",
                                       selectmode="browse")
        for col, hdr_txt, w in zip(net_cols, net_hdgs, net_widths):
            self._net_tree.heading(col, text=hdr_txt, anchor="w")
            self._net_tree.column(col, width=w, minwidth=40, anchor="w",
                                  stretch=(col in {"name", "containers"}))
        self._net_tree.tag_configure("builtin", foreground=t.text_muted)
        self._net_tree.tag_configure("custom",  foreground=t.text)

        nvsb = ttk.Scrollbar(ntree_fr, orient="vertical",
                             command=self._net_tree.yview)
        self._net_tree.configure(yscrollcommand=nvsb.set)
        nvsb.pack(side="right", fill="y")
        self._net_tree.pack(fill="both", expand=True)
        self._net_tree.bind("<<TreeviewSelect>>", self._on_net_select)
        self._net_tree.bind("<Double-Button-1>",  self._net_inspect)

        # ── CONSOLE STRIP ─────────────────────────────────────────────────
        con_fr = tk.Frame(self, bg=t.surface_dark)
        con_fr.pack(fill="x", padx=16, pady=(0, 4))
        con_top = tk.Frame(con_fr, bg=t.surface_dark)
        con_top.pack(fill="x", padx=6, pady=(4, 2))
        tk.Label(con_top, text="OUTPUT", bg=t.surface_dark,
                 fg=t.text_muted, font=("Segoe UI", 7, "bold")).pack(side="left")
        tk.Button(con_top, text="Clear",
                  command=self._clear_console,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small).pack(side="right")
        self._console = tk.Text(con_fr, height=4, bg=t.surface_dark, fg=t.text,
                                font=t.font_mono, bd=0, relief="flat",
                                state="disabled", wrap="char")
        self._console.pack(fill="x", padx=6, pady=(0, 4))
        self._console.tag_configure("cmd", foreground=t.cyan)
        self._console.tag_configure("ok",  foreground=t.status_running)
        self._console.tag_configure("err", foreground=t.status_stopped)

        # Status bar
        self._status = tk.Label(self, text="Connect to server to view volumes",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            return
        self._status.config(text="Loading…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            # Volumes
            vol_out, _, _ = ssh.run(
                "docker volume ls --format "
                "'{\"name\":\"{{.Name}}\",\"driver\":\"{{.Driver}}\","
                "\"scope\":\"{{.Scope}}\",\"created\":\"{{.CreatedAt}}\"}'"
                " 2>/dev/null")
            volumes = []
            for line in vol_out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    volumes.append(json.loads(line))
                except Exception:
                    pass

            # Sizes via docker system df -v
            size_map = {}
            df_out, _, _ = ssh.run("docker system df -v 2>/dev/null")
            in_vol_section = False
            for line in df_out.splitlines():
                if line.startswith("VOLUME NAME"):
                    in_vol_section = True
                    continue
                if in_vol_section:
                    if not line.strip():
                        break
                    parts = line.split()
                    if len(parts) >= 2:
                        vname = parts[0]
                        links = parts[1] if len(parts) > 1 else "0"
                        size  = parts[2] if len(parts) > 2 else "?"
                        size_map[vname] = (size, links)

            for v in volumes:
                name = v.get("name", "")
                sz, lk = size_map.get(name, ("?", "0"))
                v["size"]  = sz
                v["links"] = lk

            self._volumes = volumes

            # Networks
            net_out, _, _ = ssh.run(
                "docker network ls --format "
                "'{\"id\":\"{{.ID}}\",\"name\":\"{{.Name}}\","
                "\"driver\":\"{{.Driver}}\",\"scope\":\"{{.Scope}}\","
                "\"created\":\"{{.CreatedAt}}\"}'"
                " 2>/dev/null")
            networks = []
            for line in net_out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    networks.append(json.loads(line))
                except Exception:
                    pass

            # Get container lists per network (quick inspect)
            for net in networks:
                name = net.get("name", "")
                c_out, _, _ = ssh.run(
                    "docker network inspect {} --format "
                    "'{{{{range $k,$v := .Containers}}}}{{{{$v.Name}}}} {{{{end}}}}'"
                    " 2>/dev/null".format(shlex.quote(name)))
                net["containers"] = ", ".join(c_out.split()) if c_out.strip() else ""

            self._networks = networks

            self.after(0, self._redraw)
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Error: {}".format(msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------------------------
    def _redraw(self):
        self._vol_tree.delete(*self._vol_tree.get_children())
        unused_count = 0
        for v in self._volumes:
            links = v.get("links", "0")
            try:
                is_unused = int(links) == 0
            except ValueError:
                is_unused = links == "0"
            if is_unused:
                unused_count += 1
            tag = "unused" if is_unused else "inuse"
            self._vol_tree.insert("", "end", iid=v.get("name", ""), tags=(tag,),
                                  values=(
                                      v.get("name", ""),
                                      v.get("driver", ""),
                                      v.get("scope", ""),
                                      v.get("size", "?"),
                                      links,
                                      v.get("created", "")[:19],
                                  ))

        self._net_tree.delete(*self._net_tree.get_children())
        builtins = {"bridge", "host", "none"}
        for n in self._networks:
            name = n.get("name", "")
            tag = "builtin" if name in builtins else "custom"
            self._net_tree.insert("", "end", iid=name, tags=(tag,),
                                  values=(
                                      name,
                                      n.get("driver", ""),
                                      n.get("scope", ""),
                                      n.get("id", "")[:12],
                                      n.get("containers", ""),
                                      n.get("created", "")[:19],
                                  ))

        self._status.config(
            text="{} volumes ({} unused)  |  {} networks".format(
                len(self._volumes), unused_count, len(self._networks)),
            bg=self.theme.surface_dark, fg=self.theme.text_muted)

    # -----------------------------------------------------------------------
    # SELECTION
    # -----------------------------------------------------------------------
    def _on_vol_select(self, _=None):
        state = "normal" if self._vol_tree.selection() else "disabled"
        self._vol_rm_btn.config(state=state)

    def _on_net_select(self, _=None):
        sel = self._net_tree.selection()
        if sel and sel[0] not in {"bridge", "host", "none"}:
            self._net_rm_btn.config(state="normal")
        else:
            self._net_rm_btn.config(state="disabled")

    # -----------------------------------------------------------------------
    # VOLUME ACTIONS
    # -----------------------------------------------------------------------
    def _vol_inspect(self, _=None):
        sel = self._vol_tree.selection()
        if not sel:
            return
        name = sel[0]
        def _run():
            out, err, code = self.controller.ssh.run(
                "docker volume inspect {} 2>&1".format(shlex.quote(name)))
            self.after(0, lambda: messagebox.showinfo(
                "Volume: {}".format(name), (out or err)[:2000], parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _remove_volume(self):
        sel = self._vol_tree.selection()
        if not sel:
            return
        name = sel[0]
        if not messagebox.askyesno("Remove Volume",
                                    "Remove volume '{}'?\nThis cannot be undone.".format(name),
                                    parent=self):
            return
        def _run():
            self._log("$ docker volume rm {}".format(name), "cmd")
            out, err, code = self.controller.ssh.run(
                "docker volume rm {} 2>&1".format(shlex.quote(name)))
            combined = (out or "") + (err or "")
            if code == 0:
                self._log("Removed: {}".format(name), "ok")
                self.after(800, self.refresh)
            else:
                self._log(combined or "Failed", "err")
                self.after(0, lambda: messagebox.showerror(
                    "Remove Failed", combined[:400], parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _prune_volumes(self):
        if not messagebox.askyesno("Prune Unused Volumes",
                                    "Remove ALL unused volumes?\nThis cannot be undone.",
                                    parent=self):
            return
        def _run():
            self._log("$ docker volume prune -f", "cmd")
            out, err, code = self.controller.ssh.run(
                "docker volume prune -f 2>&1")
            combined = (out or "") + (err or "")
            self._log(combined or "Done", "ok" if code == 0 else "err")
            self.after(1000, self.refresh)
        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------------
    # NETWORK ACTIONS
    # -----------------------------------------------------------------------
    def _net_inspect(self, _=None):
        sel = self._net_tree.selection()
        if not sel:
            return
        name = sel[0]
        def _run():
            out, err, code = self.controller.ssh.run(
                "docker network inspect {} 2>&1".format(shlex.quote(name)))
            self.after(0, lambda: messagebox.showinfo(
                "Network: {}".format(name), (out or err)[:2000], parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _remove_network(self):
        sel = self._net_tree.selection()
        if not sel:
            return
        name = sel[0]
        if name in {"bridge", "host", "none"}:
            messagebox.showwarning("Cannot Remove",
                                   "Built-in network '{}' cannot be removed.".format(name),
                                   parent=self)
            return
        if not messagebox.askyesno("Remove Network",
                                    "Remove network '{}'?".format(name),
                                    parent=self):
            return
        def _run():
            self._log("$ docker network rm {}".format(name), "cmd")
            out, err, code = self.controller.ssh.run(
                "docker network rm {} 2>&1".format(shlex.quote(name)))
            combined = (out or "") + (err or "")
            if code == 0:
                self._log("Removed: {}".format(name), "ok")
                self.after(800, self.refresh)
            else:
                self._log(combined or "Failed", "err")
                self.after(0, lambda: messagebox.showerror(
                    "Remove Failed", combined[:400], parent=self))
        threading.Thread(target=_run, daemon=True).start()

    def _create_network(self):
        _CreateNetworkDialog(self, self.controller, self.theme,
                             on_create=self._do_create_network)

    def _do_create_network(self, name, driver):
        def _run():
            cmd = "docker network create --driver {} {} 2>&1".format(driver, name)
            self._log("$ " + cmd, "cmd")
            out, err, code = self.controller.ssh.run(cmd)
            combined = (out or "") + (err or "")
            self._log(combined or "Done", "ok" if code == 0 else "err")
            if code == 0:
                self.after(800, self.refresh)
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Create Failed", combined[:400], parent=self))
        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------------
    # CONSOLE
    # -----------------------------------------------------------------------
    def _log(self, text, tag=None):
        def _do():
            self._console.config(state="normal")
            if tag:
                self._console.insert("end", text + "\n", tag)
            else:
                self._console.insert("end", text + "\n")
            self._console.see("end")
            self._console.config(state="disabled")
        self.after(0, _do)

    def _clear_console(self):
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        self._console.config(state="disabled")

    # -----------------------------------------------------------------------
    # on_show
    # -----------------------------------------------------------------------
    def on_show(self):
        if self.controller.ssh.connected:
            self.refresh()


class _CreateNetworkDialog(tk.Toplevel):

    def __init__(self, parent, controller, theme, on_create):
        super().__init__(parent)
        self.title("Create Network")
        self.configure(bg=theme.bg)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()
        self._on_create = on_create
        t = theme

        body = tk.Frame(self, bg=t.bg, padx=24, pady=20)
        body.pack(fill="both")

        tk.Label(body, text="Network Name:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", pady=6)
        self._name_var = tk.StringVar()
        e = tk.Entry(body, textvariable=self._name_var, font=t.font_regular, width=22)
        t.style_entry(e)
        e.grid(row=0, column=1, sticky="ew", padx=12, pady=6)
        e.focus_set()

        tk.Label(body, text="Driver:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", pady=6)
        self._driver_var = tk.StringVar(value="bridge")
        drv_menu = tk.OptionMenu(body, self._driver_var,
                                 "bridge", "overlay", "macvlan", "none")
        drv_menu.config(bg=t.surface_dark, fg=t.text, relief="flat",
                        font=t.font_regular, bd=0, highlightthickness=0)
        drv_menu["menu"].config(bg=t.surface_dark, fg=t.text, font=t.font_regular)
        drv_menu.grid(row=1, column=1, sticky="w", padx=12, pady=6)

        btns = tk.Frame(body, bg=t.bg)
        btns.grid(row=2, column=0, columnspan=2, pady=(16, 0))

        ok_btn = tk.Button(btns, text="Create", command=self._ok)
        t.style_button(ok_btn)
        ok_btn.pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Cancel", command=self.destroy,
                  bg=t.surface_dark, fg=t.text, bd=0, relief="flat",
                  font=t.font_regular, padx=12, pady=4,
                  cursor="hand2").pack(side="left")

        self.bind("<Return>",  lambda _: self._ok())
        self.bind("<Escape>",  lambda _: self.destroy())

        self.update_idletasks()
        pw = parent.winfo_rootx()
        py = parent.winfo_rooty()
        self.geometry("+{}+{}".format(pw + 80, py + 100))

    def _ok(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a network name.", parent=self)
            return
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', name):
            messagebox.showwarning("Invalid name",
                                   "Name may only contain letters, digits, _, -, .",
                                   parent=self)
            return
        driver = self._driver_var.get()
        self.destroy()
        self._on_create(name, driver)
