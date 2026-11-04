from .keys import BUTTON_LONG, MODIFIERS
from .model import new_action

SAME_SPOT = 3
DOUBLE_CLICK_S = 0.35
WHEEL_MERGE_S = 0.3
ROLLOVER_LOOKBACK = 8


class Recorder:
    def __init__(self, backend):
        self.b = backend
        self.active = False
        self.events = []
        self.settings = {}
        self._skip_buttons = set()
        self._down = set()
        self._last_motion = 0
        self._last_pos = None
        self.count = 0

    def start(self, settings):
        self.settings = settings
        self.events = []
        self._skip_buttons = set()
        self._down = set()
        self._last_motion = 0
        self._last_pos = self.b.cursor_pos()
        self.count = 0
        self.b.motion_wanted = bool(settings.get("rec_moves"))
        self.b.recording = True
        self.active = True

    def feed(self, ev):
        if not self.active:
            return False
        s = self.settings
        k = ev["kind"]
        if k == "key":
            if not s.get("rec_keys", True) or ev.get("repeat"):
                return False
            if s.get("ignore_self", True) and self.b.self_focused():
                return False
            # the release of a key that was already held when recording began
            # (the ctrl of ctrl+f9, say) has no press to pair with
            if ev["down"]:
                self._down.add(ev["name"])
            elif ev["name"] not in self._down:
                return False
            else:
                self._down.discard(ev["name"])
        elif k == "button":
            if not s.get("rec_mouse", True):
                return False
            if ev["down"]:
                if s.get("ignore_self", True) and self.b.point_in_self(ev["x"], ev["y"]):
                    self._skip_buttons.add(ev["name"])
                    return False
                self._down.add(ev["name"])
            elif ev["name"] in self._skip_buttons:
                self._skip_buttons.discard(ev["name"])
                return False
            elif ev["name"] not in self._down:
                return False
            else:
                self._down.discard(ev["name"])
        elif k == "wheel":
            if not s.get("rec_wheel", True):
                return False
            x, y = self.b.cursor_pos()
            if s.get("ignore_self", True) and self.b.point_in_self(x, y):
                return False
        elif k == "motion":
            interval = int(s.get("move_interval", 40)) / 1000.0
            if ev["t"] - self._last_motion < interval:
                return False
            self._last_motion = ev["t"]
            pos = self.b.cursor_pos()
            if pos == self._last_pos:
                return False
            if s.get("ignore_self", True) and self.b.point_in_self(*pos):
                return False
            self._last_pos = pos
            ev = dict(ev, x=pos[0], y=pos[1])
        self.events.append(ev)
        self.count += 1
        return True

    def stop(self, held=()):
        self.active = False
        self.b.motion_wanted = False
        self.b.recording = False
        events = self.events
        self.events = []
        return build_actions(events, self.settings, self.b.keymap, held)


def _pair_key_release(items, name, t):
    # fast typing rolls over: a down, b down, a up, b up. walk back past other
    # plain presses so that still comes out as two presses
    for it in reversed(items[-ROLLOVER_LOOKBACK:]):
        a = it[0]
        if a["type"] != "key" or a["p"]["key"] in MODIFIERS:
            return False
        if a["p"]["key"] == name:
            if a["p"]["mode"] != "down":
                return False
            a["p"]["mode"] = "press"
            it[2] = t
            return True
    return False


def _near(p, x, y):
    return abs(int(p["x"]) - x) <= SAME_SPOT and abs(int(p["y"]) - y) <= SAME_SPOT


