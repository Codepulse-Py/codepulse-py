"""Detector 4: indentation scope (exploratory).

Signature (§6.4): a statement whose indentation puts it inside or outside an
if / for / while body other than the one intended. Intent is not visible in
the AST (§8.3), so this detector reports two structural symptoms of a
mis-indented statement and leaves the decision to the behavioural context:

- ``loop_exits_first_pass``: every path through a loop body ends in
  ``return`` or ``break``, so the loop can never run a second time. The classic
  case is ``return False`` indented into the loop instead of after it.
- ``unreachable_after_exit``: a statement directly after ``return``,
  ``break``, ``continue`` or ``raise`` in the same block can never run; it was
  usually meant one level out. Placeholders (``pass``, a bare string or
  ``...``) and a lone half-typed name (``p`` while typing ``print``) are
  ignored: in the 2021 data these come from starter templates and mid-typing
  states, not from indentation.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, register

NAME = "indentation_scope"

EXITS = (ast.Return, ast.Break, ast.Raise, ast.Continue)


def _always_leaves_loop(body: list[ast.stmt]) -> bool:
    """Does every path through ``body`` end in return/break (raise counts too)?"""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, ast.Return | ast.Break | ast.Raise):
        return True
    if isinstance(last, ast.If):
        return _always_leaves_loop(last.body) and _always_leaves_loop(last.orelse)
    return False


def _placeholder(stmt: ast.stmt) -> bool:
    """``pass``, a docstring / ``...``, or a lone name being typed."""
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant | ast.Name)


def _blocks(node: ast.AST):
    for field in ("body", "orelse", "finalbody"):
        block = getattr(node, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            yield block
    for handler in getattr(node, "handlers", []):
        yield handler.body


@register(4, NAME, "Indentation scope", phase="pre-run", exploratory=True)
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For | ast.AsyncFor | ast.While) and _always_leaves_loop(node.body):
            kind = "for" if isinstance(node, ast.For | ast.AsyncFor) else "while"
            found.append(
                finding(
                    NAME,
                    node,
                    f"every path through this {kind} loop ends in return/break, so it never "
                    "runs a second time; a statement may be indented into the loop by mistake",
                    rule="loop_exits_first_pass",
                )
            )
        for block in _blocks(node):
            for i, stmt in enumerate(block):
                if not isinstance(stmt, EXITS):
                    continue
                dead = [s for s in block[i + 1 :] if not _placeholder(s)]
                if dead:
                    word = type(stmt).__name__.lower()
                    found.append(
                        finding(
                            NAME,
                            dead[0],
                            f"line {dead[0].lineno} can never run because it follows '{word}' "
                            f"on line {stmt.lineno} in the same block; it may belong one level out",
                            rule="unreachable_after_exit",
                        )
                    )
                break
    return found
