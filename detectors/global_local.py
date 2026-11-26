"""Detector 5: global vs local scope.

Signature (Table 3.3): a function body that reads and assigns a module-level
name without a ``global`` statement. Any assignment makes the name local to the
whole function, so:

- ``unbound_local``: the function reads the name before assigning it (or uses
  ``count += 1``), which raises UnboundLocalError. This is the Table 3.3
  signature.
- ``shadows_global``: the function assigns the name but never reads that local
  copy, while the program reads the module-level variable elsewhere
  (``def finish(): done = True`` with ``while not done:`` at module level).
  The assignment only makes sense if the student expected it to change the
  global. A function that assigns *and* uses its own local of the same name is
  ordinary code and is not flagged: on the 2021 data that broader rule mostly
  hit intentional locals such as ``radius`` or ``word1``.

Parameters, ``global``/``nonlocal`` names and loop / ``with`` / ``except``
targets are not flagged: a loop variable named like a module variable is
almost always an intentional local. Functions nested inside other functions
are skipped, since their names may come from the enclosing function.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, local_nodes, register

NAME = "global_local"


def _names(target: ast.AST) -> list[ast.Name]:
    if isinstance(target, ast.Name):
        return [target]
    if isinstance(target, ast.Tuple | ast.List):
        return [n for t in target.elts for n in _names(t)]
    if isinstance(target, ast.Starred):
        return _names(target.value)
    return []


def _bindings(scope: ast.AST):
    """(name node, binding statement, is_loop_like) for statement-level bindings."""
    for node in local_nodes(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for n in _names(target):
                    yield n, node, False
        elif isinstance(node, ast.AugAssign) or (
            isinstance(node, ast.AnnAssign) and node.value is not None
        ):
            for n in _names(node.target):
                yield n, node, False
        elif isinstance(node, ast.For | ast.AsyncFor):
            for n in _names(node.target):
                yield n, node, True
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars is not None:
                    for n in _names(item.optional_vars):
                        yield n, node, True
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield ast.Name(node.name, lineno=node.lineno, col_offset=node.col_offset), node, True


def _bound_at(binding) -> tuple[int, int]:
    """When the name is bound: after the statement, or at a loop / with target."""
    name, stmt, loop_like = binding
    if loop_like:
        return name.lineno, name.col_offset
    return stmt.end_lineno or stmt.lineno, stmt.end_col_offset or 0


def _functions(tree: ast.Module):
    """Module-level functions and methods of module-level classes."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield item


def _loads(scope: ast.AST) -> dict[str, list[ast.Name]]:
    loads: dict[str, list[ast.Name]] = {}
    for node in local_nodes(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.setdefault(node.id, []).append(node)
    return loads


@register(5, NAME, "Global vs local scope", phase="post-run")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    module_vars = {n.id: stmt.lineno for n, stmt, _ in _bindings(tree)}
    functions = list(_functions(tree))
    local_to = {fn: {n.id for n, _, _ in _bindings(fn)} for fn in functions}
    # Where the module-level value is read: module code, or functions that do not rebind it.
    global_reads = set(_loads(tree))
    for fn in functions:
        global_reads |= set(_loads(fn)) - local_to[fn]
    found = []
    for fn in functions:
        args = fn.args
        params = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
        params |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
        declared = {
            name
            for node in local_nodes(fn)
            if isinstance(node, ast.Global | ast.Nonlocal)
            for name in node.names
        }
        first_bind: dict[str, tuple[ast.AST, bool, tuple[int, int]]] = {}
        for n, stmt, loop_like in sorted(_bindings(fn), key=_bound_at):
            first_bind.setdefault(n.id, (stmt, loop_like, _bound_at((n, stmt, loop_like))))
        loads = _loads(fn)

        for name, (stmt, loop_like, bind_at) in first_bind.items():
            if name not in module_vars or name in params or name in declared:
                continue
            early = [n for n in loads.get(name, []) if (n.lineno, n.col_offset) < bind_at]
            augmented = isinstance(stmt, ast.AugAssign)
            if (early or augmented) and not loop_like:
                at = early[0] if early else stmt
                found.append(
                    finding(
                        NAME,
                        at,
                        f"{fn.name}() assigns '{name}' on line {stmt.lineno}, so '{name}' is "
                        f"local to the whole function; reading it on line {at.lineno} before "
                        f"that raises UnboundLocalError. The module-level '{name}' (line "
                        f"{module_vars[name]}) needs 'global {name}'",
                        rule="unbound_local",
                    )
                )
            elif not loads.get(name) and not loop_like and name in global_reads:
                found.append(
                    finding(
                        NAME,
                        stmt,
                        f"{fn.name}() assigns '{name}' without 'global', which creates a new "
                        f"local variable; the module-level '{name}' (line {module_vars[name]}), "
                        "which the program reads elsewhere, is not changed",
                        rule="shadows_global",
                    )
                )
    return found
