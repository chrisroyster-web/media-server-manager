# ui/sessions_tab.py
"""
Active SSH / login session viewer.
Shows output of `who` and `w`, lets you send SIGHUP to a pts to kick a user.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time


class SessionsTab(tk.Frame):

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
        tk.Label(hdr, text="ACTIVE SESSIONS",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._refresh_btn = tk.Button(hdr, text="⟳ Refresh", command=self._refresh)
        t.style_button(self._refresh_btn)
        self._refresh_btn.pack(side="right")
        self._kick_btn = tk.Button(hdr, text="✕  Kick Session", command=self._kick)
        t.style_button(self._kick_btn)
        self._kick_btn.configure(fg=t.status_stopped)
        self._kick_btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Summary cards
        self._summary_frame = tk.Frame(self, bg=t.bg)
        self._summary_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Sessions treeview
        tree_frame = tk.Frame(self, bg=t.bg)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Sess.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=28, font=t.font_mono)
        style.configure("Sess.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("Sess.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("user", "tty", "from", "login", "idle", "cpu", "what")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  style="Sess.Treeview", selectmode="browse")

        headings = [
            ("user",  "User",       110, "w"),
            ("tty",   "TTY",         80, "w"),
            ("from",  "From",       180, "w"),
            ("login", "Login",      130, "w"),
            ("idle",  "Idle",        80, "e"),
            ("cpu",   "CPU",         60, "e"),
            ("what",  "Command",    200, "w"),
        ]
        for col, text, width, anchor in headings:
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=40,
                             anchor=anchor, stretch=(col in ("from", "what")))

        self.tree.tag_configure("odd",   background=t.surface_dark)
        self.tree.tag_configure("even",  background=t.card_bg)
        self.tree.tag_configure("self",  foreground=t.cyan)   # our own session
        self.tree.tag_configure("other", foreground=t.text)
        self.tree.tag_configure("root",  foreground=t.status_stopped)

        vsb = tk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # Last logins section
        tk.Label(self, text="Recent Logins  (last 10)",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(
            anchor="w", padx=16, pady=(8, 2))

        last_frame = tk.Frame(self, bg=t.bg)
        last_frame.pack(fill="x", padx=16, pady=(0, 4))

        style.configure("Last.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("Last.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("Last.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        last_cols = ("user", "tty", "from", "datetime", "duration")
        self.last_tree = ttk.Treeview(last_frame, columns=last_cols, show="headings",
                                       style="Last.Treeview", height=6,
                                       selectmode="none")
        last_hdgs = [
            ("user",     "User",     110, "w"),
            ("tty",      "TTY",       80, "w"),
            ("from",     "From",     180, "w"),
            ("datetime", "Date/Time",180, "w"),
            ("duration", "Duration", 100, "e"),
        ]
        for col, text, width, anchor in last_hdgs:
            self.last_tree.heading(col, text=text, anchor=anchor)
            self.last_tree.column(col, width=width, minwidth=40,
                                   anchor=anchor, stretch=(col in ("from",)))
        self.last_tree.tag_configure("odd",  background=t.surface_dark)
        self.last_tree.tag_configure("even", background=t.card_bg)

        last_vsb = tk.Scrollbar(last_frame, orient="vertical",
                                 command=self.last_tree.yview)
        self.last_tree.configure(yscrollcommand=last_vsb.set)
        last_vsb.pack(side="right", fill="y")
        self.last_tree.pack(fill="x")

        # Status bar
        self._status_lbl = tk.Label(self, text="Not connected",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(4, 8))

    # =========================================================
    # REFRESH
    # =========================================================
    def _refresh(self):
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._refresh_btn.config(state="disabled", text="Loading…")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        ssh = self.controller.ssh

        # w -h: current sessions with idle/cpu/command
        w_out, _, _ = ssh.run("w -h 2>/dev/null")
        sessions = []
        for line in w_out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 7:
                sessions.append({
                    "user":  parts[0],
                    "tty":   parts[1],
                    "from":  parts[2],
                    "login": parts[3],
                    "idle":  parts[4],
                    "cpu":   parts[5],
                    "what":  " ".join(parts[7:]) if len(parts) > 7 else parts[6],
                })

        # last -n 10: recent logins
        last_out, _, _ = ssh.run("last -n 10 --time-format iso 2>/dev/null || last -n 10 2>/dev/null")
        recents = []
        for line in last_out.strip().splitlines():
            if not line or line.startswith("wtmp") or line.startswith("reboot"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                user     = parts[0]
                tty      = parts[1]
                frm      = parts[2] if not parts[2].startswith("-") else "--"
                dt       = parts[3] if len(parts) > 3 else "--"
                duration = parts[-1] if "(" in parts[-1] else "--"
                recents.append((user, tty, frm, dt, duration))

        self.after(0, lambda s=sessions, r=recents: self._populate(s, r))

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, sessions, recents):
        t = self.theme
        self.tree.delete(*self.tree.get_children())

        for idx, s in enumerate(sessions):
            row_tag = "even" if idx % 2 == 0 else "odd"
            if s["user"] == "root":
                user_tag = "root"
            else:
                user_tag = "other"
            self.tree.insert("", "end",
                             values=(s["user"], s["tty"], s["from"],
                                     s["login"], s["idle"], s["cpu"], s["what"]),
                             tags=(row_tag, user_tag),
                             iid="{}_{}".format(s["user"], s["tty"]))

        self.last_tree.delete(*self.last_tree.get_children())
        for idx, (user, tty, frm, dt, dur) in enumerate(recents):
            tag = "even" if idx % 2 == 0 else "odd"
            self.last_tree.insert("", "end",
                                   values=(user, tty, frm, dt, dur),
                                   tags=(tag,))

        # Summary cards
        for w in self._summary_frame.winfo_children():
            w.destroy()
        root_sessions = sum(1 for s in sessions if s["user"] == "root")
        for label, val, color in [
            ("Active Sessions", str(len(sessions)), t.cyan if sessions else t.text_muted),
            ("Root Sessions",   str(root_sessions), t.status_stopped if root_sessions else t.text_muted),
            ("Unique Users",    str(len({s["user"] for s in sessions})), t.text),
        ]:
            card = tk.Frame(self._summary_frame, bg=t.card_bg,
                            highlightbackground=t.card_border, highlightthickness=1)
            card.pack(side="left", padx=(0, 8), pady=4, ipadx=16, ipady=8)
            tk.Label(card, text=label, bg=t.card_bg,
                     fg=t.text_muted, font=t.font_small).pack()
            tk.Label(card, text=val, bg=t.card_bg,
                     fg=color, font=("Segoe UI", 18, "bold")).pack()

        self._refresh_btn.config(state="normal", text="⟳ Refresh")
        self._last_lbl.config(text="Updated: " + time.strftime("%H:%M:%S"))
        self._set_status("{} active session{}".format(
            len(sessions), "s" if len(sessions) != 1 else ""))

    # =========================================================
    # KICK SESSION
    # =========================================================
    def _kick(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Kick Session", "Select a session first.")
            return
        iid    = sel[0]
        values = self.tree.item(iid, "values")
        user, tty = values[0], values[1]

        if not messagebox.askyesno(
                "Kick Session",
                "Disconnect {} on {}?\n\nThis will send SIGHUP to their terminal.".format(user, tty),
                parent=self):
            return

        def worker():
            ssh = self.controller.ssh
            # pkill -SIGHUP -t pts/N  (works for pts sessions)
            out, err, code = ssh.run(
                "sudo pkill -SIGHUP -t {} 2>&1".format(tty))
            def _done(code=code):
                if code == 0:
                    self._set_status("Kicked {} on {}".format(user, tty), "ok")
                else:
                    self._set_status("Failed to kick {} on {}: {}".format(
                        user, tty, err.strip()), "error")
                self._refresh()
            self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, text, level="info"):
        colors = {"info": self.theme.text_muted,
                  "error": self.theme.status_stopped,
                  "ok": self.theme.status_running}
        self._status_lbl.config(text=text, fg=colors.get(level, self.theme.text_muted))
