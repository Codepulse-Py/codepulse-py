"""Inject a misconception into real student code with a minimal text edit.

Each injector takes a parseable code state that does *not* show the
misconception and returns the edits that introduce it, in the student's own
code and naming. Edits are ``(offset, delete, insert)`` on the current text,
applied in order. The result is checked with the same detector the real data
is mined with, so a synthetic example matches the structural signature
exactly (Table 3.3).

| Misconception    | Injection                                                     |
|------------------|---------------------------------------------------------------|
| mutable_default  | a repeatedly-called function's ``acc = []`` moved into a default; |
|                  | fallback: a new ``history=[]`` parameter it appends to         |
| aliasing         | ``alias = xs`` inserted, an ``xs`` mutation retargeted to it   |
| identity_literal | ``==`` / ``!=`` against a literal turned into ``is`` / ``is not`` |
| self_confusion   | ``self`` removed from a method, or ``obj.m()`` -> ``Cls.m()``  |
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass

from detectors import analyse
from detectors.analyzer import parse
from detectors.base import local_nodes, scopes

Edit = tuple[int, str, str]  # (offset, delete, insert)


@dataclass(frozen=True)
class Injection:
    misconception: str
    rule: str  # detector rule that fires, "" for single-rule detectors
    method: str  # how it was injected, e.g. "moved_local" or "accumulator_param"
    edits: list[Edit]
    note: str  # human-readable description, e.g. "`total == 0` -> `total is 0`"


# ---------------------------------------------------------------- positions


def _line_starts(source: str) -> list[int]:
    starts, pos = [0], 0
    for line in source.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts


class Positions:
    """Convert ast (line, utf-8 byte column) positions to string offsets."""

    def __init__(self, source: str):
        self.source = source
        self.starts = _line_starts(source)
        self.lines = source.splitlines(keepends=True)

    def offset(self, line: int, col_bytes: int) -> int:
        text = self.lines[line - 1] if line - 1 < len(self.lines) else ""
        col = len(text.encode()[:col_bytes].decode(errors="ignore"))
        return self.starts[line - 1] + col

    def start(self, node: ast.AST) -> int:
        return self.offset(node.lineno, node.col_offset)

    def end(self, node: ast.AST) -> int:
        return self.offset(node.end_lineno, node.end_col_offset)


def apply(source: str, edits: list[Edit]) -> str:
    for offset, delete, insert in edits:
        assert source[offset : offset + len(delete)] == delete, (offset, delete)
        source = source[:offset] + insert + source[offset + len(delete) :]
    return source


def _names_in(tree: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        a.arg for a in ast.walk(tree) if isinstance(a, ast.arg)
    }


# ---------------------------------------------------------------- injectors


def _identity(tree, source, rng):
    pos, options = Positions(source), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        op, right = node.ops[0], node.comparators[0]
        if not isinstance(op, ast.Eq | ast.NotEq):
            continue
        sides = (node.left, right)
        if not any(isinstance(s, ast.Constant) and type(s.value) in (int, str) for s in sides):
            continue
        lo, hi = pos.end(node.left), pos.start(right)
        token = "==" if isinstance(op, ast.Eq) else "!="
        i = source.find(token, lo, hi)
        if i < 0:
            continue
        word = "is" if token == "==" else "is not"
        before = "" if source[i - 1 : i].isspace() else " "
        after = "" if source[i + 2 : i + 3].isspace() else " "
        options.append(
            (
                "eq_to_is",
                [(i, token, f"{before}{word}{after}")],
                f"`{token}` -> `{word}` on line {node.lineno}",
            )
        )
    return "", options


def _called_repeatedly(tree: ast.Module, name: str) -> bool:
    """Is ``name`` called at two or more sites, inside a loop, or recursively?

    A mutable default only misbehaves when the function runs more than once; a
    default on a ``main()`` called once is harmless and would be labelled NONE
    under the codebook (Appendix A).
    """
    calls, in_loop = 0, False
    for node in ast.walk(tree):
        is_loop = isinstance(node, ast.For | ast.While)
        for sub in ast.walk(node) if is_loop or isinstance(node, ast.Module) else ():
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == name:
                if is_loop:
                    in_loop = True
                else:
                    calls += 1
    return calls >= 2 or in_loop


def _mutable_default(tree, source, rng):
    pos, options = Positions(source), []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.args.vararg or fn.args.kwarg:
            continue
        if not _called_repeatedly(tree, fn.name):
            continue
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
        for stmt in fn.body:
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.List | ast.Dict)
                and not (stmt.value.elts if isinstance(stmt.value, ast.List) else stmt.value.keys)
            ):
                continue
            name = stmt.targets[0].id
            if name in params or stmt is fn.body[-1]:
                continue
            # The line holding the assignment, including its newline.
            line_start = pos.starts[stmt.lineno - 1]
            line_end = pos.starts[stmt.end_lineno]
            if source[line_start:line_end].strip() != ast.get_source_segment(source, stmt):
                continue  # something else shares the line
            literal = ast.get_source_segment(source, stmt.value)
            args = fn.args.args
            if args:
                close = source.find(")", pos.end(args[-1]))
                insert = f", {name}={literal}"
            else:
                close = source.find(")", source.find("(", pos.start(fn)))
                insert = f"{name}={literal}"
            if close < 0 or close > line_start:
                continue
            # Delete the body line first (it is after the header), then extend the header.
            edits = [(line_start, source[line_start:line_end], ""), (close, "", insert)]
            note = f"{fn.name}(): local `{name} = {literal}` moved into a default"
            options.append(("moved_local", edits, note))
    return "", options + _accumulator_param(tree, source, rng, pos)


def _accumulator_param(tree, source, rng, pos):
    """Fallback when no function has a local accumulator to move: give a repeatedly
    called function a new ``history=[]`` parameter that it appends to.

    Less grounded than ``moved_local`` (two lines are invented), so items record
    the method and are judged separately in the real-vs-synthetic checks (#75).
    """
    options, taken = [], _names_in(tree)
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.args.vararg or fn.args.kwarg:
            continue
        params = [a for a in fn.args.args if a.arg not in ("self", "cls")]
        if not params or fn.args.defaults or not _called_repeatedly(tree, fn.name):
            continue
        first = fn.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if len(fn.body) == 1:
                continue
            first = fn.body[1]  # keep a docstring first
        if first.lineno == fn.lineno:
            continue  # one-line function body
        acc = rng.choice(
            [
                n
                for n in ("history", "seen", "values", "calls", "results", "saved")
                if n not in taken
            ]
            or [f"{params[0].arg}_list"]
        )
        line_start = pos.starts[first.lineno - 1]
        indent = source[line_start : pos.start(first)]
        close = source.find(")", pos.end(fn.args.args[-1]))
        if close < 0 or close > line_start or indent.strip():
            continue
        edits = [
            (line_start, "", f"{indent}{acc}.append({params[0].arg})\n"),
            (close, "", f", {acc}=[]"),
        ]
        note = f"{fn.name}(): new `{acc}=[]` parameter appended to on each call"
        options.append(("accumulator_param", edits, note))
    return options


def _aliasing(tree, source, rng):
    pos, options = Positions(source), []
    taken = _names_in(tree)
    for scope in scopes(tree):
        body = scope.body
        for i, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.List | ast.Dict | ast.ListComp)
            ):
                continue
            xs = stmt.targets[0].id
            later = body[i + 1 :]
            mutation, method = None, ""
            for node in (n for s in later for n in ast.walk(s)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == xs
                    and node.func.attr in {"append", "extend", "insert", "remove", "pop", "sort"}
                ):
                    mutation, method = node.func.value, node.func.attr
                    break
            if mutation is None:
                continue
            reads_after = [
                n
                for n in local_nodes(scope)
                if isinstance(n, ast.Name)
                and n.id == xs
                and isinstance(n.ctx, ast.Load)
                and (n.lineno, n.col_offset) > (mutation.end_lineno, mutation.end_col_offset)
            ]
            if not reads_after:
                continue
            choices = [f"{xs}2", f"new_{xs}", f"{xs}_copy", "temp", "backup", f"old_{xs}"]
            alias = rng.choice([c for c in choices if c not in taken] or [f"{xs}_b"])
            line_end = pos.starts[stmt.end_lineno]
            if source[line_end - 1 : line_end] != "\n":
                continue
            indent = source[pos.starts[stmt.lineno - 1] : pos.start(stmt)]
            m = pos.start(mutation)
            # Retarget the mutation first (it is later in the text), then insert the alias line.
            edits = [(m, xs, alias), (line_end, "", f"{indent}{alias} = {xs}\n")]
            note = f"`{alias} = {xs}` added; `{xs}.{method}()` now called on `{alias}`"
            options.append(("alias_then_mutate", edits, note))
    return "", options


def _self(tree, source, rng):
    pos, options = Positions(source), []
    classes = {c.name: c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
    for cls in classes.values():
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef) or fn.decorator_list or not fn.args.args:
                continue
            first = fn.args.args[0]
            if first.arg != "self":
                continue
            start = pos.start(first)
            rest = fn.args.args[1:]
            end = pos.start(rest[0]) if rest else pos.end(first)
            options.append(
                (
                    "remove_self",
                    [(start, source[start:end], "")],
                    f"`self` removed from {cls.name}.{fn.name}()",
                )
            )
    missing = options
    # obj.m() -> Cls.m() where obj = Cls(...)
    calls = []
    instances = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in classes
        ):
            instances[node.targets[0].id] = node.value.func.id
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in instances
        ):
            cls = instances[node.func.value.id]
            methods = {
                f.name
                for f in classes[cls].body
                if isinstance(f, ast.FunctionDef) and f.args.args and f.args.args[0].arg == "self"
            }
            if node.func.attr in methods:
                obj = node.func.value
                calls.append(
                    (
                        "call_on_class",
                        [(pos.start(obj), obj.id, cls)],
                        f"`{obj.id}.{node.func.attr}()` -> `{cls}.{node.func.attr}()`",
                    )
                )
    return "both", (missing, calls)


INJECTORS = {
    "mutable_default": _mutable_default,
    "aliasing": _aliasing,
    "identity_literal": _identity,
    "self_confusion": _self,
}
MISCONCEPTIONS = tuple(INJECTORS)


# Injections that only edit what the student wrote; the rest invent lines.
GROUNDED = {"moved_local", "alias_then_mutate", "eq_to_is", "remove_self", "call_on_class"}


def inject(
    misconception: str, source: str, rng: random.Random, methods: set[str] | None = None
) -> Injection | None:
    """One random injection of ``misconception`` into ``source``, or None if none applies.

    The seed must parse and must not already show the misconception; the
    result must parse and must show it. ``methods`` restricts which injection
    methods may be used.
    """
    tree, _ = parse(source)
    if tree is None or analyse(source, only=[misconception]).findings:
        return None
    kind, options = INJECTORS[misconception](tree, source, rng)
    if kind == "both":
        missing, calls = options
        groups = [("missing_self", missing), ("called_on_class", calls)]
        groups = [g for g in groups if g[1]]
        if not groups:
            return None
        rule, options = rng.choice(groups)
    else:
        rule = ""
    if methods is not None:
        options = [o for o in options if o[0] in methods]
    rng.shuffle(options)
    for method, edits, note in options:
        result = apply(source, edits)
        found = analyse(result, only=[misconception])
        if found.parsed and any(f.rule == rule or not rule for f in found.findings):
            return Injection(misconception, rule or found.findings[0].rule, method, edits, note)
    return None
