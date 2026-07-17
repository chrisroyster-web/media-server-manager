# ui/media_integrity_tab.py
"""
Media Integrity Scan tab.
Walks the Sonarr/Radarr-managed library over SSH and runs ffprobe against
every video file to flag corrupt/unplayable ones (core/media_integrity.py).
Deliberately does NOT auto-scan on tab show — a full-library scan can take
a long time, so scanning is always an explicit user action, same rationale
as ui/vuln_scan_tab.py and ui/media_dedup_tab.py.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from datetime import datetime

from core.media_integrity import get_scan_roots, run_scan, verify_file, diff_new_corrupt


_SCHEDULE_LABELS = {"disabled": "Disabled", "daily": "Daily", "weekly": "Weekly"}
_SCHEDULE_KEYS   = {v: k for k, v in _SCHEDULE_LABELS.items()}


def _fmt_size(num_bytes):
    if num_bytes >= 1024 ** 3:
        return "{:.1f} GB".format(num_bytes / 1024 ** 3)
    if num_bytes >= 1024 ** 2:
        return "{:.0f} MB".format(num_bytes / 1024 ** 2)
    return "{:.0f} KB".format(num_bytes / 1024)


def _fmt_duration(seconds_str):
    try:
        secs = int(float(seconds_str))
    except (TypeError, ValueError):
        return "--"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return "{:d}:{:02d}:{:02d}".format(h, m, s) if h else "{:d}:{:02d}".format(m, s)


class MediaIntegrityTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._row_info  = {}   # tree iid -> file dict
        self._scanning  = False
        self._verifying = False
        self._only_problems = tk.BooleanVar(value=False)
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="MEDIA INTEGRITY SCAN", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._scan_btn = tk.Button(hdr, text="⟳ Scan Library", command=self._scan)
        t.style_button(self._scan_btn)
        self._scan_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        self._auto_var = tk.StringVar(
            value=_SCHEDULE_LABELS.get(
                self.controller.config_manager.get_integrity_scan_schedule(), "Disabled"))
        ttk.Combobox(hdr, textvariable=self._auto_var,
                     values=list(_SCHEDULE_LABELS.values()),
                     state="readonly", width=9, font=t.font_small
                     ).pack(side="right", padx=(0, 12))
        tk.Label(hdr, text="Auto-scan:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="right", padx=(0, 4))
        self._auto_var.trace_add("write", self._on_schedule_change)

        # Summary cards
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._draw_summary_cards()

        # Not-ready empty state (ffprobe missing, or no Sonarr/Radarr key)
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
        filter_row.pack(fill="x")
        tk.Checkbutton(filter_row, text="Show only problems", variable=self._only_problems,
                        command=self._render_rows, bg=t.bg, fg=t.text_muted,
                        selectcolor=t.surface_dark, activebackground=t.bg,
                        font=t.font_small).pack(anchor="w")

        self._tree = self._make_tree(tree_frame,
            cols=("path", "size", "duration", "status"),
            headings=[
                ("path",     "File",     480, "w"),
                ("size",     "Size",      90, "center"),
                ("duration", "Duration",  90, "center"),
                ("status",   "Status",   100, "center"),
            ])
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Detail console
        detail_hdr = tk.Frame(self, bg=t.bg)
        detail_hdr.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(detail_hdr, text="Detail (select a row)", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._verify_btn = tk.Button(detail_hdr, text="Deep Verify",
                                      command=self._deep_verify_selected, state="disabled")
        t.style_button(self._verify_btn)
        self._verify_btn.pack(side="right")

        self._console = tk.Text(self, height=6, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="x", padx=16, pady=(0, 4))

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    def _make_tree(self, parent, cols, headings, height=10):
        t = self.theme
        style = ttk.Style()
        sid = "Integrity{}.Treeview".format(id(parent))
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
        tree.tag_configure("odd",     background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",    background=t.card_bg,      foreground=t.text)
        tree.tag_configure("corrupt", foreground=t.status_stopped_text)
        tree.tag_configure("clean",   foreground=t.status_running)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _draw_summary_cards(self):
        t = self.theme
        for w in self._summary_frame.winfo_children():
            w.destroy()
        files = [info["file"] for info in self._row_info.values()]
        total = len(files)
        corrupt = sum(1 for f in files if not f.get("ok"))
        ok = total - corrupt
        for label, val, color in [
            ("Total Files", str(total), t.text),
            ("OK",          str(ok),      t.status_running),
            ("Corrupt",     str(corrupt), t.status_stopped_text if corrupt else t.status_running),
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
        self.controller.config_manager.set_integrity_scan_schedule(key)

    def _sonarr_radarr_cfg(self):
        srv = (self.controller.config_manager.get_active_server() or {}).get("settings", {})
        sonarr_cfg = {"host": srv.get("sonarr_host", "localhost"),
                      "port": srv.get("sonarr_port", "8989"),
                      "apikey": srv.get("sonarr_apikey", "")}
        radarr_cfg = {"host": srv.get("radarr_host", "localhost"),
                      "port": srv.get("radarr_port", "7878"),
                      "apikey": srv.get("radarr_apikey", "")}
        return sonarr_cfg, radarr_cfg

    # =========================================================
    # ON SHOW — checks ffprobe availability, then Sonarr/Radarr config
    # =========================================================
    def on_show(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        threading.Thread(target=self._check_prereqs, daemon=True).start()

    def _check_prereqs(self):
        out, _, code = self.controller.ssh.run("which ffprobe 2>/dev/null")
        has_ffprobe = code == 0 and bool(out.strip())
        sonarr_cfg, radarr_cfg = self._sonarr_radarr_cfg()
        configured = bool(sonarr_cfg["apikey"] or radarr_cfg["apikey"])
        self.after(0, lambda: self._set_ready(has_ffprobe, configured))

    def _set_ready(self, has_ffprobe, configured):
        if not has_ffprobe:
            self._show_empty(
                "ffprobe is not installed on this server.\n\n"
                "Install ffmpeg from the Install Apps tab to enable "
                "integrity scanning.")
            self._set_status("ffprobe not installed.", "error")
            return
        if not configured:
            self._show_empty(
                "No Sonarr or Radarr API key configured for this server.\n\n"
                "Add one in Config to enable integrity scanning.")
            self._set_status("No Sonarr/Radarr API key configured.", "error")
            return
        self._empty_frame.pack_forget()
        self._tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._scan_btn.config(state="normal")
        self._set_status("Ready — click Scan Library to check for corrupt files.")

    def _show_empty(self, text):
        self._empty_lbl.config(text=text)
        self._tree_frame.pack_forget()
        self._empty_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._scan_btn.config(state="disabled")

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
        ssh = self.controller.ssh
        sonarr_cfg, radarr_cfg = self._sonarr_radarr_cfg()
        roots, errors = get_scan_roots(sonarr_cfg, radarr_cfg)
        result = run_scan(ssh, roots)
        self.after(0, lambda r=result, e=errors: self._finish_scan(r, e))

    def _finish_scan(self, result, root_errors):
        self._scanning = False
        self._scan_btn.config(state="normal", text="⟳ Scan Library")
        self._last_lbl.config(text="Last scan: " + time.strftime("%H:%M:%S"))

        self._row_info = {}
        for f in result.get("files", []):
            self._row_info[f["path"]] = {"file": f}
        self._render_rows()
        self._draw_summary_cards()

        files = result.get("files", [])
        corrupt = sum(1 for f in files if not f.get("ok"))
        if result.get("error"):
            self._set_status("Scan error: " + result["error"], "error")
        elif root_errors:
            self._set_status("Scan complete with errors: " + "; ".join(root_errors), "error")
        else:
            self._set_status(
                "Scan complete — {} file{} checked, {} corrupt.".format(
                    len(files), "s" if len(files) != 1 else "", corrupt),
                "error" if corrupt else "ok")

        cfg = self.controller.config_manager
        new_baseline, newly_corrupt = diff_new_corrupt(cfg.get_integrity_scan_baseline(), files)
        cfg.set_integrity_scan_baseline(new_baseline)
        cfg.set_integrity_scan_last_run(datetime.now().isoformat(timespec="seconds"))
        if newly_corrupt:
            title = "New corrupt media files found"
            names = ", ".join(f["path"].rsplit("/", 1)[-1] for f in newly_corrupt[:5])
            more = "" if len(newly_corrupt) <= 5 else " (+{} more)".format(len(newly_corrupt) - 5)
            body = "{} new corrupt file{}: {}{}".format(
                len(newly_corrupt), "s" if len(newly_corrupt) != 1 else "", names, more)
            self.controller.notification_manager.send_alert(title, body)

    def _render_rows(self):
        self._tree.delete(*self._tree.get_children())
        only_problems = self._only_problems.get()
        idx = 0
        for path, info in sorted(self._row_info.items()):
            f = info["file"]
            if only_problems and f.get("ok"):
                continue
            row_tag = "even" if idx % 2 == 0 else "odd"
            status = "OK" if f.get("ok") else "Corrupt"
            sev_tag = "clean" if f.get("ok") else "corrupt"
            self._tree.insert("", "end", iid=path,
                values=(path, _fmt_size(f.get("size", 0)),
                        _fmt_duration(f.get("duration")), status),
                tags=(row_tag, sev_tag))
            idx += 1

    # =========================================================
    # DETAIL / DEEP VERIFY
    # =========================================================
    def _on_select(self, _event=None):
        sel = self._tree.selection()
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        if not sel:
            self._verify_btn.config(state="disabled")
            self._console.config(state="disabled")
            return
        info = self._row_info.get(sel[0])
        self._verify_btn.config(state="normal" if info else "disabled")
        if info:
            f = info["file"]
            if f.get("ok"):
                self._console.insert("end", "No errors detected.")
            else:
                self._console.insert("end", f.get("error") or "Unknown error.")
        self._console.config(state="disabled")

    def _deep_verify_selected(self):
        sel = self._tree.selection()
        if not sel or self._verifying:
            return
        path = sel[0]
        self._verifying = True
        self._verify_btn.config(state="disabled", text="Verifying…")
        self._set_status("Deep verifying " + path.rsplit("/", 1)[-1] + "…")
        threading.Thread(target=self._do_deep_verify, args=(path,), daemon=True).start()

    def _do_deep_verify(self, path):
        result = verify_file(self.controller.ssh, path)
        self.after(0, lambda p=path, r=result: self._apply_deep_verify(p, r))

    def _apply_deep_verify(self, path, result):
        self._verifying = False
        self._verify_btn.config(state="normal", text="Deep Verify")
        info = self._row_info.get(path)
        if info:
            info["file"]["ok"] = result["ok"]
            info["file"]["error"] = result["error"] or info["file"].get("error", "")
            self._render_rows()
            self._draw_summary_cards()
            self._tree.selection_set(path)
            self._on_select()
        self._set_status(
            "Deep verify: {} is {}.".format(
                path.rsplit("/", 1)[-1], "OK" if result["ok"] else "corrupt"),
            "ok" if result["ok"] else "error")

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
