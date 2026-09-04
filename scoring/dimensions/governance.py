"""
Governance Dimension Scorer.

Consumes:
- tables.json: Table metadata and naming
- measures.json: Measure metadata and descriptions
- roles data (if available): RLS roles

Evaluates:
- Naming convention compliance
- RLS and security
- Documentation (descriptions)
- Metadata completeness
"""

from typing import Dict, List, Any, Optional
from .base import BaseDimension, DimensionScore


class GovernanceDimension(BaseDimension):
    """Scores governance maturity based on naming, RLS, and documentation."""
    
    def __init__(self, data: Dict[str, Any], rules: Dict[str, Any], weight: float = 0.15):
        """
        Initialize governance scorer.
        
        Args:
            data: Must contain:
                - "tables": list of table metadata
                - "measures": list of measure metadata
                - "roles" (optional): RLS role definitions
            rules: Rules from scoring.governance
            weight: Dimension weight (default 0.15)
        """
        super().__init__(data, rules, weight)
        self.tables = data.get("tables", [])
        self.measures = data.get("measures", [])
        self.roles = data.get("roles", [])
    
    def calculate(self) -> DimensionScore:
        """
        Calculate governance score.
        
        Returns:
            DimensionScore with breakdown and issues
        """
        # ====================================================================
        # Penalty: Naming violations
        # ====================================================================
        naming_violations = []
        naming_conventions = self.rules["naming_conventions"]
        
        for table in self.tables:
            name = table.get("name", "")
            
            # Check forbidden names
            if name in naming_conventions["forbidden_names"]:
                naming_violations.append(name)
                continue
            
            # Check convention compliance (optional: can be warnings only)
            # For now, we'll be permissive and only flag truly bad names
        
        if naming_violations:
            penalty_value = min(
                self.rules["penalties"]["naming_violations"]["max"],
                len(naming_violations) * self.rules["penalties"]["naming_violations"]["per_table"]
            )
            self._apply_penalty(
                "naming_violations",
                penalty_value,
                self.rules["penalties"]["naming_violations"]["label"],
                affected=naming_violations,
                severity="INFO"
            )
        
        # ====================================================================
        # Penalty: Measures without descriptions
        # ====================================================================
        measures_no_desc = [
            m.get("name", "Unknown") for m in self.measures
            if not m.get("description") or len(m.get("description", "").strip()) == 0
        ]
        measures_no_desc = list(dict.fromkeys(measures_no_desc))
        
        if measures_no_desc and len(measures_no_desc) / len(self.measures) > self.rules["penalties"]["no_description_on_measures"]["ratio_threshold"]:
            self._apply_penalty(
                "no_description_on_measures",
                self.rules["penalties"]["no_description_on_measures"]["value"],
                self.rules["penalties"]["no_description_on_measures"]["label"],
                affected=measures_no_desc[:10],  # Show first 10
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: No RLS defined (if sensitive data detected)
        # ====================================================================
        # For now, this is simplified: check if there are roles at all
        # In production, would need to detect sensitive data markers
        
        if len(self.roles) == 0:
            # Only apply if we detect sensitive patterns in table names
            has_sensitive_tables = any(
                keyword in t.get("name", "").lower()
                for t in self.tables
                for keyword in ["salary", "ssn", "email", "password", "credit", "financial"]
            )
            
            if has_sensitive_tables:
                self._apply_penalty(
                    "no_rls_defined",
                    self.rules["penalties"]["no_rls_defined"]["value"],
                    self.rules["penalties"]["no_rls_defined"]["label"],
                    severity="CRITICAL"
                )
        
        # ====================================================================
        # Penalty: Static RLS overuse
        # ====================================================================
        static_rls_count = sum(
            1 for role in self.roles
            if role.get("type", "").lower() == "static"
        )
        
        if static_rls_count > self.rules["penalties"]["static_rls_overuse"]["threshold"]:
            excess = static_rls_count - self.rules["penalties"]["static_rls_overuse"]["threshold"]
            penalty_value = min(
                self.rules["penalties"]["static_rls_overuse"]["max"],
                excess * self.rules["penalties"]["static_rls_overuse"]["per_role_over_threshold"]
            )
            
            self._apply_penalty(
                "static_rls_overuse",
                penalty_value,
                self.rules["penalties"]["static_rls_overuse"]["label"],
                affected=[r.get("name", "Unknown") for r in self.roles],
                severity="INFO"
            )
        
        # ====================================================================
        # Bonuses
        # ====================================================================
        
        # Bonus: Consistent naming
        if not naming_violations:
            self._apply_bonus(
                "consistent_naming",
                self.rules["bonuses"]["consistent_naming"]["value"],
                self.rules["bonuses"]["consistent_naming"]["label"]
            )
        
        # Bonus: Dynamic RLS implemented
        dynamic_rls_count = sum(
            1 for role in self.roles
            if role.get("type", "").lower() == "dynamic" or "USERPRINCIPALNAME" in role.get("filter", "")
        )
        
        if dynamic_rls_count > 0:
            self._apply_bonus(
                "dynamic_rls_implemented",
                self.rules["bonuses"]["dynamic_rls_implemented"]["value"],
                self.rules["bonuses"]["dynamic_rls_implemented"]["label"]
            )
        
        # Bonus: All measures have descriptions
        if not measures_no_desc:
            self._apply_bonus(
                "documented_measures",
                5,  # Small bonus
                "All measures have descriptions"
            )
        
        # ====================================================================
        # Final clamp
        # ====================================================================
        self._clamp_score()
        
        return self._make_dimension_score()
    
    def _make_dimension_score(self) -> DimensionScore:
        """Create DimensionScore object."""
        return DimensionScore(
            name="GOVERNANCE",
            score=max(0, min(100, self.score)),
            weight=self.weight,
            weighted=round(self.score * self.weight, 2),
            issues=self.issues,
            bonuses_applied=self.bonuses_applied,
            penalties_applied=self.penalties_applied,
            breakdown=self.breakdown
        )
