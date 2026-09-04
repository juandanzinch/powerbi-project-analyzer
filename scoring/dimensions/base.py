"""
Base class for all scoring dimensions.

Provides common interface and utility methods for penalty/bonus application.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class DimensionScore:
    """Structured score for a single dimension (re-exported from engine)."""
    name: str
    score: int
    weight: float
    weighted: float
    issues: List[Any]
    bonuses_applied: List[str]
    penalties_applied: List[str]
    breakdown: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        # Convert Issue objects to dicts if they have to_dict method
        issues_list = []
        for issue in self.issues:
            if hasattr(issue, 'to_dict'):
                issues_list.append(issue.to_dict())
            else:
                # Fallback: try to convert manually
                issues_list.append({
                    "severity": getattr(issue, 'severity', 'UNKNOWN'),
                    "dimension": getattr(issue, 'dimension', 'UNKNOWN'),
                    "code": getattr(issue, 'code', ''),
                    "message": getattr(issue, 'message', ''),
                    "affected": getattr(issue, 'affected', []),
                    "recommendation": getattr(issue, 'recommendation', '')
                })
        
        critical_count = sum(1 for i in self.issues if getattr(i, 'severity', '') == 'CRITICAL')
        warning_count = sum(1 for i in self.issues if getattr(i, 'severity', '') == 'WARNING')
        
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "weighted": self.weighted,
            "issues": issues_list,
            "bonuses_applied": self.bonuses_applied,
            "penalties_applied": self.penalties_applied,
            "breakdown": self.breakdown,
            "critical_issues_count": critical_count,
            "warnings_count": warning_count
        }


class BaseDimension(ABC):
    """
    Base class for all scoring dimensions.
    
    Subclasses implement calculate() to return DimensionScore.
    """
    
    def __init__(self, data: Dict[str, Any], rules: Dict[str, Any], weight: float = 1.0):
        """
        Initialize dimension scorer.
        
        Args:
            data: Parsed JSON data (tables, relationships, measures, pages, etc)
            rules: Rules from rules.yaml for this dimension
            weight: Weight from scoring.weights (e.g., 0.35 for model)
        """
        self.data = data
        self.rules = rules
        self.weight = weight
        
        self.score = 100
        self.issues: List[Any] = []
        self.bonuses_applied: List[str] = []
        self.penalties_applied: List[str] = []
        self.breakdown: Dict[str, int] = {}
    
    @abstractmethod
    def calculate(self) -> DimensionScore:
        """
        Calculate dimension score and return structured result.
        
        Must be implemented by subclasses.
        """
        raise NotImplementedError
    
    # ========================================================================
    # Utility Methods for Penalty/Bonus Application
    # ========================================================================
    
    def _apply_penalty(
        self,
        key: str,
        value: int,
        label: str,
        affected: Optional[List[str]] = None,
        severity: str = "WARNING"
    ) -> None:
        """
        Apply a penalty and create associated Issue.
        
        Args:
            key: Rule key from rules.yaml (e.g., "no_relationships")
            value: Points to subtract
            label: Human-readable label from rules.yaml
            affected: List of affected table/measure names
            severity: CRITICAL | WARNING | INFO
        """
        if value <= 0:
            return
        
        self.score -= value
        self.penalties_applied.append(key)
        self.breakdown[key] = -value
        
        # Create Issue (will be populated with code by engine)
        # Note: code generation happens at engine level for unique IDs
        from ..engine import Issue
        
        issue = Issue(
            severity=severity,
            dimension=self.__class__.__name__.replace("Dimension", "").upper(),
            code="",  # Will be filled by engine
            message=label,
            affected=affected or [],
            recommendation=self._get_recommendation(key)
        )
        self.issues.append(issue)
    
    def _apply_bonus(self, key: str, value: int, label: str) -> None:
        """
        Apply a bonus and track it.
        
        Args:
            key: Rule key from rules.yaml
            value: Points to add
            label: Human-readable label
        """
        if value <= 0:
            return
        
        self.score += value
        self.bonuses_applied.append(key)
        self.breakdown[key] = value
    
    def _get_recommendation(self, key: str) -> str:
        """Get recommendation text for a penalty key."""
        recommendations = {
            "no_relationships": "Define relationships between fact and dimension tables.",
            "isolated_tables": "Review isolated tables and establish connections to the main model.",
            "no_fact_table": "Identify or define at least one fact table with numeric measures.",
            "string_keys": "Replace string-typed relationship keys with integer surrogate keys.",
            "calculated_columns_in_facts": "Move calculations from fact tables to dimensions or measures.",
            "many_to_many": "Use bridge tables or reconsider relationship design for many-to-many scenarios.",
            "bidirectional": "Validate bidirectional filtering; consider unidirectional for clarity.",
            "inactive_relationships": "Document inactive relationships or remove them if unused.",
            
            "filter_over_full_table": "Use CALCULATETABLE or column-based filters instead of FILTER() over tables.",
            "no_var_in_complex_measure": "Use VAR for intermediate calculations to prevent repeated evaluation.",
            "nested_iterators": "Avoid nesting SUMX/AVERAGEX; refactor with helper measures.",
            "measure_without_format": "Add explicit formatString property (e.g., '0.00' for currency).",
            "duplicate_logic": "Consolidate duplicate measure logic into a base measure.",
            "measures_outside_table": "Move all measures to a dedicated _Measures or Calculations table.",
            "measures_outside_dedicated_table": "Move all measures to a dedicated _Measures or Calculations table so model logic stays centralized.",
            
            "visuals_per_page": "Reduce visual density; consider splitting into multiple pages or drill-through.",
            "slicers_on_fact_columns": "Bind slicers to dimension columns instead of fact table columns.",
            "hidden_visuals": "Remove hidden visuals or explain why they are retained.",
            
            "no_rls_defined": "Implement RLS roles for data security.",
            "naming_violations": "Follow naming convention: fact_*, dim_*, bridge_*, _calc.",
            "no_description_on_measures": "Add descriptions to measures for documentation.",
        }
        
        return recommendations.get(key, "Review this item for improvement.")
    
    def _clamp_score(self, min_val: int = 0, max_val: int = 100) -> None:
        """Clamp score to valid range."""
        self.score = max(min_val, min(max_val, self.score))
    
    def _apply_ceiling(self, ceiling: int) -> None:
        """Apply maximum score ceiling (e.g., for schema type)."""
        self.score = min(self.score, ceiling)
