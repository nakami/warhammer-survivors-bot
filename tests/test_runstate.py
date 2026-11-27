import os
import time

import pytest

from warhammer_survivors_bot import runstate


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(runstate, "_DIR", tmp_path)
    monkeypatch.setattr(runstate, "STATUS_FILE", tmp_path / "running.json")


def test_heartbeat_then_clear() -> None:
    assert runstate.current() is None
    runstate.heartbeat("script", time.time(), "in_run")
    run = runstate.current()
    assert run["pid"] == os.getpid() and run["source"] == "script" and run["state"] == "in_run"
    runstate.clear()
    assert runstate.current() is None


def test_stale_heartbeat_is_ignored(monkeypatch) -> None:
    runstate.heartbeat("script", time.time(), "in_run")
    real_time = time.time
    monkeypatch.setattr(runstate.time, "time", lambda: real_time() + runstate.STALE_AFTER + 1)
    assert runstate.current() is None


def test_stop_request_roundtrip() -> None:
    assert not runstate.stop_requested()
    runstate.request_stop(os.getpid())
    assert runstate.stop_requested()
    runstate.clear()
    assert not runstate.stop_requested()


def test_clear_leaves_other_processes_alone() -> None:
    runstate.heartbeat("script", time.time(), "in_run")
    data = runstate.STATUS_FILE.read_text(encoding="utf-8").replace(
        f'"pid": {os.getpid()}', '"pid": 999999')
    runstate.STATUS_FILE.write_text(data, encoding="utf-8")
    runstate.clear()
    assert runstate.current()["pid"] == 999999
