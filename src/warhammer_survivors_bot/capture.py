"""Grab pixels of the game window, exactly what a human sees on screen."""

from __future__ import annotations

import mss
import numpy as np

from warhammer_survivors_bot.window import Rect


class Capturer:
    def __init__(self) -> None:
        self._sct = mss.MSS()

    def grab(self, rect: Rect) -> np.ndarray:
        """Return a BGR uint8 image of the given screen rectangle."""
        shot = self._sct.grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
        return np.asarray(shot)[:, :, :3].copy()  # BGRA -> BGR

    def close(self) -> None:
        self._sct.close()
