# ui/empty_state.py
"""Reusable centered empty-state panel: icon + title + subtitle + optional CTA."""

import tkinter as tk


class EmptyState(tk.Frame):
    """
    Centered panel shown when a tab has no data to display.
    Place with pack(fill="both", expand=True) or place(relwidth=1, relheight=1).
    """

    def __init__(self, parent, theme, icon="📭", title="Nothing here yet",
                 subtitle="", action_text=None, action_cmd=None):
        super().__init__(parent, bg=theme.bg)
        t = theme

        inner = tk.Frame(self, bg=t.bg)
        inner.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(inner, text=icon, bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 38)).pack()

        tk.Label(inner, text=title, bg=t.bg, fg=t.text,
                 font=("Segoe UI Semibold", 14)).pack(pady=(12, 0))

        if subtitle:
            tk.Label(inner, text=subtitle, bg=t.bg, fg=t.text_muted,
                     font=("Segoe UI", 10), wraplength=320,
                     justify="center").pack(pady=(6, 0))

        if action_text and action_cmd:
            btn = tk.Button(inner, text=action_text, command=action_cmd)
            t.style_button(btn, "primary")
            btn.pack(pady=(20, 0))


class ErrorState(tk.Frame):
    """Centered error panel with an optional Retry button."""

    def __init__(self, parent, theme, message="Could not load data.", retry_cmd=None):
        super().__init__(parent, bg=theme.bg)
        t = theme

        inner = tk.Frame(self, bg=t.bg)
        inner.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(inner, text="⚠", bg=t.bg, fg=t.yellow,
                 font=("Segoe UI", 36)).pack()
        tk.Label(inner, text="Something went wrong", bg=t.bg, fg=t.text,
                 font=("Segoe UI Semibold", 13)).pack(pady=(10, 0))
        tk.Label(inner, text=message, bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 10), wraplength=340,
                 justify="center").pack(pady=(6, 0))

        if retry_cmd:
            btn = tk.Button(inner, text="↺  Retry", command=retry_cmd)
            t.style_button(btn)
            btn.pack(pady=(18, 0))
