import math

from warhammer_survivors_bot import risk
from warhammer_survivors_bot.vision import PLAYER_POS, Objects


def _ring(radius: float, count: int):
    px, py = PLAYER_POS
    return [(int(px + radius * math.cos(2 * math.pi * i / count)),
             int(py + radius * math.sin(2 * math.pi * i / count)), 400) for i in range(count)]


def test_empty_screen_is_relaxed() -> None:
    value = risk.assess(Objects(), 0.0, 0.95)
    assert value < 0.2 and risk.mood(value)[1] == "relaxed"


def test_one_distant_enemy_is_calm() -> None:
    px, py = PLAYER_POS
    assert risk.assess(Objects(enemies=[(px + 400, py, 400)]), 1 / 16, 0.95) < 0.2


def test_surrounded_and_in_contact_is_critical() -> None:
    value = risk.assess(Objects(enemies=_ring(70, 24)), 1.0, 0.95)
    assert value >= 0.8 and risk.mood(value)[1] == "critical"


def test_low_health_raises_risk() -> None:
    objs = Objects(enemies=_ring(200, 6))
    assert risk.assess(objs, 0.4, 0.2) > risk.assess(objs, 0.4, 0.95)


def test_moods_cover_the_whole_range() -> None:
    labels = [risk.mood(v / 100)[1] for v in range(0, 101)]
    assert labels[0] == "relaxed" and labels[-1] == "critical"
    assert {"focused", "tense", "danger"} <= set(labels)


def test_nearby_elite_raises_risk() -> None:
    px, py = PLAYER_POS
    calm = risk.assess(Objects(), 0.0, 1.0)
    assert risk.assess(Objects(elites=[(px + 150, py)]), 0.0, 1.0) >= calm + 0.35
