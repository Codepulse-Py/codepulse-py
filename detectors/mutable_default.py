"""Detector 1: mutable default argument.

Signature (§6.4): a function whose default value is a list, dict or set. The
default is created once when ``def`` runs, so every call that mutates it sees
the previous calls' changes.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, is_mutable_value, register, source_of

NAME = "mutable_default"


@register(1, NAME, "Mutable default argument")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        pairs = list(
            zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True)
        )
        pairs += [
            (a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is not None
        ]
        name = getattr(node, "name", "<lambda>")
        for arg, default in pairs:
            if is_mutable_value(default):
                found.append(
                    finding(
                        NAME,
                        default,
                        f"{name}(): parameter '{arg.arg}' defaults to "
                        f"{source_of(source, default)}, which is shared between calls",
                    )
                )
    return found
