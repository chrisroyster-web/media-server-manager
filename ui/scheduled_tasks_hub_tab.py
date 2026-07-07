# ui/scheduled_tasks_hub_tab.py
"""
Unifies the two "things that run on a timer" views — server-side cron/
systemd timers/Docker schedules (CronTab) and the app's own local task
runner (SchedulerTab) — into one sidebar entry with an internal
sub-notebook, same pattern as ui/docker_hub_tab.py. They were previously
two separate sidebar entries ("Cron Jobs" / "Scheduler") whose in-tab
headers didn't even match those labels ("Server Jobs" / "Automation &
Scheduling"); this hub uses one consistent name throughout. The two
wrapped tabs are unchanged; each is just parented to this sub-notebook
instead of the main app notebook.
"""

import tkinter as tk
from tkinter import ttk

from ui.cron_tab import CronTab
from ui.scheduler_tab import SchedulerTab


class ScheduledTasksHubTab(tk.Frame):

    def __init__(self, parent, controller):
        super().__init__(parent, bg=controller.theme.bg)
        self.controller = controller
        self.theme = controller.theme
        self._build_ui()

    def _build_ui(self):
        t = self.theme
        nb_style = ttk.Style()
        nb_style.configure("ScheduledTasksHub.TNotebook", background=t.bg, borderwidth=0)
        nb_style.configure("ScheduledTasksHub.TNotebook.Tab", background=t.surface,
                           foreground=t.text_muted, padding=[12, 6], font=t.font_small)
        nb_style.map("ScheduledTasksHub.TNotebook.Tab",
                     background=[("selected", t.surface_light)],
                     foreground=[("selected", t.text)])

        self._nb = ttk.Notebook(self, style="ScheduledTasksHub.TNotebook")
        self._nb.pack(fill="both", expand=True)

        self.server_jobs_tab = CronTab(self._nb, self.controller)
        self.automation_tab  = SchedulerTab(self._nb, self.controller)

        self._nb.add(self.server_jobs_tab, text="  Server Jobs  ")
        self._nb.add(self.automation_tab,  text="  Automation  ")

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    def _on_subtab_changed(self, _event=None):
        current = self._nb.nametowidget(self._nb.select())
        if current is self.server_jobs_tab:
            if self.controller.ssh.connected:
                self.server_jobs_tab.refresh()
        elif current is self.automation_tab:
            self.automation_tab.on_show()

    def on_show(self):
        """Called when the hub tab itself becomes active — refresh
        whichever sub-tab is currently selected."""
        self._on_subtab_changed()

    def current_subtab_is_automation(self):
        return self._nb.nametowidget(self._nb.select()) is self.automation_tab
