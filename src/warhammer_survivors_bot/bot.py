"""The automatic player: capture -> understand -> act, on a background thread."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2

from warhammer_survivors_bot import levelup, runstate, window
from warhammer_survivors_bot.capture import CaptureError, Capturer
from warhammer_survivors_bot.controls import Controller, KeyboardMouse
from warhammer_survivors_bot.settings import LABELS, Settings
from warhammer_survivors_bot.steering import DIRECTIONS, Steering
from warhammer_survivors_bot.vision import PLAYER_POS, Screen, Vision

# Screens passed with one action on the way to a new run: (controls method, log message).
_MENU_ACTIONS: dict[Screen, tuple[str, str]] = {
    Screen.WARNING: ("confirm", ""),
    Screen.TITLE: ("title", ""),
    Screen.UNIVERSE: ("universe_start", "Universe select: starting Warhammer 40,000."),
    Screen.MAIN_MENU: ("main_menu_start", "Main menu: starting a new run."),
    Screen.CHARACTER_SELECT: ("confirm", "Character select: keeping last character."),
    Screen.MISSION_SELECT: ("confirm", "Mission select: starting last mission."),
    Screen.GAME_OVER: ("confirm", "Game over: continuing."),
    Screen.OBJECTIVES: ("confirm", "Completed objectives: continuing."),
    Screen.RECAP: ("confirm", "Recap: continuing."),
}

STOP_HOTKEY_VK = 0x77  # F8
_user32 = ctypes.WinDLL("user32")

Log = Callable[[str], None]
Status = Callable[[dict], None]


class Bot:
    def __init__(self, log: Log = print, status: Status = lambda s: None,
                 debug_dir: Path = Path("screenshots"),
                 settings: Settings | None = None, overlay_every: float = 0.0,
                 source: str = "script") -> None:
        # Who started this bot; shown by the control window ("control window"
        # for its own runs, anything else is displayed as a test/script run).
        self.source = source
        # Save an annotated frame every N seconds during runs (0 = off); for tuning.
        self.overlay_every = overlay_every
        # Read on every frame, so toggles take effect while the bot is running.
        self.settings = settings or Settings()
        self._log = log
        self._status = status
        self._debug_dir = debug_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._controller: Controller | None = None  # kept between runs (see Controller)
        self.controls: KeyboardMouse | Controller = KeyboardMouse(log)

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

    def _select_controls(self) -> None:
        if self.settings.background_mode:
            if self._controller is None:
                self._controller = Controller(self._log)
            self.controls = self._controller
        else:
            self.controls = KeyboardMouse(self._log)
        self.controls.open()
        self._log(f"Input: {self.controls.name}"
                  + ("" if self.controls.needs_focus else " (works while the game is unfocused)"))

    # ---- debug output ----------------------------------------------------------
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
        if self.controls.needs_focus and not window.is_foreground(hwnd):
            window.focus(hwnd)  # clicking Stop in the UI moves focus away from the game
            time.sleep(0.3)
            if not window.is_foreground(hwnd):
                return
        capturer = Capturer()
        try:
            img = capturer.grab(hwnd)
        except CaptureError:
            return
        finally:
            capturer.close()
        if Vision().screen(img)[0] == Screen.IN_RUN:
            self.controls.pause()
            self._log("Paused the game.")

    # ---- main loop -------------------------------------------------------------
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # surface errors in the UI instead of dying silently
            self._log(f"ERROR: {exc!r}")
            raise
        finally:
            try:
                self.controls.release()
                self._pause_if_in_run()
            finally:
                self.controls.close()
                runstate.clear()
                self._status({"state": "stopped"})
                self._log("Bot stopped.")

    def _loop(self) -> None:
        other = runstate.current()
        if other and other["pid"] != os.getpid():
            self._log(f"Another bot is already running ({other['source']}, PID "
                      f"{other['pid']}); not starting a second one.")
            return
        started_wall = time.time()
        runstate.heartbeat(self.source, started_wall, "starting")
        self._log("Bot started. Press F8 or Stop to halt.")
        if window.find_window() is None:
            self._log("Game window not found. Start the game first.")
            return
        self._select_controls()
        ctl = self.controls
        vision = Vision()
        steering = Steering()
        capturer = Capturer()

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
        last_beat = 0.0
        beat_state = "starting"

        while not self._stop.is_set():
            if time.monotonic() - last_beat > 0.5:
                runstate.heartbeat(self.source, started_wall, beat_state)
                last_beat = time.monotonic()
                if runstate.stop_requested():
                    self._log("Stop requested from the control window.")
                    break
            if _user32.GetAsyncKeyState(STOP_HOTKEY_VK) & 0x8000:
                self._log("F8 pressed.")
                break

            hwnd = window.find_window()
            if hwnd is None:
                self._log("Game window disappeared.")
                break
            if ctl.needs_focus and not window.is_foreground(hwnd):
                # Keyboard/mouse input would go to another application: wait.
                if was_foreground:
                    ctl.release()
                    self._log("Game not in foreground; waiting (click the game to resume).")
                    self._status({"state": "waiting for focus"})
                was_foreground = False
                time.sleep(0.2)
                continue
            if not was_foreground:
                self._log("Game focused again; resuming.")
                was_foreground = True

            try:
                img = capturer.grab(hwnd)
            except CaptureError as exc:
                ctl.release()
                self._status({"state": "cannot see game"})
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
            beat_state = screen.value
            menu_ready = now - last_action > 1.5
            s = self.settings

            def wait_for_user(reason: str) -> None:
                if screen not in told_waiting:
                    self._log(f"{screen.value}: {reason}; leaving this screen to you.")
                    told_waiting.add(screen)

            if ctl.moving and (screen != Screen.IN_RUN or not s.move):
                ctl.release()

            if screen == Screen.IN_RUN and not s.move:
                status["direction"] = "off"
            elif screen == Screen.IN_RUN:
                objs = vision.objects(img)
                steering.observe_motion(img, now)
                hp = vision.health(img)
                decision = steering.decide(objs, now, hp)
                ctl.move(decision.direction)
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
                every = self.overlay_every or (5.0 if s.debug_overlays else 0.0)
                if every and now - last_overlay > every:
                    self._save_overlay(img, objs, decision, hp)
                    last_overlay = now
            elif screen == Screen.DISCONNECTED and menu_ready:
                self._log("'Player disconnected' dialog: closing it.")
                ctl.confirm()
                last_action = now
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
                    # Controller navigation takes several small steps; clicks need
                    # time for the highlight-then-confirm sequence.
                    ready = now - last_action > (0.35 if not ctl.needs_focus else 1.5)
                    if (settled or now - screen_since > 4.0) and ready:
                        card = levelup.choose(state)
                        index = card.index if card else 0
                        if screen not in told_waiting:  # once per level-up screen
                            self._save_levelup(img)
                            offered = ", ".join(c.kind for c in state.cards) or "unreadable"
                            self._log(f"Level up: offered [{offered}], own {state.weapons} "
                                      f"weapons / {state.passives} passives; taking card "
                                      f"{index + 1}"
                                      + (f" ({card.kind})." if card else " (fallback)."))
                            told_waiting.add(screen)
                        ctl.select_card(index, levelup.highlighted(img), levelup.CARD_CENTERS)
                        last_action = now
            elif screen == Screen.WARGEAR:
                if not s.open_chests:
                    wait_for_user(f"'{LABELS['open_chests']}' is off")
                elif menu_ready:
                    self._log("Wargear chest: confirming (Open / Accept).")
                    ctl.confirm()
                    last_action = now
            elif screen == Screen.PAUSED and menu_ready:
                self._log("Game is paused: resuming.")
                ctl.resume()
                last_action = now
            elif screen == Screen.ENHANCEMENTS:
                if s.buy_enhancements:
                    # Not implemented yet: purchases need an affordable upgrade to be
                    # observed first. Never guess when spending the player's coins.
                    wait_for_user("buying enhancements is not implemented yet")
                elif not s.auto_restart:
                    wait_for_user(f"'{LABELS['auto_restart']}' is off")
                elif menu_ready:
                    # Confirm = "Finish", then confirm the "End Recap" dialog. Never
                    # anything else here (on a controller, Y would refund everything).
                    self._log("Enhancements: finishing without buying.")
                    ctl.confirm()
                    last_action = now
            elif screen in _MENU_ACTIONS:
                if not s.auto_restart:
                    wait_for_user(f"'{LABELS['auto_restart']}' is off")
                elif menu_ready:
                    method, message = _MENU_ACTIONS[screen]
                    if message:
                        self._log(message)
                    getattr(ctl, method)()
                    last_action = now
            elif screen == Screen.UNKNOWN:
                # Unknown screen: do nothing, keep evidence.
                if unknown_since and not unknown_saved and now - unknown_since > 2.0:
                    self._log("Unknown screen for 2s; not acting.")
                    self._save_debug(img, "unknown")
                    unknown_saved = True

            if run_started is not None:
                status["run_time"] = int(now - run_started)
            self._status(status)
            time.sleep(0.01)
