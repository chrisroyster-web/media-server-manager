# ui/storage_hub_tab.py
"""
Unifies the three disk/storage-related views (SMART health, filesystem/
pool health, du-style usage breakdown) into one sidebar entry with an
internal sub-notebook — same pattern as ui/docker_hub_tab.py. The three
wrapped tabs are unchanged; each is just parented to this sub-notebook
instead of the main app notebook.
"""

import tkinter as tk
from tkinter import ttk

from ui.smart_tab import SmartTab
from ui.storage_health_tab import StorageHealthTab
from ui.disk_usage_tab import DiskUsageTab


class StorageHubTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        nb_style = ttk.Style()
        nb_style.configure("StorageHub.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("StorageHub.TNotebook.Tab", background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("StorageHub.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="StorageHub.TNotebook")
        self._nb.pack(fill="both", expand=True)

        self.health_tab      = SmartTab(self._nb, self.controller)
        self.filesystems_tab = StorageHealthTab(self._nb, self.controller)
        self.usage_tab       = DiskUsageTab(self._nb, self.controller)

        self._nb.add(self.health_tab,      text="  Disk Health  ")
        self._nb.add(self.filesystems_tab, text="  Filesystems  ")
        self._nb.add(self.usage_tab,       text="  Usage  ")

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    def _on_subtab_changed(self, _event=None):
        # The three wrapped tabs have inconsistent entry-point method
        # names — dispatch each explicitly rather than normalizing three
        # unrelated tabs just for this. Unlike the old version, this no
        # longer gates the whole thing on ssh.connected: health_tab and
        # filesystems_tab both show a proper "Not connected" status when
        # disconnected, so calling them unconditionally is what actually
        # keeps that message accurate (e.g. after connecting, using this
        # tab, then disconnecting again) instead of leaving whatever was
        # last fetched on screen.
        current = self._nb.nametowidget(self._nb.select())
        if current is self.health_tab:
            self.health_tab._refresh()
        elif current is self.filesystems_tab:
            self.filesystems_tab.refresh()
        elif current is self.usage_tab and self.controller.ssh.connected:
            # _scan() pops up a "select a root path" dialog when no path
            # is set yet, checked *before* its own connection check, so
            # unlike the other two this one still needs to be skipped
            # while disconnected rather than shown a proper status.
            self.usage_tab._scan()

    def on_show(self):
        """Called when the Storage hub tab itself becomes active — refresh
        whichever sub-tab is currently selected."""
        self._on_subtab_changed()
