"""Minimal control window: Start / Stop and a live view of what the bot is doing."""

from __future__ import annotations

import os
import queue
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from warhammer_survivors_bot import __version__, runstate, window
from warhammer_survivors_bot.bot import Bot
from warhammer_survivors_bot.settings import LABELS, Settings

_WIDTH, _HEIGHT = 540, 820

# Banner colours (background, foreground).
_IDLE = ("#e0e0e0", "#404040")
_OWN = ("#2e7d32", "#ffffff")       # running, started from this window
_EXTERNAL = ("#e65100", "#ffffff")  # running, started elsewhere (test run)

_STATUS_FIELDS = [
    ("state", "State"), ("direction", "Moving"), ("enemies", "Enemies"),
    ("xp", "XP pickups"), ("health", "Health %"), ("run_time", "Run time (s)"), ("fps", "FPS"),
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"Warhammer Survivors Bot v{__version__}")
        root.geometry(self._initial_geometry())
        root.attributes("-topmost", True)  # stay visible above the game window

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = Settings.load()
        self.bot = Bot(log=lambda m: self._events.put(("log", m)),
                       status=lambda s: self._events.put(("status", s)),
                       settings=self.settings, source="control window")
        self._external_pid: int | None = None

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.start_btn = ttk.Button(top, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(top, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Label(top, text="Hotkey: F8 stops the bot").pack(side="right")

        # Banner: is a bot running, and was it started here or by a script/test?
        banner = tk.Frame(root, bg=_IDLE[0])
        banner.pack(fill="x", padx=8, pady=(0, 8))
        self._banner = banner
        self._banner_text = tk.Label(banner, text="No bot running", bg=_IDLE[0], fg=_IDLE[1],
                                     font=("Segoe UI", 10, "bold"), anchor="w",
                                     justify="left", padx=8, pady=6, wraplength=400)
        self._banner_text.pack(side="left", fill="x", expand=True)
        self._stop_external_btn = ttk.Button(banner, text="Stop test run",
                                             command=self.stop_external)

        features = ttk.LabelFrame(root, text="Features (apply immediately)", padding=8)
        features.pack(fill="x", padx=8, pady=(0, 8))
        self._feature_vars: dict[str, tk.BooleanVar] = {}
        for i, (name, label) in enumerate(LABELS.items()):
            var = tk.BooleanVar(value=getattr(self.settings, name))
            ttk.Checkbutton(features, text=label, variable=var,
                            command=lambda n=name: self._toggle(n)).grid(
                row=i, column=0, sticky="w")
            self._feature_vars[name] = var

        grid = ttk.LabelFrame(root, text="Status", padding=8)
        grid.pack(fill="x", padx=8)
        self._vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(_STATUS_FIELDS):
            ttk.Label(grid, text=label + ":").grid(row=i // 2, column=(i % 2) * 2, sticky="w")
            var = tk.StringVar(value="-")
            ttk.Label(grid, textvariable=var, width=14).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(4, 16))
            self._vars[key] = var
        self._vars["state"].set("idle")

        self.log = scrolledtext.ScrolledText(root, height=14, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._poll)

    def _initial_geometry(self) -> str:
        """Place the window beside the game so it never covers what the bot sees."""
        w, h = _WIDTH, _HEIGHT
        screen_w = self.root.winfo_screenwidth()
        hwnd = window.find_window()
        if hwnd is None:
            return f"{w}x{h}+10+10"
        game = window.client_rect(hwnd)
        if game.left >= w + 20:                      # room on the left
            return f"{w}x{h}+{game.left - w - 16}+10"
        if screen_w - game.right >= w + 20:          # room on the right
            return f"{w}x{h}+{game.right + 16}+10"
        return f"{w}x{h}+10+10"

    def _overlaps_game(self) -> bool:
        hwnd = window.find_window()
        if hwnd is None:
            return False
        g = window.client_rect(hwnd)
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        return x < g.right and x + w > g.left and y < g.bottom and y + h > g.top

    def _toggle(self, name: str) -> None:
        value = self._feature_vars[name].get()
        setattr(self.settings, name, value)
        self.settings.save()
        self._append(f"{LABELS[name]}: {'on' if value else 'off'}")

    def start(self) -> None:
        for var in self._vars.values():
            var.set("-")
        if self._overlaps_game():
            self._append("WARNING: this window overlaps the game and hides part of what "
                         "the bot sees. Move it next to the game window.")
        self.bot.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def stop(self) -> None:
        self.bot.stop()

    def stop_external(self) -> None:
        if self._external_pid is not None:
            runstate.request_stop(self._external_pid)
            self._append(f"Asked the test run (PID {self._external_pid}) to stop.")

    def _update_banner(self) -> None:
        run = runstate.current()
        if self.bot.running:
            colors, text, external = _OWN, "Bot running (started from this window)", None
        elif run and run["pid"] != os.getpid():
            since = time.strftime("%H:%M:%S", time.localtime(run["started"]))
            colors = _EXTERNAL
            text = (f"TEST RUN in progress: {run['source']}\n"
                    f"PID {run['pid']} | since {since} | screen: {run['state']}")
            external = run["pid"]
        else:
            colors, text, external = _IDLE, "No bot running", None
        self._banner.configure(bg=colors[0])
        self._banner_text.configure(text=text, bg=colors[0], fg=colors[1])
        if external and self._external_pid is None:
            self._stop_external_btn.pack(side="right", padx=6, before=self._banner_text)
        elif not external and self._external_pid is not None:
            self._stop_external_btn.pack_forget()
        self._external_pid = external

    def close(self) -> None:
        self.bot.stop()
        self.root.after(300, self.root.destroy)

    def _append(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 1000:
            self.log.delete("1.0", "200.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        latest_status = None
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    self._append(str(payload))
                else:
                    latest_status = payload
        except queue.Empty:
            pass
        if latest_status is not None:
            for key, value in latest_status.items():
                if key in self._vars:
                    self._vars[key].set("-" if value is None else str(value))
        self._update_banner()
        if not self.bot.running:
            # Never start a second bot while a test run controls the game.
            self.start_btn.configure(state="disabled" if self._external_pid else "normal")
            self.stop_btn.configure(state="disabled")
        self.root.after(250, self._poll)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
