import ast
import functools
import math
import re


class ExprError(Exception):
    pass


NUM_RE = re.compile(r"^\s*[-+]?(0[xX][0-9a-fA-F]+|\d+(\.\d*)?|\.\d+)\s*$")
VAR_RE = re.compile(r"%([A-Za-z_][\w#@$]*)%")
MAX_POWER = 4096


def is_num(v):
    if isinstance(v, (bool, int, float)):
        return True
    return bool(NUM_RE.match(str(v)))


def num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s == "":
        return 0
    if not NUM_RE.match(s):
        raise ExprError(f"not a number: {s!r}")
    if "x" in s.lower():
        return int(s, 16)
    if "." in s:
        return float(s)
    return int(s)


def fmt(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.6f}".rstrip("0").rstrip(".")
    return str(v)


def truthy(v):
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v)
    if s == "":
        return False
    if is_num(s):
        return num(s) != 0
    return True


class Vars(dict):
    def get(self, k, default=""):
        return super().get(str(k).lower(), default)

    def set(self, k, v):
        self[str(k).lower()] = v


def deref(text, variables):
    return VAR_RE.sub(lambda m: fmt(variables.get(m.group(1))), str(text))


def translate(src):
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if c == '"':
            j = i + 1
            buf = []
            while j < n:
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(src[j])
                j += 1
            if j >= n:
                raise ExprError("unterminated string")
            out.append(repr("".join(buf)))
            i = j + 1
            continue
        if two == ":=":
            raise ExprError("use a variable step for assignment")
        if two == "<>":
            out.append("!=")
            i += 2
            continue
        if two in ("<=", ">=", "!=", "==", "**", "//"):
            out.append(two)
            i += 2
            continue
        if two == "&&":
            out.append(" and ")
            i += 2
            continue
        if two == "||":
            out.append(" or ")
            i += 2
            continue
        if c == "=":
            out.append("==")
            i += 1
            continue
        if c == "!":
            out.append(" not ")
            i += 1
            continue
        # ahk concat needs spaces around the dot, 1.5 and a.b must not match
        if c == "." and 0 < i < n - 1 and src[i - 1].isspace() and src[i + 1].isspace():
            out.append("@")
            i += 1
            continue
        if c == "%":
            j = src.find("%", i + 1)
            if j < 0:
                raise ExprError("unmatched %")
            out.append("_v_" + src[i + 1:j].strip())
            i = j + 1
            continue
        if c.isdigit():
            j = i
            if src[i:i + 2].lower() == "0x":
                j = i + 2
                while j < n and src[j] in "0123456789abcdefABCDEF":
                    j += 1
            else:
                while j < n and (src[j].isdigit() or src[j] == "."):
                    j += 1
            out.append(src[i:j])
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            lw = word.lower()
            if lw in ("and", "or", "not"):
                out.append(f" {lw} ")
            elif lw == "true":
                out.append("1")
            elif lw == "false":
                out.append("0")
            else:
                out.append("_v_" + word)
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=512)
def parse(src):
    try:
        return ast.parse(translate(src).strip(), mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise ExprError(f"syntax error in {src!r}") from e


def _round(x, n=0):
    x = num(x)
    n = int(num(n))
    f = 10 ** n
    r = math.floor(abs(x) * f + 0.5) / f
    r = -r if x < 0 else r
    return int(r) if n <= 0 else r


def _substr(s, start, length=None):
    s = str(s)
    start = int(num(start))
    i = start - 1 if start > 0 else len(s) + start
    i = max(i, 0)
    if length is None:
        return s[i:]
    return s[i:i + int(num(length))]


def _instr(hay, needle, case=0):
    hay, needle = str(hay), str(needle)
    if not truthy(case):
        hay, needle = hay.lower(), needle.lower()
    return hay.find(needle) + 1


def _mod(a, b):
    a, b = num(a), num(b)
    if b == 0:
        raise ExprError("mod by zero")
    r = math.fmod(a, b)
    return r if isinstance(a, float) or isinstance(b, float) else int(r)


def _sqrt(x):
    x = num(x)
    if x < 0:
        raise ExprError("sqrt of a negative number")
    return math.sqrt(x)


FUNCS = {
    "abs": lambda x: abs(num(x)),
    "round": _round,
    "floor": lambda x: math.floor(num(x)),
    "ceil": lambda x: math.ceil(num(x)),
    "mod": _mod,
    "min": lambda *a: min(num(x) for x in a),
    "max": lambda *a: max(num(x) for x in a),
    "sqrt": _sqrt,
    "strlen": lambda s: len(str(s)),
    "substr": _substr,
    "instr": _instr,
    "strreplace": lambda s, a, b="": str(s).replace(str(a), str(b)),
}


def _cmp(a, b, op):
    if is_num(a) and is_num(b) and str(a).strip() != "" and str(b).strip() != "":
        x, y = num(a), num(b)
    else:
        x, y = fmt(a).lower(), fmt(b).lower()
    if isinstance(op, ast.Eq):
        return x == y
    if isinstance(op, ast.NotEq):
        return x != y
    if isinstance(op, ast.Lt):
        return x < y
    if isinstance(op, ast.LtE):
        return x <= y
    if isinstance(op, ast.Gt):
        return x > y
    if isinstance(op, ast.GtE):
        return x >= y
    raise ExprError("unsupported comparison")


def _binop(op, a, b):
    if isinstance(op, ast.MatMult):
        return fmt(a) + fmt(b)
    a, b = num(a), num(b)
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        return a * b
    if isinstance(op, (ast.Div, ast.FloorDiv)):
        if b == 0:
            raise ExprError("division by zero")
        return a / b if isinstance(op, ast.Div) else a // b
    if isinstance(op, ast.Pow):
        # a huge int power holds the gil long enough to freeze the ui
        if abs(b) > MAX_POWER:
            raise ExprError("exponent too large")
        return a ** b
    if isinstance(op, ast.BitAnd):
        return int(a) & int(b)
    if isinstance(op, ast.BitOr):
        return int(a) | int(b)
    if isinstance(op, ast.BitXor):
        return int(a) ^ int(b)
    if isinstance(op, (ast.LShift, ast.RShift)):
        if abs(b) > MAX_POWER:
            raise ExprError("shift too large")
        return int(a) << int(b) if isinstance(op, ast.LShift) else int(a) >> int(b)
    raise ExprError("unsupported operator")


class Evaluator:
    def __init__(self, variables, extra_funcs=None):
        self.vars = variables
        self.funcs = dict(FUNCS)
        if extra_funcs:
            self.funcs.update(extra_funcs)

    def eval(self, src):
        src = str(src).strip()
        if src == "":
            return ""
        return self._ev(parse(src))

    def eval_num(self, v):
        if isinstance(v, (int, float)):
            return v
        s = str(v).strip()
        if s == "":
            return 0
        if is_num(s):
            return num(s)
        return num(self.eval(s))

    def _ev(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str)):
                return node.value
            raise ExprError("bad constant")
        if isinstance(node, ast.Name):
            return self.vars.get(node.id[3:] if node.id.startswith("_v_") else node.id)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return int(all(truthy(self._ev(v)) for v in node.values))
            return int(any(truthy(self._ev(v)) for v in node.values))
        if isinstance(node, ast.UnaryOp):
            v = self._ev(node.operand)
            if isinstance(node.op, ast.Not):
                return int(not truthy(v))
            if isinstance(node.op, ast.USub):
                return -num(v)
            if isinstance(node.op, ast.UAdd):
                return num(v)
            if isinstance(node.op, ast.Invert):
                return ~int(num(v))
        if isinstance(node, ast.BinOp):
            return _binop(node.op, self._ev(node.left), self._ev(node.right))
        if isinstance(node, ast.Compare):
            left = self._ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = self._ev(comp)
                if not _cmp(left, right, op):
                    return 0
                left = right
            return 1
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ExprError("bad function call")
            name = node.func.id[3:] if node.func.id.startswith("_v_") else node.func.id
            fn = self.funcs.get(name.lower())
            if fn is None:
                raise ExprError(f"unknown function {name}()")
            try:
                return fn(*[self._ev(a) for a in node.args])
            except TypeError as e:
                raise ExprError(f"{name}(): {e}") from e
        raise ExprError(f"unsupported expression: {type(node).__name__.lower()}")
