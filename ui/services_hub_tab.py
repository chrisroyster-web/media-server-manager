# ui/services_hub_tab.py
"""
Unifies the two service-lifecycle views — per-service start/stop/restart
with logs/tail (ServicesTab) and the ordered bulk restart sequence
(RestartSequenceTab) — into one sidebar entry with an internal
sub-notebook, same pattern as ui/docker_hub_tab.py. The two wrapped tabs
are unchanged; each is just parented to this sub-notebook instead of the
main app notebook.
"""

import tkinter as tk
from tkinter import ttk

from ui.services_tab import ServicesTab
from ui.restart_sequence_tab import RestartSequenceTab


class ServicesHubTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        nb_style = ttk.Style()
        nb_style.configure("ServicesHub.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("ServicesHub.TNotebook.Tab", background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("ServicesHub.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="ServicesHub.TNotebook")
        self._nb.pack(fill="both", expand=True)

        self.services_sub_tab = ServicesTab(self._nb, self.controller)
        self.restart_sequence_sub_tab = RestartSequenceTab(self._nb, self.controller)

        self._nb.add(self.services_sub_tab,         text="  Services  ")
        self._nb.add(self.restart_sequence_sub_tab, text="  Restart Sequence  ")

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    def _on_subtab_changed(self, _event=None):
        current = self._nb.nametowidget(self._nb.select())
        if current is self.services_sub_tab:
            self.services_sub_tab.refresh_all()
        elif current is self.restart_sequence_sub_tab:
            self.restart_sequence_sub_tab.on_show()

    def on_show(self):
        """Called when the Services hub tab itself becomes active — refresh
        whichever sub-tab is currently selected."""
        self._on_subtab_changed()

    def refresh_all(self):
        """Passthrough kept for existing call sites (e.g. quick_commands.py)
        that refresh the services list directly regardless of which
        sub-tab is currently showing."""
        self.services_sub_tab.refresh_all()
