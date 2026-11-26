"""AST structural pattern detectors (Algorithm 3, §6.4).

    from detectors import analyse, StructuralAnalyzer, REGISTRY

Importing the package registers every detector in ``REGISTRY``.
"""

from detectors import aliasing, identity, indentation, mutable_default  # noqa: F401  (register)
from detectors.analyzer import Analysis, StructuralAnalyzer, analyse, run_detectors
from detectors.base import REGISTRY, Detector, Finding

__all__ = [
    "REGISTRY",
    "Analysis",
    "Detector",
    "Finding",
    "StructuralAnalyzer",
    "analyse",
    "run_detectors",
]
