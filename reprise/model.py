import copy
import os
import re

CATEGORY_COLORS = {
    "mouse": "#5b9dff",
    "keyboard": "#b08cff",
    "flow": "#e0b040",
    "search": "#4cc76a",
    "window": "#3fc9d4",
    "vars": "#f58ac0",
    "misc": "#a0a4ae",
}

FOUND_CHOICES = ["continue", "move", "left click", "right click", "middle click", "double click",
                 "break loop", "stop macro", "goto label"]
NAME_RE = re.compile(r"^[A-Za-z_]\w*$")


def F(key, label, kind, opts=None, show=None):
    return {"key": key, "label": label, "kind": kind, "opts": opts, "show": show}


def _found_fields():
    return [
        F("wait", "keep looking until found", "bool"),
        F("timeout", "give up after ms (0 = never)", "int", (0, 3600000), ("wait", [True])),
        F("found", "when found", "choice", FOUND_CHOICES),
        F("goto_found", "label", "str", None, ("found", ["goto label"])),
        F("not_found", "when not found", "choice", FOUND_CHOICES[:1] + FOUND_CHOICES[6:]),
        F("goto_nf", "label", "str", None, ("not_found", ["goto label"])),
        F("offset_x", "click offset x", "int", (-10000, 10000)),
        F("offset_y", "click offset y", "int", (-10000, 10000)),
    ]


IF_KINDS = ["expression", "window active", "window exists", "pixel color", "image found",
            "key down", "last search found"]

