"""Shared types and registry for the AST misconception detectors (Algorithm 3).

A detector is a function ``(tree, source) -> list[Finding]`` registered under a
stable name. Detectors only flag *candidate* structural patterns; whether a
candidate is a misconception is decided later with the behavioural context.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    detector: str  # registry name, e.g. "mutable_default"
    line: int
    col: int
    end_line: int
    message: str
    rule: str = ""  # which signal fired, for detectors with more than one


DetectorFn = Callable[[ast.Module, str], list[Finding]]


# Detection phase (final proposal Table 3.3): a pre-run misconception has a
# complete structural signature before the code runs, so earliness is measured
# for it; a post-run one only shows once a run reveals it.
PHASES = ("pre-run", "post-run")


@dataclass(frozen=True, slots=True)
class Detector:
    number: int  # numbering of Table 3.3
    name: str
    title: str
    phase: str
    fn: DetectorFn
    exploratory: bool = False


REGISTRY: dict[str, Detector] = {}


def register(number: int, name: str, title: str, phase: str, exploratory: bool = False):
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}, not {phase!r}")

    def wrap(fn: DetectorFn) -> DetectorFn:
        if name in REGISTRY:
            raise ValueError(f"detector {name!r} registered twice")
        if any(d.number == number for d in REGISTRY.values()):
            raise ValueError(f"detector number {number} registered twice")
        REGISTRY[name] = Detector(number, name, title, phase, fn, exploratory)
        return fn

    return wrap


def finding(detector: str, node: ast.AST, message: str, rule: str = "") -> Finding:
    return Finding(
        detector,
        node.lineno,
        node.col_offset,
        getattr(node, "end_lineno", None) or node.lineno,
        message,
        rule,
    )


# ---------------------------------------------------------------- AST helpers

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def scopes(tree: ast.Module) -> Iterator[ast.AST]:
    """The module and every function body, each analysed as its own scope."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def local_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Nodes inside ``scope`` without descending into nested functions or classes."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def is_mutable_value(node: ast.AST) -> bool:
    """A new list, dict or set: literal, comprehension or constructor call."""
    if isinstance(node, ast.List | ast.Dict | ast.Set | ast.ListComp | ast.DictComp | ast.SetComp):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"list", "dict", "set", "sorted"}:
            return True
        if isinstance(func, ast.Attribute) and func.attr in {"split", "splitlines", "copy"}:
            return True
    return False


def source_of(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ast.unparse(node)
