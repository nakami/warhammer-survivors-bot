"""Read the Enhancements shop and decide what to buy.

Only the first three grid rows are ever considered. Row 4 (Veterancy, Tithe,
Corruption, Redeployment, ...) would need scrolling and contains Corruption,
which makes the game harder, so the bot never goes there.

Per cell, readable from pixels (1920x1080 client area):
- a coin icon next to the price -> purchasable; no coin icon -> MAX;
- a red price -> not affordable;
- the selected cell has a much brighter border.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

COLS = [220, 408, 596, 784]          # cell center x
ROW_TOPS = [155, 387, 619]           # cell top y
GRID = [
    ["Strength", "Save", "Reload", "Wounds"],
    ["Toughness", "Sustain", "Range", "Attacks"],
    ["Skill", "Move", "Aura", "Chance"],
]
# What to buy first (see docs/game-knowledge.md): the strongest offensive
# upgrades, then survivability, then utility.
PRIORITY = ["Attacks", "Strength", "Wounds", "Save", "Reload", "Toughness", "Range",
            "Move", "Aura", "Chance", "Sustain", "Skill"]
MAX_PURCHASES_PER_VISIT = 10

POSITION = {name: (r, c) for r, row in enumerate(GRID) for c, name in enumerate(row)}


@dataclass(frozen=True)
class Cell:
    name: str
    row: int
    col: int
    state: str  # "affordable", "expensive" or "max"


@dataclass(frozen=True)
class Shop:
    cells: dict[str, Cell]
    selected: tuple[int, int] | None


def center(row: int, col: int) -> tuple[int, int]:
    return COLS[col], ROW_TOPS[row] + 100


def ranks_patch(img: np.ndarray, row: int, col: int) -> np.ndarray:
    """The rank squares of a cell (changes when a rank is bought)."""
    cx, top = COLS[col], ROW_TOPS[row]
    return img[top + 160:top + 210, cx - 70:cx + 70]


def read(img: np.ndarray) -> Shop:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    red = cv2.inRange(hsv, (0, 120, 120), (10, 255, 255)) | cv2.inRange(
        hsv, (170, 120, 120), (180, 255, 255))
    gold = cv2.inRange(hsv, (15, 80, 120), (35, 255, 255))
    cells: dict[str, Cell] = {}
    best, best_border = None, 55.0
    for r, top in enumerate(ROW_TOPS):
        price_y = top + 137
        for c, cx in enumerate(COLS):
            coin = gold[price_y - 14:price_y + 14, cx - 45:cx - 20].mean() / 255
            is_red = red[price_y - 14:price_y + 14, cx - 15:cx + 40].mean() / 255
            if coin < 0.04:
                state = "max"
            elif is_red >= 0.05:
                state = "expensive"
            else:
                state = "affordable"
            cells[GRID[r][c]] = Cell(GRID[r][c], r, c, state)
            border = np.hstack([gray[top + 20:top + 200, cx - 88:cx - 82],
                                gray[top + 20:top + 200, cx + 82:cx + 88]]).mean()
            if border > best_border:
                best, best_border = (r, c), border
    return Shop(cells, best)


def next_purchase(shop: Shop) -> Cell | None:
    """Highest-priority enhancement that can be bought right now."""
    for name in PRIORITY:
        cell = shop.cells.get(name)
        if cell and cell.state == "affordable":
            return cell
    return None


def step_towards(selected: tuple[int, int], target: tuple[int, int]) -> str | None:
    """D-pad direction that moves the selection one cell towards the target."""
    (r, c), (tr, tc) = selected, target
    if r < tr:
        return "DOWN"
    if r > tr:
        return "UP"
    if c < tc:
        return "RIGHT"
    if c > tc:
        return "LEFT"
    return None
