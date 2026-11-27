"""How dangerous is the current moment? A 0..1 risk level plus a mood emoji.

Inputs come from what the bot already sees each frame:
- contact: how close the nearest enemy is, relative to the measured contact
  distance (~80 px; nothing at >= 1.6 x SAFE_DISTANCE),
- encirclement: share of directions around the player blocked by enemies,
- health: low health raises the risk,
- crowd: many enemies close by.
"""

from __future__ import annotations

import math

from warhammer_survivors_bot.steering import CONTACT_DISTANCE, SAFE_DISTANCE
from warhammer_survivors_bot.vision import PLAYER_POS, Objects

# (upper bound of the level, emoji, label)
MOODS = [
    (0.2, "\U0001F60E", "relaxed"),    # smiling face with sunglasses
    (0.4, "\U0001F642", "focused"),    # slightly smiling face
    (0.6, "\U0001F62C", "tense"),      # grimacing face
    (0.8, "\U0001F630", "danger"),     # anxious face with sweat
    (1.01, "\U0001F631", "critical"),  # face screaming in fear
]
GAME_OVER = ("\U0001F480", "game over")   # skull
IDLE = ("\U0001F4A4", "not in a run")     # zzz


def assess(objs: Objects, encirclement: float, health: float | None) -> float:
    """Risk level 0 (nothing around) .. 1 (about to be overrun)."""
    px, py = PLAYER_POS
    nearest = min((math.hypot(ex - px, ey - py) for ex, ey, _ in objs.enemies),
                  default=math.inf)
    far = SAFE_DISTANCE * 1.6
    contact = min(1.0, max(0.0, (far - nearest) / (far - CONTACT_DISTANCE)))
    close = sum(1 for ex, ey, _ in objs.enemies if math.hypot(ex - px, ey - py) < 300)
    crowd = min(1.0, close / 25.0)
    hurt = 0.0 if health is None else min(1.0, max(0.0, (0.7 - health) / 0.6))
    # Being surrounded *and* in contact is what kills; each factor alone less so.
    risk = (0.30 * contact + 0.30 * encirclement + 0.25 * hurt + 0.15 * crowd
            + 0.25 * contact * encirclement)
    return min(1.0, risk)


def mood(risk: float) -> tuple[str, str]:
    for upper, emoji, label in MOODS:
        if risk < upper:
            return emoji, label
    return MOODS[-1][1], MOODS[-1][2]
