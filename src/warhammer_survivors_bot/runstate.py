"""Share "is a bot running, and who started it?" between processes.

Every running :class:`~warhammer_survivors_bot.bot.Bot` writes a small
heartbeat file. The control window reads it, so it can show when a bot is
running from somewhere else (e.g. a test run started from a script) and ask
that run to stop.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

_DIR = Path(tempfile.gettempdir()) / "warhammer_survivors_bot"
STATUS_FILE = _DIR / "running.json"
STALE_AFTER = 5.0  # seconds without heartbeat -> the run is considered gone


def _stop_file(pid: int) -> Path:
    return _DIR / f"stop_{pid}"


def heartbeat(source: str, started: float, state: str, status: dict | None = None) -> None:
    """Called regularly by a running bot. ``status`` = its latest live status, so
    the control window can display runs started elsewhere (e.g. from a script)."""
    _DIR.mkdir(parents=True, exist_ok=True)
    data = {"pid": os.getpid(), "source": source, "started": started,
            "updated": time.time(), "state": state, "status": status or {}}
    tmp = STATUS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, STATUS_FILE)
    except OSError:
        pass  # another process may be reading/replacing it; next beat retries


def clear() -> None:
    """Called when a bot stops."""
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            STATUS_FILE.unlink()
    except (OSError, ValueError):
        pass
    for path in (_stop_file(os.getpid()), log_file(os.getpid())):
        try:
            path.unlink()
        except OSError:
            pass


def current() -> dict | None:
    """The running bot's heartbeat, or None if no bot is running."""
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - data.get("updated", 0) > STALE_AFTER:
        return None
    return data


def log_file(pid: int) -> Path:
    """Shared log of the bot in process ``pid`` (read by the control window)."""
    return _DIR / f"log_{pid}.txt"


def append_log(line: str) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_file(os.getpid()), "a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")
    except OSError:
        pass


def request_stop(pid: int) -> None:
    """Ask the bot in process ``pid`` to stop (it checks every frame)."""
    _DIR.mkdir(parents=True, exist_ok=True)
    _stop_file(pid).touch()


def stop_requested() -> bool:
    return _stop_file(os.getpid()).exists()
