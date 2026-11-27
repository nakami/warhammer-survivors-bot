"""Minimal control window: Start / Stop and a live view of what the bot is doing."""

from __future__ import annotations

import os
import queue
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from warhammer_survivors_bot import __version__, risk, runstate, window
from warhammer_survivors_bot.bot import Bot
from warhammer_survivors_bot.gui_charts import LiveChart
from warhammer_survivors_bot.learning import LEARNING_FILE, Learner
from warhammer_survivors_bot.runlog import RunHistory
from warhammer_survivors_bot.settings import LABELS, Settings

_WIDTH, _HEIGHT = 540, 1000

# Banner colours (background, foreground).
_IDLE = ("#e0e0e0", "#404040")
_OWN = ("#2e7d32", "#ffffff")       # running, started from this window
_EXTERNAL = ("#e65100", "#ffffff")  # running, started elsewhere (test run)

# Run table: (key, heading, width px, anchor)
_RUN_COLUMNS = [
    ("started", "Started", 86, "w"), ("play", "Play", 46, "e"), ("level", "Level", 44, "e"),
    ("chests", "Chests", 50, "e"), ("hits", "Hits", 40, "e"), ("minhp", "Min HP", 52, "e"),
    ("risk", "Risk", 44, "e"), ("bought", "Bought", 52, "e"), ("end", "End", 40, "center"),
]