TYPES = {
    "click": dict(label="click", cat="mouse", delay=10, hint="clicks a mouse button at a spot on screen.",
                  defaults=dict(button="left", mode="click", clicks=1, x="0", y="0", at_cursor=False, relative=False),
                  fields=[
        F("button", "button", "choice", ["left", "right", "middle", "x1", "x2"]),
        F("mode", "action", "choice", ["click", "down", "up"]),
        F("clicks", "clicks", "int", (1, 20), ("mode", ["click"])),
        F("at_cursor", "wherever the cursor already is", "bool"),
        F("pos", "position", "point", None, ("at_cursor", [False])),
        F("relative", "relative to the cursor", "bool", None, ("at_cursor", [False])),
    ]),
    "mousemove": dict(label="move", cat="mouse", delay=10, hint="moves the cursor without clicking.",
                      defaults=dict(x="0", y="0", relative=False, speed=0), fields=[
        F("pos", "position", "point"),
        F("relative", "relative to the cursor", "bool"),
        F("speed", "speed (0 instant, 100 slowest)", "int", (0, 100)),
    ]),
    "wheel": dict(label="scroll", cat="mouse", delay=10, hint="turns the mouse wheel.",
                  defaults=dict(direction="down", amount=1), fields=[
        F("direction", "direction", "choice", ["up", "down", "left", "right"]),
        F("amount", "notches", "int", (1, 100)),
    ]),
    "key": dict(label="key", cat="keyboard", delay=0, hint="presses one key, with or without modifiers.",
                defaults=dict(key="enter", mode="press", ctrl=False, shift=False, alt=False, win=False), fields=[
        F("key", "key", "key"),
        F("mode", "action", "choice", ["press", "down", "up"]),
        F("ctrl", "ctrl", "bool", None, ("mode", ["press"])),
        F("shift", "shift", "bool", None, ("mode", ["press"])),
        F("alt", "alt", "bool", None, ("mode", ["press"])),
        F("win", "win / super", "bool", None, ("mode", ["press"])),
    ]),
    "text": dict(label="text", cat="keyboard", delay=0, hint="types text as if you typed it. %name% inserts a variable.",
                 defaults=dict(text="", char_delay=0), fields=[
        F("text", "text", "text"),
        F("char_delay", "ms between characters", "int", (0, 5000)),
    ]),
    "sleep": dict(label="pause", cat="flow", delay=0, hint="waits before the next step.",
                  defaults=dict(ms=500, random_to=0), fields=[
        F("ms", "milliseconds", "int", (0, 86400000)),
        F("random_to", "random up to ms (0 = off)", "int", (0, 86400000)),
    ]),
    "loop": dict(label="loop", cat="flow", delay=0, block="open", hint="repeats the steps between loop and end loop.",
                 defaults=dict(kind="count", count=2, expr=""), fields=[
        F("kind", "type", "choice", ["count", "forever", "while", "until"]),
        F("count", "times", "int", (1, 100000000), ("kind", ["count"])),
        F("expr", "expression", "expr", None, ("kind", ["while", "until"])),
    ]),
    "endloop": dict(label="end loop", cat="flow", delay=0, block="close", hint="closes a loop.", defaults={}, fields=[]),
    "break": dict(label="break", cat="flow", delay=0, hint="leaves the current loop.", defaults={}, fields=[]),
    "continue": dict(label="continue", cat="flow", delay=0, hint="jumps to the next run of the current loop.",
                     defaults={}, fields=[]),
    "if": dict(label="if", cat="flow", delay=0, block="open", hint="only runs the steps inside when the condition is true.",
               defaults=dict(kind="expression", negate=False, expr="", window="", x="0", y="0", color="ffffff",
                             variation=0, x1="0", y1="0", x2="1919", y2="1079", image="", key="lbutton"), fields=[
        F("kind", "condition", "choice", IF_KINDS),
        F("negate", "flip it (not)", "bool"),
        F("expr", "expression", "expr", None, ("kind", ["expression"])),
        F("window", "window", "window", None, ("kind", ["window active", "window exists"])),
        F("pos", "pixel position", "point", None, ("kind", ["pixel color"])),
        F("color", "color", "color", None, ("kind", ["pixel color"])),
        F("variation", "color tolerance 0-255", "int", (0, 255), ("kind", ["pixel color", "image found"])),
        F("region", "search area", "region", None, ("kind", ["image found"])),
        F("image", "image", "image", None, ("kind", ["image found"])),
        F("key", "key", "key", ("buttons",), ("kind", ["key down"])),
    ]),
    "else": dict(label="else", cat="flow", delay=0, block="mid", hint="runs when the if above was false.",
                 defaults={}, fields=[]),
    "endif": dict(label="end if", cat="flow", delay=0, block="close", hint="closes an if.", defaults={}, fields=[]),
    "label": dict(label="label", cat="flow", delay=0, hint="a named spot that goto can jump to.",
                  defaults=dict(name="label1"), fields=[F("name", "name", "str")]),
    "goto": dict(label="goto", cat="flow", delay=0, hint="jumps to a label.",
                 defaults=dict(name="label1"), fields=[F("name", "label", "str")]),
    "setvar": dict(label="variable", cat="vars", delay=0, hint="stores a value you can use later with %name%.",
                   defaults=dict(var="count", mode="expression", value="0", min="1", max="100"), fields=[
        F("var", "name", "str"),
        F("mode", "value is", "choice", ["expression", "text", "random"]),
        F("value", "value", "expr", None, ("mode", ["expression", "text"])),
        F("min", "min", "str", None, ("mode", ["random"])),
        F("max", "max", "str", None, ("mode", ["random"])),
    ]),
    "pixelgetcolor": dict(label="read pixel", cat="search", delay=0, hint="reads the color at a spot into a variable.",
                          defaults=dict(x="0", y="0", var="color"), fields=[
        F("pos", "position", "point"),
        F("var", "store in variable", "str"),
    ]),
    "pixelsearch": dict(label="find pixel", cat="search", delay=0,
                        hint="looks for a color on screen. foundx and foundy hold where it was.",
                        defaults=dict(x1="0", y1="0", x2="1919", y2="1079", color="ffffff", variation=0, wait=False,
                                      timeout=5000, found="continue", not_found="continue", goto_found="", goto_nf="",
                                      offset_x=0, offset_y=0), fields=[
        F("region", "search area", "region"),
        F("color", "color", "color"),
        F("variation", "color tolerance 0-255", "int", (0, 255)),
    ] + _found_fields()),
    "imagesearch": dict(label="find image", cat="search", delay=0,
                        hint="looks for a picture on screen. foundx and foundy hold where it was.",
                        defaults=dict(x1="0", y1="0", x2="1919", y2="1079", image="", variation=30, center=True,
                                      wait=False, timeout=5000, found="continue", not_found="continue", goto_found="",
                                      goto_nf="", offset_x=0, offset_y=0), fields=[
        F("region", "search area", "region"),
        F("image", "image", "image"),
        F("variation", "color tolerance 0-255", "int", (0, 255)),
        F("center", "use the middle of the image", "bool"),
    ] + _found_fields()),
    "winactivate": dict(label="focus window", cat="window", delay=100, hint="brings a window to the front.",
                        defaults=dict(window=""), fields=[F("window", "window", "window")]),
    "winwait": dict(label="wait for window", cat="window", delay=0, hint="waits until a window is the active one.",
                    defaults=dict(window="", timeout=10), fields=[
        F("window", "window", "window"),
        F("timeout", "give up after s (0 = never)", "int", (0, 86400)),
    ]),
    "winclose": dict(label="close window", cat="window", delay=0, hint="asks a window to close.",
                     defaults=dict(window=""), fields=[F("window", "window", "window")]),
    "wingettitle": dict(label="read title", cat="window", delay=0, hint="stores the active window's title in a variable.",
                        defaults=dict(var="title"), fields=[F("var", "store in variable", "str")]),
    "run": dict(label="run", cat="misc", delay=0, hint="starts a program, file or url.",
                defaults=dict(command="", wait=False), fields=[
        F("command", "command, file or url", "str"),
        F("wait", "wait for it to exit", "bool"),
    ]),
    "msgbox": dict(label="message", cat="misc", delay=0, hint="shows a message and waits for you to close it.",
                   defaults=dict(title="macro", text=""), fields=[
        F("title", "title", "str"),
        F("text", "message", "text"),
    ]),
    "keywait": dict(label="wait for key", cat="keyboard", delay=0, hint="waits until a key is pressed or let go.",
                    defaults=dict(key="lbutton", state="press", timeout=0), fields=[
        F("key", "key", "key", ("buttons",)),
        F("state", "wait for", "choice", ["press", "release"]),
        F("timeout", "give up after s (0 = never)", "int", (0, 86400)),
    ]),
    "comment": dict(label="note", cat="misc", delay=0, hint="a note to yourself. it does nothing when played.",
                    defaults=dict(text=""), fields=[F("text", "note", "str")]),
    "stop": dict(label="stop", cat="flow", delay=0, hint="ends the macro.", defaults={}, fields=[]),
}

