import string

KEY_TABLE = []
for _c in string.ascii_lowercase:
    KEY_TABLE.append((_c, "KEY_" + _c.upper(), ord(_c.upper())))
for _d in "0123456789":
    KEY_TABLE.append((_d, "KEY_" + _d, ord(_d)))
for _i in range(1, 25):
    KEY_TABLE.append((f"f{_i}", f"KEY_F{_i}", 0x6F + _i))
for _i in range(10):
    KEY_TABLE.append((f"numpad{_i}", f"KEY_KP{_i}", 0x60 + _i))
KEY_TABLE += [
    ("enter", "KEY_ENTER", 0x0D), ("esc", "KEY_ESC", 0x1B), ("space", "KEY_SPACE", 0x20),
    ("tab", "KEY_TAB", 0x09), ("backspace", "KEY_BACKSPACE", 0x08), ("delete", "KEY_DELETE", 0x2E),
    ("insert", "KEY_INSERT", 0x2D), ("home", "KEY_HOME", 0x24), ("end", "KEY_END", 0x23),
    ("pgup", "KEY_PAGEUP", 0x21), ("pgdn", "KEY_PAGEDOWN", 0x22), ("up", "KEY_UP", 0x26),
    ("down", "KEY_DOWN", 0x28), ("left", "KEY_LEFT", 0x25), ("right", "KEY_RIGHT", 0x27),
    ("lshift", "KEY_LEFTSHIFT", 0xA0), ("rshift", "KEY_RIGHTSHIFT", 0xA1),
    ("lctrl", "KEY_LEFTCTRL", 0xA2), ("rctrl", "KEY_RIGHTCTRL", 0xA3),
    ("lalt", "KEY_LEFTALT", 0xA4), ("ralt", "KEY_RIGHTALT", 0xA5),
    ("lwin", "KEY_LEFTMETA", 0x5B), ("rwin", "KEY_RIGHTMETA", 0x5C), ("appskey", "KEY_COMPOSE", 0x5D),
    ("capslock", "KEY_CAPSLOCK", 0x14), ("numlock", "KEY_NUMLOCK", 0x90),
    ("scrolllock", "KEY_SCROLLLOCK", 0x91), ("printscreen", "KEY_SYSRQ", 0x2C), ("pause", "KEY_PAUSE", 0x13),
    ("numpaddot", "KEY_KPDOT", 0x6E), ("numpadenter", "KEY_KPENTER", 0x0D),
    ("numpadadd", "KEY_KPPLUS", 0x6B), ("numpadsub", "KEY_KPMINUS", 0x6D),
    ("numpadmult", "KEY_KPASTERISK", 0x6A), ("numpaddiv", "KEY_KPSLASH", 0x6F),
    ("volume_up", "KEY_VOLUMEUP", 0xAF), ("volume_down", "KEY_VOLUMEDOWN", 0xAE),
    ("volume_mute", "KEY_MUTE", 0xAD), ("media_play_pause", "KEY_PLAYPAUSE", 0xB3),
    ("media_next", "KEY_NEXTSONG", 0xB0), ("media_prev", "KEY_PREVIOUSSONG", 0xB1),
    ("media_stop", "KEY_STOPCD", 0xB2),
    ("-", "KEY_MINUS", 0xBD), ("=", "KEY_EQUAL", 0xBB), ("[", "KEY_LEFTBRACE", 0xDB),
    ("]", "KEY_RIGHTBRACE", 0xDD), (";", "KEY_SEMICOLON", 0xBA), ("'", "KEY_APOSTROPHE", 0xDE),
    ("`", "KEY_GRAVE", 0xC0), ("\\", "KEY_BACKSLASH", 0xDC), (",", "KEY_COMMA", 0xBC),
    (".", "KEY_DOT", 0xBE), ("/", "KEY_SLASH", 0xBF), ("sc056", "KEY_102ND", 0xE2),
]

BUTTON_TABLE = [
    ("lbutton", "BTN_LEFT", 0x01), ("rbutton", "BTN_RIGHT", 0x02), ("mbutton", "BTN_MIDDLE", 0x04),
    ("xbutton1", "BTN_SIDE", 0x05), ("xbutton2", "BTN_EXTRA", 0x06),
]

BUTTON_SHORT = {"left": "lbutton", "right": "rbutton", "middle": "mbutton", "x1": "xbutton1", "x2": "xbutton2"}
BUTTON_LONG = {v: k for k, v in BUTTON_SHORT.items()}

MODIFIERS = {
    "lshift": "shift", "rshift": "shift", "lctrl": "ctrl", "rctrl": "ctrl",
    "lalt": "alt", "ralt": "alt", "lwin": "win", "rwin": "win",
}
MOD_PREFIX = {"^": "ctrl", "!": "alt", "+": "shift", "#": "win"}
MOD_KEY = {"ctrl": "lctrl", "alt": "lalt", "shift": "lshift", "win": "lwin"}

