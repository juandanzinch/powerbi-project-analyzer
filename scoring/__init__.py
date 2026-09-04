"""
Power BI Scoring Framework.

Comprehensive analysis engine for Power BI models, reports, and governance.

Modules:
- engine: Main orchestrator and data classes
- rules.yaml: Configuration (single source of truth)
- dimensions/: Individual dimension scorers (model, DAX, report, governance)
"""

from .engine import ScoringEngine, ScoringResult, DimensionScore, Issue

__version__ = "1.0.0"
__author__ = "Power BI Analysis Framework"

__all__ = [
    "ScoringEngine",
    "ScoringResult",
    "DimensionScore",
    "Issue"
]
