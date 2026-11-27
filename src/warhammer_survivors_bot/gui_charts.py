"""Small live line charts for the control window (plain Tk canvas, no extra deps).

Design (data-viz method): one y-axis per chart (never two scales), 2px lines
with round caps, an 8px end dot plus a direct end label with the current value
for each series, a legend for 2+ series, hairline solid gridlines in a gray one
step off the surface, text in text colors (never the series color), gaps where
there is no data (outside a run), and a hover crosshair that shows the values.
Series colors are categorical slots 1-2 of the reference palette, validated:
blue #257de0, orange #f47230 (orange is below 3:1 on white, hence the visible
end labels).
"""

from __future__ import annotations

import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field

SURFACE = "#ffffff"
GRID = "#e6e6e6"
TEXT_PRIMARY = "#191919"
TEXT_SECONDARY = "#666666"
SERIES_COLORS = ["#257de0", "#f47230"]  # categorical slots 1, 2 (fixed order)
FONT = ("Segoe UI", 8)
FONT_BOLD = ("Segoe UI", 9, "bold")


@dataclass
class Series:
    name: str
    color: str
    points: deque = field(default_factory=lambda: deque(maxlen=2000))  # (t, value|None)


class LiveChart(tk.Canvas):
    """A time-series line chart of the last `window` seconds."""

    def __init__(self, master, title: str, series: list[str], *, unit: str = "",
                 y_max: float | None = None, window: float = 180.0,
                 width: int = 496, height: int = 150) -> None:
        super().__init__(master, width=width, height=height, bg=SURFACE,
                         highlightthickness=0)
        self.title = title
        self.unit = unit
        self.fixed_max = y_max
        self.window = window
        self.w, self.h = width, height
        # Plot area: room for the title (top), ticks (left/bottom), end labels (right).
        self.left, self.right, self.top, self.bottom = 34, width - 92, 24, height - 20
        self.series = [Series(n, SERIES_COLORS[i]) for i, n in enumerate(series)]
        self._hover_x: int | None = None
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.redraw()

    # ---- data -----------------------------------------------------------------
    def add(self, values: list[float | None], t: float | None = None) -> None:
        """Append one sample per series; None leaves a gap in the line."""
        t = time.monotonic() if t is None else t
        for s, v in zip(self.series, values):
            s.points.append((t, v))

    def clear(self) -> None:
        for s in self.series:
            s.points.clear()
        self.redraw()

    # ---- drawing --------------------------------------------------------------
    def _y_max(self) -> float:
        if self.fixed_max is not None:
            return self.fixed_max
        peak = max((v for s in self.series for _, v in s.points if v is not None), default=0)
        for nice in (10, 20, 50, 100, 200, 300, 500, 1000):
            if peak <= nice:
                return nice
        return float(int(peak / 500 + 1) * 500)

    def _xy(self, t: float, v: float, now: float, ymax: float) -> tuple[float, float]:
        x = self.right - (now - t) / self.window * (self.right - self.left)
        y = self.bottom - min(v, ymax) / ymax * (self.bottom - self.top)
        return x, y

    def redraw(self) -> None:
        self.delete("all")
        now = time.monotonic()
        ymax = self._y_max()
        unit = f" ({self.unit})" if self.unit else ""
        self.create_text(4, 4, text=self.title + unit, anchor="nw", fill=TEXT_PRIMARY,
                         font=FONT_BOLD)
        # Legend (2+ series): short line key + name, in text color.
        if len(self.series) > 1:
            x = self.w - 4
            for s in reversed(self.series):
                item = self.create_text(x, 6, text=s.name, anchor="ne", fill=TEXT_SECONDARY,
                                        font=FONT)
                x0 = self.bbox(item)[0]
                self.create_line(x0 - 18, 12, x0 - 4, 12, fill=s.color, width=2,
                                 capstyle="round")
                x = x0 - 26
        # Gridlines and y ticks (0, half, max).
        for frac in (0.0, 0.5, 1.0):
            y = self.bottom - frac * (self.bottom - self.top)
            self.create_line(self.left, y, self.right, y, fill=GRID, width=1)
            self.create_text(self.left - 4, y, text=f"{ymax * frac:g}", anchor="e",
                             fill=TEXT_SECONDARY, font=FONT)
        # x ticks: minutes ago.
        for ago in range(0, int(self.window) + 1, 60):
            x = self.right - ago / self.window * (self.right - self.left)
            label = "now" if ago == 0 else f"-{ago // 60} min"
            self.create_text(x, self.bottom + 3, text=label, anchor="n",
                             fill=TEXT_SECONDARY, font=FONT)
        # Lines (gaps where value is None or the sample is older than the window).
        for s in self.series:
            run: list[float] = []
            for t, v in s.points:
                if now - t > self.window or v is None:
                    if len(run) >= 4:
                        self.create_line(*run, fill=s.color, width=2, capstyle="round",
                                         joinstyle="round")
                    run = []
                    continue
                run.extend(self._xy(t, v, now, ymax))
            if len(run) >= 4:
                self.create_line(*run, fill=s.color, width=2, capstyle="round",
                                 joinstyle="round")
        # End dots + direct end labels (current values), leader-free: labels that
        # would collide are shifted apart by at least one text line.
        ends = []
        for s in self.series:
            last = next(((t, v) for t, v in reversed(s.points) if v is not None
                         and now - t <= self.window), None)
            if last and now - last[0] < 3.0:
                x, y = self._xy(last[0], last[1], now, ymax)
                ends.append([y, x, s, last[1]])
        ends.sort(key=lambda e: e[0])
        gap = 13  # one text line
        for i in range(1, len(ends)):  # push apart downwards ...
            ends[i][0] = max(ends[i][0], ends[i - 1][0] + gap)
        if ends and ends[-1][0] > self.bottom:  # ... and keep inside the plot area
            ends[-1][0] = self.bottom
            for i in range(len(ends) - 2, -1, -1):
                ends[i][0] = min(ends[i][0], ends[i + 1][0] - gap)
        for label_y, x, s, v in ends:
            _, y = self._xy(0, v, 0, ymax)
            self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=s.color, outline=SURFACE, width=2)
            self.create_text(self.right + 8, label_y, text=f"{s.name} {v:g}", anchor="w",
                             fill=TEXT_PRIMARY, font=FONT)
        self._draw_hover(now, ymax)

    # ---- hover crosshair ------------------------------------------------------
    def _on_motion(self, event) -> None:
        self._set_hover(event.x if self.left <= event.x <= self.right else None)

    def _set_hover(self, x: int | None) -> None:
        self._hover_x = x
        self.redraw()

    def _draw_hover(self, now: float, ymax: float) -> None:
        if self._hover_x is None:
            return
        x = self._hover_x
        t = now - (self.right - x) / (self.right - self.left) * self.window
        self.create_line(x, self.top, x, self.bottom, fill=TEXT_SECONDARY, width=1)
        parts = []
        for s in self.series:
            near = min(s.points, key=lambda p: abs(p[0] - t), default=None)
            if near and abs(near[0] - t) < 2.0 and near[1] is not None:
                parts.append(f"{s.name} {near[1]:g}")
                _, y = self._xy(0, near[1], 0, ymax)
                self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=s.color, outline=SURFACE,
                                 width=2)
        ago = max(0, int(now - t))
        text = f"{ago // 60}:{ago % 60:02d} ago   " + ("   ".join(parts) or "no data")
        anchor = "nw" if x < self.w / 2 else "ne"
        item = self.create_text(x + (6 if anchor == "nw" else -6), self.top + 2, text=text,
                                anchor=anchor, fill=TEXT_PRIMARY, font=FONT)
        bx = self.bbox(item)
        bg = self.create_rectangle(bx[0] - 3, bx[1] - 2, bx[2] + 3, bx[3] + 2,
                                   fill=SURFACE, outline=GRID)
        self.tag_lower(bg, item)