_US_BASE = {c: "KEY_" + c.upper() for c in string.ascii_lowercase}
_US_BASE.update({d: "KEY_" + d for d in "0123456789"})
_US_BASE.update({
    "-": "KEY_MINUS", "=": "KEY_EQUAL", "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE",
    ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE", "\\": "KEY_BACKSLASH",
    ",": "KEY_COMMA", ".": "KEY_DOT", "/": "KEY_SLASH", " ": "KEY_SPACE", "\n": "KEY_ENTER", "\t": "KEY_TAB",
})
_US_SHIFT = {c.upper(): "KEY_" + c.upper() for c in string.ascii_lowercase}
_US_SHIFT.update(dict(zip(")!@#$%^&*(", ["KEY_" + d for d in "0123456789"])))
_US_SHIFT.update({
    "_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_LEFTBRACE", "}": "KEY_RIGHTBRACE", ":": "KEY_SEMICOLON",
    '"': "KEY_APOSTROPHE", "~": "KEY_GRAVE", "|": "KEY_BACKSLASH", "<": "KEY_COMMA", ">": "KEY_DOT", "?": "KEY_SLASH",
})

_GB_BASE = dict(_US_BASE)
_GB_BASE["\\"] = "KEY_102ND"
_GB_BASE["#"] = "KEY_BACKSLASH"
_GB_SHIFT = {c.upper(): "KEY_" + c.upper() for c in string.ascii_lowercase}
_GB_SHIFT.update(dict(zip(')!"£$%^&*(', ["KEY_" + d for d in "0123456789"])))
_GB_SHIFT.update({
    "_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_LEFTBRACE", "}": "KEY_RIGHTBRACE", ":": "KEY_SEMICOLON",
    "@": "KEY_APOSTROPHE", "¬": "KEY_GRAVE", "~": "KEY_BACKSLASH", "|": "KEY_102ND", "<": "KEY_COMMA",
    ">": "KEY_DOT", "?": "KEY_SLASH",
})
_GB_ALTGR = {"€": "KEY_4", "¦": "KEY_GRAVE"}

LAYOUTS = {
    "us": (_US_BASE, _US_SHIFT, {}),
    "gb": (_GB_BASE, _GB_SHIFT, _GB_ALTGR),
}


class Keymap:
    def __init__(self, layout="us"):
        self.layout = layout if layout in LAYOUTS else "us"
        base, shift, altgr = LAYOUTS[self.layout]
        self.chars = {}
        for c, k in base.items():
            self.chars[c] = (k, False, False)
        for c, k in shift.items():
            self.chars[c] = (k, True, False)
        for c, k in altgr.items():
            self.chars[c] = (k, False, True)
        self.rev = {}
        for c, (k, sh, ag) in self.chars.items():
            if not ag and c not in "\n\t":
                self.rev[(k, sh)] = c
        self.name_to_evdev = {}
        self.evdev_to_name = {}
        for name, ev, _vk in KEY_TABLE + BUTTON_TABLE:
            self.name_to_evdev[name] = ev
            self.evdev_to_name[ev] = name
        if self.layout == "gb":
            self.evdev_to_name["KEY_BACKSLASH"] = "#"
            self.evdev_to_name["KEY_102ND"] = "\\"
            self.name_to_evdev["#"] = "KEY_BACKSLASH"
            self.name_to_evdev["\\"] = "KEY_102ND"
        self.name_to_evdev.update({"return": "KEY_ENTER", "escape": "KEY_ESC", "del": "KEY_DELETE",
                                   "ins": "KEY_INSERT", "ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL",
                                   "shift": "KEY_LEFTSHIFT", "alt": "KEY_LEFTALT", "bs": "KEY_BACKSPACE",
                                   "lcontrol": "KEY_LEFTCTRL", "rcontrol": "KEY_RIGHTCTRL"})

    def char_for(self, evdev_name, shift):
        return self.rev.get((evdev_name, shift))

    def knows(self, name):
        return str(name).lower() in self.name_to_evdev


def key_names():
    names = [n for n, _e, _v in KEY_TABLE if n != "sc056"]
    names.sort(key=lambda n: (len(n) == 1, n))
    return names


def parse_hotkey(spec):
    spec = (spec or "").strip().lower()
    mods = set()
    i = 0
    while i < len(spec) - 1 and spec[i] in MOD_PREFIX:
        mods.add(MOD_PREFIX[spec[i]])
        i += 1
    return frozenset(mods), spec[i:]


def hotkey_matches(spec, key, held_mods):
    mods, k = parse_hotkey(spec)
    return bool(k) and k == key and mods == frozenset(held_mods)


def format_hotkey(key, mods):
    prefix = "".join(c for c, m in (("^", "ctrl"), ("!", "alt"), ("+", "shift"), ("#", "win")) if m in mods)
    return prefix + key
