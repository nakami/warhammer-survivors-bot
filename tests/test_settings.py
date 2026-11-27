from pathlib import Path

from warhammer_survivors_bot.settings import LABELS, Settings


def test_enhancement_buying_is_off_by_default() -> None:
    assert Settings().buy_enhancements is False


def test_every_setting_has_a_label() -> None:
    assert set(LABELS) == set(vars(Settings()))


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(move=False, buy_enhancements=True).save(path)
    loaded = Settings.load(path)
    assert loaded.move is False
    assert loaded.buy_enhancements is True
    assert loaded.pick_level_ups is True


def test_missing_or_broken_file_gives_defaults(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "nope.json") == Settings()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert Settings.load(broken) == Settings()
