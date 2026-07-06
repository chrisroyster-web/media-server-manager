# ui/restart_sequence_tab.py
"""
Service Restart Sequence tab.

Lets the user define an ordered list of services/containers to restart
in a controlled sequence.  On Run:
  1. Stop everything in REVERSE order (dependents before dependencies).
  2. Start everything in FORWARD order (dependencies before dependents).
  3. Wait the configured per-item delay between each operation.

Config is persisted under config["restart_sequence"] as a list of dicts:
  {"name": str, "type": "service"|"docker"|"compose",
   "identifier": str, "delay": int}
"""

import time
import threading
import shlex
import tkinter as tk
from tkinter import ttk, messagebox


_TYPES = ("service", "docker", "compose")
_TYPE_LABELS = {"service": "systemd", "docker": "Docker", "compose": "Compose"}


class RestartSequenceTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme = t
        self._sequence = []   # list of dicts from config
        self._running = False
        self._build_ui()
        self._load_sequence()

    # ──────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.surface_dark)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔄  Service Restart Sequence",
                 bg=t.surface_dark, fg=t.text,
                 font=t.font_title, anchor="w").pack(side="left", padx=18, pady=14)

        self._run_btn = tk.Button(
            hdr, text="▶  Run Sequence",
            command=self._run_sequence,
            bg=t.status_running, fg="#ffffff",
            bd=0, relief="flat", font=t.font_small,
            padx=14, pady=4, cursor="hand2",
        )
        self._run_btn.pack(side="right", padx=(0, 14), pady=10)

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        note = tk.Frame(self, bg=t.surface, padx=18, pady=7)
        note.pack(fill="x")
        tk.Label(note,
                 text="Services stop in reverse order, then start in forward order. "
                      "Configure the delay (seconds) each item waits before the next step begins.",
                 bg=t.surface, fg=t.text_muted,
                 font=t.font_small, anchor="w").pack(side="left")
        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # Body — list (left) + add panel (right)
        body = tk.Frame(self, bg=t.bg)
        body.pack(fill="both", expand=True)

        # ── Left: sequence list ───────────────────────────────────────────
        left = tk.Frame(body, bg=t.bg)
        left.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=14)

        tk.Label(left, text="SEQUENCE",
                 bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 6))

        tree_wrap = tk.Frame(left, bg=t.card_border, padx=1, pady=1)
        tree_wrap.pack(fill="both", expand=True)

        tree_sb = ttk.Scrollbar(tree_wrap, orient="vertical")
        self._tree = ttk.Treeview(
            tree_wrap,
            columns=("order", "name", "type", "identifier", "delay"),
            show="headings",
            selectmode="browse",
            yscrollcommand=tree_sb.set,
        )
        tree_sb.configure(command=self._tree.yview)
        for col, txt, w, anc in [
            ("order",      "#",          40,  "center"),
            ("name",       "Name",       160, "w"),
            ("type",       "Type",       90,  "center"),
            ("identifier", "Identifier", 160, "w"),
            ("delay",      "Delay (s)",  80,  "center"),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor=anc)
        tree_sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Sequence controls
        ctrl = tk.Frame(left, bg=t.bg)
        ctrl.pack(fill="x", pady=(8, 0))

        self._up_btn = tk.Button(
            ctrl, text="↑  Up",
            command=self._move_up,
            bg=t.surface_light, fg=t.text,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=4, cursor="hand2", state="disabled",
        )
        self._up_btn.pack(side="left", padx=(0, 4))

        self._down_btn = tk.Button(
            ctrl, text="↓  Down",
            command=self._move_down,
            bg=t.surface_light, fg=t.text,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=4, cursor="hand2", state="disabled",
        )
        self._down_btn.pack(side="left", padx=(0, 4))

        self._remove_btn = tk.Button(
            ctrl, text="✕  Remove",
            command=self._remove_selected,
            bg=t.surface_dark, fg=t.text_dim,
            bd=0, relief="flat", font=t.font_small,
            padx=10, pady=4, cursor="hand2", state="disabled",
        )
        self._remove_btn.pack(side="left")

        # ── Right: add panel ──────────────────────────────────────────────
        sep = tk.Frame(body, bg=t.card_border, width=1)
        sep.pack(side="left", fill="y", pady=14)

        right = tk.Frame(body, bg=t.bg, width=260)
        right.pack(side="left", fill="y", padx=(12, 16), pady=14)
        right.pack_propagate(False)

        tk.Label(right, text="ADD ITEM",
                 bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 10))

        def _field(label, widget_fn):
            row = tk.Frame(right, bg=t.bg)
            row.pack(fill="x", pady=(0, 8))
            tk.Label(row, text=label,
                     bg=t.bg, fg=t.text_dim,
                     font=t.font_small, width=10, anchor="w").pack(side="left")
            w = widget_fn(row)
            w.pack(side="left", fill="x", expand=True)
            return w

        # Type
        self._type_var = tk.StringVar(value="service")
        type_row = tk.Frame(right, bg=t.bg)
        type_row.pack(fill="x", pady=(0, 8))
        tk.Label(type_row, text="Type",
                 bg=t.bg, fg=t.text_dim,
                 font=t.font_small, width=10, anchor="w").pack(side="left")
        type_cb = ttk.Combobox(type_row, textvariable=self._type_var,
                               values=list(_TYPES), state="readonly", width=12)
        type_cb.pack(side="left")

        # Name
        self._name_var = tk.StringVar()
        _field("Name", lambda p: tk.Entry(
            p, textvariable=self._name_var,
            bg=t.surface_dark, fg=t.text,
            insertbackground=t.blue,
            relief="flat", bd=4))

        # Identifier
        self._id_var = tk.StringVar()
        id_entry = _field("Identifier", lambda p: tk.Entry(
            p, textvariable=self._id_var,
            bg=t.surface_dark, fg=t.text,
            insertbackground=t.blue,
            relief="flat", bd=4))

        tk.Label(right,
                 text="systemd unit name, container name,\nor compose project name",
                 bg=t.bg, fg=t.text_dim, font=("Segoe UI", 8),
                 anchor="w", justify="left").pack(anchor="w", pady=(0, 8))

        # Delay
        self._delay_var = tk.StringVar(value="3")
        delay_row = tk.Frame(right, bg=t.bg)
        delay_row.pack(fill="x", pady=(0, 16))
        tk.Label(delay_row, text="Delay (s)",
                 bg=t.bg, fg=t.text_dim,
                 font=t.font_small, width=10, anchor="w").pack(side="left")
        tk.Entry(delay_row, textvariable=self._delay_var,
                 bg=t.surface_dark, fg=t.text,
                 insertbackground=t.blue,
                 relief="flat", bd=4, width=6).pack(side="left")

        self._add_btn = tk.Button(
            right, text="+ Add to Sequence",
            command=self._add_item,
            bg=t.blue, fg="#ffffff",
            bd=0, relief="flat", font=t.font_small,
            padx=12, pady=5, cursor="hand2",
        )
        self._add_btn.pack(fill="x")

        # ── Console ───────────────────────────────────────────────────────
        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")
        con_outer = tk.Frame(self, bg=t.surface_dark)
        con_outer.pack(fill="x", side="bottom")
        con_outer.pack_propagate(False)
        con_outer.configure(height=160)

        con_hdr = tk.Frame(con_outer, bg=t.surface_dark, padx=14, pady=5)
        con_hdr.pack(fill="x")
        tk.Label(con_hdr, text="OUTPUT",
                 bg=t.surface_dark, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(con_hdr, text="Clear",
                  command=self._clear_log,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small,
                  cursor="hand2").pack(side="right")

        con_sb = ttk.Scrollbar(con_outer, orient="vertical")
        self._console = tk.Text(
            con_outer,
            bg=t.surface_dark, fg=t.text,
            font=t.font_mono, bd=0, relief="flat",
            state="disabled", wrap="word",
            yscrollcommand=con_sb.set,
        )
        con_sb.configure(command=self._console.yview)
        con_sb.pack(side="right", fill="y")
        self._console.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        self._console.tag_configure("cmd",     foreground=t.cyan)
        self._console.tag_configure("ok",      foreground=t.status_running)
        self._console.tag_configure("error",   foreground=t.status_stopped)
        self._console.tag_configure("warn",    foreground=t.yellow)
        self._console.tag_configure("section", foreground=t.blue,
                                    font=("Segoe UI Semibold", 9))

    # ──────────────────────────────────────────────────────────────────────
    # CONFIG PERSISTENCE
    # ──────────────────────────────────────────────────────────────────────

    def _load_sequence(self):
        self._sequence = self.controller.config_manager.get(
            "restart_sequence", []) or []
        self._refresh_tree()

    def _save_sequence(self):
        self.controller.config_manager.set("restart_sequence", self._sequence)

    # ──────────────────────────────────────────────────────────────────────
    # TREE MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_tree(self):
        for row in self._tree.get_children():
            self._tree.delete(row)
        for i, item in enumerate(self._sequence, start=1):
            self._tree.insert("", "end", iid=str(i - 1), values=(
                i,
                item.get("name", ""),
                _TYPE_LABELS.get(item.get("type", "service"), item.get("type", "")),
                item.get("identifier", ""),
                item.get("delay", 3),
            ))
        self._set_ctrl_state(False)

    def _on_select(self, _event):
        sel = self._tree.selection()
        self._set_ctrl_state(bool(sel))

    def _set_ctrl_state(self, on):
        t = self.theme
        if on:
            self._up_btn.config(state="normal",    bg=t.surface_light, fg=t.text)
            self._down_btn.config(state="normal",   bg=t.surface_light, fg=t.text)
            self._remove_btn.config(state="normal", bg=t.status_stopped, fg="#ffffff")
        else:
            self._up_btn.config(state="disabled",    bg=t.surface_dark, fg=t.text_dim)
            self._down_btn.config(state="disabled",  bg=t.surface_dark, fg=t.text_dim)
            self._remove_btn.config(state="disabled", bg=t.surface_dark, fg=t.text_dim)

    def _selected_index(self):
        sel = self._tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        self._sequence[idx - 1], self._sequence[idx] = (
            self._sequence[idx], self._sequence[idx - 1])
        self._save_sequence()
        self._refresh_tree()
        self._tree.selection_set(str(idx - 1))
        self._set_ctrl_state(True)

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._sequence) - 1:
            return
        self._sequence[idx], self._sequence[idx + 1] = (
            self._sequence[idx + 1], self._sequence[idx])
        self._save_sequence()
        self._refresh_tree()
        self._tree.selection_set(str(idx + 1))
        self._set_ctrl_state(True)

    def _remove_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        self._sequence.pop(idx)
        self._save_sequence()
        self._refresh_tree()

    def _add_item(self):
        name = self._name_var.get().strip()
        identifier = self._id_var.get().strip()
        if not name or not identifier:
            self._log("  ⚠  Name and Identifier are required.\n", "warn")
            return
        try:
            delay = max(0, int(self._delay_var.get()))
        except ValueError:
            delay = 3

        self._sequence.append({
            "name":       name,
            "type":       self._type_var.get(),
            "identifier": identifier,
            "delay":      delay,
        })
        self._save_sequence()
        self._refresh_tree()
        self._name_var.set("")
        self._id_var.set("")

    # ──────────────────────────────────────────────────────────────────────
    # RUN SEQUENCE
    # ──────────────────────────────────────────────────────────────────────

    def _run_sequence(self):
        if self._running:
            return
        if not self.controller.ssh.connected:
            self._log("✗  Not connected.\n", "error")
            return
        if not self._sequence:
            self._log("  ⚠  Sequence is empty. Add items first.\n", "warn")
            return

        names = ", ".join(item["name"] for item in self._sequence)
        if not messagebox.askyesno(
                "Run Restart Sequence",
                "This will stop and restart {} item(s) in order:\n\n{}\n\n"
                "Continue?".format(len(self._sequence), names),
                parent=self):
            return

        self._running = True
        self._run_btn.config(state="disabled", text="Running…",
                             bg=self.theme.surface_dark, fg=self.theme.text_dim)
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self):
        seq = list(self._sequence)
        ssh = self.controller.ssh

        self._log("\n── Stop phase (reverse order) ────────────────────────\n", "section")
        for item in reversed(seq):
            self._stop_item(ssh, item)
            delay = item.get("delay", 3)
            if delay > 0:
                self._log(f"  ⏳ waiting {delay}s…\n")
                time.sleep(delay)

        self._log("\n── Start phase (forward order) ───────────────────────\n", "section")
        for item in seq:
            self._start_item(ssh, item)
            delay = item.get("delay", 3)
            if delay > 0:
                self._log(f"  ⏳ waiting {delay}s…\n")
                time.sleep(delay)

        self._log("\n── Sequence complete ──────────────────────────────────\n", "section")
        self._running = False
        t = self.theme
        self.after(0, lambda: self._run_btn.config(
            state="normal", text="▶  Run Sequence",
            bg=t.status_running, fg="#ffffff"))

    def _stop_item(self, ssh, item):
        itype = item.get("type", "service")
        name  = item.get("name", item.get("identifier", "?"))
        ident = item.get("identifier", "")

        q = shlex.quote(ident)
        if itype == "service":
            cmd = f"systemctl stop {q}"
        elif itype == "docker":
            cmd = f"docker stop {q}"
        else:  # compose
            cmd = f"docker compose -p {q} down"

        self._log(f"  STOP  {name}  →  $ {cmd}\n", "cmd")
        out, err, code = ssh.run_sudo(cmd) if itype == "service" else ssh.run(f"{cmd} 2>&1")
        self.controller.audit_log(
            "restart_sequence.stop", name, detail=(err or out or "").strip()[:200],
            result="ok" if code == 0 else "fail")
        if code == 0:
            self._log(f"  ✓  {name} stopped\n", "ok")
        else:
            self._log(f"  ✗  {name}: {(err or out).strip()}\n", "error")

    def _start_item(self, ssh, item):
        itype = item.get("type", "service")
        name  = item.get("name", item.get("identifier", "?"))
        ident = item.get("identifier", "")

        q = shlex.quote(ident)
        if itype == "service":
            cmd = f"systemctl start {q}"
        elif itype == "docker":
            cmd = f"docker start {q}"
        else:  # compose
            cmd = f"docker compose -p {q} up -d"

        self._log(f"  START {name}  →  $ {cmd}\n", "cmd")
        out, err, code = ssh.run_sudo(cmd) if itype == "service" else ssh.run(f"{cmd} 2>&1")
        self.controller.audit_log(
            "restart_sequence.start", name, detail=(err or out or "").strip()[:200],
            result="ok" if code == 0 else "fail")
        if code == 0:
            self._log(f"  ✓  {name} started\n", "ok")
        else:
            self._log(f"  ✗  {name}: {(err or out).strip()}\n", "error")

    # ──────────────────────────────────────────────────────────────────────
    # CONSOLE
    # ──────────────────────────────────────────────────────────────────────

    def _log(self, text, tag=None):
        def _do():
            self._console.configure(state="normal")
            if tag:
                self._console.insert("end", text, tag)
            else:
                self._console.insert("end", text)
            self._console.see("end")
            self._console.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")

    # ──────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ──────────────────────────────────────────────────────────────────────

    def on_show(self):
        self._load_sequence()
