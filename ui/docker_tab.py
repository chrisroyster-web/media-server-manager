# ui/docker_tab.py
"""
Docker container management tab.

Discovers all standalone containers on the server (those NOT managed by
Docker Compose) and shows them as live cards.  Compose stacks are handled
separately by the Compose tab so nothing appears in both places.
"""

import time
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import shlex

from ui.base_tab import CardConsoleTab
from ui.refresh_control import RefreshControl
from ui.log_tail_window import LogTailWindow

# Container names / images that run on a schedule rather than staying up
_SCHEDULER_KEYWORDS = ("watchtower", "wud", "whats-up-docker", "ouroboros")


class DockerTab(CardConsoleTab):

    TITLE = "DOCKER CONTAINERS"

    def __init__(self, parent, controller):
        super().__init__(parent, controller)

    # ------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------
    def _populate_header(self, hdr_row):
        t = self.theme
        self._rc = RefreshControl(hdr_row, self.controller, "docker",
                                  default=15, on_refresh=self.refresh_all)
        self._rc.pack(side="right")

        self._last_lbl = tk.Label(hdr_row, text="", bg=t.bg,
                                   fg=t.text_muted, font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        prune_vol_btn = tk.Button(hdr_row, text="Prune Volumes",
                                   command=self._prune_volumes)
        t.style_button(prune_vol_btn, "danger")
        prune_vol_btn.pack(side="right", padx=(0, 6))

        prune_img_btn = tk.Button(hdr_row, text="Prune Images",
                                   command=self._prune_images)
        t.style_button(prune_img_btn, "danger")
        prune_img_btn.pack(side="right", padx=(0, 6))

    def _host(self):
        return self.controller.config_manager.last_host or "localhost"

    # ------------------------------------------------------------------
    # STRUCTURE  (called once at init; cards are built dynamically)
    # ------------------------------------------------------------------
    def _populate_cards(self):
        t = self.theme

        # Two-column card grid — children are destroyed/rebuilt on each refresh
        self._cards_area = tk.Frame(self.inner, bg=t.bg)
        self._cards_area.pack(fill="x", padx=4)
        self._cards_area.columnconfigure(0, weight=1, uniform="dc")
        self._cards_area.columnconfigure(1, weight=1, uniform="dc")

        # Separator + local images treeview (always below cards)
        tk.Frame(self.inner, bg=t.card_border, height=1).pack(
            fill="x", padx=8, pady=(12, 8))
        self._build_images_section()

    def reload_cards(self):
        """Override base: no static config — just refresh from the server."""
        self.refresh_all()

    # ------------------------------------------------------------------
    # LOCAL IMAGES TREEVIEW
    # ------------------------------------------------------------------
    def _build_images_section(self):
        t = self.theme

        hdr = tk.Frame(self.inner, bg=t.bg)
        hdr.pack(fill="x", padx=8, pady=(0, 6))
        self._bind_mousewheel(hdr)
        tk.Label(hdr, text="LOCAL IMAGES", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._img_count_lbl = tk.Label(hdr, text="", bg=t.bg,
                                        fg=t.text_muted, font=t.font_small)
        self._img_count_lbl.pack(side="left", padx=12)

        tv_frame = tk.Frame(self.inner, bg=t.bg)
        tv_frame.pack(fill="both", expand=True, padx=8, pady=(0, 16))
        self._bind_mousewheel(tv_frame)

        style = ttk.Style()
        style.configure("DockerImg.Treeview",
                        background=t.card_bg, foreground=t.text,
                        fieldbackground=t.card_bg, borderwidth=0,
                        rowheight=26, font=t.font_mono)
        style.configure("DockerImg.Treeview.Heading",
                        background=t.surface_dark, foreground=t.text_muted,
                        font=t.font_small, relief="flat", borderwidth=0)
        style.map("DockerImg.Treeview",
                  background=[("selected", t.surface_light)],
                  foreground=[("selected", t.text)])

        cols = ("repo", "tag", "id", "size", "layers", "created")
        self._images_tree = ttk.Treeview(tv_frame, columns=cols,
                                          show="headings",
                                          style="DockerImg.Treeview",
                                          height=8, selectmode="browse")
        for col, text, width, anchor in [
            ("repo",    "Repository", 220, "w"),
            ("tag",     "Tag",        110, "w"),
            ("id",      "Image ID",    90, "w"),
            ("size",    "Size",        90, "e"),
            ("layers",  "Layers",      60, "e"),
            ("created", "Created",    140, "w"),
        ]:
            self._images_tree.heading(col, text=text, anchor=anchor)
            self._images_tree.column(col, width=width, minwidth=40,
                                      anchor=anchor, stretch=(col == "repo"))

        self._images_tree.tag_configure("odd",  background=t.surface_dark, foreground=t.text)
        self._images_tree.tag_configure("even", background=t.card_bg,      foreground=t.text)

        vsb = tk.Scrollbar(tv_frame, orient="vertical",
                            command=self._images_tree.yview)
        self._images_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._images_tree.pack(fill="both", expand=True)

    def _populate_images_tree(self, images):
        self._images_tree.delete(*self._images_tree.get_children())
        for i, img in enumerate(images):
            tag = "even" if i % 2 == 0 else "odd"
            self._images_tree.insert("", "end",
                                      values=(img["repo"], img["tag"], img["id"],
                                              img["size"], img["layers"], img["created"]),
                                      tags=(tag,))
        count = len(images)
        self._img_count_lbl.config(
            text="{} image{}".format(count, "s" if count != 1 else ""))

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def refresh_all(self):
        if getattr(self, "_fetching", False): return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            return
        self._fetching = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            ssh        = self.controller.ssh
            containers = []
            stats_map  = {}
            image_map  = {}

            # All container IDs (running + stopped)
            ids_out, _, _ = ssh.run("docker ps -aq 2>/dev/null")
            ids = ids_out.strip().split() if ids_out.strip() else []

            if ids:
                ids_str = " ".join(shlex.quote(i) for i in ids)

                # One inspect call — pipe-delimited: name|status|image|compose-project|ports
                fmt = (
                    "{{.Name}}"
                    "|{{.State.Status}}"
                    "|{{.Config.Image}}"
                    "|{{index .Config.Labels \"com.docker.compose.project\"}}"
                    "|{{range $p,$b := .NetworkSettings.Ports}}"
                    "{{if $b}}{{(index $b 0).HostPort}}->{{$p}} {{end}}{{end}}"
                )
                out, _, _ = ssh.run(
                    "docker inspect {} --format '{}' 2>/dev/null".format(ids_str, fmt))

                for line in out.strip().splitlines():
                    parts = line.split("|", 4)
                    if len(parts) < 4:
                        continue
                    name         = parts[0].lstrip("/").strip()
                    raw_status   = parts[1].strip()
                    image        = parts[2].strip()
                    compose_proj = parts[3].strip()
                    ports        = parts[4].strip() if len(parts) > 4 else ""

                    if compose_proj:        # belongs to a compose stack — skip
                        continue

                    is_scheduler = any(
                        kw in name.lower() or kw in image.lower()
                        for kw in _SCHEDULER_KEYWORDS
                    )
                    if is_scheduler and raw_status == "exited":
                        display_status = "scheduled"
                    elif raw_status == "running":
                        display_status = "running"
                    elif raw_status == "exited":
                        display_status = "stopped"
                    else:
                        display_status = raw_status

                    containers.append({
                        "name":   name,
                        "status": display_status,
                        "image":  image,
                        "ports":  ports,
                    })

                # Live stats for running containers
                running = [c["name"] for c in containers if c["status"] == "running"]
                if running:
                    stats_out, _, _ = ssh.run(
                        "docker stats --no-stream --format "
                        "'{{{{.Name}}}}|{{{{.CPUPerc}}}}|{{{{.MemPerc}}}}|{{{{.RunningFor}}}}'"
                        " {} 2>/dev/null".format(" ".join(shlex.quote(n) for n in running)))
                    for line in stats_out.strip().splitlines():
                        p = line.split("|")
                        if len(p) == 4:
                            stats_map[p[0].strip()] = {
                                "cpu": p[1], "mem": p[2], "uptime": p[3]}

                # Image sizes for the label
                sz_out, _, _ = ssh.run(
                    "docker images --format "
                    "'{{{{.Repository}}}}:{{{{.Tag}}}}|{{{{.Size}}}}' 2>/dev/null")
                for line in sz_out.strip().splitlines():
                    p = line.split("|", 1)
                    if len(p) == 2:
                        image_map[p[0]] = p[1]

            self.after(0, lambda: self._sync_cards(containers, stats_map, image_map))

            images = self.controller.docker_manager.list_images()
            self.after(0, lambda imgs=images: self._populate_images_tree(imgs))
            self.after(0, self._rc.schedule)
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M:%S"))))
        finally:
            self._fetching = False

    # ------------------------------------------------------------------
    # SYNC CARDS
    # ------------------------------------------------------------------
    def _sync_cards(self, containers, stats_map, image_map):
        for w in self._cards_area.winfo_children():
            w.destroy()
        self.cards = {}

        if not containers:
            t = self.theme
            msg = ("No standalone containers found."
                   if self.controller.ssh.connected else "Not connected.")
            tk.Label(self._cards_area, text=msg, bg=t.bg, fg=t.text_muted,
                     font=t.font_regular).grid(row=0, column=0, columnspan=2,
                                               padx=16, pady=24)
            return

        for i, c in enumerate(sorted(containers, key=lambda x: x["name"].lower())):
            row, col = divmod(i, 2)
            name   = c["name"]
            card   = self._create_card(name, c["image"], c["ports"], row, col)
            self.cards[name] = card
            self._update_card(name, c["status"],
                              stats_map.get(name, {}),
                              c["image"], image_map.get(c["image"], ""))

    # ------------------------------------------------------------------
    # CREATE CARD
    # ------------------------------------------------------------------
    def _create_card(self, name, image, ports, grid_row, grid_col):
        t = self.theme
        frame = tk.Frame(self._cards_area, bg=t.card_bg,
                         highlightbackground=t.card_border, highlightthickness=1)
        frame.grid(row=grid_row, column=grid_col, padx=8, pady=6, sticky="nsew")
        self._bind_mousewheel(frame)

        # Header: dot + name + status badge
        hdr = tk.Frame(frame, bg=t.card_bg)
        hdr.pack(fill="x", pady=(6, 2))
        self._bind_mousewheel(hdr)

        dot = tk.Canvas(hdr, width=14, height=14,
                        bg=t.card_bg, highlightthickness=0)
        dot.pack(side="left", padx=(6, 10))
        self._bind_mousewheel(dot)

        tk.Label(hdr, text=name, bg=t.card_bg,
                 fg=t.text, font=t.font_title).pack(side="left")
        status_lbl = tk.Label(hdr, text="…", bg=t.card_bg,
                               fg=t.text_muted, font=t.font_small)
        status_lbl.pack(side="right", padx=10)
        self._bind_mousewheel(status_lbl)

        # Image
        image_lbl = tk.Label(frame, text=image, bg=t.card_bg,
                              fg=t.text_muted, font=t.font_small)
        image_lbl.pack(anchor="w", padx=10)
        self._bind_mousewheel(image_lbl)

        # Port mappings (shown only when present)
        ports_lbl = None
        if ports:
            ports_lbl = tk.Label(frame, text=ports, bg=t.card_bg,
                                  fg=t.text_muted, font=t.font_small)
            ports_lbl.pack(anchor="w", padx=10)
            self._bind_mousewheel(ports_lbl)

        # Action buttons
        btn_row = tk.Frame(frame, bg=t.card_bg)
        btn_row.pack(fill="x", pady=6)
        self._bind_mousewheel(btn_row)
        for label, action in [
            ("Start", "start"), ("Stop", "stop"), ("Restart", "restart"),
            ("Pull", "pull"), ("Logs", "logs"), ("Tail", "tail"), ("Inspect", "inspect"),
        ]:
            btn = tk.Button(btn_row, text=label,
                            command=lambda a=action, n=name: self._action(n, a))
            t.style_button(btn)
            btn.pack(side="left", padx=4)

        # Stats / schedule row
        stats_lbl = tk.Label(frame, text="", bg=t.card_bg,
                             fg=t.text_dim, font=t.font_small)
        stats_lbl.pack(anchor="w", padx=8, pady=(0, 6))
        self._bind_mousewheel(stats_lbl)

        return {
            "frame": frame, "dot": dot,
            "status_lbl": status_lbl, "stats_lbl": stats_lbl,
            "image_lbl": image_lbl, "ports_lbl": ports_lbl,
            "container": name,
        }

    # ------------------------------------------------------------------
    # UPDATE CARD
    # ------------------------------------------------------------------
    def _update_card(self, name, status, stats=None, image="", image_size=""):
        card = self.cards.get(name)
        if not card:
            return
        t = self.theme

        card["status_lbl"].config(text=status)

        dot = card["dot"]
        dot.delete("all")
        color = {
            "running":   t.status_running,
            "stopped":   t.status_stopped,
            "paused":    t.yellow,
            "scheduled": t.cyan,
        }.get(status, t.status_unknown)
        dot.create_oval(2, 2, 12, 12, fill=color, outline=color)

        if stats and status == "running":
            cpu      = stats.get("cpu", "--")
            mem      = stats.get("mem", "--")
            uptime   = stats.get("uptime", "")
            up_lower = uptime.lower()
            up_color = (
                t.status_running if any(w in up_lower for w in ("day", "week", "hour"))
                else t.yellow    if "minute" in up_lower
                else t.status_stopped
            )
            card["stats_lbl"].config(
                text="CPU {}  MEM {}  Up: {}".format(cpu, mem, uptime),
                fg=up_color)
        elif status == "scheduled":
            card["stats_lbl"].config(text="runs on schedule", fg=t.cyan)
        else:
            card["stats_lbl"].config(text="", fg=t.text_dim)

        size_str = "  ·  {}".format(image_size) if image_size else ""
        card["image_lbl"].config(text="{}{}".format(image, size_str))

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def _action(self, name, action):
        self._log("{} {}".format(action.upper(), name), "cmd")

        def worker():
            dm  = self.controller.docker_manager

            if action == "tail":
                self.after(0, lambda: LogTailWindow(
                    self.controller,
                    title="docker logs -f {}".format(name),
                    cmd="docker logs -f --tail=200 {}".format(name),
                ))
                return

            if   action == "start":   result = dm.start(name)
            elif action == "stop":    result = dm.stop(name)
            elif action == "restart": result = dm.restart(name)
            elif action == "pull":    result = dm.pull(name)
            elif action == "logs":    result = dm.logs(name)
            elif action == "inspect": result = dm.inspect(name)
            else:
                return

            out, err, code = result
            self._log_output("{} {}".format(name, action), out, err, code)
            self.after(1500, self.refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # PRUNE
    # ------------------------------------------------------------------
    def _prune_images(self):
        if not self.controller.ssh.connected:
            self._log("Not connected to server.", "error")
            return
        if not messagebox.askyesno(
                "Prune Images",
                "Remove all dangling (unused) Docker images?\n\n"
                "Only images not referenced by any container are removed.\n"
                "This cannot be undone.",
                parent=self):
            return
        self._log("docker image prune -f", "cmd")

        def worker():
            out, err, code = self.controller.docker_manager.prune_images()
            self._log_output("Prune Images", out, err, code)
            if code == 0:
                self.after(1500, self.refresh_all)

        threading.Thread(target=worker, daemon=True).start()

    def _prune_volumes(self):
        if not self.controller.ssh.connected:
            self._log("Not connected to server.", "error")
            return
        if not messagebox.askyesno(
                "Prune Volumes",
                "Remove all unused Docker volumes?\n\n"
                "WARNING: This may permanently delete data from volumes\n"
                "not attached to any running container.\n\n"
                "This cannot be undone.",
                parent=self):
            return
        self._log("docker volume prune -f", "cmd")

        def worker():
            out, err, code = self.controller.docker_manager.prune_volumes()
            self._log_output("Prune Volumes", out, err, code)
            if code == 0:
                self.after(1500, self.refresh_all)

        threading.Thread(target=worker, daemon=True).start()
