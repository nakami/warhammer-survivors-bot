import ctypes

from warhammer_survivors_bot import gui


def test_second_control_window_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(gui, "_MUTEX_NAME", "Local\WarhammerSurvivorsBotTestMutex")
    first = gui._claim_single_instance()
    try:
        assert first is not None
        assert gui._claim_single_instance() is None
    finally:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(first))
    again = gui._claim_single_instance()
    assert again is not None
    ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(again))
