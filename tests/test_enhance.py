from warhammer_survivors_bot import enhance
from warhammer_survivors_bot.enhance import Cell, Shop


def _shop(states: dict[str, str], selected=(0, 0)) -> Shop:
    cells = {}
    for name, (r, c) in enhance.POSITION.items():
        cells[name] = Cell(name, r, c, states.get(name, "expensive"))
    return Shop(cells, selected)


def test_never_corruption_or_scrolled_rows() -> None:
    names = {n for row in enhance.GRID for n in row}
    assert "Corruption" not in names and "Corruption" not in enhance.PRIORITY
    assert set(enhance.PRIORITY) == names


def test_priority_order() -> None:
    shop = _shop({"Wounds": "affordable", "Strength": "affordable", "Skill": "affordable"})
    assert enhance.next_purchase(shop).name == "Strength"
    shop = _shop({"Wounds": "affordable", "Skill": "affordable", "Strength": "max"})
    assert enhance.next_purchase(shop).name == "Wounds"


def test_nothing_affordable() -> None:
    assert enhance.next_purchase(_shop({"Save": "max"})) is None


def test_step_towards() -> None:
    assert enhance.step_towards((0, 0), (1, 1)) == "DOWN"
    assert enhance.step_towards((1, 0), (1, 1)) == "RIGHT"
    assert enhance.step_towards((2, 3), (0, 3)) == "UP"
    assert enhance.step_towards((0, 2), (0, 0)) == "LEFT"
    assert enhance.step_towards((1, 1), (1, 1)) is None
