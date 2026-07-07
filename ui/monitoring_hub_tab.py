# ui/monitoring_hub_tab.py
"""
Unifies the two system-metrics views (Netdata, Glances) into one sidebar
entry with an internal sub-notebook — same pattern as ui/docker_hub_tab.py
and ui/storage_hub_tab.py. The two wrapped tabs are unchanged; each is just
parented to this sub-notebook instead of the main app notebook.

Unlike Docker/Storage's sub-tabs, both of these pull their data straight
from each backend's own HTTP API rather than through the SSH connection, so
refreshing here is not gated on self.controller.ssh.connected.
"""

import tkinter as tk
from tkinter import ttk

from ui.netdata_tab import NetdataTab
from ui.glances_tab import GlancesTab


class MonitoringHubTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        nb_style = ttk.Style()
        nb_style.configure("MonitoringHub.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("MonitoringHub.TNotebook.Tab", background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("MonitoringHub.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="MonitoringHub.TNotebook")
        self._nb.pack(fill="both", expand=True)

        self.netdata_tab = NetdataTab(self._nb, self.controller)
        self.glances_tab = GlancesTab(self._nb, self.controller)

        self._nb.add(self.netdata_tab, text="  Netdata  ")
        self._nb.add(self.glances_tab, text="  Glances  ")

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    def _on_subtab_changed(self, _event=None):
        current = self._nb.nametowidget(self._nb.select())
        current.refresh()

    def on_show(self):
        """Called when the Monitoring hub tab itself becomes active — refresh
        whichever sub-tab is currently selected."""
        self._on_subtab_changed()
