# ui/watchstate_tab.py
"""
Watchstate status tab.
Watchstate (https://github.com/arabcoders/watchstate) syncs watched/play
state between Plex, Emby, and Jellyfin. All backend configuration and
per-user identity matching happens in its own web UI — this tab just
surfaces reachability and container logs, and links out to that UI.
"""

import tkinter as tk
import threading
import time
import urllib.request
import urllib.error
import webbrowser

from ui.refresh_control import RefreshControl
from ui.log_tail_window import LogTailWindow


def _check_health(host, port):
    host = host.removeprefix("https://").removeprefix("http://").strip("/").strip()
    url = "http://{}:{}/v1/api/system/healthcheck".format(host, port)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.status


class WatchstateTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="WATCHSTATE", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "watchstate",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        desc = tk.Label(
            self,
            text=("Syncs watched/play state between Plex, Emby, and Jellyfin. "
                  "Backend connections and per-user identity matching are "
                  "configured in Watchstate's own web UI, not here."),
            bg=t.bg, fg=t.text_muted, font=t.font_small,
            justify="left", wraplength=900, anchor="w")
        desc.pack(fill="x", padx=16, pady=(0, 10))

        # Status card
        card = tk.Frame(self, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=(0, 10), ipadx=12, ipady=10)

        row = tk.Frame(card, bg=t.card_bg)
        row.pack(fill="x", padx=8)
        tk.Label(row, text="Status", bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._status_dot = tk.Label(row, text="●", bg=t.card_bg,
                                     fg=t.text_muted, font=("Segoe UI", 12))
        self._status_dot.pack(side="left", padx=(12, 4))
        self._status_lbl = tk.Label(row, text="Not configured", bg=t.card_bg,
                                     fg=t.text, font=t.font_regular)
        self._status_lbl.pack(side="left")

        btn_row = tk.Frame(card, bg=t.card_bg)
        btn_row.pack(fill="x", padx=8, pady=(10, 0))
        open_btn = tk.Button(btn_row, text="Open Web UI ↗",
                             command=self._open_web_ui)
        t.style_button(open_btn)
        open_btn.pack(side="left")
        logs_btn = tk.Button(btn_row, text="View Container Logs",
                             command=self._view_logs,
                             bg=t.surface_light, fg=t.text,
                             bd=0, relief="flat", font=t.font_small,
                             padx=10, pady=5, cursor="hand2")
        logs_btn.pack(side="left", padx=(8, 0))

        # Status bar
        self._status = tk.Label(
            self, text="Configure Watchstate in Settings to get started",
            bg=t.surface_dark, fg=t.text_muted,
            font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8), side="bottom")

    def _url(self):
        cfg  = self.controller.config_manager
        host = cfg.watchstate_host.removeprefix("https://").removeprefix("http://").strip("/").strip()
        return "http://{}:{}".format(host, cfg.watchstate_port)

    def _open_web_ui(self):
        cfg = self.controller.config_manager
        if not cfg.watchstate_host:
            return
        webbrowser.open(self._url())

    def _view_logs(self):
        LogTailWindow(self.controller, "watchstate logs",
                      "docker logs -f --tail=200 watchstate")

    # =========================================================
    # REFRESH
    # =========================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        cfg = self.controller.config_manager
        if not cfg.watchstate_host:
            self._status_dot.config(fg=self.theme.text_muted)
            self._status_lbl.config(text="Not configured")
            self._status.config(
                text="No host configured — add it in Settings > Monitoring",
                bg=self.theme.surface_dark, fg=self.theme.yellow)
            return
        self._status.config(text="Checking…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        cfg = self.controller.config_manager
        try:
            code = _check_health(cfg.watchstate_host, cfg.watchstate_port)
            ok, detail = True, "HTTP {}".format(code)
        except urllib.error.HTTPError as e:
            # Any HTTP response at all means the service is up and answering.
            ok, detail = True, "HTTP {}".format(e.code)
        except Exception as e:
            ok, detail = False, str(e)
        finally:
            self._fetching = False

        self.after(0, lambda: self._populate(ok, detail))
        self.after(0, lambda: self._last_lbl.config(
            text="Updated {}".format(time.strftime("%H:%M"))))
        self.after(0, self._rc.schedule)

    def _populate(self, ok, detail):
        t = self.theme
        if ok:
            self._status_dot.config(fg=t.status_running)
            self._status_lbl.config(text="Reachable — {}".format(self._url()))
            self._status.config(text="Watchstate is up ({})".format(detail),
                                bg=t.surface_dark, fg=t.status_running)
        else:
            self._status_dot.config(fg=t.status_stopped)
            self._status_lbl.config(text="Unreachable — {}".format(self._url()))
            self._status.config(text="Cannot reach Watchstate: {}".format(detail),
                                bg=t.surface_dark, fg=t.status_stopped)
