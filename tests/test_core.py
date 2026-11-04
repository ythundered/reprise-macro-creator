import threading
import unittest

import numpy as np

from reprise import ahk
from reprise.engine import Player, image_search, parse_color, pixel_search
from reprise.expr import Evaluator, ExprError, Vars, deref, fmt
from reprise.keys import Keymap, format_hotkey, hotkey_matches, parse_hotkey
from reprise.model import analyze, check_action, describe, new_action, new_macro, normalize, normalize_macro, with_partners
from reprise.recorder import build_actions

from .fake import FakeBackend, FakeProc


def run(acts, repeat=1, backend=None, **start):
    b = backend or FakeBackend()
    done = threading.Event()
    result = {"msg": None, "steps": []}

    def finished(m):
        result["msg"] = m
        done.set()
    p = Player(b, {"step": result["steps"].append, "finished": finished, "log": lambda m: None,
                   "iteration": lambda n, t: None, "msgbox": lambda t, x: None})
    m = dict(new_macro(), actions=acts, repeat=repeat)
    p.start(m, 0, **start)
    return p, b, done, result


def play(acts, **kw):
    p, b, done, result = run(acts, **kw)
    if not done.wait(5):
        p.stop()
        raise AssertionError("macro did not finish")
    p.wait()
    return p, b, result


class ExprTests(unittest.TestCase):
    def ev(self, src, **variables):
        v = Vars()
        for k, x in variables.items():
            v.set(k, x)
        return Evaluator(v).eval(src)

    def test_arithmetic_and_compare(self):
        self.assertEqual(self.ev("1 + 2 * 3"), 7)
        self.assertEqual(self.ev("count < 10 && count > 2", count=5), 1)
        self.assertEqual(self.ev("!(1 = 1)"), 0)
        self.assertEqual(self.ev('name = "ABC"', name="abc"), 1)
        self.assertEqual(self.ev("%x% + 1", x=4), 5)

    def test_concat_and_decimals(self):
        self.assertEqual(self.ev('"a" . name', name="b"), "ab")
        self.assertEqual(self.ev("1.5 + 1"), 2.5)

    def test_functions(self):
        self.assertEqual(self.ev('strlen("abc")'), 3)
        self.assertEqual(self.ev('substr("hello", 2, 3)'), "ell")
        self.assertEqual(self.ev("mod(7, 3)"), 1)
        self.assertEqual(self.ev('instr("Hello", "L")'), 3)

    def test_rejected(self):
        for bad in ("a := 1", '"open', "1 / 0", "mod(1, 0)", "sqrt(-1)", "nope()", "a.b", "2 ** 999999", "1 << 999999",
                    "__import__('os')"):
            with self.assertRaises(ExprError, msg=bad):
                self.ev(bad)

    def test_python_names_are_not_reachable(self):
        self.assertEqual(self.ev("open"), "")

    def test_deref_and_fmt(self):
        v = Vars()
        v.set("n", 2.0)
        self.assertEqual(deref("a %n% %missing%b", v), "a 2 b")
        self.assertEqual(fmt(1.5), "1.5")


class KeyTests(unittest.TestCase):
    def test_hotkeys(self):
        self.assertEqual(parse_hotkey("^!F3"), (frozenset({"ctrl", "alt"}), "f3"))
        self.assertEqual(parse_hotkey("+"), (frozenset(), "+"))
        self.assertTrue(hotkey_matches("^f3", "f3", {"ctrl"}))
        self.assertFalse(hotkey_matches("^f3", "f3", set()))
        self.assertEqual(format_hotkey("f3", {"ctrl", "shift"}), "^+f3")

    def test_layouts(self):
        gb = Keymap("gb")
        self.assertEqual(gb.chars["@"][0], "KEY_APOSTROPHE")
        self.assertTrue(gb.knows("#"))
        self.assertFalse(Keymap("us").knows("nonsense"))


