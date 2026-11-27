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


def test_steering_flees_from_enemy_on_the_right() -> None:
    px, py = PLAYER_POS
    objs = Objects(enemies=[(px + 120, py, 800)])
    assert "left" in Steering().decide(objs).direction


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
