# ui/metadata_scan_tab.py
"""
Emby Metadata Scan tab.

Pages through the Emby library over its REST API and flags any item with no
Primary image — the exact condition that makes Emby's own ImageService
throw a 500 instead of a clean 404 (see core/metadata_scan.py for the full
story, including the real incident this tab exists to catch ahead of time).

Deliberately does NOT auto-scan on tab show — same rationale as
ui/media_integrity_tab.py and ui/media_dedup_tab.py: a full-library scan
is always an explicit user action.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from datetime import datetime

from core.metadata_scan import scan, generate_and_upload_thumbnail, diff_new_missing


_SCHEDULE_LABELS = {"disabled": "Disabled", "daily": "Daily", "weekly": "Weekly"}
_SCHEDULE_KEYS   = {v: k for k, v in _SCHEDULE_LABELS.items()}


class MetadataScanTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller  = controller
        self.theme       = controller.theme
        self._row_info   = {}   # tree iid (item id) -> item dict
        self._scanning   = False
        self._fixing     = False
        self._filter_var = tk.StringVar()
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="🖼  EMBY METADATA SCAN", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._scan_btn = tk.Button(hdr, text="⟳ Scan Library", command=self._scan)
        t.style_button(self._scan_btn)
        self._scan_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        self._auto_var = tk.StringVar(
            value=_SCHEDULE_LABELS.get(
                self.controller.config_manager.get_metadata_scan_schedule(), "Disabled"))
        ttk.Combobox(hdr, textvariable=self._auto_var,
                     values=list(_SCHEDULE_LABELS.values()),
                     state="readonly", width=9, font=t.font_small
                     ).pack(side="right", padx=(0, 12))
        tk.Label(hdr, text="Auto-scan:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="right", padx=(0, 4))
        self._auto_var.trace_add("write", self._on_schedule_change)

        note = tk.Frame(self, bg=t.surface, padx=18, pady=7)
        note.pack(fill="x")
        tk.Label(note,
                 text="Flags items with no Primary image — the one field Emby's "
                      "own image endpoint 500s on when requested directly, instead "
                      "of a clean 404. Missing backdrops/logos aren't flagged; those "
                      "are common and cosmetic.",
                 bg=t.surface, fg=t.text_muted, font=t.font_small,
                 justify="left", wraplength=900).pack(anchor="w")

        # Summary cards
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(8, 8))
        self._draw_summary_cards()

        # Not-ready empty state (no Emby API key configured)
        self._empty_frame = tk.Frame(self, bg=t.bg)
        self._empty_lbl = tk.Label(self._empty_frame, text="", bg=t.bg,
                                    fg=t.text_muted, font=t.font_regular,
                                    justify="center")
        self._empty_lbl.pack(pady=40)

        # Treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        self._tree_frame = tree_frame
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        filter_row = tk.Frame(tree_frame, bg=t.bg)
        filter_row.pack(fill="x", pady=(0, 4))
        tk.Label(filter_row, text="Filter:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(0, 4))
        filter_entry = tk.Entry(filter_row, textvariable=self._filter_var, width=28,
                                 bg=t.surface_light, fg=t.text, relief="flat",
                                 insertbackground=t.blue, font=t.font_small)
        filter_entry.pack(side="left", ipady=3)
        self._filter_var.trace_add("write", lambda *_: self._render_rows())

        self._tree = self._make_tree(tree_frame,
            cols=("type", "name", "series", "fixable"),
            headings=[
                ("type",    "Type",      80,  "w"),
                ("name",    "Name",     380,  "w"),
                ("series",  "Series",   260,  "w"),
                ("fixable", "Auto-fix",  90,  "center"),
            ])
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Detail / fix panel
        detail_hdr = tk.Frame(self, bg=t.bg)
        detail_hdr.pack(fill="x", padx=16, pady=(4, 0))
        self._selection_lbl = tk.Label(detail_hdr, text="Select one or more rows",
                                        bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._selection_lbl.pack(side="left")
        self._fix_btn = tk.Button(detail_hdr, text="Generate & Upload Thumbnail",
                                   command=self._fix_selected, state="disabled")
        t.style_button(self._fix_btn)
        self._fix_btn.pack(side="right")

        self._console = tk.Text(self, height=6, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="x", padx=16, pady=(0, 4))
        self._console.tag_configure("ok",      foreground=t.status_running)
        self._console.tag_configure("error",   foreground=t.status_stopped_text)
        self._console.tag_configure("section", foreground=t.blue_bright,
                                     font=("Segoe UI Semibold", 9))

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    def _make_tree(self, parent, cols, headings, height=14):
        t = self.theme
        style = ttk.Style()
        sid = "MetadataScan{}.Treeview".format(id(parent))
        style.configure(sid, background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure(sid + ".Heading", background=t.surface_dark,
                        foreground=t.text_muted, font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map(sid, background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=sid, height=height, selectmode="extended")
        for col, text, width, anchor in headings:
            tree.heading(col, text=text, anchor=anchor)
            tree.column(col, width=width, minwidth=50,
                        anchor=anchor, stretch=(width > 150))
        tree.tag_configure("odd",       background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",      background=t.card_bg,      foreground=t.text)
        tree.tag_configure("fixable",   foreground=t.text)
        tree.tag_configure("unfixable", foreground=t.text_muted)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _draw_summary_cards(self):
        t = self.theme
        for w in self._summary_frame.winfo_children():
            w.destroy()
        items = [info["item"] for info in self._row_info.values()]
        total_checked = getattr(self, "_last_total_checked", 0)
        missing = len(items)
        fixable = sum(1 for it in items if it.get("path"))
        for label, val, color in [
            ("Items Checked", str(total_checked), t.text),
            ("Missing Primary Image", str(missing),
             t.status_stopped_text if missing else t.status_running),
            ("Auto-fixable", str(fixable), t.text),
        ]:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=label, bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            tk.Label(card, text=val, bg=t.card_bg,
                     fg=color, font=("Segoe UI", 18, "bold")).pack()

    def _on_schedule_change(self, *_args):
        key = _SCHEDULE_KEYS.get(self._auto_var.get(), "disabled")
        self.controller.config_manager.set_metadata_scan_schedule(key)

    def _emby_cfg(self):
        cfg = self.controller.config_manager
        return cfg.emby_host, cfg.emby_port, cfg.emby_apikey

    # =========================================================
    # ON SHOW
    # =========================================================
    def on_show(self):
        host, port, apikey = self._emby_cfg()
        if not apikey:
            self._show_empty(
                "No Emby API key configured for this server.\n\n"
                "Add one in Config to enable metadata scanning.")
            self._set_status("No Emby API key configured.", "error")
            return
        self._empty_frame.pack_forget()
        self._tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._scan_btn.config(state="normal")
        self._set_status("Ready — click Scan Library to check for missing Primary images.")

    def _show_empty(self, text):
        self._empty_lbl.config(text=text)
        self._tree_frame.pack_forget()
        self._empty_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._scan_btn.config(state="disabled")

    # =========================================================
    # SCAN
    # =========================================================
    def _scan(self):
        if self._scanning:
            return
        host, port, apikey = self._emby_cfg()
        if not apikey:
            self._set_status("No Emby API key configured.", "error")
            return
        self._scanning = True
        self._scan_btn.config(state="disabled", text="Scanning…")
        self._set_status("Scanning Emby library — this can take a while on large libraries…")
        threading.Thread(target=self._do_scan, args=(host, port, apikey), daemon=True).start()

    def _do_scan(self, host, port, apikey):
        result = scan(host, port, apikey)
        self.after(0, lambda r=result: self._finish_scan(r))

    def _finish_scan(self, result):
        self._scanning = False
        self._scan_btn.config(state="normal", text="⟳ Scan Library")
        self._last_lbl.config(text="Last scan: " + time.strftime("%H:%M:%S"))
        self._last_total_checked = result.get("total_checked", 0)

        self._row_info = {}
        for it in result.get("items", []):
            self._row_info[it["id"]] = {"item": it}
        self._render_rows()
        self._draw_summary_cards()

        items = result.get("items", [])
        if result.get("error"):
            self._set_status("Scan error: " + result["error"], "error")
        else:
            self._set_status(
                "Scan complete — {} item{} checked, {} missing a Primary image.".format(
                    result.get("total_checked", 0),
                    "s" if result.get("total_checked", 0) != 1 else "", len(items)),
                "error" if items else "ok")

        cfg = self.controller.config_manager
        new_baseline, newly_missing = diff_new_missing(cfg.get_metadata_scan_baseline(), items)
        cfg.set_metadata_scan_baseline(new_baseline)
        cfg.set_metadata_scan_last_run(datetime.now().isoformat(timespec="seconds"))
        if newly_missing:
            title = "New items missing a Primary image"
            names = ", ".join(it["name"] for it in newly_missing[:5])
            more = "" if len(newly_missing) <= 5 else " (+{} more)".format(len(newly_missing) - 5)
            body = "{} new item{}: {}{}".format(
                len(newly_missing), "s" if len(newly_missing) != 1 else "", names, more)
            self.controller.notification_manager.send_alert(title, body)

    def _render_rows(self):
        self._tree.delete(*self._tree.get_children())
        needle = self._filter_var.get().strip().lower()
        idx = 0
        rows = sorted(self._row_info.items(),
                      key=lambda kv: (kv[1]["item"].get("series_name") or "",
                                       kv[1]["item"].get("name") or ""))
        for item_id, info in rows:
            it = info["item"]
            if needle and needle not in (it["name"] + " " + it["series_name"]).lower():
                continue
            row_tag = "even" if idx % 2 == 0 else "odd"
            fixable = bool(it.get("path"))
            self._tree.insert("", "end", iid=item_id,
                values=(it["type"], it["name"], it["series_name"],
                        "Yes" if fixable else "No"),
                tags=(row_tag, "fixable" if fixable else "unfixable"))
            idx += 1

    # =========================================================
    # DETAIL / FIX
    # =========================================================
    def _on_select(self, _event=None):
        sel = self._tree.selection()
        fixable_count = sum(1 for iid in sel
                             if self._row_info.get(iid, {}).get("item", {}).get("path"))
        if not sel:
            self._selection_lbl.config(text="Select one or more rows")
            self._fix_btn.config(state="disabled", text="Generate & Upload Thumbnail")
        elif fixable_count == 0:
            self._selection_lbl.config(
                text="{} selected — none have a video file to extract from".format(len(sel)))
            self._fix_btn.config(state="disabled", text="Generate & Upload Thumbnail")
        else:
            plural = "s" if fixable_count != 1 else ""
            self._selection_lbl.config(text="{} selected ({} fixable)".format(len(sel), fixable_count))
            self._fix_btn.config(
                state="normal",
                text="Generate & Upload Thumbnail{}".format(" ({})".format(fixable_count)
                                                              if fixable_count > 1 else ""))

    def _fix_selected(self):
        if self._fixing:
            return
        sel = self._tree.selection()
        targets = [self._row_info[iid]["item"] for iid in sel
                   if self._row_info.get(iid, {}).get("item", {}).get("path")]
        if not targets:
            return

        if len(targets) > 1 and not messagebox.askyesno(
                "Generate Thumbnails",
                "Set a Primary image for {} items?\n\n"
                "Tries TVmaze's real episode stills first, falling back to an "
                "ffmpeg frame extraction on the server — it may take a while "
                "for a large selection.".format(len(targets)),
                parent=self):
            return

        self._fixing = True
        self._fix_btn.config(state="disabled", text="Working…")
        self._set_status("Generating thumbnails for {} item(s)…".format(len(targets)))
        threading.Thread(target=self._do_fix, args=(targets,), daemon=True).start()

    def _do_fix(self, targets):
        host, port, apikey = self._emby_cfg()
        ssh = self.controller.ssh
        ok_count, fail_count = 0, 0
        # Shared across the whole run so fixing multiple episodes of the same
        # show only resolves that series' TVmaze id once, not once per episode.
        tvmaze_cache = {}
        self._log("\n── Generate & upload thumbnails ──────────────────────\n", "section")
        for it in targets:
            self._log("  {} — {}… ".format(it["type"], it["name"]))
            result = generate_and_upload_thumbnail(
                ssh, host, port, apikey, it["id"], it["path"],
                item_type=it.get("type", ""), series_id=it.get("series_id"),
                season=it.get("season"), episode=it.get("episode"),
                tvmaze_cache=tvmaze_cache)
            if result["ok"]:
                ok_count += 1
                self._log("done (via {})\n".format(result.get("source") or "?"), "ok")
                self.after(0, lambda i=it["id"]: self._row_info.pop(i, None))
            else:
                fail_count += 1
                self._log((result.get("error") or "failed") + "\n", "error")
        self.after(0, lambda: self._finish_fix(ok_count, fail_count))

    def _finish_fix(self, ok_count, fail_count):
        self._fixing = False
        self._fix_btn.config(state="disabled", text="Generate & Upload Thumbnail")
        self._render_rows()
        self._draw_summary_cards()
        self.controller.audit_log(
            "metadata_scan.generate_thumbnail", "Emby",
            detail="{} fixed, {} failed".format(ok_count, fail_count),
            result="ok" if not fail_count else "fail")
        self._set_status(
            "Done — {} fixed, {} failed.".format(ok_count, fail_count),
            "ok" if not fail_count else "error")

    # =========================================================
    # HELPERS
    # =========================================================
    def _log(self, text: str, tag: str = None):
        def _do():
            self._console.configure(state="normal")
            if tag:
                self._console.insert("end", text, tag)
            else:
                self._console.insert("end", text)
            self._console.see("end")
            self._console.configure(state="disabled")
        self.after(0, _do)

    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…"):
            self._status_lbl.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "error": t.status_stopped, "ok": t.status_running}
        self._status_lbl.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
