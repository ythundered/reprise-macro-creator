import os
import re

from .expr import VAR_RE, is_num
from .model import UNTIMED, analyze

IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
INDENT = "    "

HEADER = [
    "#noenv",
    "#singleinstance force",
    "sendmode input",
    "setworkingdir %a_scriptdir%",
    "coordmode, mouse, screen",
    "coordmode, pixel, screen",
    "settitlematchmode, 2",
    "setbatchlines, -1",
    "setkeydelay, -1",
    "setmousedelay, -1",
    "setdefaultmousespeed, 0",
]


def _esc_plain(s, last):
    s = s.replace("`", "``").replace("%", "`%").replace(";", "`;").replace("\n", "`n").replace("\t", "`t")
    return s if last else s.replace(",", "`,")


def esc(s, last=True):
    s = str(s).replace("\r", "")
    out = []
    pos = 0
    # %name% stays a variable, any other % would be a load error in ahk
    for m in VAR_RE.finditer(s):
        out.append(_esc_plain(s[pos:m.start()], last))
        out.append(m.group(0))
        pos = m.end()
    out.append(_esc_plain(s[pos:], last))
    s = "".join(out)
    # ahk trims command args, so edge spaces have to go through a_space
    body = s.strip(" ")
    lead = len(s) - len(s.lstrip(" "))
    trail = len(s) - len(s.rstrip(" ")) if body else 0
    return "%a_space%" * lead + body + "%a_space%" * trail


def qstr(s):
    return '"' + str(s).replace('"', '""') + '"'


def expr_src(e):
    return VAR_RE.sub(lambda m: m.group(1), str(e))


def param(v):
    s = str(v).strip()
    if s == "":
        return "0"
    if is_num(s):
        return s
    if IDENT_RE.match(s):
        return f"%{s}%"
    if s.startswith("%") and s.endswith("%") and s.count("%") == 2:
        return s
    return f"% {s}"


def _expr_part(v):
    s = str(v).strip()
    return s if is_num(s) else f"({expr_src(s)})"


def _scaled(ms, speed):
    return max(0, int(round(int(ms) / (speed or 1.0))))


def _click_line(btn, x, y, extra, rel):
    if x is None:
        return f"click, {btn}{extra}"
    if is_num(x) and is_num(y):
        return f"click, {x}, {y} {btn}{extra}{' rel' if rel else ''}"
    return f'click, % {_expr_part(x)} ", " {_expr_part(y)} " {btn}{extra}{" rel" if rel else ""}"'


def _found_lines(handler, label, p, ctx):
    if handler == "continue":
        return []
    ox, oy = int(p.get("offset_x", 0) or 0), int(p.get("offset_y", 0) or 0)
    xs = "foundx" + (f" + {ox}" if ox else "")
    ys = "foundy" + (f" + {oy}" if oy else "")
    if handler == "move":
        return [f"mousemove, % {xs}, % {ys}, 0" if (ox or oy) else "mousemove, %foundx%, %foundy%, 0"]
    clicks = {"left click": ("left", 1), "right click": ("right", 1), "middle click": ("middle", 1),
              "double click": ("left", 2)}
    if handler in clicks:
        b, n = clicks[handler]
        if ox or oy:
            return [f'click, % {xs} ", " {ys} " {b}, {n}"']
        return [f"click, %foundx%, %foundy% {b}, {n}"]
    if handler == "break loop":
        return ["break"]
    if handler == "stop macro":
        return ["return"]
    if handler == "goto label":
        return [f"goto, {ctx['label'](label or 'label1')}"]
    return []


def _image_ref(path, images):
    if not path:
        return "image.png"
    if path not in images:
        base, ext = os.path.splitext(os.path.basename(path))
        name = base + ext
        taken = set(images.values())
        n = 2
        while name in taken:
            name = f"{base}_{n}{ext}"
            n += 1
        images[path] = name
    return f"%a_scriptdir%\\{images[path]}"


def _pixel_search_line(x1, y1, x2, y2, p):
    return f"pixelsearch, foundx, foundy, {x1}, {y1}, {x2}, {y2}, 0x{p['color']}, {int(p['variation'])}, fast rgb"


def _image_search_line(p, images):
    var = f"*{int(p['variation'])} " if int(p.get("variation", 0)) else ""
    return (f"imagesearch, foundx, foundy, {param(p['x1'])}, {param(p['y1'])}, {param(p['x2'])}, {param(p['y2'])}, "
            f"{var}{_image_ref(p['image'], images)}")


def _center_lines(p, image_size):
    if not p.get("center"):
        return []
    size = image_size(p.get("image", ""))
    if not size:
        return []
    w, h = size
    # on one line ahk can read the second half as the time units of envadd
    return [f"foundx += {w // 2}", f"foundy += {h // 2}"]


