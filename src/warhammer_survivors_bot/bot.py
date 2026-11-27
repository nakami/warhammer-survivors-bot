"""The automatic player: capture -> understand -> act, on a background thread."""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2

from warhammer_survivors_bot import inputs, levelup, window
from warhammer_survivors_bot.capture import CaptureError, Capturer
from warhammer_survivors_bot.settings import LABELS, Settings
from warhammer_survivors_bot.steering import DIRECTIONS, Steering
from warhammer_survivors_bot.vision import PLAYER_POS, Screen, Vision

# Arrow keys are layout independent, so they are used for movement.
_DIR_KEYS = {
    "stay": (), "up": ("up",), "down": ("down",), "left": ("left",), "right": ("right",),
    "up-left": ("up", "left"), "up-right": ("up", "right"),
    "down-left": ("down", "left"), "down-right": ("down", "right"),
}
_ARROWS = ("up", "down", "left", "right")


# Screens that are passed with a single key press or click, on the way to a new run.
_MENU_ACTIONS: dict[Screen, tuple[tuple, str]] = {
    Screen.WARNING: (("key", "enter"), ""),
    Screen.TITLE: (("click", 960, 667), ""),
    Screen.UNIVERSE: (("click", 335, 957), "Universe select: starting Warhammer 40,000."),
    Screen.MAIN_MENU: (("click", 287, 207), "Main menu: starting a new run."),
    Screen.CHARACTER_SELECT: (("key", "enter"), "Character select: keeping last character."),
    Screen.MISSION_SELECT: (("key", "enter"), "Mission select: starting last mission."),
    Screen.GAME_OVER: (("key", "enter"), "Game over: continuing."),
    Screen.RECAP: (("key", "enter"), "Recap: continuing."),
}

STOP_HOTKEY_VK = 0x77  # F8
_user32 = ctypes.WinDLL("user32")

Log = Callable[[str], None]
Status = Callable[[dict], None]


