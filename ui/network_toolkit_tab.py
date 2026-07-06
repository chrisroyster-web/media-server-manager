# ui/network_toolkit_tab.py
"""
Network Toolkit tab — runs ping, traceroute, nslookup, curl -I, and
port-check (nc) FROM the server via SSH, not from the local machine.
"""

import shlex
import threading
import time
import tkinter as tk
from tkinter import ttk


_TOOLS = [
    ("ping",       "Ping",        "ping -c 4 -W 2 {host} 2>&1"),
    ("traceroute", "Traceroute",  "traceroute -w 2 -q 1 {host} 2>&1"),
    ("nslookup",   "DNS Lookup",  "nslookup {host} 2>&1"),
    ("curl",       "HTTP HEAD",   "curl -sI --max-time 8 --connect-timeout 5 {url} 2>&1"),
    ("port",       "Port Check",  "nc -zv -w 5 {host} {port} 2>&1"),
    ("whois",      "Whois",       "whois {host} 2>/dev/null | head -40"),
    ("mtr",        "MTR (brief)", "mtr --report --report-cycles 3 {host} 2>&1"),
]
_TOOL_IDS = [t[0] for t in _TOOLS]


class NetworkToolkitTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._running   = False
        self._history   = []   # list of (tool, target)
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="NETWORK TOOLKIT", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        tk.Label(hdr, text="(commands run on the server via SSH)",
                 bg=t.bg, fg=t.text_muted, font=t.font_small).pack(
                     side="left", padx=12)

        # Input row
        input_fr = tk.Frame(self, bg=t.surface_dark)
        input_fr.pack(fill="x", padx=16, pady=(0, 8))
        input_fr.columnconfigure(1, weight=1)

        # Tool selector
        tk.Label(input_fr, text="Tool:", bg=t.surface_dark, fg=t.text,
                 font=t.font_regular).grid(row=0, column=0, sticky="w",
                                           padx=(12, 6), pady=10)
        self._tool_var = tk.StringVar(value="ping")
        tool_menu = tk.OptionMenu(input_fr, self._tool_var,
                                  *[lbl for _, lbl, _ in _TOOLS],
                                  command=self._on_tool_change)
        tool_menu.config(bg=t.surface_dark, fg=t.text, relief="flat",
                         font=t.font_regular, bd=0, highlightthickness=0,
                         activebackground=t.surface_light,
                         activeforeground=t.text)
        tool_menu["menu"].config(bg=t.surface_dark, fg=t.text,
                                  font=t.font_regular)
        tool_menu.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=10)
        # Map display label → tool id
        self._tool_map = {lbl: tid for tid, lbl, _ in _TOOLS}

        # Host / URL
        tk.Label(input_fr, text="Host / URL:", bg=t.surface_dark, fg=t.text,
                 font=t.font_regular).grid(row=0, column=2, sticky="w",
                                            padx=(12, 6), pady=10)
        self._host_var = tk.StringVar()
        host_entry = tk.Entry(input_fr, textvariable=self._host_var,
                              font=t.font_regular, width=30)
        t.style_entry(host_entry)
        host_entry.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=10)
        host_entry.bind("<Return>", lambda _: self._run())
        input_fr.columnconfigure(3, weight=1)

        # Port field (shown only for port-check)
        self._port_lbl = tk.Label(input_fr, text="Port:", bg=t.surface_dark,
                                   fg=t.text, font=t.font_regular)
        self._port_var = tk.StringVar(value="80")
        self._port_entry = tk.Entry(input_fr, textvariable=self._port_var,
                                     font=t.font_regular, width=8)
        t.style_entry(self._port_entry)

        # Run / Stop buttons
        self._run_btn = tk.Button(input_fr, text="▶ Run",
                                   command=self._run)
        t.style_button(self._run_btn)
        self._run_btn.grid(row=0, column=5, padx=(0, 6), pady=10)
        self._stop_btn = tk.Button(input_fr, text="⏹ Stop",
                                    command=self._stop, state="disabled")
        t.style_button(self._stop_btn)
        self._stop_btn.grid(row=0, column=6, padx=(0, 12), pady=10)

        # History sidebar + output area in a paned layout
        body = tk.PanedWindow(self, orient="horizontal",
                              bg=t.card_border, sashwidth=4, sashrelief="flat")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        # History panel (left)
        hist_fr = tk.Frame(body, bg=t.surface_dark)
        body.add(hist_fr, minsize=160, width=180, stretch="never")
        tk.Label(hist_fr, text="HISTORY", bg=t.surface_dark,
                 fg=t.text_muted, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        self._hist_list = tk.Listbox(hist_fr, bg=t.surface_dark,
                                      fg=t.text, font=t.font_small,
                                      selectbackground=t.surface_light,
                                      selectforeground=t.text,
                                      bd=0, relief="flat",
                                      activestyle="none")
        self._hist_list.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._hist_list.bind("<<ListboxSelect>>", self._history_select)
        clear_hist = tk.Button(hist_fr, text="Clear History",
                               command=self._clear_history,
                               bg=t.surface_dark, fg=t.text_muted,
                               bd=0, relief="flat", font=t.font_small)
        clear_hist.pack(pady=(0, 6))

        # Output console (right)
        out_fr = tk.Frame(body, bg=t.bg)
        body.add(out_fr, minsize=300, stretch="always")

        out_hdr = tk.Frame(out_fr, bg=t.bg)
        out_hdr.pack(fill="x", pady=(0, 4))
        self._out_title = tk.Label(out_hdr, text="OUTPUT",
                                    bg=t.bg, fg=t.text_muted,
                                    font=("Segoe UI", 8, "bold"))
        self._out_title.pack(side="left")
        self._elapsed_lbl = tk.Label(out_hdr, text="", bg=t.bg,
                                      fg=t.text_muted, font=t.font_small)
        self._elapsed_lbl.pack(side="left", padx=12)
        tk.Button(out_hdr, text="Clear", command=self._clear_output,
                  bg=t.bg, fg=t.text_muted, bd=0, relief="flat",
                  font=t.font_small).pack(side="right")

        con_wrap = tk.Frame(out_fr, bg=t.surface_dark)
        con_wrap.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(con_wrap, orient="vertical")
        self._output = tk.Text(con_wrap, bg=t.surface_dark, fg=t.text,
                               font=t.font_mono, bd=0, relief="flat",
                               wrap="none", state="disabled",
                               yscrollcommand=vsb.set)
        xsb = ttk.Scrollbar(con_wrap, orient="horizontal",
                            command=self._output.xview)
        self._output.configure(xscrollcommand=xsb.set)
        vsb.configure(command=self._output.yview)
        xsb.pack(side="bottom", fill="x")
        vsb.pack(side="right", fill="y")
        self._output.pack(fill="both", expand=True)

        self._output.tag_configure("cmd",     foreground=t.cyan)
        self._output.tag_configure("ok",      foreground=t.status_running)
        self._output.tag_configure("err",     foreground=t.status_stopped)
        self._output.tag_configure("warn",    foreground=t.yellow)
        self._output.tag_configure("header",  foreground=t.blue)

        # Status bar
        self._status = tk.Label(self, text="Connect to server to use toolkit",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(0, 8))

        self._on_tool_change(self._tool_var.get())

    def _on_tool_change(self, label):
        tid = self._tool_map.get(label, "ping")
        # Show port field only for port check
        if tid == "port":
            self._port_lbl.grid(row=0, column=4, sticky="w",
                                padx=(0, 4), pady=10)
            self._port_entry.grid(row=0, column=5, sticky="w",
                                  padx=(0, 8), pady=10)
            self._run_btn.grid(row=0, column=6, padx=(0, 6), pady=10)
            self._stop_btn.grid(row=0, column=7, padx=(0, 12), pady=10)
        else:
            self._port_lbl.grid_remove()
            self._port_entry.grid_remove()
            self._run_btn.grid(row=0, column=5, padx=(0, 6), pady=10)
            self._stop_btn.grid(row=0, column=6, padx=(0, 12), pady=10)

    # -----------------------------------------------------------------------
    # RUN
    # -----------------------------------------------------------------------
    def _run(self):
        if self._running:
            return
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected to SSH",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            return
        label = self._tool_var.get()
        tid   = self._tool_map.get(label, "ping")
        host  = self._host_var.get().strip()
        port  = self._port_var.get().strip() or "80"
        if not host:
            self._status.config(text="Enter a hostname or IP address",
                                bg=self.theme.surface_dark,
                                fg=self.theme.yellow)
            return

        # Build URL for curl
        url = host if host.startswith(("http://", "https://")) \
              else "http://{}".format(host)

        cmd_tpl = next((c for i, _, c in _TOOLS if i == tid), "")
        cmd = cmd_tpl.format(host=shlex.quote(host), url=shlex.quote(url),
                             port=shlex.quote(port))

        self._clear_output()
        self._write("$ {}\n".format(cmd), "cmd")
        self._write("─" * 60 + "\n", "header")

        self._running = True
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status.config(text="Running {}…".format(label),
                            bg=self.theme.blue, fg="#ffffff")

        display = "{} {}{}".format(
            label, host, ":{}".format(port) if tid == "port" else "")
        self._add_history(display)

        t_start = time.time()
        self._t_start = t_start

        self._stop_event = threading.Event()
        threading.Thread(target=self._do_run, args=(cmd, t_start),
                         daemon=True).start()

    def _do_run(self, cmd, t_start):
        try:
            out, err, code = self.controller.ssh.run(cmd)
            if self._stop_event.is_set():
                # User already clicked Stop -- ssh.run() can't actually be
                # interrupted mid-flight, but don't let this late result
                # overwrite the "Stopped" message it already saw.
                return
            elapsed = time.time() - t_start
            combined = out + (("\n" + err) if err and err not in out else "")
            self.after(0, lambda: self._write(combined + "\n"))
            status = code == 0
            self.after(0, lambda: self._write(
                "─" * 60 + "\n", "header"))
            self.after(0, lambda: self._write(
                "Completed in {:.2f}s\n".format(elapsed),
                "ok" if status else "err"))
            self.after(0, lambda: self._elapsed_lbl.config(
                text="{:.2f}s".format(elapsed)))
            self.after(0, lambda: self._status.config(
                text="Done ({:.2f}s)".format(elapsed),
                bg=self.theme.surface_dark,
                fg=self.theme.status_running if status
                   else self.theme.status_stopped))
        except Exception as e:
            self.after(0, lambda err=str(e): self._write(
                "Error: {}\n".format(err), "err"))
            self.after(0, lambda err=str(e): self._status.config(
                text="Error: {}".format(err),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
        finally:
            self._running = False
            self.after(0, lambda: self._run_btn.config(state="normal"))
            self.after(0, lambda: self._stop_btn.config(state="disabled"))

    def _stop(self):
        # SSH run() is blocking — we can't kill it mid-flight without
        # a new channel, so just mark stopped and update UI. The stop
        # event tells _do_run to discard its result when the blocking
        # call eventually returns, instead of overwriting this message.
        self._stop_event.set()
        self._running = False
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._write("\n[Stopped by user]\n", "warn")
        self._status.config(text="Stopped",
                            bg=self.theme.surface_dark,
                            fg=self.theme.yellow)

    # -----------------------------------------------------------------------
    # HISTORY
    # -----------------------------------------------------------------------
    def _add_history(self, entry):
        if entry in self._history:
            self._history.remove(entry)
        self._history.insert(0, entry)
        self._history = self._history[:30]
        self._hist_list.delete(0, "end")
        for h in self._history:
            self._hist_list.insert("end", h)

    def _history_select(self, _=None):
        sel = self._hist_list.curselection()
        if not sel:
            return
        entry = self._history[sel[0]]
        # Try to parse "Tool host:port" or "Tool host" -- tool labels can
        # contain spaces (e.g. "Port Check"), so match against the known
        # labels rather than splitting on the first space.
        for tid, lbl, _ in _TOOLS:
            prefix = lbl + " "
            if entry.startswith(prefix):
                target = entry[len(prefix):]
                if tid == "port" and ":" in target:
                    host, _, port = target.rpartition(":")
                    self._port_var.set(port)
                    target = host
                self._host_var.set(target)
                self._tool_var.set(lbl)
                self._on_tool_change(lbl)
                break

    def _clear_history(self):
        self._history.clear()
        self._hist_list.delete(0, "end")

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    def _write(self, text, tag=None):
        def _do():
            self._output.config(state="normal")
            if tag:
                self._output.insert("end", text, tag)
            else:
                self._output.insert("end", text)
            self._output.see("end")
            self._output.config(state="disabled")
        self.after(0, _do)

    def _clear_output(self):
        self._output.config(state="normal")
        self._output.delete("1.0", "end")
        self._output.config(state="disabled")
        self._elapsed_lbl.config(text="")

    def on_show(self):
        pass
