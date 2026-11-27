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
  neutralised (``WM_KILLFOCUS`` -> ``WM_NULL``);
- **input isolation**: the game reads keyboard and mouse via Raw Input from
  *all* windows and only uses them while it believes it is focused. Since it
  now always believes that, keystrokes typed into other applications would
  reach it. While the game is not *really* the foreground window, keyboard and
  mouse events from ``GetRawInputData``/``GetRawInputBuffer`` are therefore
  rewritten into no-ops (unknown key released, no mouse motion/buttons), the
  "pressed" bits from ``GetKeyboardState``/``GetKeyState``/``GetAsyncKeyState``
  are cleared, and ``GetCursorPos`` reports a point far outside the game. The real foreground
  window is read via ``GetGUIThreadInfo``, which is not hooked. Controllers
  (XInput) are unaffected.
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
// ---- input isolation -------------------------------------------------------
const getGUIThreadInfo = new NativeFunction(exp('GetGUIThreadInfo'), 'int', ['uint', 'pointer']);
const gti = Memory.alloc(72);  // GUITHREADINFO (x64)
function reallyForeground() {
  gti.writeU32(72);
  if (!getGUIThreadInfo(0, gti)) return true;  // unknown: don't interfere
  return gti.add(8).readPointer().equals(HWND);  // hwndActive of the foreground thread
}
let filterOn = true;
let neutralised = 0;
const HEADER = 24;  // RAWINPUTHEADER on x64
function neutralise(raw) {  // raw: pointer to a RAWINPUT
  const type = raw.readU32();
  const body = raw.add(HEADER);
  if (type === 1) {            // RIM_TYPEKEYBOARD: unknown key released
    body.writeU16(0);          // MakeCode
    body.add(2).writeU16(1);   // Flags = RI_KEY_BREAK
    body.add(6).writeU16(0xFF);   // VKey (none)
    body.add(8).writeU32(0x101);  // Message = WM_KEYUP
    neutralised++;
  } else if (type === 0) {     // RIM_TYPEMOUSE: no motion, no buttons, no wheel
    body.writeU16(0);          // usFlags (relative)
    body.add(4).writeU32(0);   // usButtonFlags + usButtonData
    body.add(8).writeU32(0);   // ulRawButtons
    body.add(12).writeS32(0);  // lLastX
    body.add(16).writeS32(0);  // lLastY
    neutralised++;
  }
}
const RID_INPUT = 0x10000003;
Interceptor.attach(exp('GetRawInputData'), {
  onEnter(args) { this.cmd = args[1].toUInt32(); this.data = args[2]; },
  onLeave(ret) {
    if (!filterOn || this.data.isNull() || this.cmd !== RID_INPUT) return;
    if (ret.toUInt32() === 0xFFFFFFFF || ret.toUInt32() === 0) return;
    if (!reallyForeground()) neutralise(this.data);
  }
});
Interceptor.attach(exp('GetRawInputBuffer'), {
  onEnter(args) { this.data = args[0]; },
  onLeave(ret) {
    const n = ret.toUInt32();
    if (!filterOn || this.data.isNull() || n === 0 || n === 0xFFFFFFFF) return;
    if (reallyForeground()) return;
    let cur = this.data;
    for (let i = 0; i < n; i++) {
      const size = cur.add(4).readU32();
      neutralise(cur);
      cur = cur.add((size + 7) & ~7);  // NEXTRAWINPUTBLOCK: 8-byte aligned on x64
    }
  }
});
// The game also polls the system-wide key state; clear every "pressed" bit
// (keep toggle bits such as Caps Lock) while it is not really in front.
Interceptor.attach(exp('GetKeyboardState'), {
  onEnter(args) { this.buf = args[0]; },
  onLeave(ret) {
    if (!filterOn || ret.toInt32() === 0 || this.buf.isNull() || reallyForeground()) return;
    for (let vk = 0; vk < 256; vk++) {
      const b = this.buf.add(vk).readU8();
      if (b & 0x80) { this.buf.add(vk).writeU8(b & 0x01); neutralised++; }
    }
  }
});
['GetKeyState', 'GetAsyncKeyState'].forEach(name => Interceptor.attach(exp(name), {
  onLeave(ret) {
    if (!filterOn || (ret.toInt32() & 0x8001) === 0 || reallyForeground()) return;
    // GetKeyState: keep only the toggle bit; GetAsyncKeyState: nothing pressed.
    ret.replace(ptr(name === 'GetKeyState' ? (ret.toInt32() & 0x0001) : 0));
  }
}));
Interceptor.attach(exp('GetCursorPos'), {
  onEnter(args) { this.pt = args[0]; },
  onLeave(ret) {
    if (!filterOn || ret.toInt32() === 0 || this.pt.isNull() || reallyForeground()) return;
    this.pt.writeS32(-32000);
    this.pt.add(4).writeS32(-32000);
  }
});

rpc.exports = {
  stats: () => ({ wndProc: wndProc.toString(), rewritten, neutralised, filterOn,
                  reallyForeground: reallyForeground() }),
  setFilter: (on) => { filterOn = !!on; return filterOn; },
};
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

    def set_input_isolation(self, on: bool) -> None:
        """Turn the keyboard/mouse isolation on or off (on by default)."""
        if self._script:
            self._script.exports_sync.set_filter(on)

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
