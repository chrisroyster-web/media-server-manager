# ui/sftp_tab.py

import os
import stat as stat_module
import datetime
import threading
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox


def _is_dir(attr):
    try:
        return stat_module.S_ISDIR(attr.st_mode)
    except Exception:
        return False


def _fmt_size(size):
    if size is None or size == 0:
        return ""
    if size < 1024:
        return "{} B".format(size)
    if size < 1024 ** 2:
        return "{:.1f} KB".format(size / 1024)
    if size < 1024 ** 3:
        return "{:.1f} MB".format(size / 1024 ** 2)
    return "{:.2f} GB".format(size / 1024 ** 3)


def _fmt_time(mtime):
    if mtime is None:
        return ""
    try:
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d  %H:%M")
    except Exception:
        return ""


def _fmt_mode(mode):
    if mode is None:
        return ""
    try:
        return stat_module.filemode(mode)
    except Exception:
        return ""


class SFTPTab(tk.Frame):
    """
    SFTP file browser tab.
    Browse, upload, download, rename, delete and create folders on the remote server.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller    = controller
        self.theme         = controller.theme
        self._current_path = "/"
        self._back_stack   = []   # paths we came from
        self._fwd_stack    = []   # paths for forward
        self._item_is_dir  = {}   # tree item id → bool
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        # ---- Title bar ----
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="FILES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")

        # ---- Path / navigation bar ----
        nav = tk.Frame(self, bg=t.surface, padx=8, pady=6)
        nav.pack(fill="x", padx=16, pady=(0, 4))

        self._back_btn = tk.Button(nav, text="←", command=self._go_back,
                                    font=t.font_regular, bd=0, relief="flat",
                                    bg=t.surface, fg=t.text_muted,
                                    activebackground=t.surface_light)
        self._back_btn.pack(side="left", padx=(0, 2))

        self._fwd_btn = tk.Button(nav, text="→", command=self._go_fwd,
                                   font=t.font_regular, bd=0, relief="flat",
                                   bg=t.surface, fg=t.text_muted,
                                   activebackground=t.surface_light)
        self._fwd_btn.pack(side="left", padx=(0, 6))

        tk.Button(nav, text="🏠", command=self._go_home,
                  font=t.font_regular, bd=0, relief="flat",
                  bg=t.surface, fg=t.text_muted,
                  activebackground=t.surface_light).pack(side="left", padx=(0, 8))

        self._path_var = tk.StringVar(value="/")
        path_entry = tk.Entry(nav, textvariable=self._path_var,
                              font=t.font_mono, bg=t.surface_dark,
                              fg=t.text, insertbackground=t.text,
                              bd=1, relief="solid")
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        path_entry.bind("<Return>", lambda e: self._navigate(self._path_var.get().strip()))

        refresh_btn = tk.Button(nav, text="⟳ Refresh",
                                 command=self._refresh,
                                 font=t.font_small, bd=0, relief="flat",
                                 bg=t.surface, fg=t.blue_bright,
                                 activebackground=t.surface_light)
        refresh_btn.pack(side="left")

        # ---- Action toolbar ----
        tb = tk.Frame(self, bg=t.bg)
        tb.pack(fill="x", padx=16, pady=(0, 4))

        for label, cmd in [
            ("⬆  Upload",     self._upload),
            ("⬇  Download",   self._download),
            ("📁  New Folder", self._new_folder),
            ("✏   Rename",    self._rename),
            ("🗑  Delete",     self._delete),
        ]:
            btn = tk.Button(tb, text=label, command=cmd)
            t.style_button(btn)
            btn.pack(side="left", padx=(0, 6))

        # ---- File list (Treeview) ----
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        # ttk style
        style = ttk.Style()
        style.configure("SFTP.Treeview",
                        background=t.surface_dark,
                        foreground=t.text,
                        fieldbackground=t.surface_dark,
                        borderwidth=0,
                        rowheight=26,
                        font=t.font_regular)
        style.configure("SFTP.Treeview.Heading",
                        background=t.surface,
                        foreground=t.text_muted,
                        font=t.font_small,
                        relief="flat",
                        borderwidth=0)
        style.map("SFTP.Treeview",
                  background=[("selected", t.blue)],
                  foreground=[("selected", "#ffffff")])

        cols = ("name", "size", "modified", "mode")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  selectmode="browse", style="SFTP.Treeview")

        self.tree.heading("name",     text="Name",
                          command=lambda: self._sort("name"))
        self.tree.heading("size",     text="Size",
                          command=lambda: self._sort("size"))
        self.tree.heading("modified", text="Modified",
                          command=lambda: self._sort("modified"))
        self.tree.heading("mode",     text="Permissions")

        self.tree.column("name",     width=320, minwidth=160, anchor="w")
        self.tree.column("size",     width=90,  minwidth=60,  anchor="e")
        self.tree.column("modified", width=170, minwidth=120, anchor="w")
        self.tree.column("mode",     width=110, minwidth=90,  anchor="w")

        # Color tags
        self.tree.tag_configure("dir",    foreground=t.cyan)
        self.tree.tag_configure("file",   foreground=t.text)
        self.tree.tag_configure("parent", foreground=t.text_muted)

        vsb = tk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = tk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Double-1>",     self._on_double_click)
        self.tree.bind("<Return>",       self._on_double_click)
        self.tree.bind("<BackSpace>",    lambda e: self._go_back())
        self.tree.bind("<Button-3>",     self._context_menu)

        # ---- Status / log bar ----
        status_frame = tk.Frame(self, bg=t.surface_dark, height=28)
        status_frame.pack(fill="x", padx=16, pady=(0, 8))
        status_frame.pack_propagate(False)

        self._status_lbl = tk.Label(status_frame, text="Not connected — use the Connection tab first",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(side="left", padx=8, pady=4)

        self._item_count_lbl = tk.Label(status_frame, text="",
                                         bg=t.surface_dark, fg=t.text_muted,
                                         font=t.font_small, anchor="e")
        self._item_count_lbl.pack(side="right", padx=8, pady=4)

    # =========================================================
    # NAVIGATION
    # =========================================================
    def _navigate(self, path, push_history=True):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        if push_history and self._current_path != path:
            self._back_stack.append(self._current_path)
            self._fwd_stack.clear()
        self._current_path = path
        self._path_var.set(path)
        self._set_status("Loading " + path + "…")
        threading.Thread(target=self._load_dir, args=(path,), daemon=True).start()

    def _refresh(self):
        self._navigate(self._current_path, push_history=False)

    def _go_back(self):
        if self._back_stack:
            self._fwd_stack.append(self._current_path)
            prev = self._back_stack.pop()
            self._navigate(prev, push_history=False)

    def _go_fwd(self):
        if self._fwd_stack:
            self._back_stack.append(self._current_path)
            nxt = self._fwd_stack.pop()
            self._navigate(nxt, push_history=False)

    def _go_home(self):
        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                home = sftp.normalize(".")
                self.after(0, lambda h=home: self._navigate(h))
            except Exception:
                self.after(0, lambda: self._navigate("/"))
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # DIRECTORY LISTING
    # =========================================================
    def _load_dir(self, path):
        try:
            sftp = self.controller.ssh.get_sftp()
            attrs = sftp.listdir_attr(path)
        except Exception as e:
            self.after(0, lambda err=str(e): self._set_status("Error: " + err, "error"))
            return

        # Sort: parent (..) always first, then dirs A-Z, then files A-Z
        dirs  = sorted([a for a in attrs if _is_dir(a)],
                       key=lambda x: x.filename.lower())
        files = sorted([a for a in attrs if not _is_dir(a)],
                       key=lambda x: x.filename.lower())

        self.after(0, lambda: self._populate_tree(path, dirs, files))

    def _populate_tree(self, path, dirs, files):
        if path != self._current_path:
            return
        self.tree.delete(*self.tree.get_children())
        self._item_is_dir = {}

        # Parent ".." entry (unless at root)
        if path != "/":
            iid = self.tree.insert("", "end",
                                    values=("📂  ..", "", "", ""),
                                    tags=("parent",))
            self._item_is_dir[iid] = True

        for attr in dirs:
            name = "📂  " + attr.filename
            iid = self.tree.insert("", "end",
                                    values=(name,
                                            "",
                                            _fmt_time(attr.st_mtime),
                                            _fmt_mode(attr.st_mode)),
                                    tags=("dir",))
            self._item_is_dir[iid] = True

        for attr in files:
            name = "📄  " + attr.filename
            iid = self.tree.insert("", "end",
                                    values=(name,
                                            _fmt_size(attr.st_size),
                                            _fmt_time(attr.st_mtime),
                                            _fmt_mode(attr.st_mode)),
                                    tags=("file",))
            self._item_is_dir[iid] = False

        total = len(dirs) + len(files)
        self._item_count_lbl.config(
            text="{} folder{},  {} file{}".format(
                len(dirs),  "s" if len(dirs)  != 1 else "",
                len(files), "s" if len(files) != 1 else ""))
        self._set_status("{}  ({} items)".format(path, total))

    # =========================================================
    # EVENTS
    # =========================================================
    def _on_double_click(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        raw_name = self.tree.item(iid, "values")[0]
        # strip the icon prefix ("📂  " or "📄  ")
        name = raw_name.split("  ", 1)[-1].strip()

        if name == "..":
            parent = "/".join(self._current_path.rstrip("/").split("/")[:-1]) or "/"
            self._navigate(parent)
        elif self._item_is_dir.get(iid, False):
            new_path = (self._current_path.rstrip("/") + "/" + name).replace("//", "/")
            self._navigate(new_path)
        else:
            # Single-click → download on Enter; double-click → download
            self._download()

    def _context_menu(self, event):
        sel = self.tree.identify_row(event.y)
        if sel:
            self.tree.selection_set(sel)
        menu = tk.Menu(self, tearoff=0,
                       bg=self.theme.surface, fg=self.theme.text,
                       activebackground=self.theme.blue,
                       activeforeground="#ffffff",
                       bd=0, relief="flat")
        menu.add_command(label="Download",    command=self._download)
        menu.add_command(label="Rename",      command=self._rename)
        menu.add_separator()
        menu.add_command(label="Delete",      command=self._delete)
        menu.add_separator()
        menu.add_command(label="New Folder",  command=self._new_folder)
        menu.add_command(label="Upload here", command=self._upload)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # =========================================================
    # FILE ACTIONS
    # =========================================================
    def _selected_name(self):
        """Return the bare filename of the selected tree item, or None."""
        sel = self.tree.selection()
        if not sel:
            return None
        raw = self.tree.item(sel[0], "values")[0]
        return raw.split("  ", 1)[-1].strip()

    def _remote_path(self, name):
        return (self._current_path.rstrip("/") + "/" + name).replace("//", "/")

    # --- Download ---
    def _download(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        name = self._selected_name()
        if not name or name == "..":
            return
        if self._item_is_dir.get(self.tree.selection()[0], False):
            messagebox.showinfo("Download", "Folder download is not supported.\nSelect a file.")
            return
        local = filedialog.asksaveasfilename(initialfile=name,
                                             title="Save remote file as")
        if not local:
            return
        remote = self._remote_path(name)

        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                self.after(0, lambda: self._set_status("Downloading  " + name + "…"))
                sftp.get(remote, local,
                         callback=lambda done, total: self.after(
                             0, lambda d=done, t=total: self._set_status(
                                 "Downloading  {0}  ({1}/{2})".format(
                                     name, _fmt_size(d), _fmt_size(t)))))
                self.after(0, lambda: self._set_status(
                    "Downloaded  " + name + "  →  " + local, "success"))
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_status("Download failed: " + err, "error"))

        threading.Thread(target=worker, daemon=True).start()

    # --- Upload ---
    def _upload(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        local = filedialog.askopenfilename(title="Choose file to upload")
        if not local:
            return
        filename = os.path.basename(local)
        remote = self._remote_path(filename)

        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                self.after(0, lambda: self._set_status("Uploading  " + filename + "…"))
                sftp.put(local, remote,
                         callback=lambda done, total: self.after(
                             0, lambda d=done, t=total: self._set_status(
                                 "Uploading  {0}  ({1}/{2})".format(
                                     filename, _fmt_size(d), _fmt_size(t)))))
                self.after(0, lambda: self._set_status(
                    "Uploaded  " + filename, "success"))
                self.after(0, self._refresh)
                self.controller.audit_log("sftp.upload", remote, result="ok")
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_status("Upload failed: " + err, "error"))
                self.controller.audit_log("sftp.upload", remote, detail=str(e)[:200], result="fail")

        threading.Thread(target=worker, daemon=True).start()

    # --- New Folder ---
    def _new_folder(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        name = simpledialog.askstring("New Folder", "Folder name:",
                                       parent=self)
        if not name or not name.strip():
            return
        remote = self._remote_path(name.strip())

        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                sftp.mkdir(remote)
                self.after(0, lambda: self._set_status("Created folder  " + name, "success"))
                self.after(0, self._refresh)
                self.controller.audit_log("sftp.mkdir", remote, result="ok")
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_status("Create folder failed: " + err, "error"))
                self.controller.audit_log("sftp.mkdir", remote, detail=str(e)[:200], result="fail")

        threading.Thread(target=worker, daemon=True).start()

    # --- Rename ---
    def _rename(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        name = self._selected_name()
        if not name or name == "..":
            return
        new_name = simpledialog.askstring("Rename", "New name:",
                                           initialvalue=name, parent=self)
        if not new_name or not new_name.strip() or new_name.strip() == name:
            return
        old_remote = self._remote_path(name)
        new_remote = self._remote_path(new_name.strip())

        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                sftp.rename(old_remote, new_remote)
                self.after(0, lambda: self._set_status(
                    "Renamed  " + name + "  →  " + new_name.strip(), "success"))
                self.after(0, self._refresh)
                self.controller.audit_log("sftp.rename", old_remote, detail="-> " + new_remote, result="ok")
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_status("Rename failed: " + err, "error"))
                self.controller.audit_log("sftp.rename", old_remote, detail=str(e)[:200], result="fail")

        threading.Thread(target=worker, daemon=True).start()

    # --- Delete ---
    def _delete(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        name = self._selected_name()
        if not name or name == "..":
            return
        sel = self.tree.selection()
        is_dir = self._item_is_dir.get(sel[0], False) if sel else False
        kind = "folder" if is_dir else "file"

        if not messagebox.askyesno(
                "Delete", "Permanently delete {0}  \"{1}\"?".format(kind, name),
                parent=self):
            return

        remote = self._remote_path(name)

        def worker():
            try:
                sftp = self.controller.ssh.get_sftp()
                if is_dir:
                    sftp.rmdir(remote)
                else:
                    sftp.remove(remote)
                self.after(0, lambda: self._set_status(
                    "Deleted  " + name, "success"))
                self.after(0, self._refresh)
                self.controller.audit_log(
                    "sftp.delete_folder" if is_dir else "sftp.delete_file",
                    remote, result="ok")
            except Exception as e:
                self.after(0, lambda err=str(e): self._set_status("Delete failed: " + err, "error"))
                self.controller.audit_log(
                    "sftp.delete_folder" if is_dir else "sftp.delete_file",
                    remote, detail=str(e)[:200], result="fail")

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # SORT
    # =========================================================
    def _sort(self, col):
        """Toggle sort on a column — dirs always stay above files."""
        items = self.tree.get_children()
        parent_items = [i for i in items if self.tree.item(i, "values")[0].strip().startswith("📂  ..")]
        other_items  = [i for i in items if i not in parent_items]

        col_idx = {"name": 0, "size": 1, "modified": 2}
        idx = col_idx.get(col, 0)

        def sort_key(iid):
            val = self.tree.item(iid, "values")[idx]
            if col == "size":
                # parse back to bytes for correct numeric sort
                val_str = val.strip()
                mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
                try:
                    num, unit = val_str.rsplit(" ", 1)
                    return float(num) * mult.get(unit, 1)
                except Exception:
                    return 0
            return val.lower()

        dir_items  = [i for i in other_items if self._item_is_dir.get(i, False)]
        file_items = [i for i in other_items if not self._item_is_dir.get(i, False)]

        dir_items.sort(key=sort_key)
        file_items.sort(key=sort_key)

        for idx2, iid in enumerate(parent_items + dir_items + file_items):
            self.tree.move(iid, "", idx2)

    # =========================================================
    # STATUS
    # =========================================================
    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status_lbl.config(text=text, bg=t.blue, fg="#ffffff")
            return
        color = {"info": t.text_muted, "success": t.status_running, "error": t.status_stopped}.get(level, t.text_muted)
        self._status_lbl.config(text=text, bg=t.surface_dark, fg=color)
