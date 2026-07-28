# ui/vuln_scan_tab.py
"""
Vulnerability Scan tab.
Scans the server's actual running container images for known CVEs via
Trivy (core/vuln_scanner.py). Deliberately does NOT auto-scan on tab show —
a scan can take anywhere from seconds to a couple minutes per image (longer
on the very first run while Trivy downloads its vulnerability DB), so
scanning is always an explicit user action (Scan All, or a per-row Scan).
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from datetime import datetime

from core.vuln_scanner import list_scan_targets, scan_image, diff_new_findings


_SEVERITY_ORDER = ("critical", "high", "medium", "low")

_SCHEDULE_LABELS = {"disabled": "Disabled", "daily": "Daily", "weekly": "Weekly"}
_SCHEDULE_KEYS   = {v: k for k, v in _SCHEDULE_LABELS.items()}


class VulnScanTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._row_info  = {}   # tree iid -> {"image", "containers", "result"}
        self._scanning  = False
        # None until a scan-all completes in this session (or no baseline existed
        # yet to diff against) -- see _finish_scan_all. Distinct from 0, which
        # means "compared against baseline, genuinely nothing new".
        self._new_count = None
        self._build_ui()

    # =========================================================
    # BUILD UI
    # =========================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="VULNERABILITY SCAN", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._scan_btn = tk.Button(hdr, text="⟳ Scan All", command=self._scan_all)
        t.style_button(self._scan_btn)
        self._scan_btn.pack(side="right")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        self._auto_var = tk.StringVar(
            value=_SCHEDULE_LABELS.get(
                self.controller.config_manager.get_vuln_scan_schedule(), "Disabled"))
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

        # Not-installed empty state (shown/hidden by _set_trivy_available)
        self._empty_frame = tk.Frame(self, bg=t.bg)
        tk.Label(self._empty_frame,
                 text="Trivy is not installed on this server.\n\n"
                      "Install it from the Install Apps tab (Monitoring "
                      "category) to enable vulnerability scanning.",
                 bg=t.bg, fg=t.text_muted, font=t.font_regular,
                 justify="center").pack(pady=40)

        # Treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        self._tree_frame = tree_frame
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self._tree = self._make_tree(tree_frame,
            cols=("image", "containers", "critical", "high", "medium", "low", "status"),
            headings=[
                ("image",      "Image",       300, "w"),
                ("containers", "Container(s)", 220, "w"),
                ("critical",   "Critical",     70, "center"),
                ("high",       "High",         70, "center"),
                ("medium",      "Medium",       70, "center"),
                ("low",        "Low",          70, "center"),
                ("status",     "Status",       110, "center"),
            ])
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # CVE detail console
        tk.Label(self, text="CVE Detail (select a row)", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", padx=16, pady=(4, 0))
        self._console = tk.Text(self, height=8, bg=t.surface_dark,
                                 fg=t.text_secondary, font=t.font_mono,
                                 state="disabled", relief="flat", padx=8, pady=6)
        self._console.pack(fill="x", padx=16, pady=(0, 4))
        self._console.tag_config("critical", foreground=t.status_stopped_text)
        self._console.tag_config("high",     foreground=t.yellow)
        self._console.tag_config("medium",   foreground=t.blue_bright)
        self._console.tag_config("low",      foreground=t.text_muted)

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    def _make_tree(self, parent, cols, headings, height=10):
        t = self.theme
        style = ttk.Style()
        sid = "Vuln{}.Treeview".format(id(parent))
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
        tree.tag_configure("odd",      background=t.surface_dark, foreground=t.text)
        tree.tag_configure("even",     background=t.card_bg,      foreground=t.text)
        tree.tag_configure("has_crit", foreground=t.status_stopped_text)
        tree.tag_configure("has_high", foreground=t.yellow)
        tree.tag_configure("clean",    foreground=t.status_running)
        tree.tag_configure("error",    foreground=t.text_muted)

        vsb = tk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _draw_summary_cards(self):
        t = self.theme
        for w in self._summary_frame.winfo_children():
            w.destroy()
        totals   = self._totals()
        fixable  = self._fixable_totals()
        colors = {
            "critical": t.status_stopped_text, "high": t.yellow,
            "medium": t.blue_bright, "low": t.text_muted,
        }

        # Headline card: new critical/high findings since the last completed
        # scan (the same baseline diff_new_findings() uses for notifications).
        # This is the actionable number -- the raw totals below are mostly a
        # static pile of already-known, often permanently-unfixed CVEs that
        # re-alarm on every look without anything new to act on.
        new_card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
        new_card.pack(side="left", padx=(0, 16), pady=4, ipadx=16, ipady=8)
        tk.Label(new_card, text="New Since Last Scan", bg=t.card_bg,
                 fg=t.text_muted, font=t.font_small).pack()
        if self._new_count is None:
            new_text, new_color = "—", t.text_muted
        else:
            new_text = str(self._new_count)
            new_color = t.status_stopped_text if self._new_count else t.status_running
        tk.Label(new_card, text=new_text, bg=t.card_bg, fg=new_color,
                 font=("Segoe UI", 18, "bold")).pack()

        for sev in _SEVERITY_ORDER:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=sev.title(), bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            if sev in ("critical", "high"):
                fx, tot = fixable[sev]
                # Color by whether any of them are actually fixable, not by
                # raw presence -- a pile of no-fix-available OS package CVEs
                # isn't something you can act on today.
                color = colors[sev] if fx else (t.status_running if tot == 0 else t.text_muted)
            else:
                color = colors[sev] if totals[sev] else t.status_running
            tk.Label(card, text=str(totals[sev]), bg=t.card_bg, fg=color,
                     font=("Segoe UI", 18, "bold")).pack()
            if sev in ("critical", "high") and fixable[sev][1]:
                tk.Label(card, text="{} fixable".format(fixable[sev][0]),
                         bg=t.card_bg, fg=t.text_muted, font=t.font_small).pack()

    def _totals(self):
        totals = {sev: 0 for sev in _SEVERITY_ORDER}
        for info in self._row_info.values():
            result = info.get("result")
            if not result or "error" in result:
                continue
            for sev in _SEVERITY_ORDER:
                totals[sev] += result.get(sev, 0)
        return totals

    def _fixable_totals(self):
        """{sev: (fixable_count, total_count)} using per-CVE fix-version data,
        so a pile of "fixed": "" CVEs (nothing to do) can be told apart from
        ones a rebuild would actually resolve."""
        counts = {sev: [0, 0] for sev in _SEVERITY_ORDER}
        for info in self._row_info.values():
            result = info.get("result")
            if not result or "error" in result:
                continue
            for cve in result.get("cves", []):
                sev = cve.get("severity", "").lower()
                if sev not in counts:
                    continue
                counts[sev][1] += 1
                if cve.get("fixed"):
                    counts[sev][0] += 1
        return {sev: tuple(v) for sev, v in counts.items()}

    def _on_schedule_change(self, *_args):
        key = _SCHEDULE_KEYS.get(self._auto_var.get(), "disabled")
        self.controller.config_manager.set_vuln_scan_schedule(key)

    # =========================================================
    # ON SHOW — checks Trivy availability only, never auto-scans
    # =========================================================
    def on_show(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        threading.Thread(target=self._check_trivy, daemon=True).start()

    def _check_trivy(self):
        out, _, code = self.controller.ssh.run("which trivy 2>/dev/null")
        available = code == 0 and bool(out.strip())
        self.after(0, lambda a=available: self._set_trivy_available(a))

    def _set_trivy_available(self, available):
        if available:
            self._empty_frame.pack_forget()
            self._tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
            self._scan_btn.config(state="normal")
            self._set_status("Trivy is installed — click Scan All to check for CVEs.")
        else:
            self._tree_frame.pack_forget()
            self._empty_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
            self._scan_btn.config(state="disabled")
            self._set_status("Trivy not installed.", "error")

    # =========================================================
    # SCAN ALL
    # =========================================================
    def _scan_all(self):
        if self._scanning or not self.controller.ssh.connected:
            return
        self._scanning = True
        self._scan_btn.config(state="disabled", text="Scanning…")
        self._set_status("Listing running containers…")
        threading.Thread(target=self._do_scan_all, daemon=True).start()

    def _do_scan_all(self):
        ssh = self.controller.ssh
        targets = list_scan_targets(ssh)
        self.after(0, lambda tg=targets: self._seed_rows(tg))

        for target in targets:
            image = target["image"]
            self.after(0, lambda i=image: self._set_status(
                "Scanning {}…".format(i)))
            result = scan_image(ssh, image)
            self.after(0, lambda i=image, r=result: self._apply_result(i, r))

        self.after(0, self._finish_scan_all)

    def _seed_rows(self, targets):
        self._tree.delete(*self._tree.get_children())
        self._row_info = {}
        for idx, target in enumerate(targets):
            image = target["image"]
            row_tag = "even" if idx % 2 == 0 else "odd"
            iid = self._tree.insert("", "end",
                values=(image, ", ".join(target["containers"]),
                        "…", "…", "…", "…", "Pending"),
                tags=(row_tag,))
            self._row_info[iid] = {"image": image, "containers": target["containers"],
                                    "result": None}
        self._set_status("Found {} image{} to scan.".format(
            len(targets), "s" if len(targets) != 1 else ""))

    def _apply_result(self, image, result):
        for iid, info in self._row_info.items():
            if info["image"] != image:
                continue
            info["result"] = result
            if "error" in result:
                self._tree.item(iid, values=(
                    image, ", ".join(info["containers"]),
                    "--", "--", "--", "--", "Error"), tags=("error",))
            else:
                sev_tag = ("has_crit" if result["critical"] else
                           "has_high" if result["high"] else "clean")
                self._tree.item(iid, values=(
                    image, ", ".join(info["containers"]),
                    result["critical"], result["high"],
                    result["medium"], result["low"], "Scanned"), tags=(sev_tag,))
            break
        self._draw_summary_cards()

    def _finish_scan_all(self):
        self._scanning = False
        self._scan_btn.config(state="normal", text="⟳ Scan All")
        self._last_lbl.config(text="Last scan: " + time.strftime("%H:%M:%S"))
        totals = self._totals()

        # Share the same baseline the background watchdog uses (main.py's
        # start_vuln_scan_watchdog) so a manual scan and a scheduled one
        # never double-notify about the same finding.
        cfg = self.controller.config_manager
        results = {info["image"]: info["result"] for info in self._row_info.values()
                   if info.get("result") is not None}
        old_baseline = cfg.get_vuln_scan_baseline()
        new_baseline, new_findings = diff_new_findings(old_baseline, results)
        cfg.set_vuln_scan_baseline(new_baseline)
        cfg.set_vuln_scan_last_run(datetime.now().isoformat(timespec="seconds"))

        # No prior baseline means every image is being seen for the first
        # time -- diff_new_findings() correctly reports 0 "new" in that case,
        # but that's "nothing to compare against yet", not "confirmed clean",
        # so keep the headline card at "—" rather than a falsely reassuring 0.
        self._new_count = None if not old_baseline else sum(
            len(cves) for cves in new_findings.values())
        self._draw_summary_cards()

        if not old_baseline:
            self._set_status(
                "Scan complete — baseline established ({} critical, {} high total). "
                "Future scans will flag only new findings.".format(
                    totals["critical"], totals["high"]), "info")
        elif self._new_count:
            self._set_status(
                "Scan complete — {} new critical/high finding{} "
                "({} critical / {} high total).".format(
                    self._new_count, "s" if self._new_count != 1 else "",
                    totals["critical"], totals["high"]), "error")
        else:
            self._set_status(
                "Scan complete — no new critical/high findings "
                "({} critical, {} high total, all previously seen).".format(
                    totals["critical"], totals["high"]), "ok")

        if new_findings:
            title = "New vulnerabilities found"
            body  = "{} new critical/high CVE{} in: {}".format(
                self._new_count, "s" if self._new_count != 1 else "",
                ", ".join(sorted(new_findings.keys())))
            self.controller.notification_manager.send_alert(title, body)

    # =========================================================
    # DETAIL PANEL
    # =========================================================
    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        info = self._row_info.get(sel[0])
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        if not info or not info.get("result"):
            self._console.insert("end", "Not scanned yet.")
        elif "error" in info["result"]:
            self._console.insert("end", "Scan failed: " + info["result"]["error"])
        else:
            cves = info["result"].get("cves", [])
            if not cves:
                self._console.insert("end", "No vulnerabilities found.")
            for cve in cves:
                sev = cve["severity"].lower()
                tag = sev if sev in _SEVERITY_ORDER else ""
                fixed = " → fixed in {}".format(cve["fixed"]) if cve["fixed"] else " (no fix available)"
                self._console.insert("end",
                    "[{}] {}  {} {}{}\n    {}\n".format(
                        cve["severity"], cve["id"], cve["pkg"], cve["installed"],
                        fixed, cve["title"]),
                    tag)
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