def _search_action(t, p, ctx):
    if t == "pixelsearch":
        search = _pixel_search_line(param(p["x1"]), param(p["y1"]), param(p["x2"]), param(p["y2"]), p)
        center = []
    else:
        search = _image_search_line(p, ctx["images"])
        center = _center_lines(p, ctx["image_size"])
    out = []
    if p.get("wait"):
        cond = "errorlevel = 0" + (f" || a_tickcount - waitstart >= {int(p['timeout'])}" if int(p.get("timeout", 0)) else "")
        out += ["waitstart := a_tickcount", "loop", "{", INDENT + search, INDENT + f"if ({cond})",
                INDENT * 2 + "break", INDENT + "sleep, 50", "}"]
    else:
        out.append(search)
    fl = _found_lines(p["found"], p.get("goto_found"), p, ctx)
    nl = _found_lines(p["not_found"], p.get("goto_nf"), p, ctx)
    if center or fl:
        out += ["if (errorlevel = 0)", "{"] + [INDENT + s for s in center + fl] + ["}"]
        if nl:
            out += ["else", "{"] + [INDENT + s for s in nl] + ["}"]
    elif nl:
        out += ["if (errorlevel)", "{"] + [INDENT + s for s in nl] + ["}"]
    return out


def action_lines(a, ctx):
    t = a["type"]
    p = a["p"]
    speed = ctx["speed"]
    if t == "click":
        x, y = (None, None) if p["at_cursor"] else (p["x"], p["y"])
        extra = f", {int(p['clicks'])}" if p["mode"] == "click" else f", {p['mode']}"
        return [_click_line(p["button"], x, y, extra, p["relative"] and not p["at_cursor"])]
    if t == "mousemove":
        return [f"mousemove, {param(p['x'])}, {param(p['y'])}, {int(p['speed'])}{', r' if p['relative'] else ''}"]
    if t == "wheel":
        return [f"send, {{wheel{p['direction']} {int(p['amount'])}}}"]
    if t == "key":
        key = p["key"]
        if p["mode"] == "press":
            mods = "".join(s for m, s in (("ctrl", "^"), ("alt", "!"), ("shift", "+"), ("win", "#")) if p.get(m))
            return [f"send, {mods}{{{key}}}"]
        return [f"send, {{{key} {p['mode']}}}"]
    if t == "text":
        txt = esc(p["text"])
        cd = _scaled(p.get("char_delay", 0), speed)
        if cd > 0:
            return [f"setkeydelay, {cd}", f"sendevent, {{raw}}{txt}", "setkeydelay, -1"]
        return [f"sendraw, {txt}"]
    if t == "sleep":
        if int(p["random_to"]) > int(p["ms"]):
            return [f"random, sleeptime, {_scaled(p['ms'], speed)}, {_scaled(p['random_to'], speed)}", "sleep, %sleeptime%"]
        return [f"sleep, {_scaled(p['ms'], speed)}"]
    if t == "break":
        return ["break"]
    if t == "continue":
        return ["continue"]
    if t == "label":
        return [f"{ctx['label'](p['name'])}:"]
    if t == "goto":
        return [f"goto, {ctx['label'](p['name'])}"]
    if t == "setvar":
        if p["mode"] == "expression":
            return [f"{p['var']} := {expr_src(p['value']).strip() or chr(34) * 2}"]
        if p["mode"] == "text":
            return [f"{p['var']} = {esc(p['value'])}"]
        return [f"random, {p['var']}, {param(p['min'])}, {param(p['max'])}"]
    if t == "pixelgetcolor":
        return [f"pixelgetcolor, {p['var']}, {param(p['x'])}, {param(p['y'])}, rgb"]
    if t in ("pixelsearch", "imagesearch"):
        return _search_action(t, p, ctx)
    if t == "winactivate":
        return [f"winactivate, {esc(p['window'], False)}"]
    if t == "winwait":
        to = int(p["timeout"])
        return [f"winwaitactive, {esc(p['window'], False)},,{(' ' + str(to)) if to else ''}"]
    if t == "winclose":
        return [f"winclose, {esc(p['window'], False)}"]
    if t == "wingettitle":
        return [f"wingettitle, {p['var']}, a"]
    if t == "run":
        return [f"{'runwait' if p['wait'] else 'run'}, {esc(p['command'], False)}"]
    if t == "msgbox":
        return [f"msgbox, 0, {esc(p['title'], False)}, {esc(p['text'], False)}"]
    if t == "keywait":
        opts = ("d" if p["state"] == "press" else "") + (f" t{int(p['timeout'])}" if int(p["timeout"]) else "")
        return [f"keywait, {p['key']}{(', ' + opts.strip()) if opts.strip() else ''}"]
    if t == "comment":
        return [f"; {p['text']}"]
    if t == "stop":
        return ["return"]
    return []


