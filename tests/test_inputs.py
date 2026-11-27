import pytest

from warhammer_survivors_bot import inputs


def test_named_keys_are_layout_independent() -> None:
    assert inputs.scancode("esc") == 0x01
    assert inputs.scancode("up") == 0xE048


def test_raw_scancode() -> None:
    assert inputs.scancode("sc:12") == 0x12


def test_unknown_key() -> None:
    with pytest.raises(KeyError):
        inputs.scancode("not-a-key")


def test_char_resolves_through_layout() -> None:
    # Whatever the layout, a letter must map to some valid scancode.
    assert 0 < inputs.scancode("e") < 0x80
