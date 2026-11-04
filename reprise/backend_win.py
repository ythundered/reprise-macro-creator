import ctypes
import os
import subprocess
import threading
import time
import traceback
from ctypes import wintypes as W

import numpy as np

from .keys import BUTTON_TABLE, KEY_TABLE, MODIFIERS, Keymap, hotkey_matches

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")

try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, W.WPARAM, W.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

user32.SendInput.argtypes = (W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
user32.SetWindowsHookExW.restype = W.HHOOK
user32.CallNextHookEx.argtypes = (W.HHOOK, ctypes.c_int, W.WPARAM, W.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = (ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
user32.GetWindowTextLengthW.argtypes = (W.HWND,)
user32.GetWindowTextW.argtypes = (W.HWND, W.LPWSTR, ctypes.c_int)
user32.GetClassNameW.argtypes = (W.HWND, W.LPWSTR, ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (W.HWND, ctypes.POINTER(W.DWORD))
user32.IsWindowVisible.argtypes = (W.HWND,)
user32.SetForegroundWindow.argtypes = (W.HWND,)
user32.ShowWindow.argtypes = (W.HWND, ctypes.c_int)
user32.IsIconic.argtypes = (W.HWND,)
user32.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
user32.WindowFromPoint.argtypes = (W.POINT,)
user32.WindowFromPoint.restype = W.HWND
user32.GetAncestor.argtypes = (W.HWND, W.UINT)
user32.GetAncestor.restype = W.HWND
user32.GetForegroundWindow.restype = W.HWND
user32.GetDC.restype = W.HDC
gdi32.GetPixel.argtypes = (W.HDC, ctypes.c_int, ctypes.c_int)
gdi32.GetPixel.restype = W.DWORD
user32.EnumWindows.argtypes = (WNDENUMPROC, W.LPARAM)
user32.GetWindowRect.argtypes = (W.HWND, ctypes.POINTER(W.RECT))
user32.UnhookWindowsHookEx.argtypes = (W.HHOOK,)
user32.ReleaseDC.argtypes = (W.HWND, W.HDC)
user32.PostThreadMessageW.argtypes = (W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
user32.TranslateMessage.argtypes = (ctypes.POINTER(W.MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(W.MSG),)

EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5, 0x6F, 0x5B, 0x5C, 0x5D, 0x90, 0x2C}
BTN_FLAGS = {"lbutton": (0x02, 0x04, 0), "rbutton": (0x08, 0x10, 0), "mbutton": (0x20, 0x40, 0),
             "xbutton1": (0x80, 0x100, 1), "xbutton2": (0x80, 0x100, 2)}
MSG_BTN = {0x201: ("lbutton", True), 0x202: ("lbutton", False), 0x204: ("rbutton", True), 0x205: ("rbutton", False),
           0x207: ("mbutton", True), 0x208: ("mbutton", False)}


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key_input(vk, up, scan=0, unicode=False):
    flags = (0x2 if up else 0) | (0x4 if unicode else 0) | (0x1 if vk in EXTENDED and not unicode else 0)
    return INPUT(type=1, u=_INPUTUNION(ki=KEYBDINPUT(wVk=0 if unicode else vk, wScan=scan, dwFlags=flags)))


def _mouse_input(flags, data=0):
    return INPUT(type=0, u=_INPUTUNION(mi=MOUSEINPUT(mouseData=data & 0xFFFFFFFF, dwFlags=flags)))


class Backend:
    name = "windows"

    def __init__(self):
        self.keymap = Keymap("us")
        self.name_to_vk = {}
        self.vk_to_name = {}
        for name, _ev, vk in KEY_TABLE + BUTTON_TABLE:
            self.name_to_vk[name] = vk
            self.vk_to_name.setdefault(vk, name)
        self.vk_to_name[0x0D] = "enter"
        self.name_to_vk.update({"return": 0x0D, "escape": 0x1B, "ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4})
        self.pressed = set()
        self.pressed_names = set()
        self.subscribers = []
        self.motion_wanted = False
        self.recording = False
        self._hooks = []
        self._procs = []
        self._thread_id = None
        self._block_specs = []
        self._blocked_down = set()

    def problems(self):
        return []

    def cursor_pos(self):
        p = W.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def screen_size(self):
        return user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0), user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)

    def move(self, x, y):
        user32.SetCursorPos(int(x), int(y))

    def nudge(self):
        pass

    def _vk(self, name):
        vk = self.name_to_vk.get(str(name).lower())
        if vk is None:
            raise ValueError(f"unknown key {name!r}")
        return vk

    def key(self, name, down):
        _send(_key_input(self._vk(name), not down))

    def button(self, name, down):
        d, u, x = BTN_FLAGS[name]
        _send(_mouse_input(d if down else u, x))

    def wheel(self, direction, amount):
        flag = 0x800 if direction in ("up", "down") else 0x1000
        val = 120 if direction in ("up", "right") else -120
        for _ in range(int(amount)):
            _send(_mouse_input(flag, val))
            time.sleep(0.008)

    def type_char(self, ch):
        if ch == "\n":
            _send(_key_input(0x0D, False), _key_input(0x0D, True))
            return True
        for unit in ch.encode("utf-16-le").hex(" ", 2).split():
            code = int.from_bytes(bytes.fromhex(unit), "little")
            _send(_key_input(0, False, code, True), _key_input(0, True, code, True))
        return True

    def grab(self, x1, y1, x2, y2):
        from PIL import ImageGrab
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        img = ImageGrab.grab(bbox=(x1, y1, x2 + 1, y2 + 1), all_screens=True).convert("RGB")
        return np.asarray(img)

    def pixel(self, x, y):
        dc = user32.GetDC(None)
        c = gdi32.GetPixel(dc, int(x), int(y))
        user32.ReleaseDC(None, dc)
        return c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF

    def save_region(self, x1, y1, x2, y2, path):
        from PIL import Image
        Image.fromarray(self.grab(x1, y1, x2, y2)).save(path)

    def pick_point(self):
        return NotImplemented

    def pick_region(self):
        return NotImplemented

    def hide_self(self):
        return False

    def show_self(self):
        pass

    def _info(self, hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        r = W.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        return {"id": hwnd, "title": buf.value, "class": cls.value, "pid": pid.value,
                "x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "workspace": 0}

    def windows(self):
        out = []

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                out.append(self._info(hwnd))
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return out

    def active_window(self):
        h = user32.GetForegroundWindow()
        return self._info(h) if h else None

    def _exe(self, pid):
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout
            return out.split(",")[0].strip('"').lower()
        except Exception:
            return ""

    def matches(self, win, spec):
        spec = (spec or "").strip()
        if not win:
            return False
        if spec.lower() in ("", "a"):
            return True
        low = spec.lower()
        if low.startswith("ahk_class "):
            return low[10:].strip() == win["class"].lower()
        if low.startswith("ahk_exe "):
            return low[8:].strip() == self._exe(win["pid"])
        if low.startswith("ahk_pid "):
            return str(win["pid"]) == low[8:].strip()
        return low in win["title"].lower()

    def find_window(self, spec):
        if (spec or "").strip().lower() in ("", "a"):
            return self.active_window()
        for w in self.windows():
            if self.matches(w, spec):
                return w
        return None

    def activate_window(self, spec):
        w = self.find_window(spec)
        if not w:
            return False
        if user32.IsIconic(w["id"]):
            user32.ShowWindow(w["id"], 9)
        _send(_key_input(0xA4, False), _key_input(0xA4, True))
        user32.SetForegroundWindow(w["id"])
        return True

    def close_window(self, spec):
        w = self.find_window(spec)
        if not w:
            return False
        user32.PostMessageW(w["id"], 0x10, 0, 0)
        return True

    def self_focused(self):
        w = self.active_window()
        return bool(w and w["pid"] == os.getpid())

    def point_in_self(self, x, y):
        h = user32.WindowFromPoint(W.POINT(int(x), int(y)))
        if not h:
            return False
        root = user32.GetAncestor(h, 2)
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(root or h, ctypes.byref(pid))
        return pid.value == os.getpid()

    def run(self, command):
        return subprocess.Popen(command, shell=True)

    def key_down(self, name):
        return str(name).lower() in self.pressed

    def held_mods(self):
        return {MODIFIERS[k] for k in list(self.pressed_names) if k in MODIFIERS}

    def subscribe(self, fn):
        self.subscribers.append(fn)

    def _dispatch(self, ev):
        for fn in list(self.subscribers):
            try:
                fn(ev)
            except Exception:
                # one bad event must not kill the listener thread
                traceback.print_exc()

    def block_hotkeys(self, specs):
        self._block_specs = list(specs)

    def clear_hotkey_blocks(self):
        self._block_specs = []

    def start_listener(self):
        threading.Thread(target=self._hook_thread, daemon=True).start()

    def shutdown(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0)

    def _key_event(self, name, down, t):
        if down and name.lower() in self.pressed:
            self._dispatch({"kind": "key", "name": name, "down": True, "repeat": True, "t": t})
            return
        if down:
            self.pressed.add(name.lower())
            self.pressed_names.add(name)
        else:
            self.pressed.discard(name.lower())
            self.pressed_names.discard(name)
        kind = "button" if name in BTN_FLAGS else "key"
        msg = {"kind": kind, "name": name, "down": down, "repeat": False, "t": t}
        if kind == "button":
            msg["x"], msg["y"] = self.cursor_pos()
        self._dispatch(msg)

    def _hook_thread(self):
        self._thread_id = kernel32.GetCurrentThreadId()

        def kb(code, wparam, lparam):
            if code == 0:
                k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not (k.flags & 0x10):
                    name = self.vk_to_name.get(k.vkCode)
                    if k.vkCode == 0x0D and (k.flags & 0x1):
                        name = "NumpadEnter"
                    if name:
                        down = wparam in (0x100, 0x104)
                        block = False
                        if down:
                            mods = self.held_mods() - ({MODIFIERS[name]} if name in MODIFIERS else set())
                            block = any(hotkey_matches(s, name, mods) for s in self._block_specs)
                            if block:
                                self._blocked_down.add(name)
                        elif name in self._blocked_down:
                            self._blocked_down.discard(name)
                            block = True
                        self._key_event(name, down, time.monotonic())
                        if block:
                            return 1
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def ms(code, wparam, lparam):
            if code == 0:
                m = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not (m.flags & 0x1):
                    t = time.monotonic()
                    if wparam in MSG_BTN:
                        n, d = MSG_BTN[wparam]
                        self._key_event(n, d, t)
                    elif wparam in (0x20B, 0x20C):
                        n = "xbutton1" if (m.mouseData >> 16) == 1 else "xbutton2"
                        self._key_event(n, wparam == 0x20B, t)
                    elif wparam in (0x20A, 0x20E):
                        delta = ctypes.c_short(m.mouseData >> 16).value
                        if wparam == 0x20A:
                            d = "up" if delta > 0 else "down"
                        else:
                            d = "right" if delta > 0 else "left"
                        self._dispatch({"kind": "wheel", "dir": d, "amount": max(1, abs(delta) // 120), "t": t})
                    elif wparam == 0x200 and self.motion_wanted:
                        self._dispatch({"kind": "motion", "t": t})
            return user32.CallNextHookEx(None, code, wparam, lparam)

        kp, mp = HOOKPROC(kb), HOOKPROC(ms)
        self._procs = [kp, mp]
        self._hooks = [user32.SetWindowsHookExW(13, kp, None, 0), user32.SetWindowsHookExW(14, mp, None, 0)]
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for h in self._hooks:
            user32.UnhookWindowsHookEx(h)
