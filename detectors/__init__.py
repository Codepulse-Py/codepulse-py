"""AST structural pattern detectors (Algorithm 3, final proposal Table 3.3).

    from detectors import analyse, StructuralAnalyzer, REGISTRY

Importing the package registers every detector in ``REGISTRY``.
"""

from detectors import (  # noqa: F401  (importing registers each detector)
    aliasing,
    global_local,
    identity,
    indentation,
    int_division,
    mutable_default,
    self_confusion,
)
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