class ModelTests(unittest.TestCase):
    def test_structure(self):
        acts = [new_action("loop"), new_action("if"), new_action("else"), new_action("endif"), new_action("endloop")]
        info = analyze(acts)
        self.assertEqual(info["errors"], [])
        self.assertEqual(info["partner"][0], 4)
        self.assertEqual(info["else"][1], 2)
        self.assertEqual(info["indent"], [0, 1, 1, 1, 0])

    def test_errors(self):
        self.assertTrue(analyze([new_action("loop")])["errors"])
        self.assertTrue(analyze([new_action("else")])["errors"])
        self.assertTrue(analyze([new_action("endif")])["errors"])
        self.assertTrue(analyze([new_action("goto", name="nowhere")])["errors"])
        self.assertTrue(analyze([new_action("label"), new_action("label")])["errors"])
        bad = new_action("pixelsearch", found="goto label", goto_found="gone")
        self.assertTrue(analyze([bad])["errors"])

    def test_with_partners(self):
        acts = [new_action("if"), new_action("sleep"), new_action("else"), new_action("sleep"), new_action("endif")]
        self.assertEqual(with_partners([0], analyze(acts)), [0, 2, 4])
        self.assertEqual(with_partners([4], analyze(acts)), [0, 2, 4])
        self.assertEqual(with_partners([1], analyze(acts)), [1])

    def test_old_files_still_load(self):
        a = normalize({"type": "PixelSearch", "p": {"found": "Left Click", "not_found": "Continue"}})
        self.assertEqual(a["type"], "pixelsearch")
        self.assertEqual(a["p"]["found"], "left click")
        self.assertIsNone(normalize({"type": "whatever"}))
        m = normalize_macro({"name": "x", "hotkey": "F5", "actions": [{"type": "Click", "p": {"button": "Right"}}]})
        self.assertEqual(m["hotkey"], "f5")
        self.assertEqual(m["actions"][0]["p"]["button"], "right")

    def test_every_type_describes(self):
        from reprise.model import TYPES
        for t in TYPES:
            label, _ = describe(new_action(t))
            self.assertEqual(label, label.lower())

    def test_check_action(self):
        self.assertIsNotNone(check_action(new_action("imagesearch")))
        self.assertIsNotNone(check_action(new_action("label", name="1 bad")))
        self.assertIsNotNone(check_action(new_action("run")))
        self.assertIsNone(check_action(new_action("run", command="ls")))


class SearchTests(unittest.TestCase):
    def test_pixel(self):
        a = np.zeros((10, 20, 3), dtype=np.uint8)
        a[3, 7] = (10, 20, 30)
        self.assertEqual(pixel_search(a, (10, 20, 30), 0), (7, 3))
        self.assertEqual(pixel_search(a, (12, 20, 30), 2), (7, 3))
        self.assertIsNone(pixel_search(a, (12, 20, 30), 1))

    def test_pixel_near_wrap_around(self):
        a = np.full((4, 4, 3), 250, dtype=np.uint8)
        self.assertIsNone(pixel_search(a, (5, 5, 5), 10))

    def test_image(self):
        hay = np.random.default_rng(1).integers(0, 255, (60, 80, 3), dtype=np.uint8)
        needle = hay[20:30, 40:55].astype(np.int16)
        mask = np.ones(needle.shape[:2], dtype=bool)
        self.assertEqual(image_search(hay, needle, mask, 0), (40, 20))
        self.assertIsNone(image_search(np.zeros((5, 5, 3), dtype=np.uint8), needle, mask, 0))

    def test_color(self):
        self.assertEqual(parse_color("#ff8000"), (255, 128, 0))
        self.assertEqual(parse_color("0xFF8000"), (255, 128, 0))
        with self.assertRaises(ValueError):
            parse_color("zzzzzz")


