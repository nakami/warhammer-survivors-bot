"""Interactive exploration helper: perform one human-like action, then screenshot.

Usage (coordinates are relative to the game window's client area):
    python -m warhammer_survivors_bot.explore shot [name]
    python -m warhammer_survivors_bot.explore key <key> [hold_seconds]
    python -m warhammer_survivors_bot.explore click <x> <y>
    python -m warhammer_survivors_bot.explore move <x> <y>
    python -m warhammer_survivors_bot.explore windows
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

from warhammer_survivors_bot import inputs, window
from warhammer_survivors_bot.capture import Capturer

SHOT_DIR = Path("screenshots")


def _hwnd() -> int:
    hwnd = window.find_window()
    if hwnd is None:
        sys.exit("Game window not found. Is the game running?")
    return hwnd


def screenshot(name: str = "shot", delay: float = 0.0) -> Path:
    time.sleep(delay)
    hwnd = _hwnd()
    rect = window.client_rect(hwnd)
    img = Capturer().grab(rect)
    SHOT_DIR.mkdir(exist_ok=True)
    path = SHOT_DIR / f"{name}.png"
    cv2.imwrite(str(path), img)
    print(f"saved {path} ({rect.width}x{rect.height} at {rect.left},{rect.top})")
    return path


def main(argv: list[str]) -> None:
    if not argv or argv[0] == "shot":
        screenshot(argv[1] if len(argv) > 1 else "shot")
        return
    cmd, *args = argv
    if cmd == "windows":
        for hwnd, title in window.list_windows():
            print(hwnd, repr(title))
        return

    hwnd = _hwnd()
    window.focus(hwnd)
    time.sleep(0.2)
    rect = window.client_rect(hwnd)

    if cmd == "key":
        inputs.press(args[0], hold=float(args[1]) if len(args) > 1 else 0.05)
    elif cmd == "click":
        inputs.click(rect.left + int(args[0]), rect.top + int(args[1]))
    elif cmd == "move":
        inputs.move_to(rect.left + int(args[0]), rect.top + int(args[1]))
    else:
        sys.exit(f"unknown command {cmd!r}")
    screenshot("last", delay=0.6)


if __name__ == "__main__":
    main(sys.argv[1:])
