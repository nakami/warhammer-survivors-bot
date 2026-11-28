import numpy as np
import pytest

from warhammer_survivors_bot.steering import Steering
from warhammer_survivors_bot.vision import _TEMPLATE_POS, PLAYER_POS, Objects, Screen, Vision


@pytest.fixture(scope="module")
def vision() -> Vision:
    return Vision()


def _frame_with(vision: Vision, screen: Screen) -> np.ndarray:
    img = np.zeros((1080, 1920, 3), np.uint8)
    tpl = vision.templates[screen]
    x, y = _TEMPLATE_POS[screen]
    img[y:y + tpl.shape[0], x:x + tpl.shape[1]] = tpl
    return img


@pytest.mark.parametrize("screen", list(_TEMPLATE_POS))
def test_each_template_is_recognised(vision: Vision, screen: Screen) -> None:
    detected, score = vision.screen(_frame_with(vision, screen))
    assert detected == screen
    assert score > 0.95


def test_blank_frame_is_unknown(vision: Vision) -> None:
    assert vision.screen(np.zeros((1080, 1920, 3), np.uint8))[0] == Screen.UNKNOWN


def test_wrong_resolution_is_unknown(vision: Vision) -> None:
    assert vision.screen(np.zeros((720, 1280, 3), np.uint8))[0] == Screen.UNKNOWN


def test_steering_backs_off_from_touching_enemy() -> None:
    px, py = PLAYER_POS
    objs = Objects(enemies=[(px + 60, py, 800)])  # within contact range
    assert "left" in Steering().decide(objs).direction


def test_steering_keeps_close_but_does_not_close_in() -> None:
    px, py = PLAYER_POS
    objs = Objects(enemies=[(px + 120, py, 800)])  # about the engage distance
    assert "right" not in Steering().decide(objs, health=0.9).direction


def test_steering_walks_towards_safe_xp() -> None:
    px, py = PLAYER_POS
    objs = Objects(xp=[(px, py - 200)])
    assert Steering().decide(objs).direction == "up"


def test_steering_engages_distant_enemy_when_healthy() -> None:
    px, py = PLAYER_POS
    objs = Objects(enemies=[(px + 450, py, 400)])
    assert Steering().decide(objs, health=0.9).direction == "right"


def test_steering_does_not_engage_when_hurt() -> None:
    px, py = PLAYER_POS
    objs = Objects(enemies=[(px + 450, py, 400)])
    assert "right" not in Steering().decide(objs, health=0.3).direction


def test_standing_still_is_not_sticky() -> None:
    px, py = PLAYER_POS
    steering = Steering()
    steering.previous = "stay"
    objs = Objects(enemies=[(px + 450, py, 400)])
    assert steering.decide(objs, health=0.9).direction != "stay"


def test_steering_escapes_through_the_gap_when_surrounded() -> None:
    import math
    px, py = PLAYER_POS
    # Enemies all around at ~150 px, except straight up (the gap).
    enemies = []
    for deg in range(0, 360, 20):
        if 240 <= deg <= 300:  # screen y points down: 270 deg = up
            continue
        a = math.radians(deg)
        enemies.append((int(px + 150 * math.cos(a)), int(py + 150 * math.sin(a)), 400))
    decision = Steering().decide(Objects(enemies=enemies), health=0.9)
    assert decision.encirclement > 0.7
    assert decision.direction == "up"


def test_wall_memory_blocks_a_direction_where_we_got_stuck() -> None:
    steering = Steering()
    steering.previous = "right"
    for i in range(10):  # pushing right but not moving for 0.5 s
        steering.record_motion((0.0, 0.0), now=100.0 + i * 0.05)
    assert "right" in steering.blocked(now=100.6)
    # Even after the short block expired, the remembered spot keeps "right" unattractive.
    assert steering.wall_ahead(Objects(), 1.0, 0.0, now=105.0) > 0.5
    assert steering.wall_ahead(Objects(), -1.0, 0.0, now=105.0) == 0.0


def _bar(img: np.ndarray, x: int, y: int, fill: float = 1.0, width: int = 128) -> None:
    """Draw a health bar: dark frame, red fill from the left (BGR)."""
    img[y - 5:y + 9, x - 4:x + width + 4] = (20, 20, 20)
    img[y:y + 4, x:x + int(width * fill)] = (30, 30, 200)


def test_elite_is_found_by_its_health_bar(vision: Vision) -> None:
    img = np.full((1080, 1920, 3), (60, 110, 160), np.uint8)  # brown ground
    _bar(img, 600, 700, fill=0.4)  # damaged elite
    elites = vision.objects(img).elites
    assert len(elites) == 1
    ex, ey = elites[0]
    assert abs(ex - 664) < 5 and ey < 700


def test_player_health_bar_is_not_an_elite(vision: Vision) -> None:
    img = np.full((1080, 1920, 3), (60, 110, 160), np.uint8)
    _bar(img, 922, 548, width=76)  # the player's bar
    assert vision.objects(img).elites == []


def test_steering_keeps_away_from_elite_but_engages_normal_enemies() -> None:
    px, py = PLAYER_POS
    # An elite at 170 px to the right (outside the normal safe distance) and its sprite blob.
    objs = Objects(enemies=[(px + 170, py, 900)], elites=[(px + 170, py)])
    decision = Steering().decide(objs, health=1.0)
    assert "left" in decision.direction
    assert decision.engage is None  # the elite's own sprite is not an engage target
