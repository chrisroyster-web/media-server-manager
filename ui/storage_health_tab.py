# ui/storage_health_tab.py
"""
Storage Health tab - df -hT with ZFS/Btrfs fallback.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import re
import shlex
import traceback

from ui.refresh_control import RefreshControl


class StorageHealthTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme      = controller.theme
        self._build_ui()

    # =================================================================
    # BUILD UI
    # =================================================================
    def _build_ui(self):
        t = self.theme

        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="STORAGE HEALTH", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "storage_health",
                                  default=60, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._refresh_btn = btn
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        cards_row = tk.Frame(self, bg=t.bg)
        cards_row.pack(fill="x", padx=16, pady=(0, 8))
        self._card_healthy  = self._stat_card(cards_row, "Healthy",  "--", t.status_running)
        self._card_degraded = self._stat_card(cards_row, "Warning",  "--", t.yellow)
        self._card_faulted  = self._stat_card(cards_row, "Critical", "--", t.status_stopped)
        self._card_type     = self._stat_card(cards_row, "Type",     "--", t.text_muted)

        pool_frame = tk.Frame(self, bg=t.bg)
        pool_frame.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(pool_frame, text="Pools / Filesystems", bg=t.bg,
                 fg=t.text_secondary, font=t.font_title).pack(anchor="w", pady=(0, 4))

        style = ttk.Style()
        style.configure("SH.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0, rowheight=26,
                        font=t.font_mono)
        style.configure("SH.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("SH.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("name", "state", "size", "used", "free", "info")
        self._pool_tree = ttk.Treeview(pool_frame, columns=cols,
                                        show="headings", height=8,
                                        style="SH.Treeview")
        for col, w, lbl in [
            ("name",  200, "Mount / Pool"),
            ("state", 100, "State"),
            ("size",   90, "Size"),
            ("used",   90, "Used"),
            ("free",   90, "Free"),
            ("info",  300, "Filesystem / Info"),
        ]:
            self._pool_tree.heading(col, text=lbl, anchor="w")
            self._pool_tree.column(col, width=w, minwidth=60,
                                   anchor="w", stretch=(col in ("name", "info")))
        self._pool_tree.tag_configure("healthy",  foreground=t.status_running)
        self._pool_tree.tag_configure("degraded", foreground=t.yellow)
        self._pool_tree.tag_configure("faulted",  foreground=t.status_stopped)
        self._pool_tree.tag_configure("unknown",  foreground=t.text_muted)
        self._pool_tree.pack(fill="x")
        self._pool_tree.bind("<<TreeviewSelect>>", self._on_select)

        detail_frame = tk.Frame(self, bg=t.bg)
        detail_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tk.Label(detail_frame, text="Detail / Raw Output", bg=t.bg,
                 fg=t.text_secondary, font=t.font_title).pack(anchor="w", pady=(0, 4))
        self._detail = tk.Text(detail_frame, bg=t.surface_dark, fg=t.console_output,
                               font=t.font_mono, state="disabled", relief="flat",
                               padx=8, pady=6, wrap="none")
        sb = tk.Scrollbar(detail_frame, command=self._detail.yview)
        self._detail.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._detail.pack(fill="both", expand=True)

        self._status = tk.Label(self, text="Press Refresh to scan filesystems",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

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

    # =================================================================
    # REFRESH
    # =================================================================
    def refresh(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._set_status("Not connected to SSH", "error")
            return
        self._refresh_btn.config(state="disabled", text="Scanning…")
        self._set_status("Scanning filesystems…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            self._fetch_inner()
        except Exception:
            err = traceback.format_exc()
            self.after(0, lambda e=err: self._populate([], "ERROR:\n" + e, "error"))
        finally:
            self._fetching = False

    def _fetch_inner(self):
        ssh = self.controller.ssh

        probe, _, _ = ssh.run(
            "command -v zpool 2>/dev/null && echo HAS_ZFS || true;"
            "command -v btrfs 2>/dev/null && echo HAS_BTRFS || true")
        has_zfs   = "HAS_ZFS"   in (probe or "")
        has_btrfs = "HAS_BTRFS" in (probe or "")

        pools   = []
        raw_out = ""
        fs_type = "Standard"

        # --- ZFS ---
        if has_zfs:
            fs_type = "ZFS"
            out, _, _ = ssh.run(
                "zpool list -H -o name,health,size,alloc,free 2>/dev/null")
            raw_out += "=== zpool list ===\n" + (out or "") + "\n"
            for line in (out or "").strip().splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    name, health, size, used, free = parts[:5]
                    scrub_out, _, _ = ssh.run(
                        "zpool status {} 2>/dev/null | grep -E 'scrub:|scan:'".format(shlex.quote(name)))
                    scrub_lines = (scrub_out or "").strip().splitlines()
                    scrub = scrub_lines[0].strip() if scrub_lines else "no scrub data"
                    scrub = re.sub(r'^(scrub|scan):\s*', '', scrub)
                    pools.append({"name": name, "state": health,
                                  "size": size, "used": used, "free": free,
                                  "info": scrub, "fs": "zfs"})
            full, _, _ = ssh.run("zpool status -v 2>/dev/null")
            raw_out += "\n=== zpool status -v ===\n" + (full or "")

        # --- Btrfs ---
        if has_btrfs:
            fs_type = ("ZFS + Btrfs" if has_zfs else "Btrfs")
            out, _, _ = ssh.run("sudo btrfs filesystem show 2>/dev/null")
            raw_out += "\n=== btrfs filesystem show ===\n" + (out or "")
            cur = None
            for line in (out or "").splitlines():
                line = line.strip()
                m = re.match(r"Label: (\S+)\s+uuid: ([0-9a-f-]+)", line)
                if m:
                    cur = {"name": m.group(1).strip("'"),
                           "state": "unknown", "size": "--",
                           "used": "--", "free": "--",
                           "info": "btrfs", "fs": "btrfs"}
                    pools.append(cur)
                if cur and re.search(r"Total devices (\d+)", line):
                    cur["state"] = "ONLINE"

        # --- Standard df fallback ---
        # Run if no ZFS/Btrfs, OR if they exist but produced no pools
        # (e.g. btrfs installed but not in use as a filesystem)
        if not pools:
            out, _, _ = ssh.run("df -hT 2>/dev/null")
            raw_out = "=== df -hT raw output ===\n" + (out or "(no output)")

            smart_out, _, _ = ssh.run(
                "for d in $(lsblk -dn -o NAME 2>/dev/null | grep -vE 'loop|sr'); do"
                " echo '--- /dev/'$d' ---';"
                " smartctl -H /dev/$d 2>/dev/null | grep -E 'result|SMART overall';"
                "done")
            if smart_out and smart_out.strip():
                raw_out += "\n\n=== S.M.A.R.T. ===\n" + smart_out

            # df -hT wraps long device names onto the next line.
            # Reconstruct: if a line has fewer than 7 fields, it is a
            # continuation — prepend it to the next line before splitting.
            skip_types = {
                "tmpfs", "devtmpfs", "devpts", "sysfs", "proc",
                "cgroup", "cgroup2", "pstore", "bpf", "tracefs",
                "hugetlbfs", "mqueue", "securityfs", "overlay",
                "squashfs", "efivarfs", "debugfs", "fusectl",
                "configfs", "ramfs", "nsfs", "autofs",
            }
            skip_mounts = set()
            pending = ""
            all_lines = (out or "").splitlines()
            for raw_line in all_lines:
                if raw_line.startswith("Filesystem"):
                    pending = ""
                    continue
                # Join wrapped continuation lines
                combined = (pending + " " + raw_line).strip() if pending else raw_line
                parts = combined.split()
                if len(parts) < 7:
                    # Still incomplete — accumulate more
                    pending = combined
                    continue
                pending = ""
                # df -hT: Filesystem Type Size Used Avail Use% MountedOn
                device = parts[0]
                fstype = parts[1]
                size   = parts[2]
                used   = parts[3]
                avail  = parts[4]
                pct    = parts[5]
                mount  = " ".join(parts[6:])   # handle spaces in mount path
                if fstype.lower() in skip_types:
                    continue
                if mount in skip_mounts:
                    continue
                skip_prefixes = ("/sys", "/proc", "/dev/shm", "/run",
                                 "/snap", "/boot/efi")
                if any(mount.startswith(p) for p in skip_prefixes):
                    continue
                skip_mounts.add(mount)
                try:
                    pct_int = int(pct.rstrip("%"))
                except ValueError:
                    pct_int = 0
                if pct_int >= 95:
                    state = "CRITICAL"
                elif pct_int >= 85:
                    state = "WARNING"
                else:
                    state = "ONLINE"
                pools.append({
                    "name":  mount,
                    "state": state,
                    "size":  size,
                    "used":  used,
                    "free":  avail,
                    "info":  "{} on {} ({} used)".format(fstype, device, pct),
                    "fs":    "df",
                })

            raw_out += "\n\n=== Parsed {} filesystem(s) ===".format(len(pools))
            for p in pools:
                raw_out += "\n  {}  {}  {}".format(p["name"], p["state"], p["info"])

        self.after(0, lambda p=pools, r=raw_out, f=fs_type: self._populate(p, r, f))

    # =================================================================
    # POPULATE
    # =================================================================
    def _populate(self, pools, raw_out, fs_type):
        self._refresh_btn.config(state="normal", text="Refresh")
        self._last_lbl.config(text="Updated {}".format(time.strftime("%H:%M")))

        healthy  = sum(1 for p in pools if p["state"] == "ONLINE")
        degraded = sum(1 for p in pools if p["state"] in ("DEGRADED", "WARNING")
                       or "ERRORS" in str(p.get("state", "")))
        faulted  = sum(1 for p in pools if p["state"] in
                       ("FAULTED", "UNAVAIL", "REMOVED", "CRITICAL"))

        self._card_healthy.config(text=str(healthy))
        self._card_degraded.config(
            text=str(degraded),
            fg=self.theme.yellow if degraded else self.theme.text_muted)
        self._card_faulted.config(
            text=str(faulted),
            fg=self.theme.status_stopped if faulted else self.theme.text_muted)
        self._card_type.config(text=fs_type)

        self._pool_tree.delete(*self._pool_tree.get_children())
        seen_iids = set()
        for p in pools:
            state = p["state"]
            if state == "ONLINE":
                tag = "healthy"
            elif state in ("DEGRADED", "WARNING") or "ERRORS" in state:
                tag = "degraded"
            elif state in ("FAULTED", "UNAVAIL", "REMOVED", "CRITICAL"):
                tag = "faulted"
            else:
                tag = "unknown"
            iid = p["name"]
            while iid in seen_iids:
                iid = iid + "_dup"
            seen_iids.add(iid)
            self._pool_tree.insert("", "end", iid=iid,
                                   values=(p["name"], state, p["size"],
                                           p["used"], p["free"], p["info"]),
                                   tags=(tag,))

        self._set_detail(raw_out or "No output.")

        n = len(pools)
        msg = "{} filesystem{} found".format(n, "s" if n != 1 else "")
        if faulted:
            msg += " -- {} critical".format(faulted)
        elif degraded:
            msg += " -- {} at warning".format(degraded)
        level = "error" if faulted else ("warn" if degraded else "ok")
        self._set_status(msg, level)
        self._rc.schedule()

    def _on_select(self, _event=None):
        sel = self._pool_tree.selection()
        if not sel:
            return
        name = sel[0].replace("_dup", "")
        if not self.controller.ssh.connected:
            return

        def _fetch_detail():
            ssh = self.controller.ssh
            q = shlex.quote(name)
            out, _, _ = ssh.run(
                "df -hT {0} 2>/dev/null; "
                "echo; "
                "findmnt {0} 2>/dev/null || true; "
                "echo; "
                "src=$(findmnt -n -o SOURCE {0} 2>/dev/null | head -1); "
                "if [ -n \"$src\" ]; then "
                "  sudo smartctl -a \"$src\" 2>/dev/null | head -50 || true; "
                "fi".format(q))
            self.after(0, lambda o=out: self._set_detail(o or "No detail available."))

        threading.Thread(target=_fetch_detail, daemon=True).start()

    # =================================================================
    # HELPERS
    # =================================================================
    def _set_detail(self, text):
        self._detail.config(state="normal")
        self._detail.delete("1.0", "end")
        self._detail.insert("end", text.strip())
        self._detail.config(state="disabled")

    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "ok": t.status_running, "warn": t.yellow, "error": t.status_stopped}
        self._status.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
