# ui/update_dialog.py
"""
Self-update dialog.

States
------
checking        Spinner label while the GitHub API call is in flight.
up_to_date      No newer release found.
update_available Version info + scrollable release notes + Download button.
downloading     Determinate progress bar; download running in background thread.
ready           Download complete — "Install Now & Restart" button.
error           Something went wrong — message + Retry button.
no_installer    Release has no .exe asset attached.
not_frozen      Running from source (dev mode) — show info but no download.
unconfigured    GITHUB_REPO constant not set.
"""

import sys
import threading
import tkinter as tk
from tkinter import ttk

import core.updater as updater


class UpdateDialog(tk.Toplevel):

    def __init__(self, parent, controller, current_version: str = ""):
        t = controller.theme
        super().__init__(parent)
        self.controller      = controller
        self.theme           = t
        self._current_version = current_version
        self._release        = None
        self._asset          = None
        self._dl_path        = None
        self._cancelled      = False

        self.title("Check for Updates")
        self.geometry("620x480")
        self.configure(bg=t.bg)
        self.resizable(False, False)
        self.transient(parent)

        # ── Accent bar ───────────────────────────────────────────────
        tk.Frame(self, bg=t.blue, height=4).pack(fill="x")

        # ── Header ───────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=t.surface_dark, padx=20, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Software Update",
                 bg=t.surface_dark, fg=t.text,
                 font=("Segoe UI Semibold", 14)).pack(side="left")
        self._state_badge = tk.Label(hdr, text="",
                                      bg=t.surface_dark, fg=t.text_muted,
                                      font=t.font_small)
        self._state_badge.pack(side="right")

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # ── Body ─────────────────────────────────────────────────────
        self._body = tk.Frame(self, bg=t.bg, padx=28, pady=20)
        self._body.pack(fill="both", expand=True)

        # Version row
        ver_row = tk.Frame(self._body, bg=t.bg)
        ver_row.pack(fill="x")

        self._icon_lbl = tk.Label(ver_row, text="⟳", bg=t.bg, fg=t.cyan,
                                   font=("Segoe UI", 28))
        self._icon_lbl.pack(side="left", padx=(0, 16))

        ver_info = tk.Frame(ver_row, bg=t.bg)
        ver_info.pack(side="left", fill="x", expand=True)
        self._headline = tk.Label(ver_info, text="Checking for updates…",
                                   bg=t.bg, fg=t.text,
                                   font=("Segoe UI Semibold", 12), anchor="w")
        self._headline.pack(anchor="w")
        self._subline  = tk.Label(ver_info,
                                   text="Current version: v{}".format(
                                       self._current_ver()),
                                   bg=t.bg, fg=t.text_muted,
                                   font=t.font_small, anchor="w")
        self._subline.pack(anchor="w")

        # Release notes (hidden until update found)
        self._notes_frame = tk.Frame(self._body, bg=t.bg)
        tk.Label(self._notes_frame, text="What's new:",
                 bg=t.bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w", pady=(12, 4))
        notes_inner = tk.Frame(self._notes_frame,
                                bg=t.surface_dark,
                                highlightbackground=t.card_border,
                                highlightthickness=1)
        notes_inner.pack(fill="both", expand=True)
        self._notes_txt = tk.Text(notes_inner, height=8,
                                   bg=t.surface_dark, fg=t.text,
                                   font=("Cascadia Code", 9) if self._font_ok() else ("Consolas", 9),
                                   wrap="word", relief="flat",
                                   bd=0, padx=10, pady=8,
                                   state="disabled",
                                   cursor="arrow")
        vsb = tk.Scrollbar(notes_inner, orient="vertical",
                            command=self._notes_txt.yview)
        self._notes_txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._notes_txt.pack(fill="both", expand=True)

        # Progress bar (hidden until download starts)
        self._prog_frame = tk.Frame(self._body, bg=t.bg)
        self._prog_bar   = ttk.Progressbar(self._prog_frame, orient="horizontal",
                                            mode="determinate", maximum=100)
        self._prog_bar.pack(fill="x")
        self._prog_lbl   = tk.Label(self._prog_frame, text="",
                                     bg=t.bg, fg=t.text_muted, font=t.font_small)
        self._prog_lbl.pack(anchor="e", pady=(4, 0))

        tk.Frame(self, bg=t.card_border, height=1).pack(fill="x")

        # ── Footer ───────────────────────────────────────────────────
        foot = tk.Frame(self, bg=t.surface_dark, padx=20, pady=12)
        foot.pack(fill="x")

        self._status_lbl = tk.Label(foot, text="",
                                     bg=t.surface_dark, fg=t.text_muted,
                                     font=t.font_small, anchor="w")
        self._status_lbl.pack(side="left", fill="x", expand=True)

        self._close_btn = tk.Button(foot, text="Close",
                                     command=self._on_close,
                                     bg=t.surface_light, fg=t.text,
                                     bd=0, relief="flat", font=t.font_regular,
                                     padx=14, pady=5, cursor="hand2")
        self._close_btn.pack(side="right")

        self._action_btn = tk.Button(foot, text="",
                                      command=self._noop,
                                      bg=t.blue, fg="#ffffff",
                                      bd=0, relief="flat", font=t.font_regular,
                                      padx=14, pady=5, cursor="hand2")
        # action_btn is shown only when there's an action to take

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

        # Centre on parent
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry("+{}+{}".format(px, py))

        # Kick off the check
        threading.Thread(target=self._do_check, daemon=True).start()

    # ----------------------------------------------------------------
    # CHECK
    # ----------------------------------------------------------------

    def _do_check(self):
        if not updater.is_configured():
            self.after(0, self._show_unconfigured)
            return
        release = updater.check_latest_release()
        if release is None:
            self.after(0, self._show_error, "Could not reach GitHub. Check your internet connection.")
            return
        self.after(0, lambda r=release: self._handle_release(r))

    def _handle_release(self, release):
        self._release = release
        tag  = release.get("tag_name", "")
        cur  = self._current_ver()

        if not updater.is_newer(tag, cur):
            self._show_up_to_date(tag)
            return

        asset = updater.find_installer_asset(release)
        self._asset = asset

        notes = (release.get("body") or "").strip() or "No release notes provided."
        self._show_update_available(tag, notes, has_installer=bool(asset))

    # ----------------------------------------------------------------
    # UI STATES
    # ----------------------------------------------------------------

    def _show_up_to_date(self, tag):
        self._icon_lbl.config(text="✓", fg=self.theme.status_running)
        self._headline.config(text="You're up to date")
        self._subline.config(
            text="v{} is the latest release.".format(self._current_ver()))
        self._state_badge.config(text=tag)
        self._status_lbl.config(text="No updates available.")

    def _show_update_available(self, tag, notes, has_installer):
        t = self.theme
        self._icon_lbl.config(text="↑", fg=t.blue)
        self._headline.config(
            text="v{} is available".format(tag.lstrip("v")),
            fg=t.blue)
        self._subline.config(
            text="You're running v{}.".format(self._current_ver()))
        self._state_badge.config(text="Update available", fg=t.blue)

        # Show release notes
        self._notes_txt.configure(state="normal")
        self._notes_txt.delete("1.0", "end")
        self._notes_txt.insert("1.0", notes)
        self._notes_txt.configure(state="disabled")
        self._notes_frame.pack(fill="both", expand=True, pady=(12, 0))

        if not getattr(sys, "frozen", False):
            # Running from source — can't run the installer
            self._status_lbl.config(
                text="Dev build — download from GitHub to update.")
            return

        if not has_installer:
            self._status_lbl.config(
                text="No installer asset found in this release.")
            return

        self._action_btn.config(text="Download & Install",
                                 command=self._start_download,
                                 bg=t.blue)
        self._action_btn.pack(side="right", padx=(0, 8))
        self._status_lbl.config(text="Ready to download  ({:.1f} MB)".format(
            self._asset.get("size", 0) / 1_048_576))

    def _show_error(self, msg):
        self._icon_lbl.config(text="✗", fg=self.theme.status_stopped)
        self._headline.config(text="Update check failed")
        self._subline.config(text=msg, fg=self.theme.status_stopped)
        self._status_lbl.config(text=msg)
        self._action_btn.config(text="Retry",
                                 command=self._retry,
                                 bg=self.theme.blue)
        self._action_btn.pack(side="right", padx=(0, 8))

    def _show_unconfigured(self):
        self._icon_lbl.config(text="⚙", fg=self.theme.yellow)
        self._headline.config(text="GitHub repository not configured")
        self._subline.config(
            text="Set GITHUB_REPO in core/updater.py to enable automatic updates.",
            fg=self.theme.text_muted)
        self._status_lbl.config(text="")

    # ----------------------------------------------------------------
    # DOWNLOAD
    # ----------------------------------------------------------------

    def _start_download(self):
        self._cancelled = False
        self._action_btn.config(state="disabled", text="Downloading…")
        self._prog_frame.pack(fill="x", pady=(16, 0))
        self._status_lbl.config(text="Connecting…")

        total_hint = self._asset.get("size", 0)
        url        = self._asset["browser_download_url"]

        def _on_progress(done, total):
            t = total or total_hint or 1
            pct  = min(done / t * 100, 100)
            done_mb  = done / 1_048_576
            total_mb = t    / 1_048_576
            self.after(0, lambda p=pct, d=done_mb, tt=total_mb:
                       self._update_progress(p, d, tt))

        def _worker():
            if self._cancelled:
                return
            path = updater.download_to_temp(url, total_hint, _on_progress)
            if self._cancelled:
                return
            if path:
                self.after(0, lambda p=path: self._download_done(p))
            else:
                self.after(0, lambda: self._show_error("Download failed. Check your connection."))

        threading.Thread(target=_worker, daemon=True).start()

    def _update_progress(self, pct, done_mb, total_mb):
        self._prog_bar.configure(value=pct)
        if total_mb:
            self._prog_lbl.config(
                text="{:.1f} / {:.1f} MB  ({:.0f}%)".format(done_mb, total_mb, pct))
        else:
            self._prog_lbl.config(text="{:.1f} MB".format(done_mb))

    def _download_done(self, path):
        self._dl_path = path
        self._prog_bar.configure(value=100)
        self._prog_lbl.config(text="Download complete.")
        self._status_lbl.config(
            text="The app will close, install the update, then restart.")
        self._action_btn.config(
            state="normal",
            text="Install Now & Restart",
            command=self._install_now,
            bg=self.theme.status_running)

    # ----------------------------------------------------------------
    # INSTALL
    # ----------------------------------------------------------------

    def _install_now(self):
        if not self._dl_path:
            return
        exe = sys.executable if getattr(sys, "frozen", False) else ""
        updater.launch_installer_and_exit(self._dl_path, exe)
        # Give the batch a moment to start, then kill this process
        self.controller.after(300, self._do_exit)

    def _do_exit(self):
        try:
            self.controller.tray.stop()
        except Exception:
            pass
        self.controller.destroy()
        sys.exit(0)

    # ----------------------------------------------------------------
    # HELPERS
    # ----------------------------------------------------------------

    def _retry(self):
        self._action_btn.pack_forget()
        self._headline.config(text="Checking for updates…",
                               fg=self.theme.text)
        self._subline.config(text="Current version: v{}".format(self._current_ver()),
                              fg=self.theme.text_muted)
        self._icon_lbl.config(text="⟳", fg=self.theme.cyan)
        self._status_lbl.config(text="")
        threading.Thread(target=self._do_check, daemon=True).start()

    def _on_close(self):
        self._cancelled = True
        self.destroy()

    def _noop(self):
        pass

    def _current_ver(self) -> str:
        return self._current_version or "?"

    @staticmethod
    def _font_ok() -> bool:
        try:
            import tkinter.font as tkf
            return "Cascadia Code" in tkf.families()
        except Exception:
            return False
