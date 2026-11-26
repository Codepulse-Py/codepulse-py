"""Detector 2: variable aliasing.

Signature (§6.4): ``b = a`` where ``a`` holds a list, dict or set (no copy),
then one of the two names is mutated in place and the *other* is read
afterwards. Both names refer to one object, so the read sees the change.

Each scope (module, each function) is read as a straight line of events in
source order. Rebinding either name ends the alias. Only values known to be
new lists/dicts/sets are tracked, so parameters of unknown type are not
flagged; this trades recall for precision.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from detectors.base import Finding, finding, is_mutable_value, local_nodes, register, scopes

NAME = "aliasing"

MUTATORS = {
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",  # list
    "update", "setdefault", "popitem",  # dict
    "add", "discard", "difference_update", "intersection_update",  # set
    "symmetric_difference_update",
}  # fmt: skip


@dataclass
class _Alias:
    alias: str
    original: str
    node: ast.Assign
    mutated_by: str | None = None
    mutated_at: tuple[int, int] | None = None
    mutation_line: int = 0


def _end(node: ast.AST) -> tuple[int, int]:
    return node.end_lineno or node.lineno, node.end_col_offset or 0


def _start(node: ast.AST) -> tuple[int, int]:
    return node.lineno, node.col_offset


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [n for t in target.elts for n in _target_names(t)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _events(scope: ast.AST):
    """(position, kind, payload) in execution order for one scope."""
    events = []
    for node in local_nodes(scope):
        if isinstance(node, ast.Assign):
            # The binding happens after the right-hand side is evaluated.
            for target in node.targets:
                for name in _target_names(target):
                    events.append((_end(node), 1, "bind", (name, node)))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign) and isinstance(node.target, ast.Name):
            kind = "augbind" if isinstance(node, ast.AugAssign) else "bind"
            events.append((_end(node), 1, kind, (node.target.id, node)))
        elif isinstance(node, ast.For | ast.AsyncFor | ast.With | ast.comprehension):
            targets = (
                [i.optional_vars for i in node.items if i.optional_vars]
                if isinstance(node, ast.With)
                else [node.target]
            )
            for t in targets:
                for name in _target_names(t):
                    events.append((_start(t), 1, "bind", (name, None)))
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in MUTATORS
                and isinstance(func.value, ast.Name)
            ):
                events.append((_end(node), 1, "mutate", (func.value.id, node)))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store | ast.Del):
            if isinstance(node.value, ast.Name):
                events.append((_end(node), 2, "mutate", (node.value.id, node)))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            events.append((_start(node), 0, "load", (node.id, node)))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


@register(2, NAME, "Variable aliasing", phase="pre-run")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found = []
    for scope in scopes(tree):
        mutable: set[str] = set()
        aliases: list[_Alias] = []
        reported: set[int] = set()
        for pos, _, kind, (name, node) in _events(scope):
            if kind in ("bind", "augbind"):
                if kind == "augbind" and name in mutable:
                    # `xs += [...]` mutates a list in place.
                    kind = "mutate"
                else:
                    aliases = [a for a in aliases if name not in (a.alias, a.original)]
                    value = getattr(node, "value", None)
                    if isinstance(value, ast.Name) and value.id in mutable and value.id != name:
                        aliases.append(_Alias(name, value.id, node))
                        mutable.add(name)
                    elif value is not None and is_mutable_value(value):
                        mutable.add(name)
                    else:
                        mutable.discard(name)
                    continue
            if kind == "mutate":
                for a in aliases:
                    if name in (a.alias, a.original) and a.mutated_by is None:
                        a.mutated_by, a.mutated_at, a.mutation_line = name, pos, node.lineno
                continue
            # A read of the other name after the mutation sees the change.
            for a in aliases:
                if a.mutated_by is None or id(a) in reported or pos <= a.mutated_at:
                    continue
                other = a.original if a.mutated_by == a.alias else a.alias
                if name == other:
                    reported.add(id(a))
                    found.append(
                        finding(
                            NAME,
                            a.node,
                            f"'{a.alias} = {a.original}' makes both names refer to the same "
                            f"object; changing '{a.mutated_by}' on line {a.mutation_line} also "
                            f"changes '{other}', read on line {node.lineno}",
                        )
                    )
    return found
