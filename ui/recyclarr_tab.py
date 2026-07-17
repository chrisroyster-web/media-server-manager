# ui/recyclarr_tab.py
"""
Recyclarr tab -- lets the user pick TRaSH Guides quality-profile templates
for Sonarr/Radarr and push them via core/recyclarr.py. Deliberately does NOT
auto-sync on tab show, same rationale as ui/vuln_scan_tab.py and
ui/media_integrity_tab.py: a sync mutates Sonarr/Radarr's live config, so
it's always an explicit user action unless scheduled.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from datetime import datetime

from core.recyclarr import TEMPLATES, sync_templates


_SCHEDULE_LABELS = {"disabled": "Disabled", "daily": "Daily", "weekly": "Weekly"}
_SCHEDULE_KEYS   = {v: k for k, v in _SCHEDULE_LABELS.items()}


class RecyclarrTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._syncing   = False
        self._template_vars = {}   # template_id -> BooleanVar
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="RECYCLARR  —  TRASH GUIDES SYNC", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._sync_btn = tk.Button(hdr, text="⟳ Sync Now", command=self._sync)
        t.style_button(self._sync_btn)
        self._sync_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        self._auto_var = tk.StringVar(
            value=_SCHEDULE_LABELS.get(
                self.controller.config_manager.get_recyclarr_schedule(), "Disabled"))
        ttk.Combobox(hdr, textvariable=self._auto_var,
                     values=list(_SCHEDULE_LABELS.values()),
                     state="readonly", width=9, font=t.font_small
                     ).pack(side="right", padx=(0, 12))
        tk.Label(hdr, text="Auto-sync:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="right", padx=(0, 4))
        self._auto_var.trace_add("write", self._on_schedule_change)

        tk.Label(self, text="Applies TRaSH Guides' recommended quality profiles and "
                             "custom formats to Sonarr/Radarr. Select the profiles that "
                             "match your library, then Sync Now.",
                 bg=t.bg, fg=t.text_muted, font=t.font_small,
                 justify="left", wraplength=760).pack(fill="x", padx=16, pady=(0, 8))

        # Not-ready empty state (recyclarr image missing, or no Sonarr/Radarr key)
        self._empty_frame = tk.Frame(self, bg=t.bg)
        self._empty_lbl = tk.Label(self._empty_frame, text="", bg=t.bg,
                                    fg=t.text_muted, font=t.font_regular,
                                    justify="center")
        self._empty_lbl.pack(pady=40)

        # Template picker
        self._picker_frame = tk.Frame(self, bg=t.bg)
        self._picker_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._build_template_picker()

        # Console
        detail_hdr = tk.Frame(self, bg=t.bg)
        detail_hdr.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(detail_hdr, text="Last sync output", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")

        self._console = tk.Text(self, height=14, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    def _build_template_picker(self):
        t = self.theme
        selected = set(self.controller.config_manager.get_recyclarr_selected_templates())
        for service, label in (("sonarr", "Sonarr"), ("radarr", "Radarr")):
            col = tk.Frame(self._picker_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            col.pack(side="left", fill="both", expand=True, padx=(0, 8), ipadx=8, ipady=6)
            tk.Label(col, text=label, bg=t.card_bg, fg=t.text,
                     font=t.font_small).pack(anchor="w", padx=8, pady=(4, 2))
            for template_id, desc in TEMPLATES[service]:
                var = tk.BooleanVar(value=template_id in selected)
                var.trace_add("write", self._on_template_toggle)
                self._template_vars[template_id] = var
                tk.Checkbutton(col, text=desc, variable=var,
                               bg=t.card_bg, fg=t.text_muted, selectcolor=t.surface_dark,
                               activebackground=t.card_bg, font=t.font_small
                               ).pack(anchor="w", padx=8)

    def _on_template_toggle(self, *_args):
        selected = [tid for tid, var in self._template_vars.items() if var.get()]
        self.controller.config_manager.set_recyclarr_selected_templates(selected)

    def _on_schedule_change(self, *_args):
        key = _SCHEDULE_KEYS.get(self._auto_var.get(), "disabled")
        self.controller.config_manager.set_recyclarr_schedule(key)

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
    # ON SHOW — checks the recyclarr image is pulled, then Sonarr/Radarr config
    # =========================================================
    def on_show(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._render_last_result()
        threading.Thread(target=self._check_prereqs, daemon=True).start()

    def _check_prereqs(self):
        out, _, code = self.controller.ssh.run(
            "docker image inspect recyclarr/recyclarr >/dev/null 2>&1 && echo ok")
        has_image = code == 0 and "ok" in (out or "")
        sonarr_cfg, radarr_cfg = self._sonarr_radarr_cfg()
        configured = bool(sonarr_cfg["apikey"] or radarr_cfg["apikey"])
        self.after(0, lambda: self._set_ready(has_image, configured))

    def _set_ready(self, has_image, configured):
        if not has_image:
            self._show_empty(
                "The recyclarr Docker image is not installed on this server.\n\n"
                "Install Recyclarr from the Install Apps tab to enable syncing.")
            self._set_status("recyclarr image not installed.", "error")
            return
        if not configured:
            self._show_empty(
                "No Sonarr or Radarr API key configured for this server.\n\n"
                "Add one in Config to enable syncing.")
            self._set_status("No Sonarr/Radarr API key configured.", "error")
            return
        self._empty_frame.pack_forget()
        self._picker_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._sync_btn.config(state="normal")
        self._set_status("Ready — select templates and click Sync Now.")

    def _show_empty(self, text):
        self._empty_lbl.config(text=text)
        self._picker_frame.pack_forget()
        self._empty_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._sync_btn.config(state="disabled")

    # =========================================================
    # SYNC
    # =========================================================
    def _sync(self):
        if self._syncing or not self.controller.ssh.connected:
            return
        template_ids = [tid for tid, var in self._template_vars.items() if var.get()]
        if not template_ids:
            self._set_status("Select at least one template first.", "error")
            return
        self._syncing = True
        self._sync_btn.config(state="disabled", text="Syncing…")
        self._set_status("Syncing selected templates to Sonarr/Radarr…")
        threading.Thread(target=self._do_sync, args=(template_ids,), daemon=True).start()

    def _do_sync(self, template_ids):
        ssh = self.controller.ssh
        sonarr_cfg, radarr_cfg = self._sonarr_radarr_cfg()
        result = sync_templates(ssh, template_ids, sonarr_cfg, radarr_cfg)
        self.after(0, lambda r=result: self._finish_sync(r))

    def _finish_sync(self, result):
        self._syncing = False
        self._sync_btn.config(state="normal", text="⟳ Sync Now")
        self._last_lbl.config(text="Last sync: " + time.strftime("%H:%M:%S"))

        cfg = self.controller.config_manager
        cfg.set_recyclarr_last_run(datetime.now().isoformat(timespec="seconds"))
        cfg.set_recyclarr_last_result(result)
        self._render_last_result()

        if result.get("ok"):
            self._set_status("Sync complete.", "ok")
        else:
            self._set_status("Sync error: " + (result.get("error") or "unknown error"), "error")

    def _render_last_result(self):
        result = self.controller.config_manager.get_recyclarr_last_result()
        text = result.get("raw") or result.get("error") or "No sync has run yet."
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        self._console.insert("end", text)
        self._console.config(state="disabled")

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