class PlayerTests(unittest.TestCase):
    def chars(self, b):
        return "".join(e[1] for e in b.log if e[0] == "char")

    def test_loop_and_vars(self):
        acts = [new_action("setvar", var="n", value="0"), new_action("loop", count=3),
                new_action("setvar", var="n", value="n + a_index"), new_action("endloop"),
                new_action("text", text="%n%")]
        _, b, r = play(acts)
        self.assertEqual(self.chars(b), "6")
        self.assertEqual(r["msg"], "finished")

    def test_if_else(self):
        acts = [new_action("if", expr="1 = 2"), new_action("text", text="a"), new_action("else"),
                new_action("text", text="b"), new_action("endif")]
        self.assertEqual(self.chars(play(acts)[1]), "b")

    def test_break_continue_goto(self):
        acts = [new_action("loop", count=5), new_action("if", expr="a_index = 2"), new_action("continue"), new_action("endif"),
                new_action("if", expr="a_index = 4"), new_action("break"), new_action("endif"), new_action("text", text="x"),
                new_action("endloop"), new_action("goto", name="end"), new_action("text", text="skipped"),
                new_action("label", name="end"), new_action("text", text="z")]
        self.assertEqual(self.chars(play(acts)[1]), "xxz")

    def test_until_and_while(self):
        acts = [new_action("setvar", var="i", value="0"), new_action("loop", kind="until", expr="i >= 2"),
                new_action("setvar", var="i", value="i + 1"), new_action("text", text="u"), new_action("endloop")]
        self.assertEqual(self.chars(play(acts)[1]), "uu")
        acts = [new_action("loop", kind="while", expr="0"), new_action("text", text="w"), new_action("endloop")]
        self.assertEqual(self.chars(play(acts)[1]), "")

    def test_disabled_rows_are_skipped(self):
        off = new_action("text", text="a")
        off["enabled"] = False
        block = new_action("loop", count=2)
        block["enabled"] = False
        acts = [off, block, new_action("text", text="b"), new_action("endloop"), new_action("text", text="c")]
        self.assertEqual(self.chars(play(acts)[1]), "c")

    def test_repeat_counts_whole_macro(self):
        self.assertEqual(self.chars(play([new_action("text", text="r")], repeat=3)[1]), "rrr")

    def test_keys_held_at_the_end_get_released(self):
        acts = [new_action("key", key="w", mode="down"), new_action("click", mode="down", at_cursor=True)]
        _, b, _ = play(acts)
        self.assertIn(("key", "w", False), b.log)
        self.assertIn(("button", "lbutton", False), b.log)

    def test_stop_releases_and_is_prompt(self):
        acts = [new_action("key", key="w", mode="down"), new_action("sleep", ms=60000)]
        p, b, done, r = run(acts)
        import time
        time.sleep(0.1)
        self.assertTrue(p.running)
        p.stop()
        self.assertTrue(done.wait(1))
        self.assertEqual(r["msg"], "stopped")
        self.assertIn(("key", "w", False), b.log)

    def test_modifiers_released_when_key_is_bad(self):
        _, b, r = play([new_action("key", key="nonsense", ctrl=True)])
        self.assertTrue(r["msg"].startswith("error"))
        self.assertIn(("key", "lctrl", False), b.log)

    def test_only_selected_maps_back_to_table_rows(self):
        acts = [new_action("text", text=c) for c in "abcd"]
        _, b, r = play(acts, rows=[1, 3], repeat=1)
        self.assertEqual(self.chars(b), "bd")
        self.assertEqual([s for s in r["steps"] if s >= 0], [1, 3])

    def test_start_row(self):
        acts = [new_action("text", text=c) for c in "abc"]
        self.assertEqual(self.chars(play(acts, start_row=2)[1]), "c")

    def test_run_wait_can_be_stopped(self):
        b = FakeBackend()
        b.proc = FakeProc()
        p, b, done, r = run([new_action("run", command="sleep 99", wait=True)], backend=b)
        import time
        time.sleep(0.1)
        p.stop()
        self.assertTrue(done.wait(1))
        self.assertEqual(r["msg"], "stopped")

    def test_run_wait_sets_errorlevel(self):
        b = FakeBackend()
        b.proc = FakeProc(polls=2)
        acts = [new_action("run", command="x", wait=True), new_action("text", text="%errorlevel%")]
        self.assertEqual(self.chars(play(acts, backend=b)[1]), "0")

    def test_empty_forever_loop_stays_stoppable(self):
        acts = [new_action("loop", kind="forever"), new_action("comment", text="x"), new_action("endloop")]
        p, b, done, r = run(acts)
        import time
        time.sleep(0.1)
        p.stop()
        self.assertTrue(done.wait(1))

    def test_pixel_search_and_click_with_offset(self):
        b = FakeBackend()
        b.screen[5, 9] = (1, 2, 3)
        acts = [new_action("pixelsearch", x2="99", y2="99", color="010203", found="left click", offset_x=2)]
        _, b, _ = play(acts, backend=b)
        self.assertIn(("move", 11, 5), b.log)
        self.assertIn(("button", "lbutton", True), b.log)

    def test_search_wait_times_out(self):
        acts = [new_action("pixelsearch", x2="9", y2="9", color="010203", wait=True, timeout=100),
                new_action("text", text="%errorlevel%")]
        self.assertEqual(self.chars(play(acts)[1]), "1")

    def test_unknown_char_is_reported_not_fatal(self):
        _, b, r = play([new_action("text", text="aéb")])
        self.assertEqual(self.chars(b), "ab")
        self.assertEqual(r["msg"], "finished")

    def test_bad_structure_refuses_to_start(self):
        from reprise.engine import MacroError
        p = Player(FakeBackend(), {"step": None, "finished": None, "log": None, "iteration": None, "msgbox": None})
        with self.assertRaises(MacroError) as cm:
            p.start(dict(new_macro(), actions=[new_action("sleep"), new_action("loop")]), 0)
        self.assertEqual(cm.exception.row, 1)


def key(name, down, t):
    return {"kind": "key", "name": name, "down": down, "repeat": False, "t": t}


