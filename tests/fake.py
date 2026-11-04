import numpy as np

from reprise.keys import Keymap


class FakeProc:
    def __init__(self, polls=None):
        self.polls = polls
        self.returncode = None

    def poll(self):
        if self.polls is None:
            return None
        self.polls -= 1
        if self.polls <= 0:
            self.returncode = 0
            return 0
        return None


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.keymap = Keymap("us")
        self.pressed = set()
        self.pressed_names = set()
        self.motion_wanted = False
        self.recording = False
        self.log = []
        self.cursor = (0, 0)
        self.screen = np.zeros((100, 100, 3), dtype=np.uint8)
        self.focused_self = False
        self.in_self = False
        self.proc = None
        self.blocked = []
        self.subscribers = []

    def problems(self):
        return []

    def cursor_pos(self):
        return self.cursor

    def screen_size(self):
        return self.screen.shape[1], self.screen.shape[0]

    def move(self, x, y):
        self.cursor = (x, y)
        self.log.append(("move", x, y))

    def nudge(self):
        pass

    def key(self, name, down):
        if not self.keymap.knows(name):
            raise ValueError(f"unknown key {name!r}")
        self.log.append(("key", name, down))

    def button(self, name, down):
        self.log.append(("button", name, down))

    def wheel(self, direction, amount):
        self.log.append(("wheel", direction, amount))

    def type_char(self, ch):
        if ch not in self.keymap.chars:
            return False
        self.log.append(("char", ch))
        return True

    def grab(self, x1, y1, x2, y2):
        return self.screen[y1:y2 + 1, x1:x2 + 1]

    def pixel(self, x, y):
        return tuple(int(v) for v in self.screen[y, x])

    def save_region(self, *a):
        pass

    def pick_point(self):
        return None

    def pick_region(self):
        return None

    def hide_self(self):
        return True

    def show_self(self):
        pass

    def windows(self):
        return []

    def active_window(self):
        return None

    def matches(self, win, spec):
        return False

    def find_window(self, spec):
        return None

    def activate_window(self, spec):
        return False

    def close_window(self, spec):
        return False

    def self_focused(self):
        return self.focused_self

    def point_in_self(self, x, y):
        return self.in_self

    def run(self, command):
        self.log.append(("run", command))
        return self.proc

    def key_down(self, name):
        return name in self.pressed

    def held_mods(self):
        return set()

    def subscribe(self, fn):
        self.subscribers.append(fn)

    def start_listener(self):
        pass

    def block_hotkeys(self, specs):
        self.blocked = list(specs)

    def clear_hotkey_blocks(self):
        self.blocked = []

    def shutdown(self):
        pass
