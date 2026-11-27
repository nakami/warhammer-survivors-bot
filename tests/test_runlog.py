from pathlib import Path

from warhammer_survivors_bot.runlog import RunHistory, RunRecord


def test_record_stats() -> None:
    r = RunRecord(started=1.0)
    r.observe(0.5, 0.9, 0.2)
    r.observe(0.5, 0.4, 0.6)
    assert r.play_seconds == 1.0 and r.min_health == 0.4
    assert abs(r.avg_risk - 0.4) < 1e-9
    r.level_ups = 6
    assert r.level == 7


def test_history_roundtrip_update_and_order(tmp_path: Path) -> None:
    h = RunHistory(tmp_path / "runs.json")
    assert h.last() == []
    a, b = RunRecord(started=10.0), RunRecord(started=20.0)
    h.save(a)
    h.save(b)
    b.end = "game over"
    b.level_ups = 3
    h.save(b)  # update, not duplicate
    runs = h.last()
    assert [r.started for r in runs] == [20.0, 10.0]  # newest first
    assert runs[0].end == "game over" and runs[0].level == 4


def test_history_keeps_only_last_n(tmp_path: Path) -> None:
    h = RunHistory(tmp_path / "runs.json")
    for i in range(15):
        h.save(RunRecord(started=float(i)))
    assert len(h.last(10)) == 10 and h.last(10)[0].started == 14.0
