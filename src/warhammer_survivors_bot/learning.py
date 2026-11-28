"""Learn good steering parameters from run outcomes (a factorised bandit).

Each run, every tunable steering parameter gets one of a few candidate values,
chosen by Thompson sampling: values that worked well are picked more often,
rarely tried ones still get a chance. After a complete run (started from the
menu, ended by game over) the run's reward updates the statistics of every
value that was used. Runs are slow and noisy, so the model is deliberately
simple: parameters are assumed to act independently.

Reward = play minutes + 0.25 * level + 0.5 * chests (survival dominates, but
progress counts: a run that survives without killing anything is worse).
State is kept in learning.json (gitignored), so learning continues across
sessions.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from warhammer_survivors_bot import steering

LEARNING_FILE = Path("learning.json")

# Parameter -> candidate values (the current hand-tuned default is among them).
PARAMETERS: dict[str, list[float]] = {
    "ENGAGE_DISTANCE": [105.0, 125.0, 160.0],
    # Round 2 (after 74 runs): dropped the clear losers (SAFE 120, TARGET 1.5,
    # ESCAPE 1.5) and extended the ranges whose best value was at the top end.
    # Statistics of dropped values stay in learning.json but are no longer used.
    "SAFE_DISTANCE": [95.0, 105.0],
    "TARGET_WEIGHT": [2.0, 3.0, 4.0],
    "ESCAPE_WEIGHT": [2.5, 4.0, 6.0],
    "XP_SAFETY": [75.0, 95.0, 130.0],
}
# The hand-tuned values, captured once at import (before any variant is applied).
DEFAULTS: dict[str, float] = {p: getattr(steering, p) for p in PARAMETERS}

PRIOR_SD = 4.0      # spread assumed for a value that was barely tried (reward units)
MIN_SD = 1.0


def reward(play_seconds: float, level: int, chests: int) -> float:
    return play_seconds / 60.0 + 0.25 * level + 0.5 * chests


class Learner:
    def __init__(self, path: Path = LEARNING_FILE, rng: random.Random | None = None) -> None:
        self.path = path
        self.rng = rng or random.Random()
        self.stats: dict[str, dict[str, list[float]]] = {}  # param -> value -> [n, sum, sumsq]
        self.history: list[dict] = []
        self.load()

    # ---- persistence ----------------------------------------------------------
    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.stats = data.get("stats", {})
            self.history = data.get("history", [])
        except (OSError, ValueError):
            self.stats, self.history = {}, []
        for p, values in PARAMETERS.items():
            self.stats.setdefault(p, {})
            for v in values:
                self.stats[p].setdefault(_key(v), [0, 0.0, 0.0])

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stats": self.stats, "history": self.history}, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---- statistics -----------------------------------------------------------
    def _global_mean(self) -> float:
        rewards = [h["reward"] for h in self.history]
        return sum(rewards) / len(rewards) if rewards else 10.0

    def _posterior(self, p: str, v: float) -> tuple[float, float, int]:
        """Mean and standard error of the reward when parameter p had value v."""
        n, s, sq = self.stats[p][_key(v)]
        prior = self._global_mean()
        if n == 0:
            return prior, PRIOR_SD, 0
        mean = s / n
        var = max(sq / n - mean * mean, MIN_SD ** 2) if n > 1 else PRIOR_SD ** 2
        # Shrink towards the global mean while there are few runs.
        weight = n / (n + 1.0)
        return weight * mean + (1 - weight) * prior, math.sqrt(var / n), int(n)

    def choose(self) -> dict[str, float]:
        """One value per parameter by Thompson sampling."""
        config = {}
        for p, values in PARAMETERS.items():
            draws = {v: self.rng.gauss(*self._posterior(p, v)[:2]) for v in values}
            config[p] = max(draws, key=draws.get)
        return config

    def update(self, config: dict[str, float], value: float, meta: dict | None = None) -> None:
        for p, v in config.items():
            if p in self.stats and _key(v) in self.stats[p]:
                st = self.stats[p][_key(v)]
                st[0] += 1
                st[1] += value
                st[2] += value * value
        self.history.append({"time": time.time(), "config": config, "reward": value,
                             **(meta or {})})
        self.save()

    def summary(self, draws: int = 2000) -> list[tuple[str, float, int, float, float]]:
        """(parameter, value, runs, mean reward, probability of being best)."""
        rows = []
        for p, values in PARAMETERS.items():
            wins = {v: 0 for v in values}
            for _ in range(draws):
                d = {v: self.rng.gauss(*self._posterior(p, v)[:2]) for v in values}
                wins[max(d, key=d.get)] += 1
            for v in values:
                mean, _, n = self._posterior(p, v)
                rows.append((p, v, n, mean, wins[v] / draws))
        return rows

    # ---- applying a configuration ---------------------------------------------
    def apply(self, config: dict[str, float]) -> None:
        apply(config)

    def restore_defaults(self) -> None:
        restore_defaults()


def apply(config: dict[str, float]) -> None:
    """Set steering parameters (unspecified ones back to their defaults)."""
    for p, v in {**DEFAULTS, **config}.items():
        setattr(steering, p, v)


def restore_defaults() -> None:
    apply({})


def _key(v: float) -> str:
    return f"{v:g}"
