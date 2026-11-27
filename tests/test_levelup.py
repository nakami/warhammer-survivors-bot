import numpy as np

from warhammer_survivors_bot import levelup
from warhammer_survivors_bot.levelup import Card, LevelUp

GREEN = (80, 230, 40)  # BGR, bright green like the game's titles and NEW badge


def _frame(cards: list[tuple[bool, bool]], weapons: int, passives: int) -> np.ndarray:
    """Synthetic level-up screen: (is_new, is_weapon) per card, plus inventory."""
    img = np.full((1080, 1920, 3), 10, np.uint8)
    for (cx, _), (is_new, is_weapon) in zip(levelup.CARD_CENTERS, cards):
        img[380:400, cx - 80:cx + 80] = GREEN                       # title text
        if is_new:
            img[792:822, cx - 75:cx + 75] = GREEN                    # NEW badge
        if is_weapon:
            img[748:772, cx - 60:cx + 60:4] = 255                    # tag text stripes
    for x, y in levelup._WEAPON_SLOTS[:weapons] + levelup._PASSIVE_SLOTS[:passives]:
        img[y - 14:y + 14:3, x - 14:x + 14] = 220                    # icon detail
    return img


def test_reader_on_synthetic_screen() -> None:
    state = levelup.read(_frame([(True, True), (True, False), (False, True), (False, False)],
                                weapons=2, passives=1))
    assert [(c.is_new, c.is_weapon) for c in state.cards] == [
        (True, True), (True, False), (False, True), (False, False)]
    assert (state.weapons, state.passives) == (2, 1)


def test_reader_skips_missing_cards() -> None:
    state = levelup.read(_frame([(True, True), (True, False), (True, True)], 0, 0))
    assert [c.index for c in state.cards] == [0, 1, 2]


def _state(cards: list[tuple[bool, bool]], weapons: int = 1) -> LevelUp:
    return LevelUp([Card(i, n, w) for i, (n, w) in enumerate(cards)], weapons, 0)


def test_prefers_upgrading_owned_weapon() -> None:
    state = _state([(True, True), (False, False), (False, True)])
    assert levelup.choose(state).index == 2


def test_new_weapon_beats_passives_while_under_budget() -> None:
    state = _state([(False, False), (True, True)], weapons=1)
    assert levelup.choose(state).index == 1


def test_no_new_weapons_over_budget() -> None:
    state = _state([(True, True), (True, False)], weapons=levelup.WEAPON_BUDGET)
    assert levelup.choose(state).index == 1


def test_tie_goes_left_and_empty_is_none() -> None:
    assert levelup.choose(_state([(True, True), (True, True)])).index == 0
    assert levelup.choose(LevelUp([], 0, 0)) is None
