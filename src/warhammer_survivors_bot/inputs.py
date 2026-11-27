"""Simulated keyboard/mouse input via Win32 SendInput.

Keys are sent as hardware scancodes, i.e. like a physical keyboard.

The game reads *layout-translated* keys: with NEO 2 active, the game's "E"
binding is triggered by the physical key that types "e" (QWERTY "F" position).
Therefore single characters passed to :func:`press` & co. are resolved through
the active keyboard layout to the physical key that produces them. Named keys
(``esc``, ``space``, ``up``, ...) are layout independent. To force a specific
physical key, use ``"sc:<hex>"`` (e.g. ``"sc:12"`` for the QWERTY-E position).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


# Layout-independent named keys (Set 1 scancodes). 0xE0xx = extended key.
# Note: NEO 2 uses CapsLock and the key right of it as modifiers, so avoid them.
NAMED_KEYS: dict[str, int] = {
    "esc": 0x01, "backspace": 0x0E, "tab": 0x0F, "enter": 0x1C,
    "ctrl": 0x1D, "shift": 0x2A, "alt": 0x38, "space": 0x39,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40,
    "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "f11": 0x57, "f12": 0x58,
    "up": 0xE048, "left": 0xE04B, "right": 0xE04D, "down": 0xE050,
}

user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.GetKeyboardLayout.argtypes = [wt.DWORD]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetForegroundWindow.restype = wt.HWND
user32.VkKeyScanExW.argtypes = [wt.WCHAR, ctypes.c_void_p]
user32.VkKeyScanExW.restype = ctypes.c_short
user32.MapVirtualKeyExW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p]
user32.MapVirtualKeyExW.restype = wt.UINT


def _active_layout() -> int:
    """Keyboard layout of the foreground window (i.e. the game when focused)."""
    tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    return user32.GetKeyboardLayout(tid)


def scancode_for_char(char: str, hkl: int | None = None) -> int:
    """Physical scancode of the key that types ``char`` in the given layout."""
    hkl = _active_layout() if hkl is None else hkl
    res = user32.VkKeyScanExW(char, hkl)
    if res == -1:
        raise ValueError(f"character {char!r} not typeable in layout {hkl:#x}")
    if res >> 8 & 0xFF:
        raise ValueError(f"character {char!r} requires modifiers in layout {hkl:#x}")
    sc = user32.MapVirtualKeyExW(res & 0xFF, 0, hkl)  # MAPVK_VK_TO_VSC
    if not sc:
        raise ValueError(f"no scancode for {char!r}")
    return sc


def scancode(name: str) -> int:
    """Resolve a key name, single character, or ``sc:<hex>`` to a scancode."""
    if name in NAMED_KEYS:
        return NAMED_KEYS[name]
    if name.startswith("sc:"):
        return int(name[3:], 16)
    if len(name) == 1:
        return scancode_for_char(name.lower())
    raise KeyError(f"unknown key {name!r}")


def _send(*events: INPUT) -> None:
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


def _key_event(name: str, up: bool) -> INPUT:
    code = scancode(name)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if code > 0xFF:
        flags |= KEYEVENTF_EXTENDEDKEY
        code &= 0xFF
    return INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(0, code, flags, 0, 0)))


def key_down(name: str) -> None:
    _send(_key_event(name, up=False))


def key_up(name: str) -> None:
    _send(_key_event(name, up=True))


def press(name: str, hold: float = 0.05) -> None:
    key_down(name)
    time.sleep(hold)
    key_up(name)


def hold(name: str, seconds: float) -> None:
    press(name, hold=seconds)


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
    _send(INPUT(type=INPUT_MOUSE, u=_U(mi=MOUSEINPUT(dx, dy, data, flags, 0, 0))))


def move_to(x: int, y: int) -> None:
    """Move the cursor to absolute screen pixel (x, y), across all monitors."""
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    nx = round((x - vx) * 65535 / (vw - 1))
    ny = round((y - vy) * 65535 / (vh - 1))
    _mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)


def click(x: int | None = None, y: int | None = None, button: str = "left",
          hold_s: float = 0.05) -> None:
    if x is not None and y is not None:
        move_to(x, y)
        time.sleep(0.05)
    down, up = (
        (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
        else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    )
    _mouse(down)
    time.sleep(hold_s)
    _mouse(up)


def scroll(clicks: int) -> None:
    _mouse(MOUSEEVENTF_WHEEL, data=ctypes.c_uint32(clicks * 120).value)
