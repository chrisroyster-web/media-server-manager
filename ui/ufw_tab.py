# ui/ufw_tab.py
"""UFW firewall manager — view rules, add/delete, enable/disable."""

import re
import shlex
import threading
import tkinter as tk
from tkinter import ttk, messagebox


class UFWTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._rules     = []   # list of (num, to, action, from_)
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="UFW FIREWALL", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right")

        # Status row
        status_row = tk.Frame(self, bg=t.bg)
        status_row.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(status_row, text="Status:", bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left")
        self._ufw_state = tk.Label(status_row, text="—", bg=t.bg,
                                    fg=t.text_muted, font=t.font_small)
        self._ufw_state.pack(side="left", padx=(6, 16))
        self._enable_btn = tk.Button(status_row, text="Enable UFW",
                                      command=lambda: self._toggle("enable"))
        t.style_button(self._enable_btn)
        self._enable_btn.pack(side="left", padx=(0, 6))
        self._disable_btn = tk.Button(status_row, text="Disable UFW",
                                       command=lambda: self._toggle("disable"))
        t.style_button(self._disable_btn)
        self._disable_btn.pack(side="left")

        # Toolbar
        toolbar = tk.Frame(self, bg=t.bg)
        toolbar.pack(fill="x", padx=16, pady=(0, 6))
        add_btn = tk.Button(toolbar, text="＋ Add Rule", command=self._add_rule)
        t.style_button(add_btn)
        add_btn.pack(side="left")
        self._del_btn = tk.Button(toolbar, text="✕ Delete Rule",
                                   command=self._delete_rule, state="disabled")
        t.style_button(self._del_btn)
        self._del_btn.pack(side="left", padx=(6, 0))

        # Treeview
        cols   = ("num", "to", "action", "from_")
        hdgs   = ("#", "To (port/service)", "Action", "From")
        widths = (40, 280, 90, 280)
        stretches = {"to", "from_"}

        tree_fr = tk.Frame(self, bg=t.bg)
        tree_fr.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("UFW.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("UFW.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat")
        style.map("UFW.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings",
                                   style="UFW.Treeview", selectmode="browse")
        for col, hdr_txt, w in zip(cols, hdgs, widths):
            self._tree.heading(col, text=hdr_txt, anchor="w")
            self._tree.column(col, width=w, minwidth=30, anchor="w",
                              stretch=(col in stretches))

        self._tree.tag_configure("allow", foreground=t.status_running)
        self._tree.tag_configure("deny",  foreground=t.status_stopped_text)
        self._tree.tag_configure("limit", foreground=t.yellow)

        vsb = ttk.Scrollbar(tree_fr, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Console output
        con_fr = tk.Frame(self, bg=t.surface_dark)
        con_fr.pack(fill="x", padx=16, pady=(0, 4))
        con_hdr = tk.Frame(con_fr, bg=t.surface_dark)
        con_hdr.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(con_hdr, text="OUTPUT", bg=t.surface_dark, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(con_hdr, text="Clear", command=self._clear_log,
                  bg=t.surface_dark, fg=t.text_muted,
                  bd=0, relief="flat", font=t.font_small).pack(side="right")
        self._console = tk.Text(con_fr, bg=t.surface_dark, fg=t.text,
                                font=t.font_mono, height=5, bd=0,
                                relief="flat", state="disabled", wrap="word")
        self._console.tag_configure("ok",  foreground=t.status_running)
        self._console.tag_configure("err", foreground=t.status_stopped_text)
        self._console.tag_configure("cmd", foreground=t.cyan)
        self._console.pack(fill="x", padx=10, pady=(0, 6))

        # Status bar
        self._status = tk.Label(self, text="Connect to server to view firewall rules",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped_text)
            return
        self._status.config(text="Loading…", bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            out, err, code = ssh.run_sudo("ufw status numbered 2>/dev/null")
            if code != 0:
                self.after(0, lambda: self._status.config(
                    text="ufw not available: {}".format(err or out),
                    bg=self.theme.surface_dark, fg=self.theme.yellow))
                return
            rules, active = self._parse(out)
            self.after(0, lambda: self._populate(rules, active))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Error: {}".format(msg),
                bg=self.theme.surface_dark, fg=self.theme.status_stopped_text))
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # PARSE
    # -----------------------------------------------------------------------
    def _parse(self, output):
        active = False
        rules  = []
        for line in output.splitlines():
            if "Status: active" in line:
                active = True
            m = re.match(
                r"\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)\s+(.*)",
                line, re.IGNORECASE)
            if m:
                num    = m.group(1)
                to_    = m.group(2).strip()
                action = m.group(3).strip().upper()
                from_  = m.group(4).strip() or "Anywhere"
                rules.append((num, to_, action, from_))
        return rules, active

    # -----------------------------------------------------------------------
    # POPULATE
    # -----------------------------------------------------------------------
    def _populate(self, rules, active):
        t = self.theme
        self._rules = rules
        state_text  = "Active" if active else "Inactive"
        state_color = t.status_running if active else t.status_stopped
        self._ufw_state.config(text=state_text, fg=state_color)
        self._enable_btn.config(state="normal" if not active else "disabled")
        self._disable_btn.config(state="normal" if active else "disabled")

        self._tree.delete(*self._tree.get_children())
        for num, to_, action, from_ in rules:
            tag = action.lower() if action.lower() in ("allow", "deny", "limit") else ""
            self._tree.insert("", "end", iid=num, tags=(tag,), values=(
                num, to_, action, from_))

        self._status.config(
            text="UFW {}  |  {} rule{}".format(
                state_text, len(rules), "s" if len(rules) != 1 else ""),
            bg=t.surface_dark, fg=t.text_muted)

    # -----------------------------------------------------------------------
    # ACTIONS
    # -----------------------------------------------------------------------
    def _on_select(self, _=None):
        self._del_btn.config(
            state="normal" if self._tree.selection() else "disabled")

    def _toggle(self, action):
        word = "enable" if action == "enable" else "disable"
        if not messagebox.askyesno("UFW", "{}  UFW?".format(word.capitalize()),
                                   parent=self):
            return
        def _run():
            self._log("$ ufw --force {}\n".format(word), "cmd")
            out, err, code = self.controller.ssh.run_sudo(
                "ufw --force {}".format(word))
            self.controller.audit_log(
                "ufw.{}".format(word), "(firewall)",
                detail=(err or out or "").strip()[:200],
                result="ok" if code == 0 else "fail")
            if code == 0:
                self._log("✓ {}\n".format(out.strip() or word.capitalize()+"d"), "ok")
                self.after(600, self.refresh)
            else:
                self._log("✗ {}\n".format(err or out), "err")
        threading.Thread(target=_run, daemon=True).start()

    def _delete_rule(self):
        sel = self._tree.selection()
        if not sel:
            return
        num = sel[0]
        if not messagebox.askyesno("Delete Rule",
                                   "Delete rule #{}?".format(num), parent=self):
            return
        def _run():
            self._log("$ ufw --force delete {}\n".format(num), "cmd")
            out, err, code = self.controller.ssh.run_sudo(
                "ufw --force delete {}".format(num))
            self.controller.audit_log(
                "ufw.delete_rule", "rule #{}".format(num),
                detail=(err or out or "").strip()[:200],
                result="ok" if code == 0 else "fail")
            if code == 0:
                self._log("✓ Rule {} deleted\n".format(num), "ok")
                self.after(600, self.refresh)
            else:
                self._log("✗ {}\n".format(err or out), "err")
        threading.Thread(target=_run, daemon=True).start()

    def _add_rule(self):
        dlg = _AddRuleDialog(self, self.theme)
        self.wait_window(dlg)
        if not dlg.result:
            return
        cmd = dlg.result
        def _run():
            self._log("$ {}\n".format(cmd), "cmd")
            out, err, code = self.controller.ssh.run_sudo(cmd)
            self.controller.audit_log(
                "ufw.add_rule", cmd,
                detail=(err or out or "").strip()[:200],
                result="ok" if code == 0 else "fail")
            if code == 0:
                self._log("✓ {}\n".format(out.strip() or "Rule added"), "ok")
                self.after(600, self.refresh)
            else:
                self._log("✗ {}\n".format(err or out), "err")
        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------------
    # LOG
    # -----------------------------------------------------------------------
    def _log(self, text, tag=None):
        def _do():
            self._console.config(state="normal")
            if tag:
                self._console.insert("end", text, tag)
            else:
                self._console.insert("end", text)
            self._console.see("end")
            self._console.config(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        self._console.config(state="disabled")

    def on_show(self):
        if self.controller.ssh.connected:
            self.refresh()


# ---------------------------------------------------------------------------
# Add Rule Dialog
# ---------------------------------------------------------------------------
class _AddRuleDialog(tk.Toplevel):

    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme  = theme
        self.result = None
        self.title("Add UFW Rule")
        self.resizable(False, False)
        self.grab_set()
        t = theme
        self.configure(bg=t.bg)
        self._build(t)
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry("+{}+{}".format(x, y))

    def _build(self, t):
        pad = dict(padx=14, pady=6)
        f = tk.Frame(self, bg=t.bg, padx=20, pady=16)
        f.pack()

        tk.Label(f, text="Action:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w", **pad)
        self._action = tk.StringVar(value="allow")
        for col, val in enumerate(("allow", "deny", "limit")):
            tk.Radiobutton(f, text=val, variable=self._action, value=val,
                           bg=t.bg, fg=t.text, selectcolor=t.bg,
                           activebackground=t.bg, font=t.font_regular
                           ).grid(row=0, column=col+1, sticky="w", pady=6)

        tk.Label(f, text="Direction:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=1, column=0, sticky="w", **pad)
        self._dir = tk.StringVar(value="in")
        for col, val in enumerate(("in", "out")):
            tk.Radiobutton(f, text=val, variable=self._dir, value=val,
                           bg=t.bg, fg=t.text, selectcolor=t.bg,
                           activebackground=t.bg, font=t.font_regular
                           ).grid(row=1, column=col+1, sticky="w", pady=6)

        tk.Label(f, text="Proto:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=2, column=0, sticky="w", **pad)
        self._proto = tk.StringVar(value="tcp")
        for col, val in enumerate(("tcp", "udp", "any")):
            tk.Radiobutton(f, text=val, variable=self._proto, value=val,
                           bg=t.bg, fg=t.text, selectcolor=t.bg,
                           activebackground=t.bg, font=t.font_regular
                           ).grid(row=2, column=col+1, sticky="w", pady=6)

        tk.Label(f, text="Port:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=3, column=0, sticky="w", **pad)
        self._port = tk.StringVar()
        e = tk.Entry(f, textvariable=self._port, font=t.font_regular, width=18)
        t.style_entry(e)
        e.grid(row=3, column=1, columnspan=3, sticky="ew", **pad)
        tk.Label(f, text="e.g. 80, 443, 8000:9000, ssh",
                 bg=t.bg, fg=t.text_muted, font=t.font_small
                 ).grid(row=4, column=1, columnspan=3, sticky="w", padx=14)

        tk.Label(f, text="From IP:", bg=t.bg, fg=t.text,
                 font=t.font_regular).grid(row=5, column=0, sticky="w", **pad)
        self._from_ip = tk.StringVar(value="any")
        e2 = tk.Entry(f, textvariable=self._from_ip, font=t.font_regular, width=18)
        t.style_entry(e2)
        e2.grid(row=5, column=1, columnspan=3, sticky="ew", **pad)
        tk.Label(f, text="leave 'any' for all sources",
                 bg=t.bg, fg=t.text_muted, font=t.font_small
                 ).grid(row=6, column=1, columnspan=3, sticky="w", padx=14)

        btn_row = tk.Frame(f, bg=t.bg)
        btn_row.grid(row=7, column=0, columnspan=4, pady=(14, 0))
        ok = tk.Button(btn_row, text="Add Rule", command=self._ok)
        t.style_button(ok)
        ok.pack(side="left", padx=(0, 8))
        cancel = tk.Button(btn_row, text="Cancel", command=self.destroy)
        t.style_button(cancel)
        cancel.pack(side="left")

    def _ok(self):
        port     = self._port.get().strip()
        from_ip  = self._from_ip.get().strip() or "any"
        action   = self._action.get()
        direction = self._dir.get()
        proto    = self._proto.get()

        if not port:
            messagebox.showwarning("Missing", "Enter a port or service name.", parent=self)
            return

        # Build ufw command — action/direction/proto are radio-button-constrained
        # to fixed literals, but port/from_ip are free-typed, so quote them.
        parts = ["ufw", action, direction]
        if from_ip != "any":
            parts += ["from", shlex.quote(from_ip)]
        parts += ["to", "any"]
        if proto != "any":
            parts += ["proto", proto, "port", shlex.quote(port)]
        else:
            parts += ["port", shlex.quote(port)]
        self.result = " ".join(parts)
        self.destroy()
