"""Detector 3: identity vs equality.

Signature (§6.4): ``is`` / ``is not`` comparing against an int, float or str
literal. Whether such a comparison is True depends on interning and caching
(``x is 256`` vs ``x is 257``), so it means "same object", not "same value".
``x is None``, ``is True`` and ``is False`` are correct and are not flagged.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, register, source_of

NAME = "identity_literal"


def _literal(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        node = node.operand
    return (
        isinstance(node, ast.Constant)
        and type(node.value) in (int, float, str)  # excludes bool and None
    )


@register(3, NAME, "Identity vs equality", phase="pre-run")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        for op, right in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.Is | ast.IsNot) and (_literal(left) or _literal(right)):
                word = "is not" if isinstance(op, ast.IsNot) else "is"
                eq = "!=" if isinstance(op, ast.IsNot) else "=="
                found.append(
                    finding(
                        NAME,
                        node,
                        f"'{source_of(source, node)}' uses '{word}' with a literal; "
                        f"'{word}' tests object identity, '{eq}' tests value",
                    )
                )
                break
            left = right
    return found
