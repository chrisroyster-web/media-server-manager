# ui/secrets_audit_tab.py
"""
Secrets Hygiene tab.
Enumerates every currently-configured secret (API keys, tokens, passwords)
via core.config_manager.list_secrets() and flags whether the app sends it
as a URL query parameter (visible in server access logs, reverse-proxy
logs, screenshots) vs. an HTTP header, using the hand-maintained map in
core/secret_exposure.py. Reads only in-memory config -- no SSH round trip,
so this never needs the tab's usual "not connected" gating.
"""

import tkinter as tk
from tkinter import ttk

from core.secret_exposure import classify


class SecretsAuditTab(tk.Frame):

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
        tk.Label(hdr, text="SECRETS HYGIENE", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")

        # Summary cards
        s_row = tk.Frame(self, bg=t.bg)
        s_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_configured = self._stat_card(s_row, "Configured", "--", t.text)
        self._card_in_url     = self._stat_card(s_row, "In URL",     "--", t.status_stopped_text)
        self._card_fixable    = self._stat_card(s_row, "Fixable",    "--", t.yellow)

        # Table
        tbl_frame = tk.Frame(self, bg=t.bg)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        style.configure("SecretsAudit.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=28, font=t.font_mono)
        style.configure("SecretsAudit.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("SecretsAudit.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("scope", "service", "key", "exposure", "fixable", "note")
        self._tree = ttk.Treeview(tbl_frame, columns=cols,
                                   show="headings", style="SecretsAudit.Treeview")
        for col, w, lbl, anchor in [
            ("scope",    140, "Scope",    "w"),
            ("service",  110, "Service",  "w"),
            ("key",      160, "Key",      "w"),
            ("exposure",  90, "Exposure", "center"),
            ("fixable",   70, "Fixable",  "center"),
            ("note",     360, "Note",     "w"),
        ]:
            self._tree.heading(col, text=lbl, anchor=anchor)
            self._tree.column(col, width=w, minwidth=50,
                              anchor=anchor, stretch=(col == "note"))

        self._tree.tag_configure("url",     foreground=t.status_stopped_text)
        self._tree.tag_configure("header",  foreground=t.status_running)
        self._tree.tag_configure("unknown", foreground=t.text_muted)
        self._tree.tag_configure("n/a",     foreground=t.text_dim)

        vsb = tk.Scrollbar(tbl_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Status bar
        self._status = tk.Label(self, text="", bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        self.refresh()

    def _stat_card(self, parent, label, value, color):
        t = self.theme
        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border, highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")
        lbl = tk.Label(card, text=value, bg=t.card_bg, fg=color,
                       font=("Segoe UI Semibold", 20))
        lbl.pack(anchor="w")
        return lbl

    # =========================================================
    # REFRESH  (in-memory read, no SSH round trip)
    # =========================================================
    def refresh(self):
        secrets = self.controller.config_manager.list_secrets()
        self._populate(secrets)

    def on_show(self):
        self.refresh()

    def _populate(self, secrets):
        self._tree.delete(*self._tree.get_children())

        configured_count = 0
        in_url_count = 0
        fixable_count = 0

        for idx, secret in enumerate(sorted(
                secrets, key=lambda s: (s["scope"], s["key"]))):
            if not secret["configured"]:
                continue
            configured_count += 1
            info = classify(secret["key"])
            exposure = info["exposure"]
            if exposure == "url":
                in_url_count += 1
            if info["fixable"]:
                fixable_count += 1

            self._tree.insert("", "end", values=(
                secret["scope"],
                info["service"] or "--",
                secret["key"],
                exposure.upper(),
                "yes" if info["fixable"] else ("no" if info["fixable"] is False else "--"),
                info["note"],
            ), tags=(exposure,))

        self._card_configured.config(text=str(configured_count))
        self._card_in_url.config(
            text=str(in_url_count),
            fg=self.theme.status_stopped_text if in_url_count else self.theme.status_running)
        self._card_fixable.config(
            text=str(fixable_count),
            fg=self.theme.yellow if fixable_count else self.theme.text_muted)

        if in_url_count:
            self._status.config(
                text="{} secret{} sent as a URL query parameter -- visible in "
                     "server/proxy logs.".format(in_url_count, "s" if in_url_count != 1 else ""),
                fg=self.theme.status_stopped_text)
        elif configured_count:
            self._status.config(text="No known URL-embedded secrets among "
                                      "code-audited services.", fg=self.theme.status_running)
        else:
            self._status.config(text="No secrets configured yet.", fg=self.theme.text_muted)