_STATUS_FIELDS = [
    ("state", "State"), ("direction", "Moving"), ("enemies", "Enemies"),
    ("xp", "XP pickups"), ("health", "Health %"), ("run_time", "Run time (s)"), ("fps", "FPS"),
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(_TITLE)
        root.geometry(self._initial_geometry())
        root.attributes("-topmost", True)  # stay visible above the game window

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = Settings.load()
        self.bot = Bot(log=lambda m: self._events.put(("log", m)),
                       status=lambda s: self._events.put(("status", s)),
                       settings=self.settings, source="control window")
        self._external_pid: int | None = None
        self._showing_external = False
        self._ext_log_pos = 0

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

        # Situation: the bot's own assessment of how dangerous the moment is.
        situation = ttk.LabelFrame(root, text="Situation", padding=(8, 2))
        situation.pack(fill="x", padx=8, pady=(0, 8))
        self._mood_emoji = tk.Label(situation, text=risk.IDLE[0], font=("Segoe UI Emoji", 30))
        self._mood_emoji.pack(side="left", padx=(0, 10))
        right = ttk.Frame(situation)
        right.pack(side="left", fill="x", expand=True)
        self._mood_text = tk.StringVar(value=risk.IDLE[1])
        ttk.Label(right, textvariable=self._mood_text,
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self._risk_bar = ttk.Progressbar(right, maximum=100, value=0, length=360)
        self._risk_bar.pack(anchor="w", fill="x", pady=(2, 0))

        # Tabs: live view, run history, log.
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        live = ttk.Frame(tabs, padding=(0, 6, 0, 0))
        runs_tab = ttk.Frame(tabs, padding=(0, 6, 0, 0))
        log_tab = ttk.Frame(tabs, padding=(0, 6, 0, 0))
        tabs.add(live, text="Live")
        tabs.add(runs_tab, text="Last runs")
        learn_tab = ttk.Frame(tabs, padding=(0, 6, 0, 0))
        tabs.add(learn_tab, text="Learning")
        tabs.add(log_tab, text="Log")

        grid = ttk.LabelFrame(live, text="Status", padding=8)
        grid.pack(fill="x")
        self._vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(_STATUS_FIELDS):
            ttk.Label(grid, text=label + ":").grid(row=i // 2, column=(i % 2) * 2, sticky="w")
            var = tk.StringVar(value="-")
            ttk.Label(grid, textvariable=var, width=14).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(4, 16))
            self._vars[key] = var
        self._vars["state"].set("idle")

        stats = ttk.LabelFrame(live, text="Live statistics (last 3 minutes)", padding=(6, 4))
        stats.pack(fill="x", pady=(8, 0))
        self._chart_health = LiveChart(stats, "Health and risk", ["Health", "Risk"],
                                       unit="%", y_max=100)
        self._chart_health.pack(pady=(0, 4))
        self._chart_screen = LiveChart(stats, "On screen", ["Enemies", "XP pickups"],
                                       unit="count")
        self._chart_screen.pack()
        self._last_status: dict = {}
        root.after(500, self._sample_charts)

        # Last runs: one row per run, newest first (from runs.json).
        self._history = RunHistory()
        self._runs_mtime = None
        self._runs = ttk.Treeview(runs_tab, columns=[c[0] for c in _RUN_COLUMNS],
                                  show="headings", height=10)
        for key, heading, width, anchor in _RUN_COLUMNS:
            self._runs.heading(key, text=heading, anchor=anchor)
            self._runs.column(key, width=width, anchor=anchor, stretch=False)
        self._runs.pack(fill="x")
        self._runs_note = ttk.Label(
            runs_tab, foreground="#666666", wraplength=500, justify="left",
            text="Play = time actually spent in the run (without level-up, chest and "
                 "pause screens). Hits = health losses. Risk = average risk level. "
                 "Bought = enhancement ranks bought after the run. "
                 "† = run ended by game over, ⏸ = bot stopped during the run.")
        self._runs_note.pack(fill="x", pady=(8, 0))
        self._summary = tk.StringVar(value="")
        ttk.Label(runs_tab, textvariable=self._summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(8, 0))
        root.after(200, self._refresh_runs)

        # Learning: what learning mode found out so far (from learning.json).
        self._learn = ttk.Treeview(learn_tab, columns=("param", "value", "runs", "reward",
                                                       "best"), show="headings", height=15)
        for key, heading, width, anchor in (("param", "Parameter", 140, "w"),
                                            ("value", "Value", 60, "e"),
                                            ("runs", "Runs", 50, "e"),
                                            ("reward", "Avg reward", 80, "e"),
                                            ("best", "P(best)", 70, "e")):
            self._learn.heading(key, text=heading, anchor=anchor)
            self._learn.column(key, width=width, anchor=anchor, stretch=False)
        self._learn.pack(fill="x")
        self._learn_summary = tk.StringVar(value="No runs learned yet. Tick 'Learning mode'.")
        ttk.Label(learn_tab, textvariable=self._learn_summary, wraplength=500,
                  justify="left", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(learn_tab, foreground="#666666", wraplength=500, justify="left",
                  text="Each run in learning mode tries one value per parameter; values that "
                       "led to better runs are chosen more often. Reward = play minutes + "
                       "0.25 x level + 0.5 x chests. Only complete runs (started from the "
                       "menu, ended by game over) count. P(best) = how likely this value is "
                       "the best one, given the runs so far.").pack(anchor="w", pady=(8, 0))
        self._learn_mtime = None
        root.after(300, self._refresh_learning)

        self.log = scrolledtext.ScrolledText(log_tab, height=10, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._poll)

    def _refresh_learning(self) -> None:
        try:
            mtime = LEARNING_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None and mtime != self._learn_mtime:
            self._learn_mtime = mtime
            learner = Learner()
            self._learn.delete(*self._learn.get_children())
            last_param = None
            for param, value, n, mean, prob in learner.summary():
                name = param.lower().replace("_", " ") if param != last_param else ""
                last_param = param
                self._learn.insert("", "end", values=(name, f"{value:g}", n,
                                                      f"{mean:.1f}" if n else "-",
                                                      f"{prob:.0%}"))
            rewards = [h["reward"] for h in learner.history]
            if rewards:
                text = (f"{len(rewards)} run(s) learned, average reward "
                        f"{sum(rewards) / len(rewards):.1f}.")
                if len(rewards) >= 10:
                    first, last = rewards[:5], rewards[-5:]
                    text += (f" First 5 runs: {sum(first) / 5:.1f}, "
                             f"last 5 runs: {sum(last) / 5:.1f}.")
                self._learn_summary.set(text)
        self.root.after(5000, self._refresh_learning)

    def _refresh_runs(self) -> None:
        """Reload the run table when runs.json changed (also for script runs)."""
        try:
            mtime = self._history.path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._runs_mtime:
            self._runs_mtime = mtime
            runs = self._history.last(10)
            self._runs.delete(*self._runs.get_children())
            for r in runs:
                play = int(r.play_seconds)
                end = {"game over": "†", "stopped": "⏸"}.get(r.end, "▶")
                self._runs.insert("", "end", values=(
                    time.strftime("%d.%m. %H:%M", time.localtime(r.started)),
                    f"{play // 60}:{play % 60:02d}",
                    r.level, r.chests, r.hits,
                    "-" if r.min_health is None else f"{r.min_health:.0%}",
                    "-" if r.avg_risk is None else f"{r.avg_risk:.0%}",
                    r.purchases, end))
            finished = [r for r in runs if r.end == "game over"]
            if finished:
                avg = sum(r.play_seconds for r in finished) / len(finished)
                best = max(r.play_seconds for r in finished)
                self._summary.set(
                    f"{len(finished)} finished run(s) shown: average play time "
                    f"{int(avg) // 60}:{int(avg) % 60:02d}, best {int(best) // 60}:"
                    f"{int(best) % 60:02d}, average level "
                    f"{sum(r.level for r in finished) / len(finished):.1f}")
            else:
                self._summary.set("")
        self.root.after(2000, self._refresh_runs)

    def _sample_charts(self) -> None:
        """Every 0.5 s: add the latest values (gaps outside a run), redraw."""
        if self.bot.running or self._external_pid:
            st = self._last_status
            if st.get("state") == "in_run":
                self._chart_health.add([st.get("health"), st.get("risk")])
                self._chart_screen.add([st.get("enemies"), st.get("xp")])
            else:
                self._chart_health.add([None, None])
                self._chart_screen.add([None, None])
        self._chart_health.redraw()
        self._chart_screen.redraw()
        self.root.after(500, self._sample_charts)

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

    def _tail_external_log(self, pid: int) -> None:
        path = runstate.log_file(pid)
        try:
            with open(path, encoding="utf-8") as f:
                f.seek(self._ext_log_pos)
                chunk = f.read()
                self._ext_log_pos = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            self._append_raw(line)

    def _append_raw(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
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
        # A bot running in another process (e.g. a script test run) shares its live
        # status and log via the run-state files: show them as if it ran here.
        if latest_status is None and not self.bot.running:
            run = runstate.current()
            if run and run["pid"] != os.getpid():
                latest_status = run.get("status") or None
                self._tail_external_log(run["pid"])
                self._showing_external = True
            elif self._showing_external:
                latest_status = {"state": "stopped"}
                self._showing_external = False
                self._ext_log_pos = 0
        if latest_status is not None:
            self._last_status = latest_status
            for key, value in latest_status.items():
                if key in self._vars:
                    self._vars[key].set("-" if value is None else str(value))
            if "mood" in latest_status:
                self._mood_emoji.configure(text=latest_status["mood"])
                self._mood_text.set(f"{latest_status['mood_label']}  "
                                    f"(risk {latest_status['risk']}%)")
                self._risk_bar.configure(value=latest_status["risk"])
            elif latest_status.get("state") == "stopped":
                self._mood_emoji.configure(text=risk.IDLE[0])
                self._mood_text.set(risk.IDLE[1])
                self._risk_bar.configure(value=0)
        self._update_banner()
        if not self.bot.running:
            # Never start a second bot while a test run controls the game.
            self.start_btn.configure(state="disabled" if self._external_pid else "normal")
            self.stop_btn.configure(state="disabled")
        self.root.after(250, self._poll)


_MUTEX_NAME = "Local\\WarhammerSurvivorsBotControlWindow"
_TITLE = f"Warhammer Survivors Bot v{__version__}"


def _claim_single_instance():
    """Return a mutex handle if this is the only control window, else None.

    Two windows could each start a bot and each plug in a virtual controller,
    which would fight over the game.
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle  # kept open (and held) until the process exits


def main() -> None:
    mutex = _claim_single_instance()
    if mutex is None:
        existing = window.find_window(_TITLE, "python.exe")
        if existing:
            window.focus(existing)
        print("The control window is already open; brought it to the front.")
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
