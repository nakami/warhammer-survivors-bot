"""Grab the pixels of the game window, exactly what a human sees in it.

Uses ``PrintWindow`` with ``PW_RENDERFULLCONTENT``, which asks the desktop
compositor for the window's own image. Unlike copying screen pixels, this
works while the game is behind other windows or not focused (but not while
it is minimized).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

import numpy as np

from warhammer_survivors_bot import window

_user32 = ctypes.WinDLL("user32")
_gdi32 = ctypes.WinDLL("gdi32")

_user32.GetDC.restype = wt.HDC
_user32.GetDC.argtypes = [wt.HWND]
_user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
_user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
_gdi32.CreateCompatibleDC.restype = wt.HDC
_gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
_gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
_gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.SelectObject.restype = wt.HGDIOBJ
_gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
_gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wt.HDC]
_gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                             ctypes.c_void_p, wt.UINT]

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class CaptureError(RuntimeError):
    pass


class Capturer:
    """Captures the client area of a window. Not thread-safe: one per thread."""

    def __init__(self) -> None:
        self._size: tuple[int, int] | None = None
        self._mdc = None
        self._bmp = None
        self._buf = None

    def _ensure(self, hwnd: int, w: int, h: int) -> None:
        if self._size == (w, h):
            return
        self.close()
        hdc = _user32.GetDC(hwnd)
        try:
            self._mdc = _gdi32.CreateCompatibleDC(hdc)
            self._bmp = _gdi32.CreateCompatibleBitmap(hdc, w, h)
        finally:
            _user32.ReleaseDC(hwnd, hdc)
        _gdi32.SelectObject(self._mdc, self._bmp)
        self._buf = ctypes.create_string_buffer(w * h * 4)
        self._size = (w, h)

    def grab(self, hwnd: int) -> np.ndarray:
        """Return a BGR uint8 image of the window's client area."""
        rect = window.client_rect(hwnd)
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            raise CaptureError("window has no client area (minimized?)")
        self._ensure(hwnd, w, h)
        if not _user32.PrintWindow(hwnd, self._mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            raise CaptureError("PrintWindow failed")
        bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        if not _gdi32.GetDIBits(self._mdc, self._bmp, 0, h, self._buf, ctypes.byref(bmi), 0):
            raise CaptureError("GetDIBits failed")
        return np.frombuffer(self._buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()

    def close(self) -> None:
        if self._bmp:
            _gdi32.DeleteObject(self._bmp)
        if self._mdc:
            _gdi32.DeleteDC(self._mdc)
        self._size = self._mdc = self._bmp = self._buf = None

    def __del__(self) -> None:
        self.close()