def _add_button(items, e, s):
    last = items[-1] if items else None
    short = BUTTON_LONG[e["name"]]
    if e["down"]:
        items.append([new_action("click", button=short, mode="down", x=str(e["x"]), y=str(e["y"])), e["t"], e["t"], e])
        return
    lp = last[0]["p"] if last and last[0]["type"] == "click" else None
    if not (lp and lp["mode"] == "down" and lp["button"] == short and _near(lp, e["x"], e["y"])):
        items.append([new_action("click", button=short, mode="up", x=str(e["x"]), y=str(e["y"])), e["t"], e["t"], e])
        return
    lp["mode"] = "click"
    last[2] = e["t"]
    prev = items[-2] if len(items) >= 2 else None
    if not (s.get("merge_double", True) and prev and prev[0]["type"] == "click"):
        return
    pp = prev[0]["p"]
    if (pp["mode"] == "click" and pp["button"] == short and last[1] - prev[2] < DOUBLE_CLICK_S
            and _near(pp, e["x"], e["y"])):
        pp["clicks"] = int(pp["clicks"]) + 1
        prev[2] = e["t"]
        items.pop()


def build_actions(events, s, keymap, held=()):
    default_delay = int(s.get("default_delay", 10))
    items = []
    for e in events:
        k = e["kind"]
        last = items[-1] if items else None
        if k == "key":
            if e["down"]:
                items.append([new_action("key", key=e["name"], mode="down"), e["t"], e["t"], e])
            elif not _pair_key_release(items, e["name"], e["t"]):
                items.append([new_action("key", key=e["name"], mode="up"), e["t"], e["t"], e])
        elif k == "button":
            _add_button(items, e, s)
        elif k == "wheel":
            if last and last[0]["type"] == "wheel" and last[0]["p"]["direction"] == e["dir"] and e["t"] - last[2] < WHEEL_MERGE_S:
                last[0]["p"]["amount"] = int(last[0]["p"]["amount"]) + int(e["amount"])
                last[2] = e["t"]
            else:
                items.append([new_action("wheel", direction=e["dir"], amount=int(e["amount"])), e["t"], e["t"], e])
        elif k == "motion":
            items.append([new_action("mousemove", x=str(e["x"]), y=str(e["y"])), e["t"], e["t"], e])
    held = {h.lower() for h in held}
    while items and items[-1][0]["type"] == "key" and items[-1][0]["p"]["mode"] == "down" and items[-1][0]["p"]["key"] in held:
        items.pop()
    if s.get("merge_text", True):
        items = _merge_text(items, keymap)
    out = []
    for i, it in enumerate(items):
        a = it[0]
        if s.get("rec_delays", True):
            a["delay"] = max(0, int(round((items[i + 1][1] - it[2]) * 1000))) if i + 1 < len(items) else 0
        else:
            a["delay"] = default_delay
        out.append(a)
    return out


def _printable(it, keymap):
    a = it[0]
    if a["type"] != "key":
        return None
    p = a["p"]
    if p["mode"] == "press":
        ev = keymap.name_to_evdev.get(p["key"])
        if ev and keymap.char_for(ev, False) is not None:
            return "char"
        return "char" if p["key"] == "space" else None
    return "shift" if p["key"] in ("lshift", "rshift") else None


def _merge_text(items, keymap):
    out = []
    i = 0
    n = len(items)
    while i < n:
        if _printable(items[i], keymap) is None:
            out.append(items[i])
            i += 1
            continue
        j = i
        while j < n and _printable(items[j], keymap) is not None:
            j += 1
        run = items[i:j]
        shift = False
        chars = []
        last_ok = -1
        for idx, it in enumerate(run):
            p = it[0]["p"]
            if _printable(it, keymap) == "shift":
                shift = p["mode"] == "down"
            else:
                ev = keymap.name_to_evdev.get(p["key"])
                c = " " if p["key"] == "space" else keymap.char_for(ev, shift)
                if c is None:
                    c = keymap.char_for(ev, False)
                chars.append((idx, c))
            if not shift:
                last_ok = idx
        if last_ok < 0 or sum(1 for idx, _ in chars if idx <= last_ok) < 2:
            out.extend(run[:1])
            i += 1
            continue
        text = "".join(c for idx, c in chars if idx <= last_ok)
        out.append([new_action("text", text=text), run[0][1], run[last_ok][2], run[0][3]])
        i += last_ok + 1
    return out
