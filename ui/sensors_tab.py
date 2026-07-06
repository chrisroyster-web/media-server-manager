# ui/sensors_tab.py
"""
Hardware Sensors tab.
- CPU / motherboard temps via `sensors -j` (lm-sensors)
- GPU via `nvidia-smi`
- HDD temps via smartctl
Keeps a rolling history (last 60 readings) per sensor for sparklines.
"""

import json
import shlex
import time
import threading
import tkinter as tk
from tkinter import ttk

from ui.refresh_control import RefreshControl


_HISTORY_LEN = 60   # readings to keep per sensor


def _color_temp(t_val, theme):
    """Return a colour string based on temperature value."""
    if t_val is None:
        return theme.text_muted
    if t_val >= 80:
        return theme.status_stopped
    if t_val >= 65:
        return theme.yellow
    return theme.status_running


def _spark(vals, width=20, height=14):
    """Return (canvas_data, min_v, max_v) for a simple line sparkline."""
    return vals


class SensorsTab(tk.Frame):

    def __init__(self, parent, controller):
        t = controller.theme
        super().__init__(parent, bg=t.bg)
        self.controller = controller
        self.theme      = t
        self._history   = {}   # key → deque-like list of float
        self._cards     = {}   # key → {"lbl_val", "lbl_unit", "canvas"}
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        t = self.theme

        # Header
        hdr = tk.Frame(self, bg=t.bg)
        hdr.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(hdr, text="HARDWARE SENSORS", bg=t.bg, fg=t.text,
                 font=t.font_title).pack(side="left")
        self._rc = RefreshControl(hdr, self.controller, "sensors",
                                  default=15, on_refresh=self.refresh)
        self._rc.pack(side="right")
        btn = tk.Button(hdr, text="⟳ Refresh", command=self.refresh)
        t.style_button(btn)
        btn.pack(side="right", padx=(0, 8))
        self._last_lbl = tk.Label(hdr, text="", bg=t.bg, fg=t.text_muted,
                                   font=t.font_small)
        self._last_lbl.pack(side="right", padx=12)

        # Scrollable body
        outer = tk.Frame(self, bg=t.bg)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=t.bg, highlightthickness=0)
        vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._scroll_canvas = canvas
        self._body = tk.Frame(canvas, bg=t.bg)
        self._body_win = canvas.create_window((0, 0), window=self._body,
                                               anchor="nw")
        self._body.bind("<Configure>",
                        lambda e: canvas.configure(
                            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(
                        self._body_win, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(
                        int(-1 * (e.delta / 120)), "units"))

        # Section frames (created lazily in _populate)
        self._cpu_frame  = None
        self._gpu_frame  = None
        self._hdd_frame  = None

        # Status bar
        self._status = tk.Label(self, text="Connect to server to read sensors",
                                bg=t.surface_dark, fg=t.text_muted,
                                font=t.font_small, anchor="w")
        self._status.pack(fill="x", padx=16, pady=(4, 8))

    # -----------------------------------------------------------------------
    # REFRESH
    # -----------------------------------------------------------------------
    def refresh(self):
        if getattr(self, "_fetching", False):
            return
        self._rc.cancel()
        if not self.controller.ssh.connected:
            self._status.config(text="Not connected",
                                bg=self.theme.surface_dark,
                                fg=self.theme.status_stopped)
            return
        self._status.config(text="Reading sensors…",
                            bg=self.theme.blue, fg="#ffffff")
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            ssh = self.controller.ssh
            data = {}

            # --- lm-sensors ---
            out, _, code = ssh.run("sensors -j 2>/dev/null")
            if code == 0 and out.strip():
                try:
                    data["lm"] = json.loads(out)
                except json.JSONDecodeError:
                    data["lm"] = {}
            else:
                data["lm"] = {}

            # --- nvidia-smi ---
            nv_cmd = (
                "nvidia-smi "
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "utilization.memory,memory.used,memory.total,power.draw "
                "--format=csv,noheader,nounits 2>/dev/null"
            )
            nv_out, _, nv_code = ssh.run(nv_cmd)
            data["nvidia"] = []
            if nv_code == 0 and nv_out.strip():
                for line in nv_out.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 6:
                        try:
                            data["nvidia"].append({
                                "name":    parts[0],
                                "temp":    float(parts[1]) if parts[1] not in ("[N/A]", "") else None,
                                "gpu_util": float(parts[2]) if parts[2] not in ("[N/A]", "") else None,
                                "mem_util": float(parts[3]) if parts[3] not in ("[N/A]", "") else None,
                                "mem_used": float(parts[4]) if parts[4] not in ("[N/A]", "") else None,
                                "mem_total":float(parts[5]) if parts[5] not in ("[N/A]", "") else None,
                                "power":    float(parts[6]) if len(parts) > 6 and parts[6] not in ("[N/A]", "") else None,
                            })
                        except (ValueError, IndexError):
                            pass

            # --- HDD temps via smartctl ---
            disk_out, _, _ = ssh.run(
                "lsblk -d -n -o NAME,TYPE 2>/dev/null | awk '$2==\"disk\"{print $1}'")
            data["hdds"] = []
            for disk in disk_out.splitlines():
                disk = disk.strip()
                if not disk:
                    continue
                t_out, _, t_code = ssh.run_sudo(
                    "smartctl -A {} 2>/dev/null | grep -i 'temperature'".format(
                        shlex.quote("/dev/" + disk)))
                temp = None
                if t_code == 0:
                    for l in t_out.splitlines():
                        m_parts = l.split()
                        if len(m_parts) >= 10:
                            try:
                                temp = float(m_parts[9])
                                break
                            except (ValueError, IndexError):
                                pass
                data["hdds"].append({"name": "/dev/" + disk, "temp": temp})

            self.after(0, lambda: self._populate(data))
            self.after(0, lambda: self._last_lbl.config(
                text="Updated {}".format(time.strftime("%H:%M"))))
            self.after(0, self._rc.schedule)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status.config(
                text="Could not read sensor data: {}".format(msg),
                bg=self.theme.surface_dark,
                fg=self.theme.status_stopped))
            self.after(0, self._rc.schedule)
        finally:
            self._fetching = False

    # -----------------------------------------------------------------------
    # POPULATE
    # -----------------------------------------------------------------------
    def _populate(self, data):
        t = self.theme
        # Clear body
        for w in self._body.winfo_children():
            w.destroy()
        self._cards = {}

        any_data = False

        # ---- lm-sensors ----
        lm = data.get("lm", {})
        if lm:
            any_data = True
            self._section_header("CPU / MOTHERBOARD SENSORS")
            for chip_name, chip_data in lm.items():
                chip_lbl = tk.Label(self._body, text=chip_name,
                                    bg=t.bg, fg=t.text_muted,
                                    font=("Segoe UI", 8, "bold"))
                chip_lbl.pack(anchor="w", padx=20, pady=(4, 2))
                card_row = tk.Frame(self._body, bg=t.bg)
                card_row.pack(fill="x", padx=16, pady=(0, 4))
                for feature_name, feature_data in chip_data.items():
                    if not isinstance(feature_data, dict):
                        continue
                    # Find the primary reading (highest priority sub-feature)
                    val = None
                    unit = "°C"
                    for sub_key, sub_val in feature_data.items():
                        if "_input" in sub_key and isinstance(sub_val, (int, float)):
                            val = sub_val
                            if "fan" in sub_key.lower():
                                unit = "RPM"
                            elif "volt" in sub_key.lower() or "in" in sub_key.lower():
                                unit = "V"
                            break
                    if val is None:
                        continue
                    key = "{}.{}".format(chip_name, feature_name)
                    self._push_history(key, val)
                    self._make_card(card_row, key, feature_name, val, unit)

        # ---- nvidia ----
        gpus = data.get("nvidia", [])
        if gpus:
            any_data = True
            self._section_header("GPU (NVIDIA)")
            for i, gpu in enumerate(gpus):
                gpu_name = gpu.get("name", "GPU {}".format(i))
                glbl = tk.Label(self._body, text=gpu_name,
                                bg=t.bg, fg=t.text_muted,
                                font=("Segoe UI", 8, "bold"))
                glbl.pack(anchor="w", padx=20, pady=(4, 2))
                card_row = tk.Frame(self._body, bg=t.bg)
                card_row.pack(fill="x", padx=16, pady=(0, 4))
                fields = [
                    ("gpu_temp",  "GPU Temp",   gpu.get("temp"),   "°C"),
                    ("gpu_util",  "GPU Util",   gpu.get("gpu_util"), "%"),
                    ("mem_util",  "Mem Util",   gpu.get("mem_util"), "%"),
                    ("mem_used",  "VRAM Used",  gpu.get("mem_used"), "MB"),
                    ("power",     "Power",      gpu.get("power"),  "W"),
                ]
                for sub_key, label, val, unit in fields:
                    if val is None:
                        continue
                    key = "gpu{}.{}".format(i, sub_key)
                    self._push_history(key, val)
                    self._make_card(card_row, key, label, val, unit)

        # ---- HDD temps ----
        hdds = [h for h in data.get("hdds", []) if h["temp"] is not None]
        if hdds:
            any_data = True
            self._section_header("DISK TEMPERATURES")
            card_row = tk.Frame(self._body, bg=t.bg)
            card_row.pack(fill="x", padx=16, pady=(0, 8))
            for hdd in hdds:
                key = "hdd." + hdd["name"]
                self._push_history(key, hdd["temp"])
                self._make_card(card_row, key, hdd["name"], hdd["temp"], "°C")

        if not any_data:
            tk.Label(self._body,
                     text="No sensor data found.\n\n"
                          "Install lm-sensors (sudo apt install lm-sensors && sudo sensors-detect)\n"
                          "and/or nvidia-smi for GPU data.",
                     bg=t.bg, fg=t.text_muted, font=t.font_regular,
                     justify="center").pack(pady=40)

        self._status.config(
            text="{} sensor reading{}".format(
                len(self._cards), "s" if len(self._cards) != 1 else ""),
            bg=t.surface_dark, fg=t.text_muted)

    def _section_header(self, text):
        t = self.theme
        tk.Frame(self._body, bg=t.surface_dark, height=1).pack(
            fill="x", padx=16, pady=(12, 4))
        tk.Label(self._body, text=text, bg=t.bg, fg=t.text_muted,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=20, pady=(0, 4))

    def _make_card(self, parent, key, label, val, unit):
        t = self.theme
        is_temp = unit == "°C"
        color = _color_temp(val if is_temp else None, t)

        card = tk.Frame(parent, bg=t.card_bg,
                        highlightbackground=t.card_border,
                        highlightthickness=1)
        card.pack(side="left", padx=(0, 8), pady=4, ipadx=12, ipady=8)

        tk.Label(card, text=label, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(anchor="w")

        val_frame = tk.Frame(card, bg=t.card_bg)
        val_frame.pack(anchor="w")

        val_str = "{:.0f}".format(val) if isinstance(val, float) and val == int(val) \
                  else "{:.1f}".format(val) if isinstance(val, float) else str(val)
        lbl_val = tk.Label(val_frame, text=val_str, bg=t.card_bg, fg=color,
                           font=("Segoe UI Semibold", 18))
        lbl_val.pack(side="left")
        tk.Label(val_frame, text=unit, bg=t.card_bg, fg=t.text_muted,
                 font=t.font_small).pack(side="left", padx=(2, 0), anchor="s")

        # Mini sparkline canvas
        hist = self._history.get(key, [])
        spark_c = tk.Canvas(card, bg=t.card_bg, width=80, height=24,
                            highlightthickness=0)
        spark_c.pack(anchor="w", pady=(2, 0))
        self._draw_spark(spark_c, hist, color)
        self._cards[key] = {"lbl": lbl_val, "canvas": spark_c,
                            "color_fn": lambda v, u=unit, is_t=is_temp:
                                _color_temp(v if is_t else None, self.theme),
                            "unit": unit}

    def _push_history(self, key, val):
        if key not in self._history:
            self._history[key] = []
        h = self._history[key]
        h.append(val)
        if len(h) > _HISTORY_LEN:
            h.pop(0)

    def _draw_spark(self, canvas, hist, color):
        canvas.delete("all")
        w = 80
        h = 24
        if len(hist) < 2:
            return
        mn = min(hist)
        mx = max(hist)
        rng = mx - mn or 1
        pts = []
        for i, v in enumerate(hist):
            x = int(i * w / (len(hist) - 1))
            y = int(h - (v - mn) / rng * (h - 4) - 2)
            pts.extend([x, y])
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=1.5, smooth=True)

    def on_show(self):
        if self.controller.ssh.connected:
            self.refresh()