class Bot:
    def __init__(self, log: Log = print, status: Status = lambda s: None,
                 debug_dir: Path = Path("screenshots"),
                 settings: Settings | None = None, overlay_every: float = 0.0) -> None:
        # Save an annotated frame every N seconds during runs (0 = off); for tuning.
        self.overlay_every = overlay_every
        # Read on every frame, so toggles take effect while the bot is running.
        self.settings = settings or Settings()
        self._log = log
        self._status = status
        self._debug_dir = debug_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held: set[str] = set()

    # ---- lifecycle -------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- input helpers ---------------------------------------------------------
    def _set_direction(self, direction: str) -> None:
        wanted = set(_DIR_KEYS[direction])
        for key in self._held - wanted:
            inputs.key_up(key)
        for key in wanted - self._held:
            inputs.key_down(key)
        self._held = wanted

    def _release_all(self) -> None:
        for key in self._held | set(_ARROWS):
            inputs.key_up(key)
        self._held = set()

    def _save_debug(self, img, name: str) -> None:
        self._debug_dir.mkdir(exist_ok=True)
        path = self._debug_dir / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.png"
        cv2.imwrite(str(path), img)
        self._log(f"Saved screenshot {path}")

    def _save_overlay(self, img, objs, decision, hp) -> None:
        """Annotated frame: what the bot detected and which way it decided to go."""
        vis = img.copy()
        for ex, ey, area in objs.enemies:
            r = max(8, int(area ** 0.5 / 2))
            cv2.rectangle(vis, (ex - r, ey - r), (ex + r, ey + r), (255, 0, 255), 2)
        for gx, gy in objs.xp:
            cv2.circle(vis, (gx, gy), 6, (255, 255, 0), 2)
        if decision.target:
            cv2.circle(vis, decision.target, 16, (0, 255, 0), 3)
        px, py = PLAYER_POS
        dx, dy = DIRECTIONS[decision.direction]
        cv2.arrowedLine(vis, (px, py), (int(px + dx * 120), int(py + dy * 120)),
                        (0, 255, 255), 4, tipLength=0.3)
        hp_s = "?" if hp is None else f"{hp:.0%}"
        cv2.putText(vis, f"{decision.direction} hp={hp_s} foes={len(objs.enemies)} "
                    f"xp={len(objs.xp)}", (120, 1060), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (255, 255, 255), 2)
        folder = self._debug_dir / "overlay"
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / f"ov_{time.strftime('%H%M%S')}.jpg"), vis,
                    [cv2.IMWRITE_JPEG_QUALITY, 80])

    def _save_levelup(self, img) -> None:
        """Keep level-up screens (small JPEGs) to verify and improve the card reader."""
        folder = self._debug_dir / "levelups"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"levelup_{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    def _pause_if_in_run(self) -> None:
        """Leave a running game paused, so the character does not die unattended."""
        hwnd = window.find_window()
        if hwnd is None:
            return
        if not window.is_foreground(hwnd):
            window.focus(hwnd)  # clicking Stop in the UI moves focus away from the game
            time.sleep(0.3)
            if not window.is_foreground(hwnd):
                return
        capturer = Capturer()
        try:
            img = capturer.grab(hwnd)
        finally:
            capturer.close()
        if Vision().screen(img)[0] == Screen.IN_RUN:
            inputs.press("esc")
            self._log("Paused the game.")

    # ---- main loop -------------------------------------------------------------
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # surface errors in the UI instead of dying silently
            self._log(f"ERROR: {exc!r}")
            raise
        finally:
            self._release_all()
            self._pause_if_in_run()
            self._status({"state": "stopped"})
            self._log("Bot stopped.")

    def _loop(self) -> None:
        self._log("Bot started. Press F8 or Stop to halt.")
        vision = Vision()
        steering = Steering()
        capturer = Capturer()

        hwnd = window.find_window()
        if hwnd is None:
            self._log("Game window not found. Start the game first.")
            return
        window.focus(hwnd)
        time.sleep(0.3)

        last_screen: Screen | None = None
        last_action = 0.0
        last_report = 0.0
        unknown_since: float | None = None
        unknown_saved = False
        was_foreground = True
        frames, fps_t0, fps = 0, time.monotonic(), 0.0
        run_started: float | None = None
        told_waiting: set[Screen] = set()
        screen_since = 0.0
        last_overlay = 0.0
        last_levelup: levelup.LevelUp | None = None

        while not self._stop.is_set():
            if _user32.GetAsyncKeyState(STOP_HOTKEY_VK) & 0x8000:
                self._log("F8 pressed.")
                break

            hwnd = window.find_window()
            if hwnd is None:
                self._log("Game window disappeared.")
                break
            if not window.is_foreground(hwnd):
                # Never send input to other applications.
                if was_foreground:
                    self._release_all()
                    self._log("Game not in foreground; waiting (click the game to resume).")
                    self._status({"state": "waiting for focus"})
                was_foreground = False
                time.sleep(0.2)
                continue
            if not was_foreground:
                self._log("Game focused again; resuming.")
                was_foreground = True

            rect = window.client_rect(hwnd)
            try:
                img = capturer.grab(hwnd)
            except CaptureError as exc:
                self._log(f"Capture failed ({exc}); retrying.")
                time.sleep(1.0)
                continue
            screen, _ = vision.screen(img)
            now = time.monotonic()

            frames += 1
            if now - fps_t0 >= 1.0:
                fps, frames, fps_t0 = frames / (now - fps_t0), 0, now

            if screen != last_screen:
                self._log(f"Screen: {screen.value}")
                told_waiting.clear()
                screen_since = now
                if screen == Screen.IN_RUN and run_started is None:
                    run_started = now
                if screen in (Screen.MAIN_MENU, Screen.MISSION_SELECT):
                    run_started = None
                last_screen = screen
                unknown_since = now if screen == Screen.UNKNOWN else None
                unknown_saved = False

            status = {"state": screen.value, "fps": round(fps, 1)}
            menu_ready = now - last_action > 1.5
            s = self.settings

            def wait_for_user(reason: str) -> None:
                if screen not in told_waiting:
                    self._log(f"{screen.value}: {reason}; leaving this screen to you.")
                    told_waiting.add(screen)

            if self._held and (screen != Screen.IN_RUN or not s.move):
                self._release_all()

            if screen == Screen.IN_RUN and not s.move:
                status["direction"] = "off"
            elif screen == Screen.IN_RUN:
                objs = vision.objects(img)
                steering.observe_motion(img, now)
                hp = vision.health(img)
                decision = steering.decide(objs, now, hp)
                self._set_direction(decision.direction)
                status.update(direction=decision.direction, enemies=len(objs.enemies),
                              xp=len(objs.xp), health=None if hp is None else round(hp * 100))
                if now - last_report > 3.0:
                    near = ("-" if decision.nearest_enemy == float("inf")
                            else f"{decision.nearest_enemy:.0f}")
                    hp_s = "?" if hp is None else f"{hp:.0%}"
                    blocked = ",".join(steering.blocked(now))
                    self._log(f"{decision.direction:<10} foes {len(objs.enemies):<3} "
                              f"xp {len(objs.xp):<3} near {near:<4} hp {hp_s}"
                              + (f"  wall: {blocked}" if blocked else ""))
                    last_report = now
                if self.overlay_every and now - last_overlay > self.overlay_every:
                    self._save_overlay(img, objs, decision, hp)
                    last_overlay = now
            elif screen == Screen.GAME_OVER and run_started is not None:
                survived = int(now - run_started)
                self._log(f"GAME OVER after ~{survived // 60}:{survived % 60:02d} of play.")
                run_started = None
            elif screen == Screen.LEVEL_UP:
                if not s.pick_level_ups:
                    wait_for_user(f"'{LABELS['pick_level_ups']}' is off")
                else:
                    # The cards fade and slide in, so only act once two frames
                    # >1 s into the screen read the same (or after 4 s regardless).
                    state = levelup.read(img)
                    settled = (now - screen_since > 1.0 and state == last_levelup
                               and bool(state.cards))
                    last_levelup = state
                    if (settled or now - screen_since > 4.0) and menu_ready:
                        card = levelup.choose(state)
                        if screen not in told_waiting:  # once per level-up screen
                            self._save_levelup(img)
                            offered = ", ".join(c.kind for c in state.cards) or "unreadable"
                            self._log(f"Level up: offered [{offered}], own {state.weapons} "
                                      f"weapons / {state.passives} passives.")
                            told_waiting.add(screen)
                        # First click highlights the card, a second click 1.5 s later
                        # (if the screen is still open) confirms the same card.
                        index = card.index if card else 0
                        x, y = levelup.CARD_CENTERS[index]
                        self._log(f"Level up: taking card {index + 1}"
                                  + (f" ({card.kind})." if card else " (fallback)."))
                        inputs.click(rect.left + x, rect.top + y)
                        last_action = now
            elif screen == Screen.WARGEAR:
                if not s.open_chests:
                    wait_for_user(f"'{LABELS['open_chests']}' is off")
                elif menu_ready:
                    self._log("Wargear chest: pressing Enter (Open / Accept).")
                    inputs.press("enter")
                    last_action = now
            elif screen == Screen.PAUSED and menu_ready:
                self._log("Game is paused: resuming.")
                inputs.press("esc")
                last_action = now
            elif screen == Screen.ENHANCEMENTS:
                if s.buy_enhancements:
                    # Not implemented yet: purchases need an affordable upgrade to be
                    # observed first. Never guess when spending the player's coins.
                    wait_for_user("buying enhancements is not implemented yet")
                elif not s.auto_restart:
                    wait_for_user(f"'{LABELS['auto_restart']}' is off")
                elif menu_ready:
                    self._log("Enhancements: pressing Enter (Finish) without buying.")
                    inputs.press("enter")
                    last_action = now
            elif screen in _MENU_ACTIONS:
                if not s.auto_restart:
                    wait_for_user(f"'{LABELS['auto_restart']}' is off")
                elif menu_ready:
                    action, message = _MENU_ACTIONS[screen]
                    if message:
                        self._log(message)
                    if action[0] == "key":
                        inputs.press(action[1])
                    else:
                        inputs.click(rect.left + action[1], rect.top + action[2])
                    last_action = now
            elif screen == Screen.UNKNOWN:
                # Unknown screen (e.g. game over, chest, dialog): do nothing, keep evidence.
                if unknown_since and not unknown_saved and now - unknown_since > 2.0:
                    self._log("Unknown screen for 2s; not acting.")
                    self._save_debug(img, "unknown")
                    unknown_saved = True

            if run_started is not None:
                status["run_time"] = int(now - run_started)
            self._status(status)
            time.sleep(0.01)
