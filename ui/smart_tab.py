# ui/smart_tab.py

import tkinter as tk
from tkinter import ttk
import threading
import time


class SmartTab(tk.Frame):
    """
    S.M.A.R.T. disk health tab.
    Lists all block devices, shows health, temperature, reallocated sectors,
    power-on hours and other key attributes via smartctl over SSH.
    """

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

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="DISK HEALTH  (S.M.A.R.T.)",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")

        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh",
                                       command=self._refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")

        self._last_scan_lbl = tk.Label(hdr, text="", bg=t.bg,
                                        fg=t.text_muted, font=t.font_small)
        self._last_scan_lbl.pack(side="right", padx=12)

        # Summary cards row
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Disk treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Smart.Treeview",
                        background=t.card_bg,
                        foreground=t.text,
                        fieldbackground=t.card_bg,
                        borderwidth=0,
                        rowheight=30,
                        font=t.font_mono)
        style.configure("Smart.Treeview.Heading",
                        background=t.surface_dark,
                        foreground=t.text_muted,
                        font=t.font_small,
                        relief="flat", borderwidth=0)
        style.map("Smart.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("device", "model", "health", "temp", "reallocated",
                "pending", "uncorr", "hours", "size")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  style="Smart.Treeview", selectmode="browse")

        headings = [
            ("device",      "Device",         90,  "w"),
            ("model",       "Model",          200, "w"),
            ("health",      "Health",         80,  "center"),
            ("temp",        "Temp (°C)",      80,  "e"),
            ("reallocated", "Reallocated",    90,  "e"),
            ("pending",     "Pending",        80,  "e"),
            ("uncorr",      "Uncorrectable",  110, "e"),
            ("hours",       "Power-On Hrs",   100, "e"),
            ("size",        "Size",           70,  "e"),
        ]
        for col, text, width, anchor in headings:
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=50,
                             anchor=anchor, stretch=(col in ("model", "device")))

        self.tree.tag_configure("good",    foreground=t.status_running)
        self.tree.tag_configure("warn",    foreground=t.yellow)
        self.tree.tag_configure("bad",     foreground=t.status_stopped)
        self.tree.tag_configure("unknown", foreground=t.text_muted)
        self.tree.tag_configure("odd",     background=t.surface_dark)
        self.tree.tag_configure("even",    background=t.card_bg)

        vsb = tk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Double-1>", self._show_detail)

        # Detail console at bottom
        detail_frame = tk.Frame(self, bg=t.bg)
        detail_frame.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(detail_frame, text="Detail Output",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(anchor="w")
        self._detail = tk.Text(detail_frame, height=8,
                                bg=t.surface_dark, fg=t.text_secondary,
                                font=t.font_mono, state="disabled",
                                relief="flat", padx=8, pady=6)
        self._detail.pack(fill="x")

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 8))

    # =========================================================
    # REFRESH
    # =========================================================
    def _refresh(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._refresh_btn.config(state="disabled", text="Scanning…")
        self._set_status("Scanning drives…")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        ssh = self.controller.ssh
        # 1. Find all block devices (physical disks, not partitions/loops)
        out, _, code = ssh.run(
            "lsblk -d -o NAME,SIZE,TYPE --noheadings 2>/dev/null | "
            "awk '$3==\"disk\"{print \"/dev/\"$1\"|\"$2}'"
        )
        if code != 0 or not out.strip():
            self.after(0, lambda: self._set_status("No disks found or lsblk unavailable", "error"))
            self.after(0, lambda: self._refresh_btn.config(state="normal", text="⟳ Refresh"))
            return

        devices = []
        for line in out.strip().splitlines():
            parts = line.split("|")
            if len(parts) == 2:
                devices.append((parts[0].strip(), parts[1].strip()))

        rows = []
        for dev, size in devices:
            row = self._query_smart(ssh, dev, size)
            rows.append(row)

        self.after(0, lambda r=rows: self._populate(r))

    def _query_smart(self, ssh, dev, size):
        """Run smartctl -A and -i on one device, return a dict."""
        result = {
            "device": dev, "size": size,
            "model": "?", "health": "UNKNOWN",
            "temp": "--", "reallocated": "--",
            "pending": "--", "uncorr": "--", "hours": "--",
            "raw_info": "", "raw_attrs": "",
        }

        # -i: identity (model, serial)
        info_out, _, _ = ssh.run(f"sudo smartctl -i {dev} 2>/dev/null")
        result["raw_info"] = info_out
        for line in info_out.splitlines():
            if line.startswith("Device Model") or line.startswith("Model Family"):
                result["model"] = line.split(":", 1)[-1].strip()[:30]
            elif line.startswith("Model Number"):
                if result["model"] == "?":
                    result["model"] = line.split(":", 1)[-1].strip()[:30]

        # -H: overall health
        health_out, _, _ = ssh.run(f"sudo smartctl -H {dev} 2>/dev/null")
        if "PASSED" in health_out:
            result["health"] = "PASSED"
        elif "FAILED" in health_out:
            result["health"] = "FAILED"
        elif "OK" in health_out:      # NVMe uses "OK"
            result["health"] = "OK"
        else:
            result["health"] = "UNKNOWN"

        # -A: attributes
        attrs_out, _, _ = ssh.run(f"sudo smartctl -A {dev} 2>/dev/null")
        result["raw_attrs"] = attrs_out

        attr_map = {
            "190": "temp", "194": "temp",
            "5":   "reallocated",
            "197": "pending",
            "198": "uncorr",
            "9":   "hours",
        }
        for line in attrs_out.splitlines():
            parts = line.split()
            if len(parts) >= 10:
                attr_id = parts[0]
                raw_val = parts[-1]
                if attr_id in attr_map:
                    key = attr_map[attr_id]
                    if key == "temp":
                        # Raw value for temp can be "39" or "39 (Min/Max ...)"
                        result[key] = raw_val.split()[0]
                    elif key == "hours":
                        try:
                            result[key] = "{:,}".format(int(raw_val))
                        except Exception:
                            result[key] = raw_val
                    else:
                        result[key] = raw_val

        # NVMe: parse differently
        if result["temp"] == "--":
            for line in attrs_out.splitlines():
                if "Temperature:" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "Temperature:" and i + 1 < len(parts):
                            result["temp"] = parts[i + 1]

        return result

    def _populate(self, rows):
        t = self.theme
        self.tree.delete(*self.tree.get_children())

        # Summary cards
        for w in self._summary_frame.winfo_children():
            w.destroy()
        passed = sum(1 for r in rows if r["health"] in ("PASSED", "OK"))
        failed = sum(1 for r in rows if r["health"] == "FAILED")
        unknown = len(rows) - passed - failed

        for label, val, color in [
            ("Drives Found", str(len(rows)),  t.text),
            ("Healthy",      str(passed),     t.status_running),
            ("Failed",       str(failed),     t.status_stopped if failed else t.text_muted),
            ("Unknown",      str(unknown),    t.text_muted),
        ]:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                     font=t.font_small).pack()
            tk.Label(card, text=val, bg=t.card_bg, fg=color,
                     font=("Segoe UI", 18, "bold")).pack()

        for idx, row in enumerate(rows):
            health  = row["health"]
            if health in ("PASSED", "OK"):
                htag = "good"
            elif health == "FAILED":
                htag = "bad"
            else:
                htag = "unknown"

            # Warn on any reallocated/pending/uncorr sectors > 0
            try:
                realloc = int(row["reallocated"])
                pend    = int(row["pending"])
                uncorr  = int(row["uncorr"])
                if realloc > 0 or pend > 0 or uncorr > 0:
                    htag = "warn" if htag == "good" else htag
            except Exception:
                pass

            row_tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", "end", iid=row["device"],
                             values=(
                                 row["device"],
                                 row["model"],
                                 health,
                                 row["temp"],
                                 row["reallocated"],
                                 row["pending"],
                                 row["uncorr"],
                                 row["hours"],
                                 row["size"],
                             ),
                             tags=(row_tag, htag))

        ts = time.strftime("%H:%M:%S")
        self._last_scan_lbl.config(text="Last scan: " + ts)
        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._set_status("{} drive{} scanned".format(
            len(rows), "s" if len(rows) != 1 else ""))

    def _show_detail(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        dev = sel[0]

        def worker():
            ssh = self.controller.ssh
            out, _, _ = ssh.run(f"sudo smartctl -a {dev} 2>/dev/null")
            self.after(0, lambda o=out: self._set_detail(o))

        threading.Thread(target=worker, daemon=True).start()

    def _set_detail(self, text):
        self._detail.config(state="normal")
        self._detail.delete("1.0", "end")
        self._detail.insert("end", text)
        self._detail.config(state="disabled")

    def _set_status(self, text, level="info"):
        colors = {"info": self.theme.text_muted,
                  "error": self.theme.status_stopped,
                  "ok": self.theme.status_running}
        self._status_lbl.config(text=text, fg=colors.get(level, self.theme.text_muted))
