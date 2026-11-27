"""Make the running game believe it always has focus (runtime only, opt-in).

The game ignores all input while unfocused. With the user's permission, this
module attaches to the running game process with Frida and installs in-memory
hooks; no game files are changed, and the hooks are removed again on
:meth:`FocusHack.detach` or when this Python process exits.

Hooks inside the game process:
- ``GetForegroundWindow`` / ``GetActiveWindow`` / ``GetFocus`` return the
  game's window;
- the game window's message procedure sees focus-loss messages rewritten as
  focus-gain ones (``WM_ACTIVATEAPP``, ``WM_ACTIVATE``, ``WM_NCACTIVATE``) or
  neutralised (``WM_KILLFOCUS`` -> ``WM_NULL``).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from collections.abc import Callable

from warhammer_survivors_bot import window

_SCRIPT = r"""
const HWND = ptr('%(hwnd)s');
const user32 = Process.getModuleByName('user32.dll');
const exp = (n) => user32.getExportByName(n);
const retHwnd = () => new NativeCallback(() => HWND, 'pointer', []);

Interceptor.replace(exp('GetForegroundWindow'), retHwnd());
Interceptor.replace(exp('GetActiveWindow'), retHwnd());
Interceptor.replace(exp('GetFocus'), retHwnd());

const getWndProc = new NativeFunction(exp('GetWindowLongPtrW'), 'pointer', ['pointer', 'int']);
const wndProc = getWndProc(HWND, -4);  // GWLP_WNDPROC
let rewritten = 0;
Interceptor.attach(wndProc, {
  onEnter(args) {
    if (!args[0].equals(HWND)) return;
    const msg = args[1].toInt32();
    const w = args[2].toInt32() & 0xffff;
    if ((msg === 0x001C || msg === 0x0086) && w === 0) {        // WM_ACTIVATEAPP / WM_NCACTIVATE
      args[2] = ptr(1); rewritten++;
    } else if (msg === 0x0006 && w === 0) {                     // WM_ACTIVATE(WA_INACTIVE)
      args[2] = ptr(1); rewritten++;
    } else if (msg === 0x0008) {                                // WM_KILLFOCUS -> WM_NULL
      args[1] = ptr(0); rewritten++;
    }
  }
});
rpc.exports = { stats: () => ({ wndProc: wndProc.toString(), rewritten }) };
send('installed');
"""

_user32 = ctypes.WinDLL("user32")
_user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.SendMessageW.restype = ctypes.c_ssize_t
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


class FocusHack:
    def __init__(self, log: Callable[[str], None] = print) -> None:
        self._log = log
        self._session = None
        self._script = None
        self.hwnd: int | None = None

    @property
    def attached(self) -> bool:
        return self._script is not None

    def attach(self) -> None:
        import frida  # optional dependency, only needed for this feature

        hwnd = window.find_window()
        if hwnd is None:
            raise RuntimeError("game window not found")
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self._session = frida.attach(pid.value)
        self._script = self._session.create_script(_SCRIPT % {"hwnd": hex(hwnd)})
        self._script.on("message", self._on_message)
        self._script.load()
        self.hwnd = hwnd
        self.reassert_focus()

    def reassert_focus(self) -> None:
        """Tell the game it is active (e.g. after it already lost focus)."""
        if self.hwnd is None:
            return
        pid_tid = _user32.GetWindowThreadProcessId(self.hwnd, None)
        _user32.SendMessageW(self.hwnd, 0x001C, 1, pid_tid)  # WM_ACTIVATEAPP(TRUE)
        _user32.SendMessageW(self.hwnd, 0x0086, 1, 0)        # WM_NCACTIVATE(TRUE)
        _user32.SendMessageW(self.hwnd, 0x0006, 1, 0)        # WM_ACTIVATE(WA_ACTIVE)
        _user32.SendMessageW(self.hwnd, 0x0007, 0, 0)        # WM_SETFOCUS

    def stats(self) -> dict:
        return self._script.exports_sync.stats() if self._script else {}

    def detach(self) -> None:
        try:
            if self._script is not None:
                self._script.unload()
            if self._session is not None:
                self._session.detach()
        finally:
            self._script = self._session = None
            self.hwnd = None

    def _on_message(self, message: dict, _data) -> None:
        if message.get("type") == "send":
            self._log(f"Focus hook: {message.get('payload')}")
        elif message.get("type") == "error":
            self._log(f"Focus hook error: {message.get('description')}")
