#!/usr/bin/env python3
"""
Scoring Engine for Power BI Models, Reports and Governance.

Purpose:
- Orchestrates all scoring dimensions (model, DAX, report, governance)
- Loads rules from rules.yaml (single source of truth)
- Reads intermediate JSON outputs from the parsing pipeline
- Calculates weighted scores with issue tracking
- Generates comprehensive ScoringResult with audit trail

Architecture:
- ScoringEngine: Orchestrator, reads YAML and JSONs
- DimensionScore: Structured result per dimension
- Issue: Granular problem with code, severity, affected items
- ScoringResult: Complete score output with grades and metadata
"""

import json
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Import dimension scorers
from .dimensions import (
    ModelHealthDimension,
    DAXQualityDimension,
    ReportDesignDimension,
    GovernanceDimension
)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Issue:
    """Granular issue with audit trail for CI/CD integration."""
    severity: str           # CRITICAL | WARNING | INFO
    dimension: str          # MODEL | DAX | REPORT | GOVERNANCE
    code: str               # Unique identifier: M001, D003, R005, G002
    message: str            # Human-readable description
    affected: List[str]     # Names of affected tables/measures/pages
    recommendation: str     # Actionable fix
    
    def __post_init__(self):
        """Validate severity levels."""
        valid_severities = {"CRITICAL", "WARNING", "INFO"}
        if self.severity not in valid_severities:
            raise ValueError(f"Invalid severity: {self.severity}. Must be one of {valid_severities}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "severity": self.severity,
            "dimension": self.dimension,
            "code": self.code,
            "message": self.message,
            "affected": self.affected,
            "recommendation": self.recommendation
        }


@dataclass
class DimensionScore:
    """Structured score for a single dimension."""
    name: str                       # MODEL | DAX | REPORT | GOVERNANCE
    score: int                      # 0-100
    weight: float                   # From rules.yaml (e.g., 0.35 for model)
    weighted: float                 # score * weight
    issues: List[Issue]             # All issues in this dimension
    bonuses_applied: List[str]      # Names of bonuses that fired
    penalties_applied: List[str]    # Names of penalties that fired
    breakdown: Dict[str, int]       # Detailed breakdown: penalty_name -> -value
    
    @property
    def critical_issues(self) -> List[Issue]:
        """Filter only CRITICAL issues."""
        return [i for i in self.issues if i.severity == "CRITICAL"]
    
    @property
    def warnings(self) -> List[Issue]:
        """Filter only WARNING issues."""
        return [i for i in self.issues if i.severity == "WARNING"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "weighted": self.weighted,
            "issues": [issue.to_dict() for issue in self.issues],
            "bonuses_applied": self.bonuses_applied,
            "penalties_applied": self.penalties_applied,
            "breakdown": self.breakdown,
            "critical_issues_count": len(self.critical_issues),
            "warnings_count": len(self.warnings)
        }


@dataclass
class ScoringResult:
    """Complete scoring result with audit trail."""
    global_score: int                           # 0-100
    grade: str                                  # A/B/C/D/F
    dimensions: Dict[str, DimensionScore]       # Score per dimension
    issues: List[Issue]                         # All issues across dimensions
    metadata: Dict[str, Any]                    # Version, timestamp, file analyzed
    breakdown: Dict[str, Any] = field(default_factory=dict)  # Audit trail
    
    @property
    def critical_count(self) -> int:
        """Count critical issues across all dimensions."""
        return sum(1 for i in self.issues if i.severity == "CRITICAL")
    
    @property
    def warning_count(self) -> int:
        """Count warning issues across all dimensions."""
        return sum(1 for i in self.issues if i.severity == "WARNING")
    
    @property
    def info_count(self) -> int:
        """Count info issues across all dimensions."""
        return sum(1 for i in self.issues if i.severity == "INFO")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "global_score": self.global_score,
            "grade": self.grade,
            "dimensions": {
                name: score.to_dict()
                for name, score in self.dimensions.items()
            },
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata,
            "breakdown": self.breakdown,
            "summary": {
                "critical_count": self.critical_count,
                "warning_count": self.warning_count,
                "info_count": self.info_count,
                "total_issues": len(self.issues)
            }
        }


