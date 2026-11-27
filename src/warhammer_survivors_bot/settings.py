"""User-toggleable bot features, persisted to a small JSON file."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SETTINGS_FILE = Path("settings.json")


@dataclass
class Settings:
    move: bool = True              # dodge enemies and collect XP during a run
    pick_level_ups: bool = True    # choose a level-up card automatically
    open_chests: bool = True       # open "Wargear Acquired!" chests and accept the reward
    auto_restart: bool = True      # navigate menus / game over to start the next run
    buy_enhancements: bool = False  # spend coins on Enhancements between runs
    debug_overlays: bool = False   # save annotated frames to screenshots/overlay/

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> Settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: bool(v) for k, v in data.items() if k in known})

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# Labels shown in the UI, in display order.
LABELS: dict[str, str] = {
    "move": "Move (dodge enemies, collect XP)",
    "pick_level_ups": "Pick level-up cards",
    "open_chests": "Open wargear chests",
    "auto_restart": "Start the next run automatically",
    "buy_enhancements": "Buy enhancements with coins",
    "debug_overlays": "Save debug overlays (every 5 s)",
}
