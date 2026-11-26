"""Run the registered detectors on a code state, with a fallback for broken code.

Students' code is often mid-edit and does not parse. ``StructuralAnalyzer``
keeps the last parseable version of each file and, when the current one fails
to parse, reports that version's findings marked ``stale`` instead of nothing.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass, field

from detectors.base import REGISTRY, Finding


@dataclass(frozen=True, slots=True)
class Analysis:
    findings: list[Finding]
    parsed: bool  # did the current source parse?
    stale: bool = False  # findings come from an earlier parseable state
    error: str = ""  # the SyntaxError message when the source did not parse


def parse(source: str) -> tuple[ast.Module | None, str]:
    """(tree, "") on success, (None, error message) if the source does not parse."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # e.g. SyntaxWarning for invalid escapes
        try:
            return ast.parse(source), ""
        except (SyntaxError, ValueError) as e:
            return None, f"{type(e).__name__}: {e}"


def run_detectors(tree: ast.Module, source: str, only: list[str] | None = None) -> list[Finding]:
    names = only or sorted(REGISTRY, key=lambda n: REGISTRY[n].number)
    findings = []
    for name in names:
        findings.extend(REGISTRY[name].fn(tree, source))
    return sorted(findings, key=lambda f: (f.line, f.col, f.detector))


def analyse(source: str, only: list[str] | None = None) -> Analysis:
    """Detect patterns in one source string (no fallback)."""
    tree, error = parse(source)
    if tree is None:
        return Analysis([], parsed=False, error=error)
    return Analysis(run_detectors(tree, source, only), parsed=True)


@dataclass
class StructuralAnalyzer:
    """Per-session analyser that falls back to each file's last parseable state."""

    only: list[str] | None = None
    _last: dict[str, Analysis] = field(default_factory=dict)

    def analyse(self, file: str, source: str) -> Analysis:
        current = analyse(source, self.only)
        if current.parsed:
            self._last[file] = current
            return current
        previous = self._last.get(file)
        if previous is None:
            return current
        return Analysis(previous.findings, parsed=False, stale=True, error=current.error)
