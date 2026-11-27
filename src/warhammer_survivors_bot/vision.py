"""Interpret captured frames: which screen is shown, and where things are.

Everything here works on plain screenshots of the game window (BGR images at
1920x1080 client resolution).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from importlib import resources

import cv2
import numpy as np

REFERENCE_SIZE = (1920, 1080)
PLAYER_POS = (960, 505)  # the camera keeps the player centered


class Screen(Enum):
    UNKNOWN = "unknown"
    WARNING = "warning"
    TITLE = "title"
    UNIVERSE = "universe"
    MAIN_MENU = "main_menu"
    CHARACTER_SELECT = "character_select"
    MISSION_SELECT = "mission_select"
    LEVEL_UP = "level_up"
    PAUSED = "paused"
    IN_RUN = "in_run"
    GAME_OVER = "game_over"
    RECAP = "recap"
    ENHANCEMENTS = "enhancements"
    WARGEAR = "wargear"  # chest dialog: "Wargear Acquired!" -> opening -> Accept


# Template name -> top-left position (x, y) where it appears in the reference frame.
# Order matters: overlays (level up, paused) must be checked before IN_RUN,
# because the in-run HUD stays visible underneath them.
_TEMPLATE_POS: dict[Screen, tuple[int, int]] = {
    Screen.LEVEL_UP: (850, 140),
    Screen.PAUSED: (875, 135),
    Screen.WARGEAR: (885, 110),
    Screen.IN_RUN: (1732, 150),
    Screen.WARNING: (850, 680),
    Screen.TITLE: (745, 650),
    Screen.UNIVERSE: (115, 115),
    Screen.MAIN_MENU: (105, 25),
    Screen.CHARACTER_SELECT: (105, 25),
    Screen.MISSION_SELECT: (105, 25),
    Screen.GAME_OVER: (760, 455),
    Screen.RECAP: (105, 25),
    Screen.ENHANCEMENTS: (105, 22),
}
_SEARCH_MARGIN = 30
_MATCH_THRESHOLD = 0.8

# HSV colour ranges (OpenCV: H 0-180), tuned on the Imperial Bastion map.
ENEMY_HSV = ((115, 60, 30), (165, 255, 200))
XP_BLUE_HSV = ((92, 140, 80), (108, 255, 255))
XP_GREY_HSV = ((0, 0, 60), (180, 35, 170))

# Regions ignored for object detection: (x0, y0, x1, y1)
_IGNORE = [
    (0, 0, 1920, 110),      # top HUD: XP bar, timer, counters
    (100, 50, 400, 160),    # weapon slots
    (1720, 140, 1830, 245),  # pause button
    (915, 440, 1005, 570),  # the player sprite and health bar
]


def _load_templates() -> dict[Screen, np.ndarray]:
    root = resources.files("warhammer_survivors_bot") / "templates"
    out = {}
    for screen in _TEMPLATE_POS:
        data = (root / f"{screen.value}.png").read_bytes()
        out[screen] = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return out


@dataclass
class Objects:
    enemies: list[tuple[int, int, int]] = field(default_factory=list)  # x, y, area
    xp: list[tuple[int, int]] = field(default_factory=list)


class Vision:
    def __init__(self) -> None:
        self.templates = _load_templates()
        self._kernel = np.ones((3, 3), np.uint8)

    def screen(self, img: np.ndarray) -> tuple[Screen, float]:
        """Classify the frame. Returns the screen and the match score."""
        h, w = img.shape[:2]
        if (w, h) != REFERENCE_SIZE:
            return Screen.UNKNOWN, 0.0
        for screen, (x, y) in _TEMPLATE_POS.items():
            tpl = self.templates[screen]
            th, tw = tpl.shape[:2]
            m = _SEARCH_MARGIN
            region = img[max(0, y - m): y + th + m, max(0, x - m): x + tw + m]
            score = float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max())
            if score >= _MATCH_THRESHOLD:
                return screen, score
        return Screen.UNKNOWN, 0.0

    def _mask(self, hsv: np.ndarray, rng: tuple[tuple[int, ...], tuple[int, ...]]) -> np.ndarray:
        mask = cv2.inRange(hsv, rng[0], rng[1])
        for x0, y0, x1, y1 in _IGNORE:
            mask[y0:y1, x0:x1] = 0
        return mask

    def objects(self, img: np.ndarray) -> Objects:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        out = Objects()

        enemy = self._mask(hsv, ENEMY_HSV)
        enemy = cv2.morphologyEx(enemy, cv2.MORPH_OPEN, self._kernel)  # drop thin lines
        enemy = cv2.dilate(enemy, self._kernel, iterations=2)
        n, _, stats, cents = cv2.connectedComponentsWithStats(enemy)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= 120:
                out.enemies.append((int(cents[i][0]), int(cents[i][1]), area))

        xp = self._mask(hsv, XP_BLUE_HSV) | self._mask(hsv, XP_GREY_HSV)
        xp = cv2.morphologyEx(xp, cv2.MORPH_OPEN, self._kernel)
        n, _, stats, cents = cv2.connectedComponentsWithStats(xp)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            if 40 <= area <= 600 and w <= 40 and h <= 40:  # skull-sized blobs only
                out.xp.append((int(cents[i][0]), int(cents[i][1])))
        return out

    @staticmethod
    def health(img: np.ndarray) -> float | None:
        """Fraction of the player's health bar that is red (0..1)."""
        bar = img[546:556, 922:998]
        hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 120, 90), (8, 255, 255)) | cv2.inRange(
            hsv, (170, 120, 90), (180, 255, 255))
        cols = (red > 0).any(axis=0)
        if not cols.any():
            return None
        return float(cols.mean())
