"""
DAX Quality Dimension Scorer.

Consumes:
- measures.json: DAX measure definitions with expressions

Evaluates:
- Pattern matching (FILTER over tables, nested iterators, etc)
- Measure complexity and VAR usage
- Format strings
- Measure organization
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from .base import BaseDimension, DimensionScore


class DAXQualityDimension(BaseDimension):
    """Scores DAX quality based on expression patterns and best practices."""
    
    def __init__(self, data: Dict[str, Any], rules: Dict[str, Any], weight: float = 0.25):
        """
        Initialize DAX quality scorer.
        
        Args:
            data: Must contain:
                - "measures": list of measure definitions with expressions
            rules: Rules from scoring.dax
            weight: Dimension weight (default 0.25)
        """
        super().__init__(data, rules, weight)
        self.measures = data.get("measures", [])
    
    def calculate(self) -> DimensionScore:
        """
        Calculate DAX quality score.
        
        Returns:
            DimensionScore with breakdown and issues
        """
        if not self.measures:
            return self._make_dimension_score()
        
        # ====================================================================
        # Penalty: FILTER over full table
        # ====================================================================
        filter_issues = []
        for measure in self.measures:
            expr = measure.get("expression", "")
            if self._has_filter_over_table(expr):
                filter_issues.append(measure.get("name", "Unknown"))
        
        if filter_issues:
            penalty_value = min(
                self.rules["penalties"]["filter_over_full_table"]["max"],
                len(filter_issues) * self.rules["penalties"]["filter_over_full_table"]["per_measure"]
            )
            self._apply_penalty(
                "filter_over_full_table",
                penalty_value,
                self.rules["penalties"]["filter_over_full_table"]["label"],
                affected=filter_issues,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: No VAR in complex measures
        # ====================================================================
        complex_no_var = []
        for measure in self.measures:
            expr = measure.get("expression", "")
            if self._is_complex(expr) and not self._uses_var(expr):
                complex_no_var.append(measure.get("name", "Unknown"))
        
        if complex_no_var:
            penalty_value = min(
                self.rules["penalties"]["no_var_in_complex_measure"]["max"],
                len(complex_no_var) * self.rules["penalties"]["no_var_in_complex_measure"]["per_measure"]
            )
            self._apply_penalty(
                "no_var_in_complex_measure",
                penalty_value,
                self.rules["penalties"]["no_var_in_complex_measure"]["label"],
                affected=complex_no_var,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: Nested iterators
        # ====================================================================
        nested_iter = []
        for measure in self.measures:
            expr = measure.get("expression", "")
            if self._has_nested_iterators(expr):
                nested_iter.append(measure.get("name", "Unknown"))
        
        if nested_iter:
            penalty_value = min(
                self.rules["penalties"]["nested_iterators"]["max"],
                len(nested_iter) * self.rules["penalties"]["nested_iterators"]["per_measure"]
            )
            self._apply_penalty(
                "nested_iterators",
                penalty_value,
                self.rules["penalties"]["nested_iterators"]["label"],
                affected=nested_iter,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: Measure without format
        # ====================================================================
        no_format = []
        for measure in self.measures:
            if not measure.get("formatString") and measure.get("dataType") in ["int64", "double", "decimal"]:
                no_format.append(measure.get("name", "Unknown"))
        
        if no_format:
            penalty_value = min(
                self.rules["penalties"]["measure_without_format"]["max"],
                len(no_format) * self.rules["penalties"]["measure_without_format"]["per_measure"]
            )
            self._apply_penalty(
                "measure_without_format",
                penalty_value,
                self.rules["penalties"]["measure_without_format"]["label"],
                affected=no_format,
                severity="INFO"
            )
        
        # ====================================================================
        # Penalty: Measures outside dedicated table
        # ====================================================================
        measures_outside = [
            m.get("name", "Unknown") for m in self.measures
            if m.get("table") not in ["_Measures", "Calculations", "_Calculations"]
        ]
        
        if measures_outside and len(measures_outside) / len(self.measures) > 0.1:
            penalty_value = min(
                self.rules["penalties"]["measures_outside_dedicated_table"]["max"],
                len(measures_outside) * self.rules["penalties"]["measures_outside_dedicated_table"]["per_measure"]
            )
            self._apply_penalty(
                "measures_outside_dedicated_table",
                penalty_value,
                self.rules["penalties"]["measures_outside_dedicated_table"]["label"],
                affected=measures_outside[:10],  # Show first 10
                severity="INFO"
            )
        
        # ====================================================================
        # Bonuses
        # ====================================================================
        
        # Bonus: All measures in dedicated table
        if all(m.get("table") in ["_Measures", "Calculations", "_Calculations"] for m in self.measures):
            self._apply_bonus(
                "all_measures_in_dedicated_table",
                self.rules["bonuses"]["all_measures_in_dedicated_table"]["value"],
                self.rules["bonuses"]["all_measures_in_dedicated_table"]["label"]
            )
        
        # Bonus: Good VAR adoption
        complex_measures = [m for m in self.measures if self._is_complex(m.get("expression", ""))]
        if complex_measures:
            var_usage = sum(1 for m in complex_measures if self._uses_var(m.get("expression", "")))
            var_rate = var_usage / len(complex_measures)
            
            if var_rate >= self.rules["bonuses"]["var_usage_rate"]["threshold"]:
                self._apply_bonus(
                    "var_usage_rate",
                    self.rules["bonuses"]["var_usage_rate"]["value"],
                    self.rules["bonuses"]["var_usage_rate"]["label"]
                )
        
        # ====================================================================
        # Final clamp
        # ====================================================================
        self._clamp_score()
        
        return self._make_dimension_score()
    
    # ========================================================================
    # DAX Pattern Detection
    # ========================================================================
    
    def _has_filter_over_table(self, expression: str) -> bool:
        """
        Detect FILTER() over full table (antipattern).
        
        Pattern: FILTER( 'TableName', ... ) or FILTER( TableName, ... )
        """
        pattern = self.rules.get("penalties", {}).get("filter_over_full_table", {}).get(
            "pattern",
            r"FILTER\s*\(\s*(?!VALUES\s*\()(?:'?[A-Za-z_][A-Za-z0-9_]*'?)\s*,"
        )
        return bool(re.search(pattern, expression, re.IGNORECASE))
    
    def _is_complex(self, expression: str) -> bool:
        """
        Determine if measure is complex (heuristic).
        
        Complex if: has multiple lines, nested functions, multiple calculations
        """
        # Simple heuristic: count lines and nested parentheses
        lines = expression.count("\n")
        nested_depth = self._calculate_nesting_depth(expression)
        
        min_lines = self.rules["thresholds"]["complex_measure_min_lines"]
        max_depth = self.rules["thresholds"]["max_measure_nesting_depth"]
        
        return lines >= min_lines or nested_depth > max_depth
    
    def _uses_var(self, expression: str) -> bool:
        """Detect VAR keyword in expression."""
        return bool(re.search(r"\bVAR\b", expression, re.IGNORECASE))
    
    def _has_nested_iterators(self, expression: str) -> bool:
        """
        Detect nested iterator functions (SUMX inside SUMX, etc).
        
        Pattern: (SUMX|AVERAGEX|MAXX|MINX) ... (SUMX|AVERAGEX|MAXX|MINX)
        """
        iterators = ["SUMX", "AVERAGEX", "MAXX", "MINX"]
        expr_upper = expression.upper()
        
        # Count how many iterators appear
        count = sum(expr_upper.count(it) for it in iterators)
        
        # If more than one iterator and they're nested (simple heuristic)
        if count >= 2:
            # More sophisticated check: look for iterator pattern inside another
            for it1 in iterators:
                for it2 in iterators:
                    pattern = rf"{it1}\s*\([^)]*{it2}\s*\("
                    if re.search(pattern, expr_upper):
                        return True
        
        return False
    
    def _calculate_nesting_depth(self, expression: str) -> int:
        """Calculate maximum parenthesis nesting depth."""
        max_depth = 0
        current_depth = 0
        
        for char in expression:
            if char == "(":
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif char == ")":
                current_depth = max(0, current_depth - 1)
        
        return max_depth
    
    def _make_dimension_score(self) -> DimensionScore:
        """Create DimensionScore object."""
        return DimensionScore(
            name="DAX",
            score=max(0, min(100, self.score)),
            weight=self.weight,
            weighted=round(self.score * self.weight, 2),
            issues=self.issues,
            bonuses_applied=self.bonuses_applied,
            penalties_applied=self.penalties_applied,
            breakdown=self.breakdown
        )