UNTIMED = {"loop", "endloop", "if", "else", "endif", "label", "comment", "break", "continue", "goto", "stop"}
LOCKED_ON = {"else", "endif", "endloop"}
_CHOICE_KEYS = {t: [f["key"] for f in s["fields"] if f["kind"] in ("choice", "key")] for t, s in TYPES.items()}


def new_action(t, default_delay=None, **params):
    spec = TYPES[t]
    p = copy.deepcopy(spec["defaults"])
    p.update(params)
    delay = spec["delay"] if default_delay is None or spec["delay"] == 0 else default_delay
    return {"type": t, "enabled": True, "repeat": 1, "delay": delay, "comment": "", "color": "", "p": p}


def normalize(a):
    t = str(a.get("type", "")).lower()
    spec = TYPES.get(t)
    if spec is None:
        return None
    p = copy.deepcopy(spec["defaults"])
    p.update(a.get("p", {}))
    for k in _CHOICE_KEYS[t]:
        if isinstance(p.get(k), str):
            p[k] = p[k].lower()
    return {"type": t, "enabled": bool(a.get("enabled", True)), "repeat": max(1, int(a.get("repeat", 1) or 1)),
            "delay": max(0, int(a.get("delay", 0) or 0)), "comment": str(a.get("comment", "")),
            "color": str(a.get("color", "")), "p": p}


def new_macro(name="macro1"):
    return {"name": name, "hotkey": "", "repeat": 1, "speed": 1.0, "actions": []}


