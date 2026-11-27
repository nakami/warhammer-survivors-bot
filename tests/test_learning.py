import random
from pathlib import Path

from warhammer_survivors_bot import learning, steering
from warhammer_survivors_bot.learning import PARAMETERS, Learner


def test_choose_gives_one_known_value_per_parameter(tmp_path: Path) -> None:
    lr = Learner(tmp_path / "l.json", random.Random(1))
    config = lr.choose()
    assert set(config) == set(PARAMETERS)
    assert all(config[p] in PARAMETERS[p] for p in PARAMETERS)


def test_learns_the_better_value_and_persists(tmp_path: Path) -> None:
    rng = random.Random(2)
    lr = Learner(tmp_path / "l.json", rng)
    good = 160.0
    for _ in range(60):  # simulated runs: ENGAGE_DISTANCE=160 is clearly better
        cfg = lr.choose()
        r = (12.0 if cfg["ENGAGE_DISTANCE"] == good else 6.0) + rng.gauss(0, 2.0)
        lr.update(cfg, r)
    rows = {(p, v): (n, prob) for p, v, n, _, prob in lr.summary()}
    assert rows[("ENGAGE_DISTANCE", good)][1] > 0.9
    # Thompson sampling should have spent most runs on the better value.
    assert rows[("ENGAGE_DISTANCE", good)][0] > 30
    again = Learner(tmp_path / "l.json")
    assert len(again.history) == 60


def test_apply_and_restore(tmp_path: Path) -> None:
    lr = Learner(tmp_path / "l.json")
    before = steering.ENGAGE_DISTANCE
    lr.apply({"ENGAGE_DISTANCE": 160.0})
    assert steering.ENGAGE_DISTANCE == 160.0
    lr.restore_defaults()
    assert steering.ENGAGE_DISTANCE == before


def test_reward_prefers_progress() -> None:
    assert learning.reward(600, 15, 3) > learning.reward(600, 8, 0)
