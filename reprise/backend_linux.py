import atexit
import json
import os
import re
import selectors
import socket
import subprocess
import threading
import time
import traceback

import evdev
import numpy as np
from evdev import ecodes as E

from .keys import BUTTON_TABLE, KEY_TABLE, MODIFIERS, Keymap, parse_hotkey
from .paths import clean_env, find_tool

VIRTUAL_NAME = "reprise virtual input"
PPM_RE = re.compile(rb"P6\s+(\d+)\s+(\d+)\s+\d+\s")
SELF_CACHE_S = 0.25
# uaccess gives the logged in user access straight away, no group change or relog
UDEV_RULE = ('SUBSYSTEM=="input", KERNEL=="event*", TAG+="uaccess"\\n'
             'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"\\n')
UDEV_PATH = "/etc/udev/rules.d/70-reprise-macro-creator.rules"


def _detect_layout():
    try:
        out = subprocess.run(["hyprctl", "getoption", "input:kb_layout", "-j"], capture_output=True, text=True, timeout=2, env=clean_env()).stdout
        return json.loads(out).get("str", "us").split(",")[0].strip() or "us"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "us"


def _tool(name):
    path, env = find_tool(name)
    if path is None:
        raise RuntimeError(f"{name} is not installed")
    return path, env


def _parse_ppm(data):
    m = PPM_RE.match(data)
    if not m:
        raise RuntimeError("grim returned no image")
    w, h = int(m.group(1)), int(m.group(2))
    return np.frombuffer(data, dtype=np.uint8, count=w * h * 3, offset=m.end()).reshape(h, w, 3)


class Backend:
    name = "linux-hyprland"

    def __init__(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.sock_path = os.path.join(run, "hypr", sig, ".socket.sock")
        self.keymap = Keymap(_detect_layout())
        self.pressed = set()
        self.pressed_names = set()
        self.subscribers = []
        self.motion_wanted = False
        self.recording = False
        self._lock = threading.Lock()
        self._ui = None
        self._ui_error = None
        self._stop = threading.Event()
        self._hidden_ws = None
        self._focus_before = None
        self._blocks = []
        self._self_cache = (0.0, [], set())
        atexit.register(self.clear_hotkey_blocks)
        self._ev_codes = {}
        for _name, ev, _vk in KEY_TABLE + BUTTON_TABLE:
            code = getattr(E, ev, None)
            if code is not None:
                self._ev_codes[ev] = code
        self._code_to_ev = {v: k for k, v in self._ev_codes.items()}
        self._open_uinput()

    def _open_uinput(self):
        try:
            keys = sorted(set(self._ev_codes.values()))
            self._ui = evdev.UInput({E.EV_KEY: keys, E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL, E.REL_HWHEEL]},
                                    name=VIRTUAL_NAME)
            self._ui_error = None
        except (OSError, evdev.UInputError) as e:
            self._ui_error = str(e)

    def missing_permissions(self):
        return self._ui is None or not evdev.list_devices()

    def fix_permissions(self):
        script = (f"printf '{UDEV_RULE}' > {UDEV_PATH} && (modprobe uinput 2>/dev/null; true) "
                  "&& udevadm control --reload-rules && udevadm trigger --subsystem-match=input --subsystem-match=misc")
        path, env = find_tool("pkexec")
        if path is None:
            return False
        try:
            if subprocess.run([path, "sh", "-c", script], env=env, timeout=180).returncode != 0:
                return False
        except (OSError, subprocess.SubprocessError):
            return False
        # udev applies the new access a moment after trigger returns
        deadline = time.monotonic() + 4
        while self.missing_permissions() and time.monotonic() < deadline:
            time.sleep(0.25)
            if self._ui is None:
                self._open_uinput()
        return not self.missing_permissions()

    def problems(self):
        out = []
        if not os.path.exists(self.sock_path):
            out.append("hyprland was not found. the linux backend only works under hyprland.")
        # list_devices silently drops anything unreadable, so empty means no permission
        if not evdev.list_devices():
            out.append("cannot read /dev/input, so hotkeys and recording will not work.")
        if self._ui_error:
            out.append(f"cannot write to /dev/uinput, so playback will not work: {self._ui_error}.")
        for tool, use in (("grim", "screen reading"), ("slurp", "picking from the screen")):
            if find_tool(tool)[0] is None:
                out.append(f"{tool} is not installed, {use} will not work.")
        return out

    def ipc(self, cmd):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(2)
            s.connect(self.sock_path)
            s.sendall(cmd.encode())
            chunks = []
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
            return b"".join(chunks).decode(errors="replace")
        except OSError as e:
            raise RuntimeError(f"cannot reach hyprland: {e}") from e
        finally:
            s.close()

    def ipc_json(self, cmd):
        try:
            return json.loads(self.ipc("j/" + cmd))
        except (RuntimeError, ValueError):
            return None

    def cursor_pos(self):
        try:
            x, y = self.ipc("cursorpos").split(",")
            return int(float(x)), int(float(y))
        except (RuntimeError, ValueError):
            return 0, 0

    def screen_size(self):
        mons = self.ipc_json("monitors") or []
        if not mons:
            return 1920, 1080
        w = max(m["x"] + int(m["width"] / m["scale"]) for m in mons)
        h = max(m["y"] + int(m["height"] / m["scale"]) for m in mons)
        return w, h

    def _need_ui(self):
        if self._ui is None:
            raise RuntimeError(self._ui_error or "uinput not available")

    def _emit(self, etype, code, value):
        self._need_ui()
        with self._lock:
            self._ui.write(etype, code, value)
            self._ui.syn()

    def move(self, x, y):
        self.ipc(f"dispatch movecursor {int(x)} {int(y)}")

    def nudge(self):
        # movecursor alone does not send pointer motion to the app under the cursor
        if self._ui is None:
            return
        with self._lock:
            self._ui.write(E.EV_REL, E.REL_X, 1)
            self._ui.syn()
            self._ui.write(E.EV_REL, E.REL_X, -1)
            self._ui.syn()

    def _code(self, name):
        ev = self.keymap.name_to_evdev.get(str(name).lower())
        if ev is None:
            raise ValueError(f"unknown key {name!r}")
        return self._ev_codes[ev]

    def key(self, name, down):
        self._emit(E.EV_KEY, self._code(name), 1 if down else 0)

    def button(self, name, down):
        self._emit(E.EV_KEY, self._code(name), 1 if down else 0)

    def wheel(self, direction, amount):
        code = E.REL_WHEEL if direction in ("up", "down") else E.REL_HWHEEL
        val = 1 if direction in ("up", "right") else -1
        for _ in range(int(amount)):
            self._emit(E.EV_REL, code, val)
            time.sleep(0.008)

    def type_char(self, ch):
        m = self.keymap.chars.get(ch)
        if m is None:
            return False
        self._need_ui()
        ev, shift, altgr = m
        code = self._ev_codes[ev]
        with self._lock:
            if shift:
                self._ui.write(E.EV_KEY, E.KEY_LEFTSHIFT, 1)
            if altgr:
                self._ui.write(E.EV_KEY, E.KEY_RIGHTALT, 1)
            self._ui.write(E.EV_KEY, code, 1)
            self._ui.syn()
            self._ui.write(E.EV_KEY, code, 0)
            if altgr:
                self._ui.write(E.EV_KEY, E.KEY_RIGHTALT, 0)
            if shift:
                self._ui.write(E.EV_KEY, E.KEY_LEFTSHIFT, 0)
            self._ui.syn()
        return True

    def grab(self, x1, y1, x2, y2):
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        w, h = x2 - x1 + 1, y2 - y1 + 1
        grim, env = _tool("grim")
        out = subprocess.run([grim, "-s", "1", "-g", f"{x1},{y1} {w}x{h}", "-t", "ppm", "-"],
                             capture_output=True, timeout=10, env=env)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode(errors="replace").strip() or "grim failed")
        return _parse_ppm(out.stdout)

    def pixel(self, x, y):
        a = self.grab(x, y, x, y)
        r, g, b = (int(v) for v in a[0, 0])
        return r, g, b

    def save_region(self, x1, y1, x2, y2, path):
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        grim, env = _tool("grim")
        subprocess.run([grim, "-s", "1", "-g", f"{x1},{y1} {x2 - x1 + 1}x{y2 - y1 + 1}", path], check=True, timeout=10, env=env)

    def pick_point(self):
        slurp, env = _tool("slurp")
        r = subprocess.run([slurp, "-p", "-b", "00000000", "-c", "5b9dffff"], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            return None
        pos = r.stdout.split()[0].split(",")
        return int(pos[0]), int(pos[1])

    def pick_region(self):
        slurp, env = _tool("slurp")
        r = subprocess.run([slurp, "-b", "0b0c1088", "-c", "5b9dffff", "-w", "2"], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            return None
        xy, wh = r.stdout.split()
        x, y = (int(v) for v in xy.split(","))
        w, h = (int(v) for v in wh.split("x"))
        return x, y, x + w - 1, y + h - 1

    def _self_clients(self):
        pid = os.getpid()
        return [c for c in self.ipc_json("clients") or [] if c.get("pid") == pid and c.get("mapped", True)]

    def hide_self(self):
        cs = self._self_clients()
        if not cs:
            return False
        self._hidden_ws = {c["address"]: c["workspace"]["id"] for c in cs}
        self._focus_before = (self.active_window() or {}).get("id")
        for c in cs:
            self.ipc(f"dispatch movetoworkspacesilent special:reprise,address:{c['address']}")
        time.sleep(0.2)
        return True

    def show_self(self):
        if not self._hidden_ws:
            return
        for addr, ws in self._hidden_ws.items():
            self.ipc(f"dispatch movetoworkspacesilent {ws},address:{addr}")
        target = self._focus_before if self._focus_before in self._hidden_ws else next(iter(self._hidden_ws))
        self.ipc(f"dispatch focuswindow address:{target}")
        self._hidden_ws = None

    def windows(self):
        out = []
        for c in self.ipc_json("clients") or []:
            if not c.get("mapped", True) or c.get("hidden"):
                continue
            out.append({"id": c["address"], "title": c.get("title", ""), "class": c.get("class", ""),
                        "pid": c.get("pid"), "x": c["at"][0], "y": c["at"][1], "w": c["size"][0], "h": c["size"][1],
                        "workspace": c["workspace"]["id"]})
        return out

    def active_window(self):
        c = self.ipc_json("activewindow") or {}
        if not c or "address" not in c:
            return None
        return {"id": c["address"], "title": c.get("title", ""), "class": c.get("class", ""), "pid": c.get("pid")}

    @staticmethod
    def matches(win, spec):
        spec = (spec or "").strip()
        if not win:
            return False
        if spec == "" or spec.lower() == "a":
            return True
        low = spec.lower()
        if low.startswith("ahk_class "):
            return low[10:].strip() in win["class"].lower()
        if low.startswith("ahk_exe "):
            exe = low[8:].strip()
            try:
                with open(f"/proc/{win['pid']}/comm", encoding="utf-8") as f:
                    comm = f.read().strip().lower()
            except OSError:
                comm = ""
            return exe in comm or exe in win["class"].lower()
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
        self.ipc(f"dispatch focuswindow address:{w['id']}")
        return True

    def close_window(self, spec):
        w = self.find_window(spec)
        if not w:
            return False
        self.ipc(f"dispatch closewindow address:{w['id']}")
        return True

    def self_focused(self):
        w = self.active_window()
        return bool(w and w.get("pid") == os.getpid())

    def point_in_self(self, x, y):
        # called for every sampled mouse move while recording
        now = time.monotonic()
        stamp, clients, active = self._self_cache
        if now - stamp > SELF_CACHE_S:
            clients = self._self_clients()
            active = set()
            for m in self.ipc_json("monitors") or []:
                active.add(m["activeWorkspace"]["id"])
                sw = m.get("specialWorkspace", {}).get("id")
                if sw:
                    active.add(sw)
            self._self_cache = (now, clients, active)
        for c in clients:
            if c["workspace"]["id"] not in active:
                continue
            ax, ay = c["at"]
            w, h = c["size"]
            if ax <= x < ax + w and ay <= y < ay + h:
                return True
        return False

    def run(self, command):
        return subprocess.Popen(command, shell=True, start_new_session=True, env=clean_env(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key_down(self, name):
        return str(name).lower() in self.pressed

    def held_mods(self):
        return {MODIFIERS[k] for k in list(self.pressed_names) if k in MODIFIERS}

    def subscribe(self, fn):
        self.subscribers.append(fn)

    def start_listener(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def block_hotkeys(self, specs):
        self.clear_hotkey_blocks()
        binds = self.ipc_json("binds") or []
        masks = {"shift": (1, "SHIFT"), "ctrl": (4, "CTRL"), "alt": (8, "ALT"), "win": (64, "SUPER")}
        for spec in specs:
            mods, key = parse_hotkey(spec)
            ev = self.keymap.name_to_evdev.get(key)
            if not ev or ev.startswith("BTN_"):
                continue
            # xkb keycodes are evdev codes plus 8
            code = self._ev_codes[ev] + 8
            mask = sum(masks[m][0] for m in mods)
            modstr = " ".join(masks[m][1] for m in sorted(mods))
            if any(b.get("modmask") == mask and (b.get("keycode") == code or b.get("key", "").lower() == key)
                   for b in binds):
                continue
            try:
                if self.ipc(f"keyword bind {modstr},code:{code},exec,true").strip() == "ok":
                    self._blocks.append(f"{modstr},code:{code}")
            except RuntimeError:
                pass

    def clear_hotkey_blocks(self):
        blocks, self._blocks = self._blocks, []
        for b in blocks:
            try:
                self.ipc(f"keyword unbind {b}")
            except RuntimeError:
                pass

    def shutdown(self):
        self.clear_hotkey_blocks()
        self._stop.set()
        if self._ui is not None:
            self._ui.close()
            self._ui = None

    def _open_devices(self, known, sel):
        for path in evdev.list_devices():
            if path in known:
                continue
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            # our own injected input must not come back as if the user typed it
            if d.name == VIRTUAL_NAME:
                d.close()
                known[path] = None
                continue
            caps = d.capabilities()
            keys = set(caps.get(E.EV_KEY, []))
            rels = set(caps.get(E.EV_REL, []))
            if E.KEY_A in keys or E.BTN_LEFT in keys or E.REL_WHEEL in rels:
                known[path] = d
                sel.register(d, selectors.EVENT_READ)
            else:
                d.close()
                known[path] = None

    def _dispatch(self, ev):
        for fn in list(self.subscribers):
            try:
                fn(ev)
            except Exception:
                # one bad event must not kill the listener thread
                traceback.print_exc()

    def _listen(self):
        sel = selectors.DefaultSelector()
        known = {}
        last_scan = 0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_scan > 2:
                self._open_devices(known, sel)
                last_scan = now
            if not sel.get_map():
                time.sleep(0.5)
                continue
            for keyobj, _ in sel.select(timeout=0.5):
                d = keyobj.fileobj
                try:
                    events = list(d.read())
                except OSError:
                    sel.unregister(d)
                    known.pop(d.path, None)
                    continue
                for e in events:
                    self._handle(e)

    def _handle(self, e):
        t = e.timestamp()
        if e.type == E.EV_KEY:
            ev = self._code_to_ev.get(e.code)
            if ev is None:
                return
            name = self.keymap.evdev_to_name.get(ev, ev)
            if e.value == 2:
                self._dispatch({"kind": "key", "name": name, "down": True, "repeat": True, "t": t})
                return
            down = e.value == 1
            if down:
                self.pressed.add(name)
                self.pressed_names.add(name)
            else:
                self.pressed.discard(name)
                self.pressed_names.discard(name)
            kind = "button" if ev.startswith("BTN_") else "key"
            msg = {"kind": kind, "name": name, "down": down, "repeat": False, "t": t}
            if kind == "button" and self.recording:
                msg["x"], msg["y"] = self.cursor_pos()
            self._dispatch(msg)
        elif e.type == E.EV_REL:
            if e.code == E.REL_WHEEL:
                self._dispatch({"kind": "wheel", "dir": "up" if e.value > 0 else "down", "amount": abs(e.value), "t": t})
            elif e.code == E.REL_HWHEEL:
                self._dispatch({"kind": "wheel", "dir": "right" if e.value > 0 else "left", "amount": abs(e.value), "t": t})
            elif e.code in (E.REL_X, E.REL_Y) and self.motion_wanted:
                self._dispatch({"kind": "motion", "t": t})
