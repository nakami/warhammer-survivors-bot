"""Unattended A/B experiment: full runs with different steering variants.

Runs the bot (background mode, no enhancement purchases, test data recorded)
through consecutive runs until game over, switching steering parameters
between runs in round-robin order. Each run is labelled in runs.json
("experiment <variant>"), so the control window's "Last runs" tab shows it;
the window also shows the orange TEST RUN banner and can stop it.

At the end (or when stopped) a per-variant summary is written to
screenshots/experiments/summary.txt.

    python scripts/run_experiments.py [runs_per_variant] [max_hours]
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from warhammer_survivors_bot import steering
from warhammer_survivors_bot.bot import Bot
from warhammer_survivors_bot.runlog import RunHistory
from warhammer_survivors_bot.settings import Settings

VARIANTS = {
    "A baseline": {},
    "B cautious": {"ENGAGE_DISTANCE": 160.0},
    "C aggressive": {"ENGAGE_DISTANCE": 105.0},
    "D no engage": {"ENGAGE_WEIGHT": 0.0, "ENGAGE_WEIGHT_WITH_XP": 0.0},
}
DEFAULTS = {k: getattr(steering, k) for v in VARIANTS.values() for k in v}
OUT = Path("screenshots/experiments")


def apply(variant: str) -> None:
    for k, v in DEFAULTS.items():
        setattr(steering, k, v)
    for k, v in VARIANTS[variant].items():
        setattr(steering, k, v)


def summary(started: float) -> str:
    runs = [r for r in RunHistory().load()
            if r.started >= started and r.source.startswith("experiment ")
            and r.end == "game over"]
    lines = [f"Experiment summary ({len(runs)} finished runs)", ""]
    for variant in VARIANTS:
        rs = [r for r in runs if r.source == f"experiment {variant}"]
        if not rs:
            lines.append(f"{variant:<14} no finished runs")
            continue
        play = [r.play_seconds / 60 for r in rs]
        lines.append(
            f"{variant:<14} n={len(rs)}  play min: mean {statistics.mean(play):.1f} "
            f"(min {min(play):.1f}, max {max(play):.1f})  level mean "
            f"{statistics.mean(r.level for r in rs):.1f}  hits/min "
            f"{statistics.mean(r.hits / max(r.play_seconds / 60, 0.1) for r in rs):.1f}  "
            f"chests mean {statistics.mean(r.chests for r in rs):.1f}  "
            f"avg risk {statistics.mean((r.avg_risk or 0) for r in rs):.0%}")
    return "\n".join(lines)


def main() -> None:
    per_variant = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    max_hours = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT / "log.txt", "a", encoding="utf-8", buffering=1)
    status: dict = {}
    bot = Bot(log=lambda m: log.write(f"{time.strftime('%H:%M:%S')} {m}\n"),
              status=lambda s: status.update(s),
              settings=Settings(background_mode=True, buy_enhancements=False,
                                record_test_data=True))
    order = [v for _ in range(per_variant) for v in VARIANTS]
    started, deadline = time.time(), time.time() + max_hours * 3600
    index, in_run = 0, False
    apply(order[0])
    bot.source = f"experiment {order[0]}"
    log.write(f"=== experiment start: {per_variant} runs per variant, order {order}\n")
    bot.start()
    try:
        while bot.running and time.time() < deadline:
            time.sleep(1.0)
            state = status.get("state")
            if state == "in_run":
                in_run = True
            elif in_run and state == "game_over":  # one run finished
                in_run = False
                index += 1
                log.write(f"=== run {index}/{len(order)} done ({order[index - 1]})\n")
                (OUT / "summary.txt").write_text(summary(started), encoding="utf-8")
                if index >= len(order):
                    break
                apply(order[index])  # takes effect before the next run starts
                bot.source = f"experiment {order[index]}"
    finally:
        bot.stop()
        time.sleep(5)
        (OUT / "summary.txt").write_text(summary(started), encoding="utf-8")
        log.write("=== experiment end\n")


if __name__ == "__main__":
    main()
