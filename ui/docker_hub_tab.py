# ui/docker_hub_tab.py
"""
Unifies the three Docker-related views (containers, live stats,
volumes/networks) into one sidebar entry with an internal sub-notebook —
the same "Arr.TNotebook"-style pattern ui/arr_tab.py already uses for its
Queue/Missing/Upcoming sub-tabs, applied here to distinct views of one
subsystem instead of content categories. The three wrapped tabs are
unchanged; each is just parented to this sub-notebook instead of the main
app notebook.
"""

import tkinter as tk
from tkinter import ttk

from ui.docker_tab import DockerTab
from ui.docker_stats_tab import DockerStatsTab
from ui.docker_volumes_tab import DockerVolumesTab


class DockerHubTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        nb_style = ttk.Style()
        nb_style.configure("DockerHub.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("DockerHub.TNotebook.Tab", background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("DockerHub.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="DockerHub.TNotebook")
        self._nb.pack(fill="both", expand=True)

        self.containers_tab = DockerTab(self._nb, self.controller)
        self.stats_tab       = DockerStatsTab(self._nb, self.controller)
        self.volumes_tab     = DockerVolumesTab(self._nb, self.controller)

        self._nb.add(self.containers_tab, text="  Containers  ")
        self._nb.add(self.stats_tab,       text="  Stats  ")
        self._nb.add(self.volumes_tab,     text="  Volumes  ")

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    def _on_subtab_changed(self, _event=None):
        # The three wrapped tabs have inconsistent entry-point method
        # names (refresh_all() vs on_show()) — dispatch each explicitly
        # rather than normalizing three unrelated tabs just for this.
        if not self.controller.ssh.connected:
            return
        current = self._nb.nametowidget(self._nb.select())
        if current is self.containers_tab:
            self.containers_tab.refresh_all()
        elif current is self.stats_tab:
            self.stats_tab.on_show()
        elif current is self.volumes_tab:
            self.volumes_tab.on_show()

    def on_show(self):
        """Called when the Docker hub tab itself becomes active — refresh
        whichever sub-tab is currently selected."""
        self._on_subtab_changed()
