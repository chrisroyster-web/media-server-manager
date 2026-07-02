# ui/loading_spinner.py
"""Small animated arc spinner widget."""

import tkinter as tk


class LoadingSpinner(tk.Canvas):
    """
    Rotating arc spinner. Drop into any frame:
        spinner = LoadingSpinner(parent, theme)
        spinner.pack(side="right", padx=4)
        spinner.start()   # begin animation
        spinner.stop()    # freeze and hide
    """

    def __init__(self, parent, theme, size=18, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=theme.bg, highlightthickness=0, **kw)
        self._color = theme.blue
        self._size  = size
        self._angle = 0
        self._job   = None
        pad = 2
        self._arc = self.create_arc(
            pad, pad, size - pad, size - pad,
            start=0, extent=250,
            outline=self._color, width=2,
            style="arc",
        )
        self.place_forget()   # hidden until start() is called

    def start(self):
        self.pack(side="right", padx=(0, 6))
        self._animate()

    def stop(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        try:
            self.pack_forget()
        except Exception:
            pass

    def _animate(self):
        self._angle = (self._angle + 10) % 360
        self.itemconfig(self._arc, start=self._angle)
        self._job = self.after(25, self._animate)
