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

from core.vuln_scanner import list_scan_targets, scan_image


_SEVERITY_ORDER = ("critical", "high", "medium", "low")


class VulnScanTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._row_info  = {}   # tree iid -> {"image", "containers", "result"}
        self._scanning  = False
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
        totals = self._totals()
        colors = {
            "critical": t.status_stopped_text, "high": t.yellow,
            "medium": t.blue_bright, "low": t.text_muted,
        }
        for sev in _SEVERITY_ORDER:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=sev.title(), bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            tk.Label(card, text=str(totals[sev]), bg=t.card_bg,
                     fg=colors[sev] if totals[sev] else t.status_running,
                     font=("Segoe UI", 18, "bold")).pack()

    def _totals(self):
        totals = {sev: 0 for sev in _SEVERITY_ORDER}
        for info in self._row_info.values():
            result = info.get("result")
            if not result or "error" in result:
                continue
            for sev in _SEVERITY_ORDER:
                totals[sev] += result.get(sev, 0)
        return totals

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
        self._set_status(
            "Scan complete — {} critical, {} high, {} medium, {} low.".format(
                totals["critical"], totals["high"], totals["medium"], totals["low"]),
            "error" if totals["critical"] or totals["high"] else "ok")

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
