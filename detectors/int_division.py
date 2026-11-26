"""Detector 7: integer vs float division.

Signature (Table 3.3): a ``/`` between integer operands used in an index,
range or count context. ``/`` always returns a float in Python 3 (``7 / 2 ==
3.5``), so it fails, or misbehaves, wherever an int is required:

- an index or slice bound: ``xs[len(xs) / 2]``;
- ``range()``, ``randint()`` and ``randrange()`` arguments;
- a repetition count: ``"*" * (n / 2)``, ``[0] * (size / 2)``.

Not flagged: ``//``; a division wrapped in a call such as ``int(n / 2)`` or
``round(n / 2)``; a division with a float operand (``n / 2.0``, ``float(n) /
2``), where a float is clearly intended.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, register, source_of

NAME = "int_division"

INT_CALLS = {"range", "randint", "randrange"}
SEQUENCE_LITERALS = (ast.List, ast.Tuple, ast.ListComp)


def _floaty(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return True
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
    )


def _divisions(expr: ast.AST):
    """Unwrapped ``/`` nodes in an expression that must evaluate to an int."""
    stack = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div) and not (_floaty(node.left) or _floaty(node.right)):
                yield node
            stack.extend([node.left, node.right])
        elif isinstance(node, ast.UnaryOp):
            stack.append(node.operand)
        # Calls (int(), round(), len() ...), subscripts and names end the search.


def _sequence(node: ast.AST) -> bool:
    return isinstance(node, SEQUENCE_LITERALS) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _contexts(tree: ast.Module):
    """(expression that must be an int, description of where it is used)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                for part in (node.slice.lower, node.slice.upper, node.slice.step):
                    if part is not None:
                        yield part, "a slice bound"
            else:
                yield node.slice, "an index"
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in INT_CALLS:
                for arg in node.args:
                    yield arg, f"{name}()"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            if _sequence(node.left):
                yield node.right, "a repetition count"
            elif _sequence(node.right):
                yield node.left, "a repetition count"


@register(7, NAME, "Integer vs float division", phase="pre-run")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found, seen = [], set()
    for expr, where in _contexts(tree):
        for div in _divisions(expr):
            if id(div) in seen:
                continue
            seen.add(id(div))
            found.append(
                finding(
                    NAME,
                    div,
                    f"'{source_of(source, div)}' uses '/', which always gives a float "
                    f"(7 / 2 == 3.5), but {where} needs an int; use '//' or int()",
                )
            )
    return found