def btn(down, t, x=10, y=10, name="lbutton"):
    return {"kind": "button", "name": name, "down": down, "repeat": False, "t": t, "x": x, "y": y}


class RecorderTests(unittest.TestCase):
    S = {"merge_text": True, "merge_double": True, "rec_delays": True}

    def build(self, events, held=(), **s):
        return build_actions(events, dict(self.S, **s), Keymap("us"), held)

    def test_text_merge(self):
        acts = self.build([key("h", True, 0), key("h", False, .05), key("i", True, .1), key("i", False, .15)])
        self.assertEqual([a["type"] for a in acts], ["text"])
        self.assertEqual(acts[0]["p"]["text"], "hi")

    def test_rollover_typing_still_merges(self):
        acts = self.build([key("h", True, 0), key("i", True, .03), key("h", False, .05), key("i", False, .08)])
        self.assertEqual([a["type"] for a in acts], ["text"])
        self.assertEqual(acts[0]["p"]["text"], "hi")

    def test_shift_merges_to_capitals(self):
        acts = self.build([key("lshift", True, 0), key("h", True, .01), key("h", False, .02), key("lshift", False, .03),
                           key("i", True, .04), key("i", False, .05)])
        self.assertEqual(acts[0]["p"]["text"], "Hi")

    def test_ctrl_combo_is_not_text(self):
        acts = self.build([key("lctrl", True, 0), key("c", True, .01), key("c", False, .02), key("lctrl", False, .03)])
        self.assertEqual([(a["type"], a["p"]["mode"]) for a in acts], [("key", "down"), ("key", "press"), ("key", "up")])

    def test_click_double_click_and_drag(self):
        acts = self.build([btn(True, 0), btn(False, .02)])
        self.assertEqual(acts[0]["p"]["mode"], "click")
        acts = self.build([btn(True, 0), btn(False, .02), btn(True, .1), btn(False, .12)])
        self.assertEqual((len(acts), acts[0]["p"]["clicks"]), (1, 2))
        acts = self.build([btn(True, 0), btn(False, .5, x=200)])
        self.assertEqual([a["p"]["mode"] for a in acts], ["down", "up"])

    def test_delays_come_from_timing(self):
        acts = self.build([btn(True, 0), btn(False, .02), btn(True, 1.02), btn(False, 1.04, x=50, y=50)], merge_double=False)
        self.assertEqual(acts[0]["delay"], 1000)

    def test_held_stop_key_is_dropped(self):
        acts = self.build([key("f1", True, 0), key("f1", False, .1), key("lctrl", True, .2)], held={"lctrl"})
        self.assertEqual(len(acts), 1)

    def test_wheel_merge(self):
        ev = {"kind": "wheel", "dir": "down", "amount": 1}
        acts = self.build([dict(ev, t=0), dict(ev, t=.1), dict(ev, t=1)])
        self.assertEqual([a["p"]["amount"] for a in acts], [2, 1])

    def test_release_with_no_press_is_ignored(self):
        from reprise.recorder import Recorder
        b = FakeBackend()
        r = Recorder(b)
        r.start({"rec_keys": True, "rec_mouse": True, "ignore_self": False})
        self.assertFalse(r.feed(key("lctrl", False, 0)))
        self.assertFalse(r.feed(btn(False, 0)))
        self.assertTrue(r.feed(key("a", True, 0)))
        self.assertTrue(r.feed(key("a", False, .1)))
        acts = r.stop()
        self.assertEqual(acts[0]["p"]["mode"], "press")

    def test_input_in_own_window_is_ignored(self):
        from reprise.recorder import Recorder
        b = FakeBackend()
        b.focused_self = True
        b.in_self = True
        r = Recorder(b)
        r.start({"ignore_self": True})
        self.assertFalse(r.feed(key("a", True, 0)))
        self.assertFalse(r.feed(btn(True, 0)))
        self.assertFalse(r.feed(btn(False, 0)))


