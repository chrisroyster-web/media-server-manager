# ui/log_viewer_tab.py

import tkinter as tk
import threading
import os
import time

from core.log_sources import list_docker_log_sources, search_sources


class LogViewerTab(tk.Frame):
    """
    Real-time log viewer.
    - Selectable log sources (journal, service-specific, backup/cleanup logs)
    - Keyword filter (live)
    - Auto-scroll toggle
    - Configurable poll interval
    - Export to file
    - Color-coded by severity
    """

    # Always-present sources.  Player sources (Plex, Jellyfin) are injected
    # dynamically by _rebuild_sources() based on what's configured.
    _BASE_SOURCES = {
        "Journal (All)":    "journalctl -n 150 --no-pager --output=short 2>/dev/null",
        "Journal (Errors)": "journalctl -p err -n 100 --no-pager --output=short 2>/dev/null",
        "Emby":             "journalctl -u emby-server -n 100 --no-pager --output=short 2>/dev/null",
        "Sonarr":           "journalctl -u sonarr -n 100 --no-pager --output=short 2>/dev/null",
        "Radarr":           "journalctl -u radarr -n 100 --no-pager --output=short 2>/dev/null",
        "Prowlarr":         "journalctl -u prowlarr -n 100 --no-pager --output=short 2>/dev/null",
        "Bazarr":           "journalctl -u bazarr -n 100 --no-pager --output=short 2>/dev/null",
        "SABnzbd":          "journalctl -u sabnzbdplus -n 100 --no-pager --output=short 2>/dev/null",
        "Backup Log":       "tail -100 /var/log/media-backup.log 2>/dev/null || echo 'Log not found'",
        "Cleanup Log":      "tail -100 /var/log/mediaserver-cleanup.log 2>/dev/null || echo 'Log not found'",
    }

    LOG_SOURCES = dict(_BASE_SOURCES)  # active copy; rebuilt on config change

    REFRESH_OPTIONS = {"Off": 0, "5s": 5, "15s": 15, "30s": 30, "60s": 60}

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller    = controller
        self.theme         = controller.theme
        self._refresh_job  = None
        self.LOG_SOURCES   = dict(self._BASE_SOURCES)   # instance copy
        self._current_src  = list(self.LOG_SOURCES.keys())[0]
        self._autoscroll   = tk.BooleanVar(value=True)
        self._filter_var   = tk.StringVar()
        self._refresh_var  = tk.StringVar(value="15s")
        self._last_content = ""
        self._aggregated_mode = False
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        # ---- Top control strip ----
        hdr = tk.Frame(self, bg=self.theme.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(hdr, text="LOG VIEWER", bg=self.theme.bg, fg=self.theme.text,
                 font=self.theme.font_title).pack(side="left")

        ctrl = tk.Frame(hdr, bg=self.theme.bg)
        ctrl.pack(side="right")

        # Auto-scroll
        tk.Checkbutton(
            ctrl, text="Auto-scroll", variable=self._autoscroll,
            bg=self.theme.bg, fg=self.theme.text_muted,
            activebackground=self.theme.bg, activeforeground=self.theme.text,
            selectcolor=self.theme.surface, font=self.theme.font_small,
        ).pack(side="left", padx=(0, 12))

        # Refresh interval
        tk.Label(ctrl, text="Refresh:", bg=self.theme.bg,
                 fg=self.theme.text_muted, font=self.theme.font_small).pack(side="left")

        rm = tk.OptionMenu(ctrl, self._refresh_var,
                            *self.REFRESH_OPTIONS.keys(),
                            command=self._on_refresh_changed)
        rm.configure(
            bg=self.theme.surface, fg=self.theme.text,
            activebackground=self.theme.surface_light, activeforeground=self.theme.text,
            relief="flat", font=self.theme.font_small, highlightthickness=0,
        )
        rm["menu"].configure(bg=self.theme.surface, fg=self.theme.text)
        rm.pack(side="left", padx=(4, 12))

        # Filter
        tk.Label(ctrl, text="Filter:", bg=self.theme.bg,
                 fg=self.theme.text_muted, font=self.theme.font_small).pack(side="left")
        fe = tk.Entry(ctrl, textvariable=self._filter_var,
                       font=self.theme.font_small, width=18)
        self.theme.style_entry(fe)
        fe.pack(side="left", padx=(4, 12))
        self._filter_var.trace_add("write", lambda *a: self._apply_filter())

        # Buttons
        self._search_all_btn = tk.Button(ctrl, text="Search All Sources",
                                         command=self._search_all_sources, state="disabled")
        self.theme.style_button(self._search_all_btn)
        self._search_all_btn.pack(side="left", padx=4)
        self._filter_var.trace_add("write", lambda *a: self._search_all_btn.config(
            state="normal" if self._filter_var.get().strip() else "disabled"))

        for label, cmd in [("Refresh", self.fetch),
                            ("Clear",   self._clear),
                            ("Export",  self._export)]:
            b = tk.Button(ctrl, text=label, command=cmd)
            self.theme.style_button(b)
            b.pack(side="left", padx=4)

        # ---- Main body: source list + log text ----
        body = tk.Frame(self, bg=self.theme.bg)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # Source list — built by _rebuild_sources(); store ref for reuse
        self._src_panel_outer = tk.Frame(body, bg=self.theme.card_bg,
                                          highlightbackground=self.theme.card_border,
                                          highlightthickness=1, width=160)
        self._src_panel_outer.pack(side="left", fill="y", padx=(0, 10))
        self._src_panel_outer.pack_propagate(False)
        self._src_btns = {}

        # Log text
        log_outer = tk.Frame(body, bg=self.theme.surface_dark)
        log_outer.pack(side="left", fill="both", expand=True)

        self.log_text = tk.Text(
            log_outer, bg=self.theme.surface_dark, fg=self.theme.console_output,
            font=self.theme.font_mono, state="disabled", relief="flat",
            padx=10, pady=8, wrap="none",
        )
        ysb = tk.Scrollbar(log_outer, orient="vertical",   command=self.log_text.yview)
        xsb = tk.Scrollbar(log_outer, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right",  fill="y")
        xsb.pack(side="bottom", fill="x")
        self.log_text.pack(fill="both", expand=True)

        self._configure_tags()
        self._rebuild_sources()

    def _configure_tags(self):
        self.log_text.tag_config("error",   foreground=self.theme.console_error)
        self.log_text.tag_config("warn",    foreground=self.theme.yellow)
        self.log_text.tag_config("success", foreground=self.theme.console_success)
        self.log_text.tag_config("dim",     foreground=self.theme.text_muted)

    # =========================================================
    # DYNAMIC SOURCE LIST
    # =========================================================
    def _rebuild_sources(self):
        """
        Rebuild LOG_SOURCES and the source-list panel from current config,
        then (if connected) refresh Docker container sources in the
        background — discovered live since which containers exist varies
        per server, unlike the fixed systemd-service sources above.
        """
        cfg = self.controller.config_manager

        sources = dict(self._BASE_SOURCES)
        if cfg.plex_token:
            sources["Plex"] = (
                "journalctl -u plexmediaserver -n 100 --no-pager --output=short 2>/dev/null"
            )
        if cfg.jellyfin_apikey:
            sources["Jellyfin"] = (
                "journalctl -u jellyfin -n 100 --no-pager --output=short 2>/dev/null"
            )
        # Preserve any previously-discovered Docker sources until the async
        # refresh below replaces them, so switching tabs/servers doesn't
        # flash the panel empty of Docker entries for a moment.
        for name, cmd in self.LOG_SOURCES.items():
            if name.startswith("Docker: "):
                sources[name] = cmd

        self.LOG_SOURCES = sources
        if self._current_src not in self.LOG_SOURCES:
            self._current_src = list(self.LOG_SOURCES.keys())[0]
        self._render_source_panel()

        if self.controller.ssh.connected:
            threading.Thread(target=self._refresh_docker_sources, daemon=True).start()

    def _refresh_docker_sources(self):
        docker_sources = list_docker_log_sources(self.controller.ssh)
        self.after(0, lambda d=docker_sources: self._merge_docker_sources(d))

    def _merge_docker_sources(self, docker_sources):
        sources = {name: cmd for name, cmd in self.LOG_SOURCES.items()
                   if not name.startswith("Docker: ")}
        sources.update(docker_sources)
        self.LOG_SOURCES = sources
        if self._current_src not in self.LOG_SOURCES:
            self._current_src = list(self.LOG_SOURCES.keys())[0]
        self._render_source_panel()

    def _render_source_panel(self):
        self._src_panel_outer.pack_forget()
        for w in self._src_panel_outer.winfo_children():
            w.destroy()

        tk.Label(self._src_panel_outer, text="Sources", bg=self.theme.card_bg,
                 fg=self.theme.text_muted, font=self.theme.font_small,
                 ).pack(anchor="w", padx=10, pady=(8, 4))
        tk.Frame(self._src_panel_outer, bg=self.theme.card_border, height=1).pack(fill="x")

        self._src_btns = {}
        for name in self.LOG_SOURCES:
            btn = tk.Button(
                self._src_panel_outer, text=name, anchor="w",
                bg=self.theme.card_bg, fg=self.theme.text,
                relief="flat", bd=0, font=self.theme.font_small, padx=10,
                command=lambda n=name: self._select_source(n),
            )
            btn.pack(fill="x", pady=1)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=self.theme.surface))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(
                bg=self.theme.blue if b is self._src_btns.get(self._current_src)
                else self.theme.card_bg))
            self._src_btns[name] = btn

        self._src_panel_outer.pack(side="left", fill="y", padx=(0, 10))
        self._highlight_source(self._current_src)

    # =========================================================
    # SOURCE SELECTION
    # =========================================================
    def _select_source(self, name):
        self._aggregated_mode = False
        self._current_src  = name
        self._last_content = ""
        self._highlight_source(name)
        self.fetch()

    def _highlight_source(self, name):
        for n, btn in self._src_btns.items():
            btn.configure(bg=self.theme.blue if n == name else self.theme.card_bg,
                           fg=self.theme.text)

    # =========================================================
    # FETCH + RENDER
    # =========================================================
    def fetch(self):
        if not self.controller.ssh.connected:
            self._set_text("Not connected.")
            return
        cmd = self.LOG_SOURCES.get(self._current_src, "")
        threading.Thread(target=self._do_fetch, args=(cmd,), daemon=True).start()

    def _do_fetch(self, cmd):
        out, err, _ = self.controller.ssh.run(cmd)
        content = (out or err or "(no output)").rstrip()
        self._last_content = content
        self.after(0, lambda c=content: self._render(c))
        self._schedule_refresh()

    def _render(self, content):
        filt  = self._filter_var.get().strip().lower()
        lines = content.splitlines()
        if filt:
            lines = [l for l in lines if filt in l.lower()]

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for line in lines:
            self.log_text.insert("end", line + "\n", self._classify(line))
        self.log_text.configure(state="disabled")

        if self._autoscroll.get():
            self.log_text.see("end")

    def _classify(self, line):
        ll = line.lower()
        if any(w in ll for w in ("error", "fatal", "critical", "failed", "fail")):
            return "error"
        if any(w in ll for w in ("warn", "warning")):
            return "warn"
        if any(w in ll for w in ("started", "success", "active", "complete", "done")):
            return "success"
        return "dim"
    def _apply_filter(self):
        if self._aggregated_mode:
            return  # aggregated results are a search result, not a live re-render
        if self._last_content:
            self._render(self._last_content)

    # =========================================================
    # SEARCH ALL SOURCES
    # =========================================================
    def _search_all_sources(self):
        keyword = self._filter_var.get().strip()
        if not keyword or not self.controller.ssh.connected:
            return
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._aggregated_mode = True
        self._search_all_btn.config(state="disabled", text="Searching…")
        self._set_text("Searching {} source{} for \"{}\"…".format(
            len(self.LOG_SOURCES), "s" if len(self.LOG_SOURCES) != 1 else "", keyword))
        threading.Thread(target=self._do_search_all, args=(keyword,), daemon=True).start()

    def _do_search_all(self, keyword):
        results = search_sources(self.controller.ssh, dict(self.LOG_SOURCES), keyword)
        self.after(0, lambda r=results, k=keyword: self._render_aggregated(r, k))

    def _render_aggregated(self, results, keyword):
        self._search_all_btn.config(state="normal", text="Search All Sources")

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if not results:
            self.log_text.insert("end", 'No matches for "{}" in any source.\n'.format(keyword))
        else:
            for name, lines in results.items():
                self.log_text.insert("end", "=== {} ===\n".format(name), "dim")
                for line in lines:
                    self.log_text.insert("end", "[{}] {}\n".format(name, line), self._classify(line))
        self.log_text.configure(state="disabled")
        if self._autoscroll.get():
            self.log_text.see("end")

    # =========================================================
    # CLEAR / EXPORT
    # =========================================================
    def _clear(self):
        self._last_content = ""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _export(self):
        if not self._last_content:
            return
        ts   = time.strftime("%Y%m%d_%H%M%S")
        safe = (self._current_src.replace(" ", "_")
                .replace("(", "").replace(")", "").replace("/", "_"))
        name = safe + "_" + ts + ".log"
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._last_content)
            self._set_text(self._last_content + "\n\n[Exported to: " + path + "]")
        except Exception as e:
            self._set_text(self._last_content + "\n\n[Export failed: " + str(e) + "]")

    def _set_text(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.configure(state="disabled")

    # =========================================================
    # AUTO-REFRESH
    # =========================================================
    def _on_refresh_changed(self, val):
        self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        secs = self.REFRESH_OPTIONS.get(self._refresh_var.get(), 0)
        if secs > 0:
            self._refresh_job = self.after(secs * 1000, self.fetch)
