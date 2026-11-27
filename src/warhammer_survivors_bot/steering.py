"""Decide which direction to move, given detected enemies and XP pickups.

Each of the 8 directions (plus standing still) is scored by looking ahead to
where the player would be:

- danger: inverse-square repulsion from every enemy blob near that point,
- reward: progress towards one *target* XP pickup (the closest safe one), so
  the player commits to a pickup instead of dithering between many,
- continuity: a bonus for keeping the current direction,
- blocked: directions recently found blocked (walls) are penalised.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from warhammer_survivors_bot.vision import PLAYER_POS, Objects

# (dx, dy) unit directions in screen space (y grows downwards).
DIRECTIONS: dict[str, tuple[float, float]] = {
    "stay": (0.0, 0.0),
    "up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0),
    "up-left": (-0.707, -0.707), "up-right": (0.707, -0.707),
    "down-left": (-0.707, 0.707), "down-right": (0.707, 0.707),
}

LOOKAHEAD = (60.0, 140.0)   # px ahead the player is assumed to be
DANGER_RADIUS = 130.0       # scale of enemy repulsion
TARGET_WEIGHT = 1.5         # reward for closing in on the target pickup
TARGET_SAFETY = 160.0       # pickups with enemies closer than this are skipped
CONTINUITY = 0.25           # bonus for keeping the current direction
BLOCKED_PENALTY = 5.0
BLOCKED_SECONDS = 1.2


@dataclass
class Decision:
    direction: str
    score: float
    nearest_enemy: float                 # px, inf if none
    target: tuple[int, int] | None       # chosen XP pickup


class MotionTracker:
    """Estimates how far the camera (= the player) moved between two frames."""

    def __init__(self) -> None:
        self._prev: np.ndarray | None = None

    def update(self, img: np.ndarray) -> tuple[float, float] | None:
        # Ground area only (skip HUD); downscale for speed.
        gray = cv2.cvtColor(img[120:1000, 120:1800], cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, None, fx=0.25, fy=0.25).astype(np.float32)
        prev, self._prev = self._prev, small
        if prev is None:
            return None
        (sx, sy), _ = cv2.phaseCorrelate(prev, small)
        # The world shifts opposite to the player's motion; scale back to full res.
        return -sx * 4.0, -sy * 4.0


class Steering:
    def __init__(self) -> None:
        self.previous = "stay"
        self._blocked: dict[str, float] = {}
        self._stuck_since: float | None = None
        self.motion = MotionTracker()

    # ---- wall handling ---------------------------------------------------------
    def observe_motion(self, img: np.ndarray, now: float | None = None) -> None:
        """Call once per in-run frame, before :meth:`decide`."""
        now = time.monotonic() if now is None else now
        shift = self.motion.update(img)
        if shift is None or self.previous == "stay":
            self._stuck_since = None
            return
        dx, dy = DIRECTIONS[self.previous]
        progress = shift[0] * dx + shift[1] * dy  # px moved along intended direction
        if progress < 1.0:
            self._stuck_since = self._stuck_since or now
            if now - self._stuck_since > 0.35:
                self._blocked[self.previous] = now + BLOCKED_SECONDS
                self._stuck_since = None
        else:
            self._stuck_since = None

    def blocked(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        return [d for d, until in self._blocked.items() if until > now]

    # ---- decision --------------------------------------------------------------
    @staticmethod
    def _pick_target(objs: Objects) -> tuple[int, int] | None:
        px, py = PLAYER_POS
        best, best_d = None, math.inf
        for gx, gy in objs.xp:
            if any(math.hypot(ex - gx, ey - gy) < TARGET_SAFETY for ex, ey, _ in objs.enemies):
                continue
            d = math.hypot(gx - px, gy - py)
            if d < best_d:
                best, best_d = (gx, gy), d
        return best

    def _score(self, name: str, objs: Objects, target: tuple[int, int] | None,
               blocked: list[str]) -> float:
        dx, dy = DIRECTIONS[name]
        px, py = PLAYER_POS
        total = 0.0
        for ahead in LOOKAHEAD:
            qx, qy = px + dx * ahead, py + dy * ahead
            for ex, ey, area in objs.enemies:
                d = math.hypot(ex - qx, ey - qy)
                weight = min(area / 400.0, 3.0)  # bigger blobs = bigger/more enemies
                total -= weight * (DANGER_RADIUS / max(d, 20.0)) ** 2
            if target is not None:
                d0 = math.hypot(target[0] - px, target[1] - py)
                d1 = math.hypot(target[0] - qx, target[1] - qy)
                total += TARGET_WEIGHT * (d0 - d1) / ahead
        if name == self.previous:
            total += CONTINUITY
        if name in blocked:
            total -= BLOCKED_PENALTY
        return total

    def decide(self, objs: Objects, now: float | None = None) -> Decision:
        target = self._pick_target(objs)
        blocked = self.blocked(now)
        scores = {name: self._score(name, objs, target, blocked) for name in DIRECTIONS}
        best = max(scores, key=scores.__getitem__)
        self.previous = best
        px, py = PLAYER_POS
        nearest = min(
            (math.hypot(ex - px, ey - py) for ex, ey, _ in objs.enemies), default=math.inf
        )
        return Decision(best, scores[best], nearest, target)
