"""The formula language of the catalog (cabinet types build their panels from formulas: ``width - 2 * side``).

A closed, small language, written so a Rust port is a line-for-line translation:

* values: numbers (binary64) and booleans; ``true`` / ``false``;
* names: ``width``, ``common.doorGap`` (letters, digits, ``_``, dotted); what a name may be is declared when the formula is compiled;
* ``+ - * /``, unary ``-``, comparisons ``< <= > >= == !=`` (not chained), ``and or not``, ``a if c else b``;
* functions ``min(a, b, ...)``, ``max(a, b, ...)``, ``clamp(x, lo, hi)``, ``round(x)`` / ``round(x, digits)`` (halves away from
  zero, ``numeric.round_half_away``), ``floor(x)``, ``ceil(x)``, ``abs(x)``.

``compile`` parses by hand (precedence climbing) into a typed tree and checks every name and type once, when the catalog loads;
``evaluate`` then only computes. Every error is an ``InvalidInput`` with a stable ``code`` and ``params.at``: the 0-based character
position in the formula the error points at.

Precedence, low to high: ``x if c else y`` < ``or`` < ``and`` < ``not`` < comparison < ``+ -`` < ``* /`` < unary ``-`` < call / atom.
``and`` / ``or`` / ``if`` evaluate only the side they need; ``/`` by zero is an error, never ``inf``.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ..errors import InvalidInput
from ..numeric import round_half_away

NUM = "num"
BOOL = "bool"
Value = float | bool

MAX_LENGTH = 2000      # characters of one formula
MAX_DEPTH = 64         # nesting of the tree (parentheses, operators, calls)
KEYWORDS = ("and", "or", "not", "if", "else", "true", "false")
FUNCTIONS: dict[str, tuple[int, int]] = {      # name -> (fewest, most) arguments, all numbers; the result is a number
    "min": (2, 32), "max": (2, 32), "clamp": (3, 3), "round": (1, 2), "floor": (1, 1), "ceil": (1, 1), "abs": (1, 1),
}
COMPARE = ("<", "<=", ">", ">=", "==", "!=")


@dataclass(frozen=True)
class Token:
    kind: str          # "num", "name", "op", "end"
    text: str
    at: int


@dataclass(frozen=True)
class Node:
    """One node of the tree. ``op``: "num", "bool", "name", "neg", "not", "+", "-", "*", "/", a comparison, "and", "or", "if", "call".
    ``value``: the number of a "num", 1.0 / 0.0 for a "bool"; ``name``: the variable or function; ``args``: the operands (an "if":
    then, condition, else). ``type``: NUM or BOOL."""
    op: str
    at: int
    type: str
    value: float = 0.0
    name: str = ""
    args: tuple["Node", ...] = ()


@dataclass(frozen=True)
class Formula:
    text: str
    tree: Node
    names: tuple[str, ...]      # the variables it reads, sorted

    @property
    def type(self) -> str:
        return self.tree.type


def _error(code: str, message: str, at: int, **params: object) -> InvalidInput:
    return InvalidInput(f"{message} (at {at})", code=code, params={"at": at, **params})


def _tokens(text: str) -> list[Token]:
    out: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
        elif c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == ".":
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            if j < n and (text[j].isalpha() or text[j] == "_" or text[j] == "."):
                raise _error("expr-syntax", f"bad number {text[i:j + 1]!r}", i, found=text[i:j + 1])
            out.append(Token("num", text[i:j], i))
            i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_" or (text[j] == "." and j + 1 < n and (text[j + 1].isalpha() or text[j + 1] == "_"))):
                j += 1
            out.append(Token("name", text[i:j], i))
            i = j
        elif text[i:i + 2] in ("<=", ">=", "==", "!="):
            out.append(Token("op", text[i:i + 2], i))
            i += 2
        elif c in "+-*/(),<>":
            out.append(Token("op", c, i))
            i += 1
        else:
            raise _error("expr-syntax", f"unexpected character {c!r}", i, found=c)
    out.append(Token("end", "", n))
    return out


class _Parser:
    def __init__(self, text: str, names: Mapping[str, str]) -> None:
        self.toks = _tokens(text)
        self.i = 0
        self.names = names
        self.used: set[str] = set()
        self.depth = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def is_(self, text: str) -> bool:
        t = self.peek()
        return t.kind in ("op", "name") and t.text == text

    def expect(self, text: str) -> Token:
        t = self.next()
        if not (t.kind in ("op", "name") and t.text == text):
            raise _error("expr-syntax", f"expected {text!r}, found {t.text or 'the end'!r}", t.at, expected=text, found=t.text or "end")
        return t

    def enter(self, at: int) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise _error("expr-too-deep", f"the formula nests deeper than {MAX_DEPTH}", at, limit=MAX_DEPTH)

    def want(self, node: Node, type: str) -> Node:
        if node.type != type:
            raise _error("expr-type", f"expected a {'number' if type == NUM else 'true/false'} here", node.at, expected=type, got=node.type)
        return node

    # expr := or ('if' or 'else' expr)?
    def expr(self) -> Node:
        self.enter(self.peek().at)
        then = self.or_()
        if self.is_("if"):
            self.next()
            cond = self.want(self.or_(), BOOL)
            self.expect("else")
            other = self.expr()
            if other.type != then.type:
                raise _error("expr-type", "both sides of 'if ... else' must be the same kind of value", other.at, expected=then.type, got=other.type)
            then = Node("if", then.at, then.type, args=(then, cond, other))
        self.depth -= 1
        return then

    def or_(self) -> Node:
        a = self.and_()
        while self.is_("or"):
            t = self.next()
            a = Node("or", t.at, BOOL, args=(self.want(a, BOOL), self.want(self.and_(), BOOL)))
        return a

    def and_(self) -> Node:
        a = self.not_()
        while self.is_("and"):
            t = self.next()
            a = Node("and", t.at, BOOL, args=(self.want(a, BOOL), self.want(self.not_(), BOOL)))
        return a

    def not_(self) -> Node:
        if self.is_("not"):
            t = self.next()
            self.enter(t.at)
            x = Node("not", t.at, BOOL, args=(self.want(self.not_(), BOOL),))
            self.depth -= 1
            return x
        return self.compare()

    def compare(self) -> Node:
        a = self.sum()
        t = self.peek()
        if t.kind == "op" and t.text in COMPARE:
            self.next()
            b = self.sum()
            if t.text in ("==", "!="):
                if a.type != b.type:
                    raise _error("expr-type", "'==' and '!=' compare two values of the same kind", b.at, expected=a.type, got=b.type)
            else:
                self.want(a, NUM)
                self.want(b, NUM)
            n = self.peek()
            if n.kind == "op" and n.text in COMPARE:
                raise _error("expr-syntax", "comparisons do not chain; use 'and'", n.at, found=n.text)
            return Node(t.text, t.at, BOOL, args=(a, b))
        return a

    def sum(self) -> Node:
        a = self.product()
        while self.peek().kind == "op" and self.peek().text in "+-":
            t = self.next()
            a = Node(t.text, t.at, NUM, args=(self.want(a, NUM), self.want(self.product(), NUM)))
        return a

    def product(self) -> Node:
        a = self.unary()
        while self.peek().kind == "op" and self.peek().text in "*/":
            t = self.next()
            a = Node(t.text, t.at, NUM, args=(self.want(a, NUM), self.want(self.unary(), NUM)))
        return a

    def unary(self) -> Node:
        if self.is_("-"):
            t = self.next()
            self.enter(t.at)
            x = Node("neg", t.at, NUM, args=(self.want(self.unary(), NUM),))
            self.depth -= 1
            return x
        return self.atom()

    def atom(self) -> Node:
        t = self.next()
        if t.kind == "num":
            return Node("num", t.at, NUM, value=float(t.text))
        if t.kind == "op" and t.text == "(":
            x = self.expr()
            self.expect(")")
            return x
        if t.kind == "name":
            if t.text in ("true", "false"):
                return Node("bool", t.at, BOOL, value=1.0 if t.text == "true" else 0.0)
            if t.text in KEYWORDS:
                raise _error("expr-syntax", f"{t.text!r} cannot start a value", t.at, found=t.text)
            if self.is_("("):
                return self.call(t)
            if t.text in FUNCTIONS:
                raise _error("expr-syntax", f"{t.text!r} is a function: write {t.text}(...)", t.at, found=t.text)
            kind = self.names.get(t.text)
            if kind is None:
                raise _error("expr-unknown-name", f"unknown name {t.text!r}", t.at, name=t.text)
            self.used.add(t.text)
            return Node("name", t.at, kind, name=t.text)
        raise _error("expr-syntax", f"expected a value, found {t.text or 'the end'!r}", t.at, expected="value", found=t.text or "end")

    def call(self, t: Token) -> Node:
        if t.text not in FUNCTIONS:
            raise _error("expr-unknown-function", f"unknown function {t.text!r}", t.at, name=t.text)
        self.expect("(")
        args: list[Node] = []
        if not self.is_(")"):
            args.append(self.want(self.expr(), NUM))
            while self.is_(","):
                self.next()
                args.append(self.want(self.expr(), NUM))
        self.expect(")")
        lo, hi = FUNCTIONS[t.text]
        if not lo <= len(args) <= hi:
            raise _error("expr-arity", f"{t.text}() takes {lo}{'' if lo == hi else f' to {hi}'} values, got {len(args)}", t.at,
                         name=t.text, n=len(args), fewest=lo, most=hi)
        return Node("call", t.at, NUM, name=t.text, args=tuple(args))


def compile(text: str, names: Mapping[str, str], want: str | None = None) -> Formula:
    """Parse ``text`` and check it against ``names`` (variable -> NUM / BOOL). ``want``: the type the whole formula must have."""
    if len(text) > MAX_LENGTH:
        raise _error("expr-too-long", f"the formula is longer than {MAX_LENGTH} characters", MAX_LENGTH, limit=MAX_LENGTH)
    if not text.strip():
        raise _error("expr-syntax", "the formula is empty", 0, expected="value", found="end")
    p = _Parser(text, names)
    tree = p.expr()
    end = p.peek()
    if end.kind != "end":
        raise _error("expr-syntax", f"unexpected {end.text!r} after the formula", end.at, found=end.text)
    if want is not None:
        p.want(tree, want)
    return Formula(text, tree, tuple(sorted(p.used)))


def _num(n: Node, env: Mapping[str, Value]) -> float:
    v = _eval(n, env)
    return float(v)


def _eval(n: Node, env: Mapping[str, Value]) -> Value:
    op = n.op
    if op == "num":
        return n.value
    if op == "bool":
        return n.value != 0.0
    if op == "name":
        if n.name not in env:
            raise _error("expr-missing-value", f"no value for {n.name!r}", n.at, name=n.name)
        v = env[n.name]
        if (n.type == BOOL) != isinstance(v, bool):
            raise _error("expr-type", f"{n.name!r} has a value of the wrong kind", n.at, expected=n.type, got=BOOL if isinstance(v, bool) else NUM)
        return v if isinstance(v, bool) else float(v)
    if op == "neg":
        return -_num(n.args[0], env)
    if op == "not":
        return not _eval(n.args[0], env)
    if op == "and":
        return bool(_eval(n.args[0], env)) and bool(_eval(n.args[1], env))
    if op == "or":
        return bool(_eval(n.args[0], env)) or bool(_eval(n.args[1], env))
    if op == "if":
        then, cond, other = n.args
        return _eval(then, env) if _eval(cond, env) else _eval(other, env)
    if op in ("==", "!="):
        a, b = _eval(n.args[0], env), _eval(n.args[1], env)
        same = a == b
        return same if op == "==" else not same
    if op in ("<", "<=", ">", ">="):
        a, b = _num(n.args[0], env), _num(n.args[1], env)
        return a < b if op == "<" else a <= b if op == "<=" else a > b if op == ">" else a >= b
    if op in ("+", "-", "*", "/"):
        a, b = _num(n.args[0], env), _num(n.args[1], env)
        if op == "/":
            if b == 0.0:
                raise _error("expr-division-by-zero", "division by zero", n.at)
            return a / b
        return a + b if op == "+" else a - b if op == "-" else a * b
    xs = [_num(a, env) for a in n.args]      # a call
    name = n.name
    if name == "min":
        return min(xs)
    if name == "max":
        return max(xs)
    if name == "clamp":
        x, lo, hi = xs
        if lo > hi:
            raise _error("expr-clamp-range", "clamp(x, lo, hi) needs lo <= hi", n.at, lo=lo, hi=hi)
        return min(max(x, lo), hi)
    if name == "round":
        digits = xs[1] if len(xs) > 1 else 0.0
        if digits != math.floor(digits) or not 0.0 <= digits <= 9.0:
            raise _error("expr-round-digits", "round(x, digits) needs a whole number of digits from 0 to 9", n.at, digits=digits)
        return round_half_away(xs[0], int(digits))
    if name == "floor":
        return float(math.floor(xs[0]))
    if name == "ceil":
        return float(math.ceil(xs[0]))
    return abs(xs[0])


def evaluate(formula: Formula, env: Mapping[str, Value]) -> Value:
    """The value of ``formula`` with the variables of ``env`` (numbers as floats, booleans as bools)."""
    return _eval(formula.tree, env)


def run(text: str, env: Mapping[str, Value], want: str | None = None) -> Value:
    """``compile`` with the names (and types) of ``env``, then ``evaluate``: for checks and the golden cases."""
    names = {k: BOOL if isinstance(v, bool) else NUM for k, v in env.items()}
    return evaluate(compile(text, names, want), env)
