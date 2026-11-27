"""Read the Level Up screen and choose a card.

What can be read reliably from pixels (1920x1080 client area):

- each card's **NEW** badge (bright green banner): the item is not owned yet,
  otherwise the card upgrades an owned item;
- each card's **damage-type tag** (e.g. "Fire", "Default"): only weapons have
  one, passives (e.g. "Glue") do not;
- the inventory panel above the cards: 6 weapon slots (left) and 6 passive
  slots (right), so the number of owned weapons/passives is known.

Policy (survivors-like rule of thumb: focus on a few weapons and level them):
upgrade owned weapons > new weapon while below the weapon budget (3) > upgrade
passives > new passives > new weapons beyond the budget.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CARD_CENTERS = [(425, 600), (782, 600), (1138, 600), (1495, 600)]
_WEAPON_SLOTS = [(x, y) for y in (241, 293) for x in (597, 699, 803)]
_PASSIVE_SLOTS = [(x, y) for y in (241, 293) for x in (1068, 1172, 1276)]
# Few weapons, levelled to max (8): evolutions need a max-level weapon
# (see docs/game-knowledge.md), and spreading upgrades is a common mistake.
WEAPON_BUDGET = 3


@dataclass(frozen=True)
class Card:
    index: int
    is_new: bool
    is_weapon: bool

    @property
    def kind(self) -> str:
        return f"{'new' if self.is_new else 'upgrade'} {'weapon' if self.is_weapon else 'passive'}"


@dataclass(frozen=True)
class LevelUp:
    cards: list[Card]
    weapons: int
    passives: int


def _occupied(gray: np.ndarray, slots: list[tuple[int, int]]) -> int:
    return sum(gray[y - 14:y + 14, x - 14:x + 14].std() > 20 for x, y in slots)


def read(img: np.ndarray) -> LevelUp:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (50, 150, 150), (80, 255, 255))
    cards = []
    for i, (cx, _) in enumerate(CARD_CENTERS):
        # A card is present if its title row has green text.
        if green[375:405, cx - 160:cx + 160].mean() < 0.01 * 255:
            continue
        # NEW is a solid green banner; upgrade cards show a row of outlined
        # level squares at the same spot, which fills far less of the area.
        is_new = green[795:818, cx - 55:cx + 55].mean() > 0.55 * 255
        is_weapon = gray[742:778, cx - 90:cx + 90].std() > 20
        cards.append(Card(i, bool(is_new), bool(is_weapon)))
    return LevelUp(cards, int(_occupied(gray, _WEAPON_SLOTS)),
                   int(_occupied(gray, _PASSIVE_SLOTS)))


def highlighted(img: np.ndarray) -> int | None:
    """Index of the card with the selection highlight (controller/keyboard focus)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (45, 80, 80), (85, 255, 255))
    best, best_val = None, 0.15
    for i, (cx, _) in enumerate(CARD_CENTERS):
        strip = np.hstack([green[380:800, cx - 162:cx - 152], green[380:800, cx + 152:cx + 162]])
        val = strip.mean() / 255.0
        if val > best_val:
            best, best_val = i, val
    return best


def score(card: Card, state: LevelUp) -> float:
    if card.is_weapon and not card.is_new:
        return 4.0
    if card.is_weapon and state.weapons < WEAPON_BUDGET:
        return 3.0
    if not card.is_new:
        return 2.0
    if not card.is_weapon:
        return 1.0
    return 0.5


def choose(state: LevelUp) -> Card | None:
    """Best card by policy; ties go to the leftmost card."""
    if not state.cards:
        return None
    return max(state.cards, key=lambda c: (score(c, state), -c.index))
