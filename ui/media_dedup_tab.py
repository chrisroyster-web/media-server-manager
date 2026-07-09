# ui/media_dedup_tab.py
"""
Duplicate / Orphaned Media tab.
Compares what's actually on disk under Sonarr/Radarr's root folders against
what their APIs say is the current tracked file, via
core/media_dedup.find_duplicate_and_orphaned_media(). Deleting a file is a
deliberately narrow, explicit action: select exactly one file from the
selected folder's file list, confirm it (the dialog names the path, size,
and whether Sonarr/Radarr currently point at it), and only that one file is
removed — no bulk/multi-select delete.

Deliberately does NOT auto-scan on tab show — this walks entire media root
folders over SSH plus two REST APIs per show/movie, not something to fire
just from clicking the tab.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

from core.media_dedup import find_duplicate_and_orphaned_media, delete_file


def _fmt_size(num_bytes):
    if num_bytes >= 1024 ** 3:
        return "{:.1f} GB".format(num_bytes / 1024 ** 3)
    if num_bytes >= 1024 ** 2:
        return "{:.0f} MB".format(num_bytes / 1024 ** 2)
    return "{:.0f} KB".format(num_bytes / 1024)


class MediaDedupTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._row_info  = {}   # tree iid -> group dict
        self._scanning  = False
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="DUPLICATE / ORPHANED MEDIA", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._scan_btn = tk.Button(hdr, text="⟳ Scan", command=self._scan)
        t.style_button(self._scan_btn)
        self._scan_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._draw_summary_cards()

        # Not-configured empty state
        self._empty_frame = tk.Frame(self, bg=t.bg)
        tk.Label(self._empty_frame,
                 text="No Sonarr or Radarr API key configured for this server.\n\n"
                      "Add one in Config to enable duplicate/orphan scanning.",
                 bg=t.bg, fg=t.text_muted, font=t.font_regular,
                 justify="center").pack(pady=40)

        # Treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        self._tree_frame = tree_frame
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._tree = self._make_tree(tree_frame,
            cols=("folder", "app", "count", "reclaimable"),
            headings=[
                ("folder",      "Folder",           420, "w"),
                ("app",         "App",               80, "center"),
                ("count",       "Files Found",       90, "center"),
                ("reclaimable", "Reclaimable Size", 130, "center"),
            ])
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # File detail — one row per file in the selected folder, selectable
        detail_hdr = tk.Frame(self, bg=t.bg)
        detail_hdr.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(detail_hdr, text="Files in Folder (select a row, then choose one to delete)",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(side="left")
        self._delete_btn = tk.Button(detail_hdr, text="Delete Selected File",
                                     command=self._delete_selected_file, state="disabled")
        t.style_button(self._delete_btn)
        self._delete_btn.configure(fg=t.status_stopped_text)
        self._delete_btn.pack(side="right")

        file_frame = tk.Frame(self, bg=t.bg)
        file_frame.pack(fill="x", padx=16, pady=(4, 4))
        self._file_tree = self._make_tree(file_frame,
            cols=("size", "tracked", "path"),
            headings=[
                ("size",    "Size",    90,  "center"),
                ("tracked", "Tracked", 90,  "center"),
                ("path",    "Path",    600, "w"),
            ], height=6)
        self._file_tree.tag_configure("tracked",   foreground=t.status_running)
        self._file_tree.tag_configure("untracked", foreground=t.yellow)
        self._file_tree.bind("<<TreeviewSelect>>", self._on_file_select)
        self._file_info = {}   # file-tree iid -> {"path", "size", "tracked"}
        self._current_group_iid = None

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    def _make_tree(self, parent, cols, headings, height=10):
        t = self.theme
        style = ttk.Style()
        sid = "Dedup{}.Treeview".format(id(parent))
        style.configure(sid, background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure(sid + ".Heading", background=t.surface_dark,
                        foreground=t.text_muted, font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map(sid, background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=sid, height=height, selectmode="browse")
        for col, text, width, anchor in headings:
            tree.heading(col, text=text, anchor=anchor)
            tree.column(col, width=width, minwidth=50,
                        anchor=anchor, stretch=(width > 150))
        tree.tag_configure("odd",  background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even", background=t.card_bg,      foreground=t.text)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _draw_summary_cards(self):
        t = self.theme
        for w in self._summary_frame.winfo_children():
            w.destroy()
        groups = list(self._row_info.values())
        total_bytes = sum(g["extra_bytes"] for g in groups)
        for label, val, color in [
            ("Folders Flagged",  str(len(groups)), t.yellow if groups else t.status_running),
            ("Reclaimable Space", _fmt_size(total_bytes) if total_bytes else "0 KB",
             t.yellow if total_bytes else t.status_running),
        ]:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=label, bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            tk.Label(card, text=val, bg=t.card_bg,
                     fg=color, font=("Segoe UI", 18, "bold")).pack()

    # =========================================================
    # ON SHOW — checks whether Sonarr/Radarr are configured only
    # =========================================================
    def on_show(self):
        srv = (self.controller.config_manager.get_active_server() or {}).get("settings", {})
        configured = bool(srv.get("sonarr_apikey") or srv.get("radarr_apikey"))
        if configured:
            self._empty_frame.pack_forget()
            self._tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
            self._scan_btn.config(state="normal")
            self._set_status("Ready — click Scan to check for duplicate/orphaned files.")
        else:
            self._tree_frame.pack_forget()
            self._empty_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
            self._scan_btn.config(state="disabled")
            self._set_status("No Sonarr/Radarr API key configured.", "error")

    # =========================================================
    # SCAN
    # =========================================================
    def _scan(self):
        if self._scanning or not self.controller.ssh.connected:
            return
        self._scanning = True
        self._scan_btn.config(state="disabled", text="Scanning…")
        self._set_status("Scanning media folders — this can take a while on large libraries…")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        cfg = self.controller.config_manager
        srv = (cfg.get_active_server() or {}).get("settings", {})
        sonarr_cfg = {"host": srv.get("sonarr_host", "localhost"),
                      "port": srv.get("sonarr_port", "8989"),
                      "apikey": srv.get("sonarr_apikey", "")}
        radarr_cfg = {"host": srv.get("radarr_host", "localhost"),
                      "port": srv.get("radarr_port", "7878"),
                      "apikey": srv.get("radarr_apikey", "")}
        result = find_duplicate_and_orphaned_media(self.controller.ssh, sonarr_cfg, radarr_cfg)
        self.after(0, lambda r=result: self._finish_scan(r))

    def _finish_scan(self, result):
        self._scanning = False
        self._scan_btn.config(state="normal", text="⟳ Scan")
        self._last_lbl.config(text="Last scan: " + time.strftime("%H:%M:%S"))

        self._tree.delete(*self._tree.get_children())
        self._row_info = {}
        for idx, group in enumerate(result["groups"]):
            row_tag = "even" if idx % 2 == 0 else "odd"
            iid = self._tree.insert("", "end",
                values=(group["folder"], group["app"].title(),
                        len(group["files"]), _fmt_size(group["extra_bytes"])),
                tags=(row_tag,))
            self._row_info[iid] = group
        self._draw_summary_cards()

        status = "{} folder{} flagged".format(
            len(result["groups"]), "s" if len(result["groups"]) != 1 else "")
        if result["errors"]:
            status += "  ·  ⚠ " + "; ".join(result["errors"])
        self._set_status(status, "error" if result["groups"] else "ok")

    # =========================================================
    # DETAIL PANEL
    # =========================================================
    def _on_select(self, _event=None):
        sel = self._tree.selection()
        self._file_tree.delete(*self._file_tree.get_children())
        self._file_info = {}
        self._delete_btn.config(state="disabled")
        if not sel:
            self._current_group_iid = None
            return
        self._current_group_iid = sel[0]
        group = self._row_info.get(sel[0])
        if not group:
            return
        for f in sorted(group["files"], key=lambda x: x["size"], reverse=True):
            tag = "tracked" if f["tracked"] else "untracked"
            iid = self._file_tree.insert("", "end",
                values=(_fmt_size(f["size"]), "Yes" if f["tracked"] else "No", f["path"]),
                tags=(tag,))
            self._file_info[iid] = f

    def _on_file_select(self, _event=None):
        sel = self._file_tree.selection()
        self._delete_btn.config(state="normal" if sel else "disabled")

    # =========================================================
    # DELETE
    # =========================================================
    def _delete_selected_file(self):
        sel = self._file_tree.selection()
        if not sel or not self._current_group_iid:
            return
        file_info = self._file_info.get(sel[0])
        if not file_info:
            return

        warning = ""
        if file_info["tracked"]:
            warning = ("\n\n⚠ This file is currently tracked by Sonarr/Radarr — "
                       "deleting it will make that episode/movie show as missing "
                       "until it's re-downloaded.")
        msg = (
            "Permanently delete this file from the server?\n\n"
            "{}\n"
            "Size: {}{}\n\n"
            "This cannot be undone."
        ).format(file_info["path"], _fmt_size(file_info["size"]), warning)
        if not messagebox.askyesno("Delete File", msg, parent=self):
            return

        self._delete_btn.config(state="disabled", text="Deleting…")
        threading.Thread(target=self._do_delete, args=(file_info,), daemon=True).start()

    def _do_delete(self, file_info):
        ok, err = delete_file(self.controller.ssh, file_info["path"])
        self.after(0, lambda: self._finish_delete(file_info, ok, err))

    def _finish_delete(self, file_info, ok, err):
        self._delete_btn.config(text="Delete Selected File")
        if not ok:
            self._set_status("Delete failed: " + err, "error")
            self._delete_btn.config(state="normal")
            return

        group_iid = self._current_group_iid
        group = self._row_info.get(group_iid)
        if group:
            group["files"] = [f for f in group["files"] if f["path"] != file_info["path"]]
            if len(group["files"]) < 2:
                # No longer a duplicate/orphan situation — drop the row entirely.
                self._tree.delete(group_iid)
                del self._row_info[group_iid]
            else:
                sizes = sorted((f["size"] for f in group["files"]), reverse=True)
                group["extra_bytes"] = sum(sizes[1:])
                self._tree.item(group_iid, values=(
                    group["folder"], group["app"].title(),
                    len(group["files"]), _fmt_size(group["extra_bytes"])))

        self._on_select()  # refresh the file list for the (possibly now-gone) group
        self._draw_summary_cards()
        self._set_status("Deleted: " + file_info["path"], "ok")

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…"):
            self._status_lbl.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "error": t.status_stopped, "ok": t.status_running}
        self._status_lbl.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
