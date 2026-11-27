"""Decide which direction to move, given detected enemies and XP pickups.

Each of the 8 directions (plus standing still) is scored by looking ahead to
where the player would be. Distances are screen pixels between the player's
center and an enemy blob's center; they were measured from telemetry
(docs/game-notes.md): every health loss happened with an enemy closer than
~80 px, never further away.

Risk model - staying close to enemies is needed (proximity weapons: auras,
melee, flamers), being *surrounded* is what kills:

- danger: steep repulsion only near contact range (SAFE_DISTANCE);
- encirclement: the share of 16 directions around the player that contain
  an enemy within ESCAPE_RADIUS. The more surrounded, the larger the engage
  distance, the weaker the urge to engage, the higher the caution, and the
  stronger the bonus for heading into a free gap (an escape route);
- engage: while healthy, hold the nearest enemy at the engage distance;
- XP: walk towards the best reachable pickup (near, several together, not
  next to an enemy, no wall in between); the previous target is preferred;
- walls: olive walls seen in the frame, plus a memory of places where the
  player got stuck (works for any obstacle, whatever its colour), kept in
  world coordinates obtained by integrating the camera motion;
- small bonuses/penalties: keep the current direction, don't stand still.
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

LOOKAHEAD = (40.0, 90.0, 160.0)   # px ahead the player is assumed to be
CONTACT_DISTANCE = 80.0           # measured: damage only below this
SAFE_DISTANCE = 105.0             # danger rises steeply below this
ENGAGE_DISTANCE = 125.0           # preferred distance to the nearest enemy (open space)
ENGAGE_BACKOFF = 100.0            # added to it when fully surrounded
ENGAGE_WEIGHT = 1.0
ENGAGE_WEIGHT_WITH_XP = 0.3       # engaging matters less while collecting XP
ENGAGE_MIN_HEALTH = 0.5
ESCAPE_RADIUS = 230.0             # enemies within this count for encirclement
SECTORS = 16
ESCAPE_WEIGHT = 2.5               # bonus for heading into a free gap, x encirclement
CROWD_RADIUS = 220.0              # mild preference for open space further ahead
CROWD_WEIGHT = 0.03
TARGET_WEIGHT = 2.0               # reward for closing in on the XP target
XP_SAFETY = 95.0                  # pickups with an enemy closer than this are skipped
XP_CLUSTER = 90.0                 # pickups this close together count as a group
CONTINUITY = 0.25
BLOCKED_PENALTY = 5.0
BLOCKED_SECONDS = 2.0
STUCK_SECONDS = 0.25
WALL_PENALTY = 6.0
WALL_PROBES = (35.0, 60.0, 90.0)  # px along a direction checked for walls
FEET_OFFSET = 25                  # the sprite's feet are below the screen center
MEMORY_CELL = 24                  # px, grid of the stuck-place memory
MEMORY_SECONDS = 90.0


@dataclass
class Decision:
    direction: str
    score: float
    nearest_enemy: float                 # px, inf if none
    target: tuple[int, int] | None       # chosen XP pickup
    engage: tuple[int, int] | None = None  # enemy being kept at engage distance
    encirclement: float = 0.0            # 0 = open space, 1 = surrounded


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


def _danger(d: float) -> float:
    """Repulsion of one enemy at distance d: ~1 at SAFE_DISTANCE, steep below."""
    return (SAFE_DISTANCE / max(d, 20.0)) ** 4


def occupied_sectors(objs: Objects) -> list[bool]:
    """Which of SECTORS directions around the player contain an enemy nearby."""
    px, py = PLAYER_POS
    occ = [False] * SECTORS
    for ex, ey, _ in objs.enemies:
        if math.hypot(ex - px, ey - py) < ESCAPE_RADIUS:
            angle = math.atan2(ey - py, ex - px) % (2 * math.pi)
            occ[int(angle / (2 * math.pi) * SECTORS) % SECTORS] = True
    return occ


def _sector_of(dx: float, dy: float) -> int:
    return int((math.atan2(dy, dx) % (2 * math.pi)) / (2 * math.pi) * SECTORS) % SECTORS


class Steering:
    def __init__(self) -> None:
        self.previous = "stay"
        self._blocked: dict[str, float] = {}
        self._stuck_since: float | None = None
        self.motion = MotionTracker()
        self.last_shift: tuple[float, float] | None = None  # player motion, last frame
        self.world = [0.0, 0.0]  # integrated player position (px since run start)
        self._memory: dict[tuple[int, int], float] = {}  # stuck places -> expiry
        self._last_target: tuple[int, int] | None = None

    def reset(self) -> None:
        """Forget everything run-specific (call when a new run starts)."""
        self.__init__()

    # ---- motion, walls ---------------------------------------------------------
    def observe_motion(self, img: np.ndarray, now: float | None = None) -> None:
        """Call once per in-run frame, before :meth:`decide`."""
        self.record_motion(self.motion.update(img), now)

    def record_motion(self, shift: tuple[float, float] | None, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.last_shift = shift
        if shift is None:
            return
        if math.hypot(*shift) < 80:  # ignore glitches (e.g. a screen transition)
            self.world[0] += shift[0]
            self.world[1] += shift[1]
        if self.previous == "stay":
            self._stuck_since = None
            return
        dx, dy = DIRECTIONS[self.previous]
        progress = shift[0] * dx + shift[1] * dy  # px moved along intended direction
        if progress < 1.0:
            self._stuck_since = self._stuck_since or now
            if now - self._stuck_since > STUCK_SECONDS:
                self._blocked[self.previous] = now + BLOCKED_SECONDS
                self._remember_obstacle(dx, dy, now)
                self._stuck_since = None
        else:
            self._stuck_since = None

    def _cell(self, wx: float, wy: float) -> tuple[int, int]:
        return int(wx // MEMORY_CELL), int(wy // MEMORY_CELL)

    def _remember_obstacle(self, dx: float, dy: float, now: float) -> None:
        for d in (30.0, 50.0):
            cell = self._cell(self.world[0] + dx * d, self.world[1] + FEET_OFFSET + dy * d)
            self._memory[cell] = now + MEMORY_SECONDS

    def _remembered(self, sx: float, sy: float, now: float) -> bool:
        """Is screen point (sx, sy) (feet level) a remembered obstacle?"""
        wx = self.world[0] + sx - PLAYER_POS[0]
        wy = self.world[1] + sy - PLAYER_POS[1]
        return self._memory.get(self._cell(wx, wy), 0.0) > now

    def blocked(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        return [d for d, until in self._blocked.items() if until > now]

    @staticmethod
    def _clear_path(objs: Objects, start: tuple[float, float], end: tuple[float, float]) -> bool:
        """True if no wall lies on the straight line between two points."""
        dist = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(dist // 30))
        for i in range(1, steps + 1):
            t = i / steps
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            if objs.blocked_at(x, y, radius=8) > 0.3:
                return False
        return True

    def wall_ahead(self, objs: Objects, dx: float, dy: float, now: float | None = None) -> float:
        """0..1: how strongly a wall blocks moving in direction (dx, dy)."""
        if not (dx or dy):
            return 0.0
        now = time.monotonic() if now is None else now
        px, py = PLAYER_POS
        worst = 0.0
        for d in WALL_PROBES:
            x, y = px + dx * d, py + FEET_OFFSET + dy * d
            frac = max(objs.blocked_at(x, y, radius=14),
                       1.0 if self._remembered(x, y, now) else 0.0)
            worst = max(worst, frac * (1.0 if d < 70 else 0.5))
        return worst

    # ---- decision --------------------------------------------------------------
    def _pick_target(self, objs: Objects) -> tuple[int, int] | None:
        px, py = PLAYER_POS
        best, best_value = None, 0.0
        # Where the previous target should be now (the camera moved with the player).
        prev = None
        if self._last_target is not None:
            sx, sy = self.last_shift or (0.0, 0.0)
            prev = (self._last_target[0] - sx, self._last_target[1] - sy)
        for gx, gy in objs.xp:
            if any(math.hypot(ex - gx, ey - gy) < XP_SAFETY for ex, ey, _ in objs.enemies):
                continue
            if not self._clear_path(objs, (px, py + FEET_OFFSET), (gx, gy)):
                continue
            group = sum(1 for ox, oy in objs.xp if math.hypot(ox - gx, oy - gy) < XP_CLUSTER)
            value = (1.0 + 0.4 * (group - 1)) / (1.0 + math.hypot(gx - px, gy - py) / 200.0)
            if prev is not None and math.hypot(gx - prev[0], gy - prev[1]) < 40:
                value *= 1.3  # stick with the current target
            if value > best_value:
                best, best_value = (gx, gy), value
        self._last_target = best
        return best

    def _score(self, name: str, objs: Objects, target: tuple[int, int] | None,
               blocked: list[str], caution: float, engage: tuple[int, int] | None,
               encircle: float, free: list[bool], now: float) -> float:
        dx, dy = DIRECTIONS[name]
        px, py = PLAYER_POS
        total = 0.0
        engage_distance = ENGAGE_DISTANCE + ENGAGE_BACKOFF * encircle
        engage_weight = (ENGAGE_WEIGHT_WITH_XP if target is not None else ENGAGE_WEIGHT)
        engage_weight *= 1.0 - encircle
        for ahead in LOOKAHEAD:
            qx, qy = px + dx * ahead, py + dy * ahead
            for ex, ey, area in objs.enemies:
                d = math.hypot(ex - qx, ey - qy)
                weight = min(area / 400.0, 3.0)  # bigger blobs = bigger/more enemies
                total -= caution * weight * _danger(d)
                if ahead == LOOKAHEAD[-1] and d < CROWD_RADIUS:
                    total -= CROWD_WEIGHT * weight
            if target is not None:
                d0 = math.hypot(target[0] - px, target[1] - py)
                d1 = math.hypot(target[0] - qx, target[1] - qy)
                total += TARGET_WEIGHT * (d0 - d1) / ahead
            if engage is not None and engage_weight > 0:
                e0 = abs(math.hypot(engage[0] - px, engage[1] - py) - engage_distance)
                e1 = abs(math.hypot(engage[0] - qx, engage[1] - qy) - engage_distance)
                total += engage_weight * (e0 - e1) / ahead
        if dx or dy:
            # Escape routes: the more surrounded, the more a free gap is worth.
            s = _sector_of(dx, dy)
            gap = free[s] + 0.5 * (free[(s - 1) % SECTORS] + free[(s + 1) % SECTORS])
            total += ESCAPE_WEIGHT * encircle * gap / 2.0
        else:
            # Don't stand still (common advice): a small cost always, a big one
            # when an enemy is about to reach us.
            total -= 0.3
            if any(math.hypot(ex - px, ey - py) < SAFE_DISTANCE * 1.5
                   for ex, ey, _ in objs.enemies):
                total -= 1.0
        if name == self.previous and name != "stay":  # don't let idling become sticky
            total += CONTINUITY
        if name in blocked:
            total -= BLOCKED_PENALTY
        total -= WALL_PENALTY * self.wall_ahead(objs, dx, dy, now)
        return total

    def decide(self, objs: Objects, now: float | None = None,
               health: float | None = None) -> Decision:
        """Pick a direction. ``health`` (0..1) makes the player more careful when low."""
        now = time.monotonic() if now is None else now
        occ = occupied_sectors(objs)
        encircle = sum(occ) / SECTORS
        free = [not o for o in occ]
        caution = 1.0 if health is None else 1.0 + 2.0 * max(0.0, 0.6 - health) / 0.6
        caution *= 1.0 + encircle
        target = self._pick_target(objs)
        blocked = self.blocked(now)
        px, py = PLAYER_POS
        engage = None
        if objs.enemies and (health is None or health >= ENGAGE_MIN_HEALTH):
            ex, ey, _ = min(objs.enemies, key=lambda e: math.hypot(e[0] - px, e[1] - py))
            engage = (ex, ey)
        scores = {name: self._score(name, objs, target, blocked, caution, engage,
                                    encircle, free, now)
                  for name in DIRECTIONS}
        best = max(scores, key=scores.__getitem__)
        self.previous = best
        nearest = min(
            (math.hypot(ex - px, ey - py) for ex, ey, _ in objs.enemies), default=math.inf
        )
        return Decision(best, scores[best], nearest, target, engage, encircle)
