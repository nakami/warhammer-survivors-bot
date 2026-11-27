"""How the bot sends input to the game: keyboard/mouse or a virtual controller.

Both backends offer the same high-level actions, so the bot logic does not
care which one is active.

- :class:`KeyboardMouse` uses ``SendInput``; the game must be the foreground
  window (Windows delivers keyboard/mouse input only there).
- :class:`Controller` uses a virtual Xbox 360 controller (ViGEmBus via
  ``vgamepad``) plus the runtime focus hook (:mod:`focus_hack`), so the game
  accepts input while you use other windows.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from warhammer_survivors_bot import inputs, window
from warhammer_survivors_bot.steering import DIRECTIONS

_DIR_KEYS = {
    "stay": (), "up": ("up",), "down": ("down",), "left": ("left",), "right": ("right",),
    "up-left": ("up", "left"), "up-right": ("up", "right"),
    "down-left": ("down", "left"), "down-right": ("down", "right"),
}

# Client-area click targets for keyboard/mouse mode (1920x1080).
CLICK_TITLE = (960, 667)
CLICK_UNIVERSE_START = (335, 957)
CLICK_MAIN_MENU_START = (287, 207)


class KeyboardMouse:
    needs_focus = True
    name = "keyboard/mouse"

    def __init__(self, log: Callable[[str], None] = print) -> None:
        self._log = log
        self._held: set[str] = set()

    def open(self) -> None:
        hwnd = window.find_window()
        if hwnd is not None:
            window.focus(hwnd)
            time.sleep(0.3)

    def close(self) -> None:
        self.release()

    def move(self, direction: str) -> None:
        wanted = set(_DIR_KEYS[direction])
        for key in self._held - wanted:
            inputs.key_up(key)
        for key in wanted - self._held:
            inputs.key_down(key)
        self._held = wanted

    def release(self) -> None:
        for key in self._held | {"up", "down", "left", "right"}:
            inputs.key_up(key)
        self._held = set()

    @property
    def moving(self) -> bool:
        return bool(self._held)

    def confirm(self) -> None:
        inputs.press("enter")

    def back(self) -> None:
        inputs.press("esc")

    def pause(self) -> None:
        inputs.press("esc")

    def resume(self) -> None:
        inputs.press("esc")

    def _click(self, pos: tuple[int, int]) -> None:
        hwnd = window.find_window()
        if hwnd is None:
            return
        rect = window.client_rect(hwnd)
        inputs.click(rect.left + pos[0], rect.top + pos[1])

    def title(self) -> None:
        self._click(CLICK_TITLE)

    def universe_start(self) -> None:
        self._click(CLICK_UNIVERSE_START)

    def main_menu_start(self) -> None:
        self._click(CLICK_MAIN_MENU_START)

    def select_card(self, index: int, highlighted: int | None, centers) -> bool:
        """Click the card (first click highlights, a later one confirms).

        Returns True when an action that may confirm the card was sent."""
        self._click(centers[index])
        return True

    def shop_select(self, target: tuple[int, int], selected: tuple[int, int] | None,
                    center: tuple[int, int]) -> None:
        """Select an Enhancements cell (keyboard/mouse: click it)."""
        self._click(center)

    def buy_rank(self) -> None:
        """'+' on the selected Enhancement (the game shows E for it)."""
        inputs.press("e")  # layout-aware: the key that types 'e'


class Controller:
    needs_focus = False
    name = "virtual controller"

    def __init__(self, log: Callable[[str], None] = print) -> None:
        self._log = log
        self._pad = None
        self._hack = None
        self._moving = False

    def open(self) -> None:
        import vgamepad as vg  # optional dependencies, only needed for this mode

        from warhammer_survivors_bot.focus_hack import FocusHack

        self._vg = vg
        if self._pad is None:
            # Keep one pad for the lifetime of the app: when a controller the game
            # uses disappears, it shows a "Player disconnected" dialog.
            self._pad = vg.VX360Gamepad()
            time.sleep(2.0)  # let the game detect the new controller
        if self._hack is None or not self._hack.attached:
            self._hack = FocusHack(self._log)
            self._hack.attach()
        else:
            self._hack.reassert_focus()

    def close(self) -> None:
        """Release inputs and remove the focus hook (the pad stays connected)."""
        self.release()
        if self._hack is not None:
            self._hack.detach()
            self._hack = None

    def _tap(self, button: str, hold: float = 0.12) -> None:
        b = getattr(self._vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{button}")
        self._pad.press_button(b)
        self._pad.update()
        time.sleep(hold)
        self._pad.release_button(b)
        self._pad.update()

    def move(self, direction: str) -> None:
        dx, dy = DIRECTIONS[direction]
        self._pad.left_joystick_float(dx, -dy)  # stick y points up, screen y down
        self._pad.update()
        self._moving = direction != "stay"

    def release(self) -> None:
        if self._pad is not None:
            self._pad.reset()
            self._pad.update()
        self._moving = False

    @property
    def moving(self) -> bool:
        return self._moving

    def confirm(self) -> None:
        self._tap("A")

    def back(self) -> None:
        self._tap("B")

    def pause(self) -> None:
        self._tap("START")

    def resume(self) -> None:
        self._tap("B")

    def title(self) -> None:
        self._tap("A")

    def universe_start(self) -> None:
        self._tap("A")

    def main_menu_start(self) -> None:
        self._tap("A")

    def shop_select(self, target: tuple[int, int], selected: tuple[int, int] | None,
                    center: tuple[int, int]) -> None:
        """Move the Enhancements selection one cell towards the target."""
        from warhammer_survivors_bot.enhance import step_towards

        step = "LEFT" if selected is None else step_towards(selected, target)
        if step:
            self._tap(f"DPAD_{step}")

    def buy_rank(self) -> None:
        """'+' on the selected Enhancement (RB on a controller)."""
        self._tap("RIGHT_SHOULDER")

    def select_card(self, index: int, highlighted: int | None, centers) -> bool:
        """Move the highlight one step towards the card, or press A when on it.

        Returns True when A was pressed."""
        if highlighted == index:
            self._tap("A")
            return True
        if highlighted is None or highlighted > index:
            self._tap("DPAD_LEFT")
        else:
            self._tap("DPAD_RIGHT")
        return False