def normalize_macro(m, fallback="macro1"):
    out = new_macro(str(m.get("name") or fallback))
    out["hotkey"] = str(m.get("hotkey") or "").lower()
    out["repeat"] = max(0, int(m.get("repeat", 1)))
    out["speed"] = max(0.05, float(m.get("speed", 1.0) or 1.0))
    out["actions"] = [a for a in (normalize(a) for a in m.get("actions", [])) if a]
    return out


def _pt(p, a="x", b="y"):
    return f"{p.get(a)}, {p.get(b)}"


def _region(p):
    return f"{p['x1']},{p['y1']} to {p['x2']},{p['y2']}"


def _found_desc(p):
    parts = []
    if p.get("wait"):
        parts.append(f"wait up to {p['timeout']} ms" if p.get("timeout") else "wait")
    f, nf = p.get("found"), p.get("not_found")
    if f and f != "continue":
        parts.append(f"found: {p.get('goto_found') if f == 'goto label' else f}")
    if nf and nf != "continue":
        parts.append(f"not found: {p.get('goto_nf') if nf == 'goto label' else nf}")
    return (", " + ", ".join(parts)) if parts else ""


def if_condition_text(p):
    k = p["kind"]
    if k == "expression":
        s = p["expr"] or "(empty)"
    elif k == "window active":
        s = f'window "{p["window"]}" is active'
    elif k == "window exists":
        s = f'window "{p["window"]}" exists'
    elif k == "pixel color":
        s = f"pixel {_pt(p)} is #{p['color']}" + (f" +-{p['variation']}" if p.get("variation") else "")
    elif k == "image found":
        s = f"{os.path.basename(p['image']) or '(no image)'} found in {_region(p)}"
    elif k == "key down":
        s = f"{p['key']} is held"
    else:
        s = "last search found"
    return ("not " if p.get("negate") else "") + s


def describe(a):
    t = a["type"]
    p = a["p"]
    label = TYPES[t]["label"]
    if t == "click":
        where = "at cursor" if p["at_cursor"] else (("by " if p["relative"] else "at ") + _pt(p))
        if p["mode"] == "click":
            n = int(p["clicks"])
            what = f"{p['button']} {'double ' if n == 2 else ''}click" + (f" x{n}" if n > 2 else "")
        else:
            what = f"{p['button']} {p['mode']}"
        return label, f"{what} {where}"
    if t == "mousemove":
        return label, ("by " if p["relative"] else "to ") + _pt(p) + (f", speed {p['speed']}" if p["speed"] else "")
    if t == "wheel":
        return label, f"{p['direction']} x{p['amount']}"
    if t == "key":
        mods = "".join(m + "+" for m in ("ctrl", "shift", "alt", "win") if p.get(m)) if p["mode"] == "press" else ""
        return label, f"{mods}{p['key']}" + ("" if p["mode"] == "press" else f" {p['mode']}")
    if t == "text":
        s = p["text"].replace("\n", " \\n ").replace("\t", " \\t ")
        return label, (s[:80] + "...") if len(s) > 80 else s
    if t == "sleep":
        return label, f"{p['ms']} to {p['random_to']} ms" if p["random_to"] else f"{p['ms']} ms"
    if t == "loop":
        k = p["kind"]
        if k == "count":
            return label, f"{p['count']} times"
        return label, "forever" if k == "forever" else f"{k} {p['expr']}"
    if t == "if":
        return label, if_condition_text(p)
    if t in ("label", "goto"):
        return label, p["name"]
    if t == "setvar":
        if p["mode"] == "random":
            return label, f"{p['var']} = random {p['min']} to {p['max']}"
        return label, f"{p['var']} {':=' if p['mode'] == 'expression' else '='} {p['value']}"
    if t == "pixelgetcolor":
        return label, f"pixel {_pt(p)} into {p['var']}"
    if t == "pixelsearch":
        v = f" +-{p['variation']}" if p["variation"] else ""
        return label, f"#{p['color']}{v} in {_region(p)}{_found_desc(p)}"
    if t == "imagesearch":
        return label, f"{os.path.basename(p['image']) or '(no image)'} +-{p['variation']} in {_region(p)}{_found_desc(p)}"
    if t in ("winactivate", "winclose"):
        return label, p["window"]
    if t == "winwait":
        return label, p["window"] + (f", up to {p['timeout']} s" if p["timeout"] else "")
    if t == "wingettitle":
        return label, f"active title into {p['var']}"
    if t == "run":
        return label, p["command"] + (" (wait)" if p["wait"] else "")
    if t == "msgbox":
        return label, p["text"].replace("\n", " ")[:80]
    if t == "keywait":
        return label, f"{p['key']} {p['state']}" + (f", up to {p['timeout']} s" if p["timeout"] else "")
    if t == "comment":
        return label, p["text"]
    return label, ""


