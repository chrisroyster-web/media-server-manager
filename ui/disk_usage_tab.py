# ui/disk_usage_tab.py
"""
Disk Usage browser tab.
Uses `du --block-size=1 -d 1 <path>` via SSH to scan a directory one level
deep.  Double-clicking a row drills down; a navigation history stack powers
the Back button.
"""

import json
import threading
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox


_BAR_CHARS  = "▏▎▍▌▋▊▉█"
_BAR_WIDTH  = 20       # characters


def _fmt_size(b):
    if b is None or b < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return "{:.1f} {}".format(b, unit)
        b /= 1024
    return "{:.1f} PB".format(b)


def _bar(ratio, width=_BAR_WIDTH):
    if ratio <= 0:
        return " " * width
    filled = ratio * width
    full   = int(filled)
    frac   = filled - full
    bar    = _BAR_CHARS[-1] * full
    if frac > 0 and full < width:
        idx  = int(frac * len(_BAR_CHARS))
        bar += _BAR_CHARS[min(idx, len(_BAR_CHARS) - 1)]
        bar += " " * (width - full - 1)
    else:
        bar += " " * (width - full)
    return bar[:width]


_DEFAULT_PATHS = ["/opt/media", "/home", "/downloads",
                  "/var/lib/docker", "/var"]


class DiskUsageTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._history   = []          # list of (path, scroll-pos)
        self._entries   = []          # current rows: (bytes, name, path)
        self._build_ui()
        self._load_paths()

    # -----------------------------------------------------------------------
    # UI BUILD
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header row
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="DISK USAGE", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")

        btn_scan = tk.Button(hdr, text="⟳ Scan", command=self._scan)
        t.style_button(btn_scan)
        btn_scan.pack(side="right")

        self._back_btn = tk.Button(hdr, text="← Back",
                                    command=self._go_back, state="disabled")
        t.style_button(self._back_btn)
        self._back_btn.pack(side="right", padx=(0, 6))

        # Path selector row
        path_row = tk.Frame(self, bg=t.bg)
        path_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(path_row, text="Root path:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._path_var = tk.StringVar()
        self._path_menu = tk.OptionMenu(path_row, self._path_var, "")
        self._path_menu.config(bg=t.surface_dark, fg=t.text,
                               activebackground=t.surface_light,
                               activeforeground=t.text,
                               font=t.font_small, bd=0, relief="flat",
                               highlightthickness=0)
        self._path_menu["menu"].config(bg=t.surface_dark, fg=t.text,
                                        font=t.font_small)
        self._path_menu.pack(side="left", padx=(8, 0))
        add_path = tk.Button(path_row, text="＋ Add Path",
                             command=self._add_path)
        t.style_button(add_path)
        add_path.pack(side="left", padx=(8, 0))
        rm_path = tk.Button(path_row, text="✕ Remove",
                            command=self._remove_path)
        t.style_button(rm_path)
        rm_path.pack(side="left", padx=(4, 0))

        # Breadcrumb
        self._crumb_var = tk.StringVar(value="Select a root path and press Scan")
        crumb = tk.Label(self, textvariable=self._crumb_var,
                         bg=t.surface_dark, fg=t.cyan,
                         font=t.font_mono, anchor="w", padx=14)
        crumb.pack(fill="x", padx=16, pady=(0, 4))

        # Treeview
        cols   = ("size", "bar", "name")
        hdgs   = ("Size", "Usage", "Name / Path")
        widths = (90, 172, 480)
        stretches = {"name"}

        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("DU.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=24, font=t.font_mono)
        style.configure("DU.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("DU.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings",
                                   style="DU.Treeview", selectmode="browse")
        for col, hdr_txt, w in zip(cols, hdgs, widths):
            self._tree.heading(col, text=hdr_txt, anchor="w",
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, minwidth=40, anchor="w",
                              stretch=(col in stretches))

        self._tree.tag_configure("large",  foreground=t.status_stopped_text)
        self._tree.tag_configure("medium", foreground=t.yellow)
        self._tree.tag_configure("small",  foreground=t.text)
        self._tree.tag_configure("dir",    foreground=t.cyan)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-Button-1>", self._on_double_click)

        # Status bar
        self._status = tk.Label(self, text="",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        self._sort_col = "size"
        self._sort_rev = True

    # -----------------------------------------------------------------------
    # PATHS CONFIG
    # -----------------------------------------------------------------------
    def _load_paths(self):
        cfg   = self.controller.config_manager
        raw   = cfg.get("disk_usage_paths", None)
        paths = json.loads(raw) if raw else list(_DEFAULT_PATHS)
        self._paths = paths
        self._rebuild_menu()

    def _save_paths(self):
        self.controller.config_manager.set(
            "disk_usage_paths", json.dumps(self._paths))

    def _rebuild_menu(self):
        menu = self._path_menu["menu"]
        menu.delete(0, "end")
        current = self._path_var.get()
        for p in self._paths:
            menu.add_command(label=p,
                             command=lambda v=p: self._path_var.set(v))
        if self._paths:
            if current not in self._paths:
                self._path_var.set(self._paths[0])
        else:
            self._path_var.set("")

    def _add_path(self):
        p = simpledialog.askstring(
            "Add Root Path",
            "Enter an absolute path to add (e.g. /mnt/data):",
            parent=self)
        if not p or not p.strip():
            return
        p = p.strip()
        if p not in self._paths:
            self._paths.append(p)
            self._save_paths()
            self._rebuild_menu()
        self._path_var.set(p)

    def _remove_path(self):
        current = self._path_var.get()
        if not current or current not in self._paths:
            return
        self._paths.remove(current)
        self._save_paths()
        self._rebuild_menu()

    # -----------------------------------------------------------------------
    # SCAN
    # -----------------------------------------------------------------------
    def _scan(self, path=None):
        if getattr(self, "_fetching", False):
            return
        if path is None:
            path = self._path_var.get().strip()
        if not path:
            messagebox.showinfo("No Path", "Select a root path first.", parent=self)
            return
        if not self.controller.ssh.connected:
            self._status.config(
                text="Not connected to SSH", bg=self.theme.surface_dark,
                fg=self.theme.status_stopped_text)
            return
        self._status.config(text="Scanning {}…".format(path),
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._do_scan, args=(path,), daemon=True).start()

    def _do_scan(self, path):
        try:
            ssh = self.controller.ssh
            # Sanitise path: wrap in single quotes, escape embedded quotes
            safe = path.replace("'", "'\\''")
            cmd  = "du --block-size=1 -d 1 '{}' 2>/dev/null".format(safe)
            out, err, code = ssh.run(cmd)
            if code != 0 and not out.strip():
                self.after(0, lambda: self._status.config(
                    text="Cannot scan {}: {}".format(path, err or "no output"),
                    bg=self.theme.surface_dark,
                    fg=self.theme.status_stopped_text))
                return
            entries = self._parse_du(out, path)
            self.after(0, lambda: self._show(path, entries))
        except Exception as e:
            self.after(0, lambda err=str(e): self._status.config(
                text="Error: {}".format(err),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped_text))
        finally:
            self._fetching = False

    def _parse_du(self, output, root):
        entries = []
        for line in output.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            path = parts[1].rstrip("/")
            name = path.split("/")[-1] or path
            # skip the root itself
            if path == root.rstrip("/"):
                continue
            entries.append((size, name, path))
        return sorted(entries, key=lambda x: x[0], reverse=True)

    # -----------------------------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------------------------
    def _show(self, path, entries):
        t = self.theme
        self._entries = entries
        self._crumb_var.set(path)
        self._redraw()
        total = sum(e[0] for e in entries)
        self._status.config(
            text="{} items  |  Total: {}".format(len(entries), _fmt_size(total)),
            bg=t.surface_dark, fg=t.text_muted)

    def _redraw(self):
        self._tree.delete(*self._tree.get_children())
        entries = self._entries
        if not entries:
            return
        top = entries[0][0] or 1

        key = self._sort_col
        if key == "size":
            entries = sorted(entries, key=lambda x: x[0], reverse=self._sort_rev)
        elif key == "name":
            entries = sorted(entries, key=lambda x: x[1].lower(),
                             reverse=self._sort_rev)
        # "bar" sorts by size as well
        elif key == "bar":
            entries = sorted(entries, key=lambda x: x[0], reverse=self._sort_rev)

        for size, name, path in entries:
            ratio = size / top if top else 0
            if ratio >= 0.6:
                tag = "large"
            elif ratio >= 0.3:
                tag = "medium"
            else:
                tag = "small"
            self._tree.insert("", "end",
                              iid=path,
                              tags=(tag,),
                              values=(
                                  _fmt_size(size),
                                  _bar(ratio),
                                  name,
                              ))

    def _sort(self, col):
        self._sort_rev = (not self._sort_rev
                          if self._sort_col == col else True)
        self._sort_col = col
        self._redraw()

    # -----------------------------------------------------------------------
    # NAVIGATION
    # -----------------------------------------------------------------------
    def _on_double_click(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        path = sel[0]     # iid == full path
        self._push_history()
        self._scan(path)

    def _push_history(self):
        crumb = self._crumb_var.get()
        self._history.append((crumb, self._entries[:]))
        self._back_btn.config(state="normal")

    def _go_back(self):
        if not self._history:
            return
        path, entries = self._history.pop()
        self._show(path, entries)
        if not self._history:
            self._back_btn.config(state="disabled")
