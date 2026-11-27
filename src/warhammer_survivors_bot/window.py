"""Locate and manage the game window via the Win32 API (read-only, no injection)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Make coordinates physical pixels regardless of Windows display scaling.
try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
except (OSError, AttributeError):
    user32.SetProcessDPIAware()

WINDOW_TITLE = "Warhammer Survivors"
PROCESS_NAME = "WarhammerSurvivors.exe"

_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def list_windows() -> list[tuple[int, str]]:
    """Return (hwnd, title) for all visible top-level windows with a title."""
    result: list[tuple[int, str]] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            title = _title(hwnd)
            if title:
                result.append((hwnd, title))
        return True

    user32.EnumWindows(_EnumWindowsProc(cb), 0)
    return result


def process_name(hwnd: int) -> str:
    """Executable file name of the process owning the window."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


def find_window(title: str = WINDOW_TITLE, exe: str = PROCESS_NAME) -> int | None:
    """Find the game window by exact title and owning executable."""
    for hwnd, t in list_windows():
        if t == title and process_name(hwnd).lower() == exe.lower():
            return hwnd
    return None


def client_rect(hwnd: int) -> Rect:
    """Client area (game pixels, no title bar/borders) in screen coordinates."""
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return Rect(pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top)


def focus(hwnd: int) -> bool:
    """Bring the window to the foreground so it receives our input."""
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    # Tapping ALT allows a background process to call SetForegroundWindow.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    return bool(user32.SetForegroundWindow(hwnd))


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd
