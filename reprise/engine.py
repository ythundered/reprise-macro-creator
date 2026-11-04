import os
import random
import threading
import time

import numpy as np

from .expr import Evaluator, ExprError, Vars, deref, fmt, truthy
from .keys import BUTTON_SHORT, MOD_KEY
from .model import analyze


class Stopped(Exception):
    pass


class MacroError(Exception):
    def __init__(self, msg, row=None):
        super().__init__(msg)
        self.row = row


def hex_color(rgb):
    return "%02x%02x%02x" % tuple(rgb)


def parse_color(s):
    s = str(s).strip().lstrip("#")
    if s.lower().startswith("0x"):
        s = s[2:]
    s = s.rjust(6, "0")[-6:]
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def pixel_search(arr, rgb, variation):
    v = int(variation)
    if v == 0:
        hits = (arr == np.array(rgb, dtype=arr.dtype)).all(axis=2)
    else:
        hits = (np.abs(arr.astype(np.int16) - np.array(rgb, dtype=np.int16)) <= v).all(axis=2)
    i = int(hits.argmax())
    if not hits.flat[i]:
        return None
    w = arr.shape[1]
    return i % w, i // w


_needle_cache = {}


def load_needle(path):
    from PIL import Image
    key = (path, os.stat(path).st_mtime_ns)
    hit = _needle_cache.get(key)
    if hit is not None:
        return hit
    img = Image.open(path)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    a = np.asarray(img.convert("RGBA"))
    mask = a[..., 3] >= 128 if has_alpha else np.ones(a.shape[:2], dtype=bool)
    if len(_needle_cache) >= 16:
        _needle_cache.pop(next(iter(_needle_cache)))
    _needle_cache[key] = (a[..., :3].astype(np.int16), mask)
    return _needle_cache[key]


def image_search(hay, needle, mask, variation):
    H = hay.astype(np.int16)
    h, w = H.shape[:2]
    nh, nw = needle.shape[:2]
    if nh > h or nw > w:
        return None
    opaque = np.argwhere(mask)
    if len(opaque) == 0:
        return 0, 0
    ch, cw = h - nh + 1, w - nw + 1
    v = int(variation)
    # test the needle's rarest colors first so most candidates die on the first pixel
    q = H >> 4
    hist = np.bincount(((q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]).ravel(), minlength=4096)
    rng = np.random.default_rng(0)
    pool = opaque[rng.choice(len(opaque), min(400, len(opaque)), replace=False)]
    nq = needle[pool[:, 0], pool[:, 1]] >> 4
    rarity = hist[(nq[:, 0] << 8) | (nq[:, 1] << 4) | nq[:, 2]]
    samples = pool[np.argsort(rarity, kind="stable")][:48]
    sy, sx = samples[0]
    first = np.abs(H[sy:sy + ch, sx:sx + cw] - needle[sy, sx]).max(axis=2) <= v
    ys, xs = np.nonzero(first)
    for sy, sx in samples[1:]:
        if len(ys) == 0:
            return None
        keep = np.abs(H[ys + sy, xs + sx] - needle[sy, sx]).max(axis=1) <= v
        ys, xs = ys[keep], xs[keep]
    for y, x in zip(ys[:5000], xs[:5000]):
        region = H[y:y + nh, x:x + nw]
        ok = (np.abs(region - needle).max(axis=2) <= v) | ~mask
        if ok.all():
            return int(x), int(y)
    return None


class RunVars(Vars):
    def get(self, k, default=""):
        lk = str(k).lower()
        if lk == "a_tickcount":
            return int(time.monotonic() * 1000)
        if lk == "a_now":
            return time.strftime("%Y%m%d%H%M%S")
        return super().get(k, default)


class Player:
    def __init__(self, backend, callbacks):
        self.b = backend
        self.cb = callbacks
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.thread = None
        self.vars = RunVars()
        self.ev = None
        self.speed = 1.0
        self.macro_index = -1
        self.skipped_chars = set()
        self.row_map = None
        self._held_keys = set()
        self._held_buttons = set()
        self._new_eval()

    def _new_eval(self):
        self.ev = Evaluator(self.vars, {
            "getkeystate": lambda k, m="P": int(self.b.key_down(k)),
            "winactive": lambda t="A": int(self.b.matches(self.b.active_window(), str(t))),
            "winexist": lambda t="": int(self.b.find_window(str(t)) is not None),
        })

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    @property
    def stopping(self):
        return self._stop.is_set()

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def wait(self, timeout=2):
        if self.thread is not None:
            self.thread.join(timeout)

    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()
        return self._pause.is_set()

    def start(self, macro, macro_index, start_row=0, rows=None, repeat=None):
        if self.running:
            return False
        acts = macro["actions"]
        self.row_map = rows
        if rows is not None:
            acts = [acts[r] for r in rows]
        info = analyze(acts)
        if info["errors"]:
            e = info["errors"][0]
            row = rows[e.row] if rows is not None else e.row
            raise MacroError(str(e), row)
        self._stop.clear()
        self._pause.clear()
        self.macro_index = macro_index
        self.speed = max(0.01, float(macro.get("speed", 1.0) or 1.0))
        self.vars = RunVars()
        self._new_eval()
        w, h = self.b.screen_size()
        self.vars.set("a_screenwidth", w)
        self.vars.set("a_screenheight", h)
        self.vars.set("errorlevel", 0)
        rep = int(macro.get("repeat", 1)) if repeat is None else repeat
        self.skipped_chars = set()
        self.thread = threading.Thread(target=self._run, args=(acts, info, start_row, rep), daemon=True)
        self.thread.start()
        return True

    def _check(self):
        if self._stop.is_set():
            raise Stopped
        if self._pause.is_set():
            t0 = time.monotonic()
            while self._pause.is_set():
                if self._stop.is_set():
                    raise Stopped
                time.sleep(0.03)
            return time.monotonic() - t0
        return 0

    def sleep(self, ms, scaled=True):
        end = time.monotonic() + (ms / 1000.0) / (self.speed if scaled else 1.0)
        while True:
            end += self._check()
            rem = end - time.monotonic()
            if rem <= 0:
                return
            time.sleep(min(rem, 0.015))

    def _run(self, acts, info, start, rep):
        msg = "finished"
        try:
            n = 0
            while rep == 0 or n < rep:
                n += 1
                self.cb["iteration"](n, rep)
                if self._exec_range(acts, info, start, n) in ("stop", "break"):
                    break
        except Stopped:
            msg = "stopped"
        except (ExprError, MacroError, ValueError, RuntimeError, OSError) as e:
            msg = f"error: {e}"
        except Exception as e:
            msg = f"error: {type(e).__name__.lower()}: {e}"
        finally:
            self._release_all()
            self.cb["step"](-1)
            self.cb["finished"](msg)

    def _table_row(self, pc):
        return self.row_map[pc] if self.row_map is not None else pc

    def _exec_range(self, acts, info, start, outer_index):
        partner = info["partner"]
        frames = []
        self.vars.set("a_index", outer_index)
        pc = start
        end = len(acts)
        ticks = 0
        while pc < end:
            self._check()
            # a forever loop of no-ops would otherwise hold the gil and hang the ui
            ticks += 1
            if ticks & 255 == 0:
                time.sleep(0.001)
            a = acts[pc]
            t = a["type"]
            if not a["enabled"]:
                pc = partner[pc] + 1 if t in ("loop", "if") and pc in partner else pc + 1
                continue
            self.cb["step"](self._table_row(pc))
            sig = None
            if t == "loop":
                p = a["p"]
                ok = True
                if p["kind"] == "count":
                    ok = int(p["count"]) >= 1
                elif p["kind"] == "while":
                    ok = truthy(self.ev.eval(p["expr"]))
                if not ok:
                    pc = partner[pc] + 1
                    continue
                frames.append({"start": pc, "end": partner[pc], "iter": 1})
                self.vars.set("a_index", 1)
                pc += 1
                continue
            if t == "endloop":
                f = frames[-1] if frames and frames[-1]["end"] == pc else None
                if f is None:
                    pc += 1
                    continue
                p = acts[f["start"]]["p"]
                k = p["kind"]
                again = (k == "forever" or (k == "count" and f["iter"] < int(p["count"]))
                         or (k == "while" and truthy(self.ev.eval(p["expr"])))
                         or (k == "until" and not truthy(self.ev.eval(p["expr"]))))
                if again:
                    f["iter"] += 1
                    self.vars.set("a_index", f["iter"])
                    pc = f["start"] + 1
                else:
                    frames.pop()
                    self.vars.set("a_index", frames[-1]["iter"] if frames else outer_index)
                    pc += 1
                continue
            if t == "if":
                if self.condition(a["p"]):
                    pc += 1
                else:
                    e = info["else"].get(pc)
                    pc = (e + 1) if e is not None else partner[pc] + 1
                continue
            if t == "else":
                pc = partner[pc] + 1
                continue
            if t in ("endif", "label", "comment"):
                pc += 1
                continue
            if t == "break":
                sig = ("break",)
            elif t == "continue":
                sig = ("continue",)
            elif t == "goto":
                sig = ("goto", a["p"]["name"])
            elif t == "stop":
                sig = ("stop",)
            else:
                for _ in range(max(1, int(a["repeat"]))):
                    sig = self.execute(a)
                    if int(a["delay"]):
                        self.sleep(int(a["delay"]))
                    if sig:
                        break
            if sig is None:
                pc += 1
                continue
            kind = sig[0]
            if kind == "stop":
                return "stop"
            if kind in ("break", "continue"):
                if not frames:
                    return kind
                f = frames[-1]
                if kind == "break":
                    frames.pop()
                    self.vars.set("a_index", frames[-1]["iter"] if frames else outer_index)
                    pc = f["end"] + 1
                else:
                    pc = f["end"]
                continue
            if kind == "goto":
                target = info["labels"].get(str(sig[1]).lower())
                if target is None:
                    raise MacroError(f"no label called {sig[1]}")
                frames = [f for f in frames if f["start"] < target <= f["end"]]
                self.vars.set("a_index", frames[-1]["iter"] if frames else outer_index)
                pc = target + 1
        return None

    def _pt(self, p, a="x", b="y"):
        return int(self.ev.eval_num(p[a])), int(self.ev.eval_num(p[b]))

    def _region(self, p):
        return (int(self.ev.eval_num(p["x1"])), int(self.ev.eval_num(p["y1"])),
                int(self.ev.eval_num(p["x2"])), int(self.ev.eval_num(p["y2"])))

    def move_to(self, x, y, speed=0):
        if speed > 0:
            sx, sy = self.b.cursor_pos()
            steps = max(2, int(speed * 1.5))
            for i in range(1, steps + 1):
                self._check()
                f = i / steps
                f = f * f * (3 - 2 * f)
                self.b.move(round(sx + (x - sx) * f), round(sy + (y - sy) * f))
                time.sleep(0.006)
        self.b.move(x, y)
        self.b.nudge()
        self.b.move(x, y)

    def _key(self, name, down):
        self.b.key(name, down)
        (self._held_keys.add if down else self._held_keys.discard)(name)

    def _button(self, name, down):
        self.b.button(name, down)
        (self._held_buttons.add if down else self._held_buttons.discard)(name)

    def _release_all(self):
        for name in list(self._held_keys):
            try:
                self.b.key(name, False)
            except (ValueError, RuntimeError, OSError):
                pass
        for name in list(self._held_buttons):
            try:
                self.b.button(name, False)
            except (ValueError, RuntimeError, OSError):
                pass
        self._held_keys.clear()
        self._held_buttons.clear()

    def click(self, button, count=1, mode="click"):
        name = BUTTON_SHORT.get(button, button)
        if mode == "down":
            self._button(name, True)
            return
        if mode == "up":
            self._button(name, False)
            return
        for i in range(int(count)):
            self._button(name, True)
            time.sleep(0.012)
            self._button(name, False)
            if i < int(count) - 1:
                time.sleep(0.04)

    def search(self, t, p):
        x1, y1, x2, y2 = self._region(p)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if t == "pixelsearch":
            hay = self.b.grab(x1, y1, x2, y2)
            r = pixel_search(hay, parse_color(p["color"]), p["variation"])
            return (x1 + r[0], y1 + r[1]) if r else None
        path = os.path.expanduser(str(p["image"]))
        if not path or not os.path.exists(path):
            raise MacroError(f"image not found: {path or '(none)'}")
        needle, mask = load_needle(path)
        hay = self.b.grab(x1, y1, x2, y2)
        r = image_search(hay, needle, mask, p["variation"])
        if not r:
            return None
        fx, fy = x1 + r[0], y1 + r[1]
        if p.get("center"):
            fx += needle.shape[1] // 2
            fy += needle.shape[0] // 2
        return fx, fy

    def _set_found(self, r):
        if r:
            self.vars.set("foundx", r[0])
            self.vars.set("foundy", r[1])
            self.vars.set("errorlevel", 0)
        else:
            self.vars.set("errorlevel", 1)

    def handle_found(self, handler, label, p, pos):
        if handler == "continue" or not handler:
            return None
        if handler == "break loop":
            return ("break",)
        if handler == "stop macro":
            return ("stop",)
        if handler == "goto label":
            return ("goto", label)
        if pos is None:
            return None
        x, y = pos[0] + int(p.get("offset_x", 0) or 0), pos[1] + int(p.get("offset_y", 0) or 0)
        self.move_to(x, y)
        if handler == "move":
            return None
        btn = {"left click": "left", "right click": "right", "middle click": "middle", "double click": "left"}[handler]
        self.click(btn, 2 if handler == "double click" else 1)
        return None

    def condition(self, p):
        k = p["kind"]
        if k == "expression":
            r = truthy(self.ev.eval(p["expr"]))
        elif k == "window active":
            r = self.b.matches(self.b.active_window(), deref(p["window"], self.vars))
        elif k == "window exists":
            r = self.b.find_window(deref(p["window"], self.vars)) is not None
        elif k == "pixel color":
            x, y = self._pt(p)
            c = self.b.pixel(x, y)
            want = parse_color(p["color"])
            r = max(abs(a - b) for a, b in zip(c, want)) <= int(p["variation"])
            self._set_found((x, y) if r else None)
        elif k == "image found":
            pos = self.search("imagesearch", p)
            self._set_found(pos)
            r = pos is not None
        elif k == "key down":
            r = self.b.key_down(p["key"])
        else:
            r = str(self.vars.get("errorlevel")) in ("0", "")
        return (not r) if p.get("negate") else bool(r)

    def _type(self, text, char_delay):
        for ch in text:
            self._check()
            if ch == "\r":
                continue
            if not self.b.type_char(ch):
                self.skipped_chars.add(ch)
            if char_delay:
                self.sleep(char_delay)
            else:
                time.sleep(0.004)
        if self.skipped_chars:
            self.cb["log"]("this keyboard layout cannot type: " + " ".join(sorted(self.skipped_chars)))

    def _run_command(self, command, wait):
        proc = self.b.run(command)
        if not wait or proc is None:
            return 0
        while proc.poll() is None:
            self.sleep(50, scaled=False)
        return proc.returncode

    def _wait_until(self, test, timeout_s, poll_ms):
        deadline = time.monotonic() + timeout_s if timeout_s else None
        while True:
            if test():
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            self.sleep(poll_ms, scaled=False)

    def execute(self, a):
        t = a["type"]
        p = a["p"]
        b = self.b
        if t == "click":
            if not p["at_cursor"]:
                x, y = self._pt(p)
                if p["relative"]:
                    cx, cy = b.cursor_pos()
                    x, y = cx + x, cy + y
                self.move_to(x, y)
            self.click(p["button"], p["clicks"], p["mode"])
        elif t == "mousemove":
            x, y = self._pt(p)
            if p["relative"]:
                cx, cy = b.cursor_pos()
                x, y = cx + x, cy + y
            self.move_to(x, y, int(p["speed"]))
        elif t == "wheel":
            b.wheel(p["direction"], p["amount"])
        elif t == "key":
            if p["mode"] == "press":
                mods = [MOD_KEY[m] for m in ("ctrl", "shift", "alt", "win") if p.get(m)]
                for m in mods:
                    self._key(m, True)
                self._key(p["key"], True)
                time.sleep(0.008)
                self._key(p["key"], False)
                for m in reversed(mods):
                    self._key(m, False)
            else:
                self._key(p["key"], p["mode"] == "down")
        elif t == "text":
            self._type(deref(p["text"], self.vars), int(p["char_delay"]))
        elif t == "sleep":
            lo, hi = int(p["ms"]), int(p["random_to"])
            self.sleep(random.randint(lo, hi) if hi > lo else lo)
        elif t == "setvar":
            if p["mode"] == "expression":
                v = self.ev.eval(p["value"])
            elif p["mode"] == "text":
                v = deref(p["value"], self.vars)
            else:
                lo, hi = self.ev.eval_num(p["min"]), self.ev.eval_num(p["max"])
                lo, hi = min(lo, hi), max(lo, hi)
                if isinstance(lo, float) or isinstance(hi, float):
                    v = random.uniform(lo, hi)
                else:
                    v = random.randint(int(lo), int(hi))
            self.vars.set(p["var"], v)
        elif t == "pixelgetcolor":
            x, y = self._pt(p)
            self.vars.set(p["var"], "0x" + hex_color(b.pixel(x, y)))
        elif t in ("pixelsearch", "imagesearch"):
            deadline = time.monotonic() + int(p["timeout"]) / 1000.0 if int(p.get("timeout", 0)) else None
            while True:
                pos = self.search(t, p)
                if pos or not p.get("wait"):
                    break
                if deadline and time.monotonic() >= deadline:
                    break
                self.sleep(50, scaled=False)
            self._set_found(pos)
            if pos:
                return self.handle_found(p["found"], p.get("goto_found"), p, pos)
            return self.handle_found(p["not_found"], p.get("goto_nf"), p, None)
        elif t == "winactivate":
            self.vars.set("errorlevel", 0 if b.activate_window(deref(p["window"], self.vars)) else 1)
        elif t == "winwait":
            spec = deref(p["window"], self.vars)
            ok = self._wait_until(lambda: b.matches(b.active_window(), spec), int(p["timeout"]), 60)
            self.vars.set("errorlevel", 0 if ok else 1)
        elif t == "winclose":
            self.vars.set("errorlevel", 0 if b.close_window(deref(p["window"], self.vars)) else 1)
        elif t == "wingettitle":
            w = b.active_window()
            self.vars.set(p["var"], w["title"] if w else "")
        elif t == "run":
            self.vars.set("errorlevel", self._run_command(deref(p["command"], self.vars), bool(p["wait"])))
        elif t == "msgbox":
            self.cb["msgbox"](deref(p["title"], self.vars), deref(p["text"], self.vars))
            self._check()
        elif t == "keywait":
            want = p["state"] == "press"
            ok = self._wait_until(lambda: b.key_down(p["key"]) == want, int(p["timeout"]), 10)
            self.vars.set("errorlevel", 0 if ok else 1)
        return None

    def test(self, a):
        t = a["type"]
        p = a["p"]
        if t == "pixelgetcolor":
            x, y = self._pt(p)
            return f"pixel {x}, {y} is #{hex_color(self.b.pixel(x, y))}"
        if t in ("pixelsearch", "imagesearch"):
            t0 = time.perf_counter()
            pos = self.search(t, p)
            ms = (time.perf_counter() - t0) * 1000
            return (f"found at {pos[0]}, {pos[1]}" if pos else "not found") + f" ({ms:.0f} ms)"
        if t == "if":
            return "condition is true" if self.condition(p) else "condition is false"
        if t == "setvar":
            if p["mode"] == "random":
                return f"{p['var']} will be random between {p['min']} and {p['max']}"
            v = fmt(self.ev.eval(p["value"])) if p["mode"] == "expression" else deref(p["value"], self.vars)
            return f"{p['var']} = {v}"
        if t in ("winactivate", "winwait", "winclose"):
            w = self.b.find_window(p["window"])
            return f"matches: {w['title']} [{w['class']}]" if w else "no matching window"
        if t == "loop" and p["kind"] in ("while", "until"):
            return f"expression is {fmt(self.ev.eval(p['expr']))}"
        return None
