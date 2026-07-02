# ui/sessions_tab.py
"""
Active SSH / login session viewer.
Shows output of `who` and `w`, lets you send SIGHUP to a pts to kick a user.
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time


_SKIP_USERS  = {"wtmp", "btmp", "reboot", "shutdown", "runlevel", "BEGIN"}
_DAY_ABBREVS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

# Matches login-time tokens produced by `w`: "12:34", "12:34:56", or "Mon12"
_LOGIN_TIME_RE = re.compile(r'^(\d{1,2}:\d{2}(:\d{2})?|[A-Z][a-z]{2}\d{1,2})$')


def _looks_like_from_field(s):
    """Return True if token looks like a host/IP/display (not a date component)."""
    if not s:
        return False
    if s in _DAY_ABBREVS:
        return False
    # ISO date start: 2024-... or a bare month name like "Jan"
    if len(s) >= 4 and s[0].isdigit() and "-" in s:
        return False
    if s in {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}:
        return False
    return True


def _parse_w_line(parts):
    """
    Parse one line from `w -h` into a session dict.
    Handles missing FROM column (empty field lost by whitespace split).
    `w` columns: USER TTY [FROM] LOGIN@ IDLE JCPU PCPU WHAT
    When FROM is absent the remaining columns shift left by one.
    """
    if len(parts) < 5:
        return None
    user = parts[0]
    tty  = parts[1]

    # If parts[2] looks like a login time rather than a host/IP, FROM is empty
    if _LOGIN_TIME_RE.match(parts[2]):
        frm   = "local"
        login = parts[2]
        idle  = parts[3] if len(parts) > 3 else "?"
        cpu   = parts[4] if len(parts) > 4 else "?"
        what  = " ".join(parts[6:]) if len(parts) > 6 else (parts[5] if len(parts) > 5 else "?")
    else:
        frm   = parts[2]
        login = parts[3] if len(parts) > 3 else "?"
        idle  = parts[4] if len(parts) > 4 else "?"
        cpu   = parts[5] if len(parts) > 5 else "?"
        what  = " ".join(parts[7:]) if len(parts) > 7 else (parts[6] if len(parts) > 6 else "?")

    return {"user": user, "tty": tty, "from": frm,
            "login": login, "idle": idle, "cpu": cpu, "what": what}


def _parse_last_output(raw):
    """
    Parse `last` output into list of (user, tty, from, datetime, duration).
    Handles both standard and -F (full date) formats, with or without a
    "from" (IP / hostname) column.
    """
    recents = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if not parts or parts[0] in _SKIP_USERS:
            continue
        if len(parts) < 4:
            continue

        user = parts[0]
        tty  = parts[1]

        # Determine whether parts[2] is a "from" field or already the date.
        if _looks_like_from_field(parts[2]):
            frm      = parts[2]
            date_idx = 3
        else:
            frm      = "local"
            date_idx = 2

        # Consume date tokens until we hit "-", "still", "gone", "crash", or "("
        dt_tokens = []
        i = date_idx
        while i < len(parts):
            tok = parts[i]
            if tok in ("-", "still", "gone", "crash") or tok.startswith("("):
                break
            dt_tokens.append(tok)
            i += 1
        dt = " ".join(dt_tokens) if dt_tokens else "--"

        # Duration: look for a "(HH:MM)" or "(HH:MM:SS)" anywhere in the line
        dur = "--"
        for tok in reversed(parts):
            if tok.startswith("(") and tok.endswith(")"):
                dur = tok[1:-1]
                break

        recents.append((user, tty, frm, dt, dur))

    return recents


# Matches journalctl short-iso lines with an sshd "Accepted" event
_JOURNAL_ACCEPTED_RE = re.compile(
    r'^(\S+)\s+\S+\s+sshd\[\d+\]:\s+Accepted\s+\S+\s+for\s+(\S+)\s+from\s+(\S+)\s+port'
)

# Matches /var/log/auth.log and /var/log/secure sshd "Accepted" lines
_AUTH_LOG_ACCEPTED_RE = re.compile(
    r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+sshd\[\d+\]:\s+'
    r'Accepted\s+\S+\s+for\s+(\S+)\s+from\s+(\S+)\s+port'
)


def _parse_journal_ssh(raw):
    """
    Parse `journalctl -t sshd -o short-iso` output for successful logins.
    Returns list of (user, tty, from, datetime, duration), newest first.
    """
    entries = []
    for line in raw.strip().splitlines():
        m = _JOURNAL_ACCEPTED_RE.match(line)
        if m:
            dt, user, frm = m.group(1), m.group(2), m.group(3)
            entries.append((user, "sshd", frm, dt, "--"))
    entries.reverse()
    return entries[:20]


def _parse_auth_log(raw):
    """
    Parse /var/log/auth.log (Debian/Ubuntu) or /var/log/secure (RHEL/CentOS)
    for SSH Accepted lines.  Returns list of (user, tty, from, datetime, duration).
    """
    entries = []
    for line in raw.strip().splitlines():
        m = _AUTH_LOG_ACCEPTED_RE.match(line)
        if m:
            dt, user, frm = m.group(1), m.group(2), m.group(3)
            entries.append((user, "ssh", frm, dt, "--"))
    entries.reverse()
    return entries[:20]


def _parse_wtmp_py(raw):
    """
    Parse pipe-separated output produced by _WTMP_PY_SCRIPT.
    Each line: user|tty|host|datetime
    """
    entries = []
    for line in raw.strip().splitlines():
        parts = line.split('|', 3)
        if len(parts) != 4:
            continue
        user, tty, host, dt = (p.strip() for p in parts)
        if not user or user in _SKIP_USERS:
            continue
        entries.append((user, tty, host or "local", dt, "--"))
    entries.reverse()
    return entries[:20]


# Python script (base64-encoded at runtime) that parses /var/log/wtmp directly.
# struct utmp on x86-64 Linux: 384 bytes; USER_PROCESS type = 7.
# Field offsets: type@0(h), pid@4(i), line@8(32s), id@40(4s),
#                user@44(32s), host@76(256s), tv_sec@340(i)
_WTMP_PY_SCRIPT = (
    "import struct,time\n"
    "RS=384;UP=7\n"
    "try:data=open('/var/log/wtmp','rb').read()\n"
    "except:data=b''\n"
    "for i in range(len(data)//RS):\n"
    " r=data[i*RS:(i+1)*RS]\n"
    " if struct.unpack_from('<h',r,0)[0]!=UP:continue\n"
    " u=r[44:76].rstrip(b'\\x00').decode(errors='replace').strip()\n"
    " l=r[8:40].rstrip(b'\\x00').decode(errors='replace').strip()\n"
    " h=r[76:332].rstrip(b'\\x00').decode(errors='replace').strip()or'local'\n"
    " ts=struct.unpack_from('<i',r,340)[0]\n"
    " dt=time.strftime('%Y-%m-%d %H:%M',time.localtime(ts))\n"
    " u and all(32<=ord(c)<=126 for c in u)and print(u+'|'+l+'|'+h+'|'+dt)\n"
)


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

        self.tree.tag_configure("odd",   background=t.surface_dark, foreground=t.text)
        self.tree.tag_configure("even",  background=t.card_bg,      foreground=t.text)
        self.tree.tag_configure("self",  foreground=t.cyan)   # our own session
        self.tree.tag_configure("other", foreground=t.text)
        self.tree.tag_configure("root",  foreground=t.status_stopped)

        vsb = tk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # Last logins section header with diagnose button
        last_hdr = tk.Frame(self, bg=t.bg)
        last_hdr.pack(fill="x", padx=16, pady=(8, 2))
        tk.Label(last_hdr, text="Recent Logins  (last 20)",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(side="left")
        self._diag_btn = tk.Button(last_hdr, text="Diagnose",
                                    command=self._diagnose_logins)
        t.style_button(self._diag_btn, "ghost")
        self._diag_btn.pack(side="right")

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
        self.last_tree.tag_configure("odd",  background=t.surface_dark, foreground=t.text)
        self.last_tree.tag_configure("even", background=t.card_bg,      foreground=t.text)

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
        if getattr(self, "_fetching", False): return
        if not self.controller.ssh.connected:
            self._set_status("Not connected", "error")
            return
        self._refresh_btn.config(state="disabled", text="Loading…")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh

            # Active sessions via `w -h`
            w_out, _, _ = ssh.run("w -h 2>/dev/null")
            sessions = []
            for line in w_out.strip().splitlines():
                s = _parse_w_line(line.split())
                if s:
                    sessions.append(s)

            recents = []
            login_source = ""

            # Source 1: last -F (full timestamps, util-linux >= 2.24)
            out, _, _ = ssh.run("last -n 20 -F 2>/dev/null")
            if out.strip():
                recents = _parse_last_output(out)
                if recents:
                    login_source = "last -F"

            # Source 2: last (default format, no -F)
            if not recents:
                out, _, _ = ssh.run("last -n 20 2>/dev/null")
                if out.strip():
                    recents = _parse_last_output(out)
                    if recents:
                        login_source = "last"

            # Source 3: direct Python parse of /var/log/wtmp binary
            # (works when `last` is absent; wtmp is typically world-readable)
            if not recents:
                import base64 as _b64
                b64 = _b64.b64encode(_WTMP_PY_SCRIPT.encode()).decode()
                out, _, _ = ssh.run(
                    "echo '{}' | base64 -d | python3 2>/dev/null | tail -20".format(b64))
                recents = _parse_wtmp_py(out)
                if recents:
                    login_source = "wtmp"

            # Source 4: systemd journal
            if not recents:
                out, _, _ = ssh.run(
                    "journalctl -t sshd --no-pager -n 200 -o short-iso 2>/dev/null"
                    " | grep 'Accepted' | tail -20")
                recents = _parse_journal_ssh(out)
                if recents:
                    login_source = "journalctl"

            # Source 5: /var/log/auth.log (Debian/Ubuntu) or /var/log/secure (RHEL)
            if not recents:
                out, _, _ = ssh.run(
                    "grep 'Accepted' /var/log/auth.log 2>/dev/null | tail -20")
                if not out.strip():
                    out, _, _ = ssh.run(
                        "grep 'Accepted' /var/log/secure 2>/dev/null | tail -20")
                recents = _parse_auth_log(out)
                if recents:
                    login_source = "auth.log"

            # Source 6: sudo variants (for servers where logs require elevated access)
            if not recents:
                out, _, _ = ssh.run(
                    "sudo grep 'Accepted' /var/log/auth.log 2>/dev/null | tail -20")
                if not out.strip():
                    out, _, _ = ssh.run(
                        "sudo grep 'Accepted' /var/log/secure 2>/dev/null | tail -20")
                recents = _parse_auth_log(out)
                if recents:
                    login_source = "auth.log (sudo)"

            self.after(0, lambda s=sessions, r=recents, src=login_source:
                       self._populate(s, r, src))
        finally:
            self._fetching = False

    # =========================================================
    # POPULATE
    # =========================================================
    def _populate(self, sessions, recents, src=""):
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

        n = len(sessions)
        session_str = "{} active session{}".format(n, "s" if n != 1 else "")
        if recents:
            login_str = "  •  {} recent login{} (via {})".format(
                len(recents), "s" if len(recents) != 1 else "", src)
        else:
            login_str = "  •  No login history found (wtmp/journal/auth.log all empty or inaccessible)"
        self._set_status(session_str + login_str)

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
    # DIAGNOSTICS
    # =========================================================
    def _diagnose_logins(self):
        if not self.controller.ssh.connected:
            messagebox.showinfo("Diagnose", "Not connected to server.")
            return
        self._diag_btn.config(state="disabled", text="Running…")

        cmd = (
            "echo '=== last -n 5 ===' && last -n 5 2>&1 | head -10; "
            "echo '=== wtmp / utmp ===' && ls -la /var/log/wtmp /var/run/utmp 2>&1; "
            "echo '=== /var/log/ files ===' && ls /var/log/ 2>/dev/null; "
            "echo '=== sshd_config logging ===' && grep -iE 'SyslogFacility|LogLevel' /etc/ssh/sshd_config 2>/dev/null; "
            "echo '=== auth.log tail ===' && tail -5 /var/log/auth.log 2>&1; "
            "echo '=== secure tail ===' && tail -5 /var/log/secure 2>&1; "
            "echo '=== syslog tail ===' && tail -5 /var/log/syslog 2>&1; "
            "echo '=== journalctl test ===' && journalctl -n 3 -t sshd 2>&1 | head -6"
        )

        def worker():
            out, err, _ = self.controller.ssh.run(cmd)
            result = out + (("\n--- stderr ---\n" + err) if err.strip() else "")
            self.after(0, lambda: (
                self._diag_btn.config(state="normal", text="Diagnose"),
                self._show_diag_dialog(result)
            ))

        threading.Thread(target=worker, daemon=True).start()

    def _show_diag_dialog(self, text):
        win = tk.Toplevel(self)
        win.title("Login History Diagnostics")
        win.geometry("760x520")
        win.configure(bg=self.theme.bg)
        win.transient(self.winfo_toplevel())

        t = self.theme
        tk.Label(win, text="Login History Diagnostics",
                 bg=t.bg, fg=t.text, font=t.font_title).pack(
            padx=16, pady=(12, 2), anchor="w")
        tk.Label(win, text="Raw output of diagnostic commands run on the server:",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(
            padx=16, pady=(0, 6), anchor="w")

        frame = tk.Frame(win, bg=t.bg)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        txt = tk.Text(frame, bg=t.card_bg, fg=t.text, font=t.font_mono,
                      wrap="none", relief="flat", state="normal")
        xsb = tk.Scrollbar(frame, orient="horizontal", command=txt.xview)
        ysb = tk.Scrollbar(frame, orient="vertical",   command=txt.yview)
        txt.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        txt.pack(fill="both", expand=True)
        txt.insert("end", text.strip() if text.strip() else "(no output returned)")
        txt.config(state="disabled")

        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 12))

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_status(self, text, level="info"):
        t = self.theme
        if text.endswith("…") or text.endswith("..."):
            self._status_lbl.config(text=text, bg=t.blue, fg="#ffffff")
            return
        colors = {"info": t.text_muted, "error": t.status_stopped, "ok": t.status_running}
        self._status_lbl.config(text=text, bg=t.surface_dark, fg=colors.get(level, t.text_muted))