def if_lines(p, ctx):
    k = p["kind"]
    neg = p.get("negate")
    if k == "expression":
        e = expr_src(p["expr"]) or "0"
        return [f"if !({e})" if neg else f"if ({e})"]
    if k == "window active":
        return [f"if {'!' if neg else ''}winactive({qstr(p['window'])})"]
    if k == "window exists":
        return [f"if {'!' if neg else ''}winexist({qstr(p['window'])})"]
    if k == "key down":
        return [f"if {'!' if neg else ''}getkeystate({qstr(p['key'])}, \"p\")"]
    pre = []
    if k == "pixel color":
        x, y = param(p["x"]), param(p["y"])
        pre = [_pixel_search_line(x, y, x, y, p)]
    elif k == "image found":
        pre = [_image_search_line(p, ctx["images"])]
    return pre + ["if (errorlevel)" if neg else "if (errorlevel = 0)"]


def _macro_labels(macros):
    used = {}
    out = []
    for i, m in enumerate(macros):
        base = re.sub(r"\W", "_", m["name"]).lower() or f"macro{i + 1}"
        name = base
        n = used.get(base, 0)
        while n and name in used:
            name = f"{base}_{n + 1}"
            n += 1
        used[base] = max(n, 1)
        used[name] = 1
        out.append(name)
    return out


def _label_namer(macros, macro_labels):
    # ahk labels are global, so a label used by two macros would fail to load
    seen = {}
    for m in macros:
        for name in {str(a["p"]["name"]).lower() for a in m["actions"] if a["type"] == "label"}:
            seen[name] = seen.get(name, 0) + 1
    taken = set(macro_labels)

    def namer(macro_label):
        def label(name):
            low = str(name).lower()
            return f"{macro_label}_{low}" if seen.get(low, 0) > 1 or low in taken else low
        return label
    return namer


def _step_lines(a, ctx):
    t = a["type"]
    body = action_lines(a, ctx)
    if t in UNTIMED:
        return body
    speed = ctx["speed"]
    n = int(a.get("repeat", 1))
    delay = _scaled(a["delay"], speed) if int(a["delay"]) else 0
    if n > 1 and t == "key" and a["p"]["mode"] == "press" and not delay:
        return [body[0][:-1] + f" {n}}}"]
    tail = [f"sleep, {delay}"] if delay else []
    if n > 1:
        return [f"loop, {n}", "{"] + [INDENT + s for s in body + tail] + ["}"]
    return body + tail


def generate(project, settings, image_size=lambda path: None):
    lines = list(HEADER)
    lines.append("")
    maps = []
    images = {}
    macros = project["macros"]
    macro_labels = _macro_labels(macros)
    namer = _label_namer(macros, macro_labels)
    for mi, m in enumerate(macros):
        acts = m["actions"]
        info = analyze(acts)
        ctx = {"images": images, "speed": float(m.get("speed", 1.0) or 1.0), "image_size": image_size,
               "label": namer(macro_labels[mi])}
        hk = (m.get("hotkey") or "").strip()
        if hk:
            lines.append(f"{hk}::")
        lines.append(f"{macro_labels[mi]}:")
        rep = int(m.get("repeat", 1))
        lines.append("loop" if rep == 0 else f"loop, {rep}")
        lines.append("{")
        mapping = []
        disabled_until = -1
        until_stack = []
        for i, a in enumerate(acts):
            pad = INDENT * (info["indent"][i] + 1)
            start = len(lines)
            t = a["type"]
            off = (not a["enabled"]) or i <= disabled_until
            if not a["enabled"] and t in ("loop", "if") and i in info["partner"]:
                disabled_until = max(disabled_until, info["partner"][i])
            if t == "loop":
                p = a["p"]
                if p["kind"] == "count":
                    body = [f"loop, {int(p['count'])}", "{"]
                elif p["kind"] == "while":
                    body = [f"while ({expr_src(p['expr']) or '0'})", "{"]
                else:
                    body = ["loop", "{"]
                until_stack.append(p if p["kind"] == "until" else None)
            elif t == "endloop":
                p = until_stack.pop() if until_stack else None
                body = ["}"] + ([f"until ({expr_src(p['expr']) or '1'})"] if p is not None else [])
            elif t == "if":
                body = if_lines(a["p"], ctx) + ["{"]
            elif t == "else":
                body = ["}", "else", "{"]
            elif t == "endif":
                body = ["}"]
            else:
                body = _step_lines(a, ctx)
            if a.get("comment") and body:
                body[0] = body[0] + f"  ; {a['comment']}"
            for s in body:
                lines.append(((";" + pad[1:]) if off else pad) + s)
            mapping.append((start, len(lines) - 1))
        lines += ["}", "return", ""]
        maps.append(mapping)
    hot = settings.get("hotkeys", {})
    if hot.get("stop"):
        # the first macro auto-runs when it has no hotkey, reload would just start it again
        auto_runs = macros and not (macros[0].get("hotkey") or "").strip()
        lines.append(f"{hot['stop']}::{'exitapp' if auto_runs else 'reload'}")
    if hot.get("pause"):
        lines.append(f"{hot['pause']}::pause")
    return "\n".join(lines) + "\n", maps, images
