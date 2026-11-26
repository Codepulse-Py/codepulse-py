"""Detector 6: ``self`` confusion.

Signature (Table 3.3): a method in a class missing ``self``, or a method called
on the class name.

- ``missing_self``: an instance method (not ``@staticmethod`` or
  ``@classmethod``) with no parameters, or whose first parameter is not
  ``self``. Python passes the instance as the first argument, so the call fails
  or the instance lands in the wrong parameter.
- ``called_on_class``: ``Dog.bark()`` where ``bark`` is an instance method of a
  class defined in the same file and the call supplies one argument too few,
  i.e. the instance was left out. ``Parent.__init__(self, ...)`` passes it and
  is not flagged.
"""

from __future__ import annotations

import ast

from detectors.base import Finding, finding, register

NAME = "self_confusion"


def _decorator_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _instance_methods(cls: ast.ClassDef):
    for item in cls.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and not (
            _decorator_names(item) & {"staticmethod", "classmethod"}
        ):
            yield item


def _required_positional(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    positional = fn.args.posonlyargs + fn.args.args
    return len(positional) - len(fn.args.defaults)


@register(6, NAME, "self confusion", phase="post-run")
def detect(tree: ast.Module, source: str) -> list[Finding]:
    found = []
    classes: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = classes.setdefault(node.name, {})
        for fn in _instance_methods(node):
            positional = fn.args.posonlyargs + fn.args.args
            if not positional and fn.args.vararg is None:
                found.append(
                    finding(
                        NAME,
                        fn,
                        f"method {node.name}.{fn.name}() has no 'self' parameter, but Python "
                        "passes the object itself as the first argument",
                        rule="missing_self",
                    )
                )
            elif positional and positional[0].arg != "self":
                found.append(
                    finding(
                        NAME,
                        fn,
                        f"method {node.name}.{fn.name}() takes '{positional[0].arg}' first, "
                        f"so the object is passed into '{positional[0].arg}'; the first "
                        "parameter of a method should be 'self'",
                        rule="missing_self",
                    )
                )
            else:
                methods[fn.name] = fn

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            continue
        cls, method = node.func.value.id, node.func.attr
        fn = classes.get(cls, {}).get(method)
        if fn is None or any(isinstance(a, ast.Starred) for a in node.args) or node.keywords:
            continue
        if len(node.args) == _required_positional(fn) - 1:
            found.append(
                finding(
                    NAME,
                    node,
                    f"{cls}.{method}() is called on the class, so no object is passed as "
                    f"'self'; call it on an object instead (e.g. obj.{method}())",
                    rule="called_on_class",
                )
            )
    return found
