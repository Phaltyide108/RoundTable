"""Reference solution for the `sheet` benchmark task. Used only to check that the
hidden tests are right; it is never copied into a benchmark run."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_CELL = re.compile(r"^([A-Za-z]{1,2})([1-9][0-9]{0,3})$")


class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


def norm(name):
    if not isinstance(name, str):
        raise ValueError("cell name must be text")
    m = _CELL.match(name.strip())
    if not m:
        raise ValueError(f"invalid cell name {name!r}")
    return m.group(1).upper() + m.group(2)


def col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def split(name):
    m = re.match(r"([A-Z]+)(\d+)", name)
    return col_num(m.group(1)), int(m.group(2))


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sort_key(name):
    c, r = split(name)
    return (c, r)


# ---------------------------------------------------------------- parsing

class ParseError(Exception):
    pass


TOKEN = re.compile(r"""\s*(?:
    (?P<num>\d+\.\d*|\.\d+|\d+)|
    (?P<str>"(?:[^"]|"")*")|
    (?P<word>[A-Za-z_][A-Za-z0-9_.]*)|
    (?P<op><=|>=|<>|[-+*/^&=<>(),:])
)""", re.X)


def tokenize(src):
    out, i = [], 0
    while i < len(src):
        if src[i:].strip() == "":
            break
        m = TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ParseError(src[i:])
        i = m.end()
        if m.group("num"):
            out.append(("num", float(m.group("num"))))
        elif m.group("str"):
            out.append(("str", m.group("str")[1:-1].replace('""', '"')))
        elif m.group("word"):
            out.append(("word", m.group("word")))
        else:
            out.append(("op", m.group("op")))
    return out


class Parser:
    PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4}

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, op):
        if self.take() != ("op", op):
            raise ParseError(op)

    def parse(self):
        node = self.expr(0)
        if self.i != len(self.t):
            raise ParseError("trailing")
        return node

    def expr(self, min_prec):
        left = self.unary()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in self.PREC or self.PREC[val] <= min_prec:
                return left
            self.take()
            left = ("bin", val, left, self.expr(self.PREC[val]))

    def unary(self):
        kind, val = self.peek()
        if kind == "op" and val in ("-", "+"):
            self.take()
            return ("neg" if val == "-" else "pos", self.unary())
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            exp = self.unary_pow()
            return ("bin", "^", base, exp)
        return base

    def unary_pow(self):
        kind, val = self.peek()
        if kind == "op" and val in ("-", "+"):
            self.take()
            return ("neg" if val == "-" else "pos", self.unary_pow())
        return self.power()

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", val)
        if kind == "str":
            return ("str", val)
        if kind == "op" and val == "(":
            node = self.expr(0)
            self.expect(")")
            return node
        if kind == "word":
            if self.peek() == ("op", "("):
                self.take()
                args = []
                if self.peek() != ("op", ")"):
                    while True:
                        args.append(self.arg())
                        if self.peek() == ("op", ","):
                            self.take()
                            continue
                        break
                self.expect(")")
                return ("call", val.upper(), args)
            if val.upper() in ("TRUE", "FALSE"):
                return ("bool", val.upper() == "TRUE")
            if re.match(r"^[A-Za-z]+[0-9]+$", val):
                if self.peek() == ("op", ":"):
                    self.take()
                    k2, v2 = self.take()
                    if k2 != "word" or not re.match(r"^[A-Za-z]+[0-9]+$", v2):
                        raise ParseError("range")
                    return ("range", val, v2)
                return ("ref", val)
            return ("name", val)
        raise ParseError(str(val))

    def arg(self):
        return self.expr(0)


def refs_of(node, out):
    kind = node[0]
    if kind == "ref":
        try:
            out.add(norm(node[1]))
        except ValueError:
            pass
    elif kind == "range":
        try:
            a, b = norm(node[1]), norm(node[2])
        except ValueError:
            return
        (c1, r1), (c2, r2) = split(a), split(b)
        for c in range(min(c1, c2), max(c1, c2) + 1):
            for r in range(min(r1, r2), max(r1, r2) + 1):
                out.add(col_name(c) + str(r))
    elif kind == "bin":
        refs_of(node[2], out)
        refs_of(node[3], out)
    elif kind in ("neg", "pos"):
        refs_of(node[1], out)
    elif kind == "call":
        for a in node[2]:
            refs_of(a, out)
    return out


# ---------------------------------------------------------------- values

def out_value(v):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def to_num(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    return Err("#VALUE!")


def to_text(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, int):
        return str(v)
    return v


def truthy(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return Err("#VALUE!")


class Sheet:
    def __init__(self):
        self.raw = {}
        self.ast = {}
        self.deps = {}
        self.cache = {}

    # -------- API
    def set(self, cell, value):
        name = norm(cell)
        old = self.deps.pop(name, set())
        self.raw.pop(name, None)
        self.ast.pop(name, None)
        if value is not None:
            self.raw[name] = value
            if isinstance(value, str) and value.startswith("="):
                try:
                    node = Parser(tokenize(value[1:])).parse()
                    self.ast[name] = node
                    self.deps[name] = refs_of(node, set())
                except (ParseError, RecursionError, IndexError, TypeError):
                    self.ast[name] = ("error", "#ERROR!")
                    self.deps[name] = set()
        del old
        self.cache.clear()

    def formula(self, cell):
        return self.raw.get(norm(cell))

    def get(self, cell):
        return out_value(self._value(norm(cell)))

    def dependents(self, cell):
        target = norm(cell)
        rev = {}
        for c, ds in self.deps.items():
            for d in ds:
                rev.setdefault(d, set()).add(c)
        seen, stack = set(), [target]
        while stack:
            for nxt in rev.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        seen.discard(target)
        return sorted(seen, key=sort_key)

    # -------- evaluation
    def _value(self, name):
        if name in self.cache:
            return self.cache[name]
        order, state, cyclic = [], {name: 1}, set()
        stack, path = [(name, iter(sorted(self.deps.get(name, ()))))], [name]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                path.pop()
                state[node] = 2
                if any(d in cyclic or (isinstance(self.cache.get(d), Err) and self.cache[d].code == "#CYCLE!") for d in self.deps.get(node, ())):
                    cyclic.add(node)
                order.append(node)
                continue
            if nxt in self.cache or state.get(nxt) == 2:
                continue
            if state.get(nxt) == 1:
                cyclic.update(path[path.index(nxt):])
                continue
            state[nxt] = 1
            path.append(nxt)
            stack.append((nxt, iter(sorted(self.deps.get(nxt, ())))))
        for c in order:
            if c in cyclic:
                self.cache[c] = Err("#CYCLE!")
            elif c not in self.ast:
                self.cache[c] = self.raw.get(c)
            else:
                self.cache[c] = self.eval(self.ast[c])
        return self.cache[name]

    def eval(self, node):
        kind = node[0]
        if kind == "error":
            return Err(node[1])
        if kind == "num":
            return node[1]
        if kind == "str":
            return node[1]
        if kind == "bool":
            return node[1]
        if kind == "name":
            return Err("#NAME?")
        if kind == "ref":
            try:
                n = norm(node[1])
            except ValueError:
                return Err("#REF!")
            return self._value(n)
        if kind == "range":
            return Err("#VALUE!")
        if kind == "neg":
            v = to_num(self.eval(node[1]))
            return v if isinstance(v, Err) else -v
        if kind == "pos":
            v = to_num(self.eval(node[1]))
            return v
        if kind == "bin":
            return self.binop(node[1], node[2], node[3])
        if kind == "call":
            return self.call(node[1], node[2])
        return Err("#ERROR!")

    def binop(self, op, ln, rn):
        a = self.eval(ln)
        if isinstance(a, Err):
            return a
        b = self.eval(rn)
        if isinstance(b, Err):
            return b
        if op == "&":
            return to_text(a) + to_text(b)
        if op in ("=", "<>", "<", ">", "<=", ">="):
            return self.compare(op, a, b)
        x, y = to_num(a), to_num(b)
        if isinstance(x, Err):
            return x
        if isinstance(y, Err):
            return y
        try:
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    return Err("#DIV/0!")
                return x / y
            if op == "^":
                r = x ** y
                if isinstance(r, complex):
                    return Err("#VALUE!")
                return r
        except ZeroDivisionError:
            return Err("#DIV/0!")
        except OverflowError:
            return Err("#VALUE!")
        return Err("#ERROR!")

    def compare(self, op, a, b):
        def kind(v):
            if v is None:
                return "empty"
            if isinstance(v, (bool, int, float)):
                return "num"
            return "text"

        ka, kb = kind(a), kind(b)
        if ka == "empty" and kb == "empty":
            x, y = 0, 0
        elif ka == "empty":
            x, y = (0, to_num(b)) if kb == "num" else ("", b.lower())
        elif kb == "empty":
            x, y = (to_num(a), 0) if ka == "num" else (a.lower(), "")
        elif ka != kb:
            return Err("#VALUE!")
        elif ka == "num":
            x, y = to_num(a), to_num(b)
        else:
            x, y = a.lower(), b.lower()
        return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]

    def _flat(self, args):
        """Values for SUM-like functions: ranges and single refs skip empty/text/bool; direct values must be numbers."""
        out = []
        for a in args:
            if a[0] in ("range", "ref"):
                if a[0] == "range":
                    try:
                        cells = sorted(refs_of(a, set()), key=lambda n: (split(n)[1], split(n)[0]))
                        norm(a[1]), norm(a[2])
                    except ValueError:
                        return Err("#REF!")
                else:
                    try:
                        cells = [norm(a[1])]
                    except ValueError:
                        return Err("#REF!")
                for c in cells:
                    v = self._value(c)
                    if isinstance(v, Err):
                        return v
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.append(v)
                continue
            v = self.eval(a)
            if isinstance(v, Err):
                return v
            n = to_num(v)
            if isinstance(n, Err):
                return n
            out.append(n)
        return out

    def call(self, name, args):
        if name in ("SUM", "MIN", "MAX", "AVERAGE", "COUNT"):
            if name == "COUNT":
                return self._count(args)
            vals = self._flat(args)
            if isinstance(vals, Err):
                return vals
            if name == "SUM":
                return sum(vals)
            if name == "MIN":
                return min(vals) if vals else 0
            if name == "MAX":
                return max(vals) if vals else 0
            if not vals:
                return Err("#DIV/0!")
            return sum(vals) / len(vals)
        if name == "IF":
            if len(args) not in (2, 3):
                return Err("#VALUE!")
            c = truthy(self.eval(args[0]))
            if isinstance(c, Err):
                return c
            if c:
                return self.eval(args[1])
            return self.eval(args[2]) if len(args) == 3 else False
        if name == "CONCAT":
            parts = []
            for a in args:
                if a[0] == "range":
                    try:
                        cells = sorted(refs_of(a, set()), key=lambda n: (split(n)[1], split(n)[0]))
                    except ValueError:
                        return Err("#REF!")
                    vals = [self._value(c) for c in cells]
                else:
                    vals = [self.eval(a)]
                for v in vals:
                    t = to_text(v)
                    if isinstance(t, Err):
                        return t
                    parts.append(t)
            return "".join(parts)
        one = {"LEN", "UPPER", "LOWER", "ABS"}
        if name in one:
            if len(args) != 1 or args[0][0] == "range":
                return Err("#VALUE!")
            v = self.eval(args[0])
            if isinstance(v, Err):
                return v
            if name == "ABS":
                n = to_num(v)
                return n if isinstance(n, Err) else abs(n)
            t = to_text(v)
            return len(t) if name == "LEN" else t.upper() if name == "UPPER" else t.lower()
        if name == "ROUND":
            if len(args) != 2:
                return Err("#VALUE!")
            v = to_num(self.eval(args[0]))
            if isinstance(v, Err):
                return v
            d = to_num(self.eval(args[1]))
            if isinstance(d, Err):
                return d
            d = int(d)
            q = Decimal(1).scaleb(-d)
            r = float(Decimal(repr(float(v))).quantize(q, rounding=ROUND_HALF_UP))
            return r
        return Err("#NAME?")

    def _count(self, args):
        n = 0
        for a in args:
            if a[0] in ("range", "ref"):
                try:
                    cells = list(refs_of(a, set())) if a[0] == "range" else [norm(a[1])]
                except ValueError:
                    return Err("#REF!")
                for c in cells:
                    v = self._value(c)
                    if isinstance(v, Err):
                        return v
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        n += 1
                continue
            v = self.eval(a)
            if isinstance(v, Err):
                return v
            if isinstance(v, (int, float)):
                n += 1
        return n
