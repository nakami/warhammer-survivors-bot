"""Per-run summaries, kept in a small JSON file so the history survives restarts."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

HISTORY_FILE = Path("runs.json")
KEEP = 200  # records kept on disk


@dataclass
class RunRecord:
    started: float = field(default_factory=time.time)  # wall clock, epoch seconds
    play_seconds: float = 0.0     # time actually in the run (not level-up/pause screens)
    level_ups: int = 0
    chests: int = 0
    hits: int = 0                 # health drops
    min_health: float | None = None
    risk_sum: float = 0.0
    risk_samples: int = 0
    purchases: int = 0            # enhancement ranks bought after the run
    end: str = "running"          # "game over", "stopped" or "running"
    source: str = ""              # who ran the bot (control window / script)

    @property
    def level(self) -> int:
        return 1 + self.level_ups

    @property
    def avg_risk(self) -> float | None:
        return self.risk_sum / self.risk_samples if self.risk_samples else None

    def observe(self, dt: float, health: float | None, risk: float) -> None:
        """Called for every in-run frame."""
        self.play_seconds += dt
        if health is not None:
            self.min_health = health if self.min_health is None else min(self.min_health, health)
        self.risk_sum += risk
        self.risk_samples += 1


class RunHistory:
    def __init__(self, path: Path = HISTORY_FILE) -> None:
        self.path = path

    def load(self) -> list[RunRecord]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        known = RunRecord.__dataclass_fields__
        return [RunRecord(**{k: v for k, v in d.items() if k in known}) for d in data]

    def save(self, record: RunRecord) -> None:
        """Insert or update a record (identified by its start time)."""
        records = [r for r in self.load() if r.started != record.started]
        records.append(record)
        records.sort(key=lambda r: r.started)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in records[-KEEP:]], indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

    def last(self, n: int = 10) -> list[RunRecord]:
        return self.load()[-n:][::-1]  # newest first