class AhkTests(unittest.TestCase):
    def gen(self, acts, settings=None, **macro):
        project = {"macros": [dict(new_macro(), actions=acts, **macro)]}
        return ahk.generate(project, settings or {})[0]

    def test_everything_is_lowercase_unless_user_text(self):
        for t in ("click", "mousemove", "wheel", "key", "sleep", "pixelgetcolor", "wingettitle"):
            body = self.gen([new_action(t)])
            self.assertEqual(body, body.lower(), t)

    def test_lone_percent_is_escaped_but_vars_are_not(self):
        body = self.gen([new_action("text", text="100% of %name%; done")])
        self.assertIn("sendraw, 100`% of %name%`; done", body)

    def test_edge_spaces_survive(self):
        self.assertIn("sendraw, %a_space%%a_space%hi%a_space%", self.gen([new_action("text", text="  hi ")]))

    def test_run_escapes_commas(self):
        self.assertIn("run, foo `,bar", self.gen([new_action("run", command="foo ,bar")]))

    def test_msgbox_escapes_commas(self):
        self.assertIn("msgbox, 0, a`,b, c`,d", self.gen([new_action("msgbox", title="a,b", text="c,d")]))

    def test_percent_vars_removed_in_expressions(self):
        self.assertIn("if (x > 1)", self.gen([new_action("if", expr="%x% > 1"), new_action("endif")]))

    def test_click_forms(self):
        self.assertIn("click, 5, 6 left, 1", self.gen([new_action("click", x="5", y="6")]))
        self.assertIn("click, right, 1", self.gen([new_action("click", button="right", at_cursor=True)]))
        self.assertIn('click, % (foundx + 1) ", " 6 " left, 1"', self.gen([new_action("click", x="foundx + 1", y="6")]))

    def test_repeat_with_delay_loops_and_keeps_delay(self):
        a = new_action("key", key="a")
        a["repeat"] = 3
        a["delay"] = 50
        body = self.gen([a])
        self.assertIn("loop, 3", body)
        self.assertIn("sleep, 50", body)
        a["delay"] = 0
        self.assertIn("send, {a 3}", self.gen([a]))

    def test_speed_scales_waits(self):
        a = new_action("sleep", ms=1000)
        self.assertIn("sleep, 500", self.gen([a], speed=2.0))

    def test_duplicate_macro_names_get_unique_labels(self):
        project = {"macros": [new_macro("same name"), new_macro("same name"), new_macro("same_name")]}
        body = ahk.generate(project, {})[0]
        labels = [ln for ln in body.splitlines() if ln.endswith(":")]
        self.assertEqual(len(labels), len(set(labels)))

    def test_shared_user_labels_get_namespaced(self):
        m1 = dict(new_macro("one"), actions=[new_action("label", name="here"), new_action("goto", name="here")])
        m2 = dict(new_macro("two"), actions=[new_action("label", name="here"), new_action("goto", name="here")])
        body = ahk.generate({"macros": [m1, m2]}, {})[0]
        self.assertIn("one_here:", body)
        self.assertIn("goto, two_here", body)
        solo = ahk.generate({"macros": [m1]}, {})[0]
        self.assertIn("goto, here", solo)

    def test_stop_key_does_not_rerun_an_autorun_macro(self):
        hot = {"hotkeys": {"stop": "f12", "pause": "f8"}}
        self.assertIn("f12::exitapp", self.gen([], hot))
        self.assertIn("f12::reload", self.gen([], hot, hotkey="f5"))

    def test_disabled_rows_are_commented(self):
        a = new_action("sleep", ms=5)
        a["enabled"] = False
        self.assertIn(";   sleep, 5", self.gen([a]))

    def test_map_lines_up(self):
        acts = [new_action("sleep"), new_action("loop"), new_action("sleep"), new_action("endloop")]
        text, maps, _ = ahk.generate({"macros": [dict(new_macro(), actions=acts)]}, {})
        lines = text.splitlines()
        self.assertEqual(len(maps[0]), 4)
        self.assertIn("sleep", lines[maps[0][0][0]])
        self.assertIn("loop, 2", lines[maps[0][1][0]])

    def test_same_image_name_from_two_folders(self):
        a = new_action("imagesearch", image="/a/x.png")
        b = new_action("imagesearch", image="/b/x.png")
        _, _, images = ahk.generate({"macros": [dict(new_macro(), actions=[a, b])]}, {})
        self.assertEqual(sorted(images.values()), ["x.png", "x_2.png"])

    def test_image_center_is_two_statements(self):
        a = new_action("imagesearch", image="/a/b.png", found="left click")
        text = ahk.generate({"macros": [dict(new_macro(), actions=[a])]}, {}, lambda p: (40, 20))[0]
        self.assertIn("foundx += 20\n", text)
        self.assertIn("foundy += 10\n", text)

    def test_every_type_generates(self):
        from reprise.model import TYPES
        for t in TYPES:
            if t not in ("else", "endif", "endloop"):
                ahk.action_lines(new_action(t, **({"image": "/a/b.png"} if t == "imagesearch" else {})),
                                 {"images": {}, "speed": 1.0, "image_size": lambda p: None, "label": str})


if __name__ == "__main__":
    unittest.main()