def check_action(a):
    t = a["type"]
    p = a["p"]
    needs_image = t == "imagesearch" or (t == "if" and p["kind"] == "image found")
    if needs_image and not str(p["image"]).strip():
        return "choose or capture an image first."
    if t in ("setvar", "pixelgetcolor", "wingettitle") and not NAME_RE.match(str(p["var"]).strip()):
        return "variable names use letters, digits and _ and cannot start with a digit."
    if t in ("label", "goto") and not NAME_RE.match(str(p["name"]).strip()):
        return "label names use letters, digits and _ and cannot start with a digit."
    if t == "run" and not str(p["command"]).strip():
        return "enter what to run."
    if t in ("winactivate", "winwait", "winclose") and not str(p["window"]).strip():
        return "say which window."
    if t == "if" and p["kind"] in ("window active", "window exists") and not str(p["window"]).strip():
        return "say which window."
    if t in ("pixelsearch", "imagesearch"):
        for key, target in (("found", "goto_found"), ("not_found", "goto_nf")):
            if p[key] == "goto label" and not NAME_RE.match(str(p[target]).strip()):
                return "enter the label to jump to."
    return None


class StructureError(Exception):
    def __init__(self, row, msg):
        super().__init__(f"row {row + 1}: {msg}")
        self.row = row


def analyze(actions):
    partner = {}
    else_of = {}
    labels = {}
    jumps = []
    indent = [0] * len(actions)
    stack = []
    errors = []
    for i, a in enumerate(actions):
        t = a["type"]
        indent[i] = len(stack)
        if t in ("loop", "if"):
            stack.append(i)
        elif t == "else":
            if not stack or actions[stack[-1]]["type"] != "if" or stack[-1] in else_of:
                errors.append(StructureError(i, "else without if"))
                continue
            indent[i] = len(stack) - 1
            else_of[stack[-1]] = i
            partner[i] = stack[-1]
        elif t in ("endloop", "endif"):
            want = "loop" if t == "endloop" else "if"
            if not stack or actions[stack[-1]]["type"] != want:
                errors.append(StructureError(i, f"{TYPES[t]['label']} without {want}"))
                continue
            o = stack.pop()
            indent[i] = len(stack)
            partner[o] = i
            partner[i] = o
            if o in else_of:
                partner[else_of[o]] = i
        elif t == "label":
            name = str(a["p"]["name"]).lower()
            if name in labels:
                errors.append(StructureError(i, f"duplicate label {a['p']['name']}"))
            labels[name] = i
        elif t == "goto":
            jumps.append((i, a["p"]["name"]))
        elif t in ("pixelsearch", "imagesearch"):
            if a["p"]["found"] == "goto label":
                jumps.append((i, a["p"]["goto_found"]))
            if a["p"]["not_found"] == "goto label":
                jumps.append((i, a["p"]["goto_nf"]))
    for o in stack:
        errors.append(StructureError(o, f"{TYPES[actions[o]['type']]['label']} is never closed"))
    for i, name in jumps:
        if str(name).lower() not in labels:
            errors.append(StructureError(i, f"no label called {name}"))
    errors.sort(key=lambda e: e.row)
    return {"partner": partner, "else": else_of, "labels": labels, "indent": indent, "errors": errors}


def with_partners(rows, info):
    out = set(rows)
    for r in rows:
        if r in info["partner"]:
            out.add(info["partner"][r])
            opener = info["partner"][r]
            if opener in info["else"]:
                out.add(info["else"][opener])
        if r in info["else"]:
            out.add(info["else"][r])
    return sorted(out)