# ============================================================================
# Scoring Engine
# ============================================================================

class ScoringEngine:
    """
    Main orchestrator for Power BI scoring.
    
    Workflow:
    1. __init__: Load rules.yaml once
    2. score(): Read JSONs → calculate dimensions → apply weights → return result
    """
    
    def __init__(self, rules_path: str):
        """
        Initialize engine with rules.yaml.
        
        Args:
            rules_path: Path to rules.yaml file
        """
        self.rules_path = Path(rules_path)
        self.rules = self._load_rules()
        self.issue_counter = 0  # For generating unique codes
        
    def _load_rules(self) -> Dict[str, Any]:
        """Load and validate rules.yaml."""
        try:
            with open(self.rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if not data or "scoring" not in data:
                raise ValueError("Invalid rules.yaml: missing 'scoring' key")
            
            return data["scoring"]
        except FileNotFoundError:
            raise FileNotFoundError(f"Rules file not found: {self.rules_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax in rules.yaml: {e}")
    
    def score(self, data_dir: str) -> ScoringResult:
        """
        Calculate complete score from intermediate JSON outputs.
        
        Args:
            data_dir: Directory containing:
                - tables.json (parsed table metadata)
                - relationships.json (relationship topology)
                - measures.json (DAX measure analysis)
                - pages.json (report page structure)
                - classifications.json (table classifications)
        
        Returns:
            ScoringResult with dimensions, issues, grade, and metadata
        """
        data_dir = Path(data_dir)
        
        # Load all intermediate JSON files
        tables_data = self._load_json(data_dir / "tables.json")
        relationships_data = self._load_json(data_dir / "relationships.json")
        measures_data = self._load_json(data_dir / "measures.json")
        pages_data = self._load_json(data_dir / "pages.json")
        analysis_data = self._load_json(data_dir / "classifications.json")
        
        # Calculate dimension scores
        model_score = self._score_model_health(tables_data, relationships_data, analysis_data)
        dax_score = self._score_dax_quality(measures_data)
        report_score = self._score_report_design(pages_data, analysis_data)
        governance_score = self._score_governance(tables_data, measures_data, analysis_data)
        
        # Aggregate dimensions
        dimensions = {
            "model_health": model_score,
            "dax_quality": dax_score,
            "report_design": report_score,
            "governance": governance_score
        }
        
        # Calculate weighted global score
        global_score, breakdown = self._calculate_weighted_score(dimensions)
        
        # Determine grade
        grade = self._grade_from_score(global_score)
        
        # Collect all issues
        all_issues = []
        for dim_score in dimensions.values():
            all_issues.extend(dim_score.issues)
        
        # Assign unique codes to all issues
        self._assign_issue_codes(all_issues)
        
        # Generate metadata
        metadata = {
            "version": self.rules.get("metadata", {}).get("version", "1.0.0"),
            "timestamp": datetime.now().isoformat(),
            "analyzed_directory": str(data_dir),
            "rules_path": str(self.rules_path),
            "total_tables": len(tables_data) if tables_data else 0,
            "total_relationships": len(relationships_data) if relationships_data else 0,
            "total_measures": len(measures_data) if measures_data else 0,
            "total_pages": len(pages_data) if pages_data else 0,
        }
        
        # Add schema type from analysis/classifications if available
        if analysis_data:
            schema_info = analysis_data.get("summary", {})
            if schema_info.get("schema_type"):
                metadata["schema_type"] = schema_info["schema_type"]
        
        # Add workspace name from parent directory (project name)
        # data_dir is typically: reports/{project-name}/data
        # So parent.parent is reports/, and parent.name is {project-name}
        try:
            project_name = data_dir.parent.name
            if project_name and project_name != "reports":
                metadata["workspace"] = project_name
        except Exception:
            pass
        
        return ScoringResult(
            global_score=global_score,
            grade=grade,
            dimensions=dimensions,
            issues=all_issues,
            metadata=metadata,
            breakdown=breakdown
        )
    
    # ========================================================================
    # Dimension Scoring (Actual Implementations)
    # ========================================================================
    
    def _score_model_health(
        self,
        tables_data: List[Dict],
        relationships_data: List[Dict],
        analysis_data: Dict
    ) -> DimensionScore:
        """
        Score model health dimension using ModelHealthDimension.
        
        Args:
            tables_data: List of table metadata
            relationships_data: List of relationships
            analysis_data: Table classification analysis
        
        Returns:
            DimensionScore for model dimension
        """
        data = {
            "tables": tables_data or [],
            "relationships": relationships_data or [],
            "analysis": analysis_data or {}
        }
        
        dimension = ModelHealthDimension(
            data=data,
            rules=self.rules.get("model", {}),
            weight=self.rules["weights"]["model_health"]
        )
        
        return dimension.calculate()
    
    def _score_dax_quality(self, measures_data: List[Dict]) -> DimensionScore:
        """
        Score DAX quality dimension using DAXQualityDimension.
        
        Args:
            measures_data: List of measure definitions with expressions
        
        Returns:
            DimensionScore for DAX dimension
        """
        data = {
            "measures": measures_data or []
        }
        
        dimension = DAXQualityDimension(
            data=data,
            rules=self.rules.get("dax", {}),
            weight=self.rules["weights"]["dax_quality"]
        )
        
        return dimension.calculate()
    
    def _score_report_design(
        self,
        pages_data: List[Dict],
        analysis_data: Dict
    ) -> DimensionScore:
        """
        Score report design dimension using ReportDesignDimension.
        
        Args:
            pages_data: List of report page configurations
            analysis_data: Additional analysis data
        
        Returns:
            DimensionScore for report dimension
        """
        data = {
            "pages": pages_data or [],
            "analysis": analysis_data or {}
        }
        
        dimension = ReportDesignDimension(
            data=data,
            rules=self.rules.get("report", {}),
            weight=self.rules["weights"]["report_design"]
        )
        
        return dimension.calculate()
    
    def _score_governance(
        self,
        tables_data: List[Dict],
        measures_data: List[Dict],
        analysis_data: Dict
    ) -> DimensionScore:
        """
        Score governance dimension using GovernanceDimension.
        
        Args:
            tables_data: List of table metadata
            measures_data: List of measure metadata
            analysis_data: Additional analysis data
        
        Returns:
            DimensionScore for governance dimension
        """
        data = {
            "tables": tables_data or [],
            "measures": measures_data or [],
            "roles": analysis_data.get("roles", []) if isinstance(analysis_data, dict) else []
        }
        
        dimension = GovernanceDimension(
            data=data,
            rules=self.rules.get("governance", {}),
            weight=self.rules["weights"]["governance"]
        )
        
        return dimension.calculate()
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def _load_json(self, filepath: Path) -> Optional[Any]:
        """Safely load JSON file, return None if not found."""
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load {filepath}: {e}")
            return None
    
    def _calculate_weighted_score(self, dimensions: Dict[str, DimensionScore]) -> Tuple[int, Dict]:
        """
        Calculate global weighted score from dimensions.
        
        Returns:
            (global_score, breakdown_dict)
        """
        total_weighted = 0.0
        breakdown = {}
        
        for dim_name, dim_score in dimensions.items():
            total_weighted += dim_score.weighted
            breakdown[dim_name] = {
                "score": dim_score.score,
                "weight": dim_score.weight,
                "weighted": round(dim_score.weighted, 2)
            }
        
        global_score = round(total_weighted)
        breakdown["global_weighted_sum"] = round(total_weighted, 2)
        breakdown["global_score"] = global_score
        
        return global_score, breakdown
    
    def _grade_from_score(self, score: int) -> str:
        """Convert numerical score to letter grade."""
        grade_thresholds = self.rules.get("grade_thresholds", {
            "A": 85,
            "B": 75,
            "C": 60,
            "D": 45,
            "F": 0
        })
        
        for grade in ["A", "B", "C", "D", "F"]:
            if score >= grade_thresholds.get(grade, 0):
                return grade
        
        return "F"
    
    def _assign_issue_codes(self, all_issues: List[Issue]) -> None:
        """
        Assign unique codes to all issues based on dimension.
        
        Convention:
        - MODEL: M001, M002, ...
        - DAX: D001, D002, ...
        - REPORT: R001, R002, ...
        - GOVERNANCE: G001, G002, ...
        
        Args:
            all_issues: List of Issue objects to code
        """
        dimension_counters = {
            "MODEL": 0,
            "DAX": 0,
            "REPORT": 0,
            "GOVERNANCE": 0
        }
        
        dimension_map = {
            "MODEL": "M",
            "DAX": "D",
            "REPORT": "R",
            "GOVERNANCE": "G",
            "MODELHEALTH": "M",  # Fallback for alternative naming
            "DAXQUALITY": "D",
            "REPORTDESIGN": "R"
        }
        
        for issue in all_issues:
            # Normalize dimension name
            dim = issue.dimension.upper()
            if dim not in dimension_counters:
                # Try to map from class name format
                if "MODEL" in dim:
                    dim = "MODEL"
                elif "DAX" in dim:
                    dim = "DAX"
                elif "REPORT" in dim:
                    dim = "REPORT"
                elif "GOVERNANCE" in dim:
                    dim = "GOVERNANCE"
            
            # Increment counter and assign code
            if dim in dimension_counters:
                dimension_counters[dim] += 1
                prefix = dimension_map.get(dim, "X")
                issue.code = f"{prefix}{dimension_counters[dim]:03d}"
            else:
                issue.code = f"X{self.issue_counter:03d}"
                self.issue_counter += 1
    
    def _generate_issue_code(self, dimension: str) -> str:
        """Generate unique issue code (e.g., M001, D003, R005, G002)."""
        dimension_map = {"MODEL": "M", "DAX": "D", "REPORT": "R", "GOVERNANCE": "G"}
        prefix = dimension_map.get(dimension, "X")
        
        self.issue_counter += 1
        return f"{prefix}{self.issue_counter:03d}"


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Quick test of the scoring engine."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python engine.py <data_dir> [rules.yaml]")
        print("  data_dir: Directory containing tables.json, relationships.json, etc.")
        print("  rules.yaml: Path to rules file (default: ./scoring/rules.yaml)")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    rules_path = sys.argv[2] if len(sys.argv) > 2 else "scoring/rules.yaml"
    
    try:
        engine = ScoringEngine(rules_path)
        result = engine.score(data_dir)
        
        print(f"\n{'='*60}")
        print(f"Power BI Scoring Result")
        print(f"{'='*60}")
        print(f"Global Score: {result.global_score}/100")
        print(f"Grade: {result.grade}")
        print(f"\nDimensions:")
        for name, dim in result.dimensions.items():
            print(f"  {name}: {dim.score}/100 (weight: {dim.weight})")
        
        print(f"\nIssues:")
        print(f"  Critical: {result.critical_count}")
        print(f"  Warnings: {result.warning_count}")
        print(f"  Info: {result.info_count}")
        print(f"\nMetadata:")
        print(f"  Timestamp: {result.metadata['timestamp']}")
        print(f"  Tables: {result.metadata['total_tables']}")
        print(f"  Relationships: {result.metadata['total_relationships']}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
