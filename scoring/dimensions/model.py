"""
Model Health Dimension Scorer.

Consumes:
- tables.json: Table metadata (columns, measures, classification)
- relationships.json: Relationship topology
- classifications.json: Table classifications and confidence

Evaluates:
- Relationship coverage and topology
- Fact/dimension balance
- Relationship cardinality and direction
- Table isolation (excluding intentional)
"""

from typing import Dict, List, Any, Optional
from collections import Counter
from .base import BaseDimension, DimensionScore


class ModelHealthDimension(BaseDimension):
    """Scores model health based on dimensional modeling best practices."""
    
    def __init__(self, data: Dict[str, Any], rules: Dict[str, Any], weight: float = 0.35):
        """
        Initialize model health scorer.
        
        Args:
            data: Must contain:
                - "tables": list of table metadata
                - "relationships": list of relationships
                - "analysis": classification analysis
            rules: Rules from scoring.model
            weight: Dimension weight (default 0.35)
        """
        super().__init__(data, rules, weight)
        
        self.tables = data.get("tables", [])
        self.relationships = data.get("relationships", [])
        self.analysis = data.get("analysis", {})
        
        # Extract classifications from analysis
        self.classifications = {}
        table_classifications = self.analysis.get("table_classifications", [])
        if isinstance(table_classifications, list):
            for item in table_classifications:
                table_name = item.get("table_name", "UNKNOWN")
                classification = item.get("classification", "UNKNOWN")
                self.classifications[table_name] = classification
        elif isinstance(self.analysis, dict):
            # Fallback for alternative format
            for table_name, info in self.analysis.items():
                if isinstance(info, dict):
                    self.classifications[table_name] = info.get("classification", "UNKNOWN")
    
    def calculate(self) -> DimensionScore:
        """
        Calculate model health score.
        
        Returns:
            DimensionScore with breakdown and issues
        """
        total_tables = len(self.tables)
        total_relationships = len(self.relationships)
        
        # Short-circuit: empty model
        if total_tables == 0:
            return self._make_dimension_score()
        
        # Get classification counts
        fact_tables = [t for t, c in self.classifications.items() if c == "FACT"]
        dimension_tables = [t for t, c in self.classifications.items() if c == "DIMENSION"]
        bridge_tables = [t for t, c in self.classifications.items() if c == "BRIDGE"]
        calculation_tables = [t for t, c in self.classifications.items() if c == "CALCULATION"]
        parameter_tables = [t for t, c in self.classifications.items() if c == "PARAMETER"]
        
        # ====================================================================
        # Penalty: No relationships
        # ====================================================================
        if total_tables > 1 and total_relationships == 0:
            self._apply_penalty(
                "no_relationships",
                self.rules["penalties"]["no_relationships"]["value"],
                self.rules["penalties"]["no_relationships"]["label"],
                severity="CRITICAL"
            )
        
        # ====================================================================
        # Penalty: Isolated tables
        # ====================================================================
        isolated_tables = self._find_isolated_tables()
        intentional_isolated = set(calculation_tables + parameter_tables)
        intentional_isolated.update(t for t in isolated_tables if t.startswith(("_", "param", "Param")))
        real_isolated = [t for t in isolated_tables if t not in intentional_isolated]
        
        if real_isolated:
            isolated_ratio = len(real_isolated) / total_tables
            penalty_value = min(
                self.rules["penalties"]["isolated_tables"]["max"],
                round(isolated_ratio * self.rules["penalties"]["isolated_tables"]["per_table_ratio"])
            )
            self._apply_penalty(
                "isolated_tables",
                penalty_value,
                self.rules["penalties"]["isolated_tables"]["label"],
                affected=real_isolated,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: No fact table
        # ====================================================================
        if total_relationships > 0 and not fact_tables:
            self._apply_penalty(
                "no_fact_table",
                self.rules["penalties"]["no_fact_table"]["value"],
                self.rules["penalties"]["no_fact_table"]["label"],
                severity="CRITICAL"
            )
        
        # ====================================================================
        # Penalty: Multiple facts without shared dimensions
        # ====================================================================
        if len(fact_tables) >= 2:
            shared_dims = self._count_shared_dimensions(fact_tables)
            if shared_dims == 0:
                self._apply_penalty(
                    "multiple_facts_no_shared_dims",
                    self.rules["penalties"]["multiple_facts_no_shared_dims"]["value"],
                    self.rules["penalties"]["multiple_facts_no_shared_dims"]["label"],
                    affected=fact_tables,
                    severity="INFO"
                )
        
        # ====================================================================
        # Penalty: Many-to-many relationships
        # ====================================================================
        m2m_rels = [r for r in self.relationships 
                    if r.get("from_cardinality") == "many" and r.get("to_cardinality") == "many"]
        
        if m2m_rels:
            penalty_value = min(
                self.rules["penalties"]["many_to_many"]["max"],
                len(m2m_rels) * self.rules["penalties"]["many_to_many"]["per_relationship"]
            )
            self._apply_penalty(
                "many_to_many",
                penalty_value,
                self.rules["penalties"]["many_to_many"]["label"],
                affected=[f"{r.get('from_table')} → {r.get('to_table')}" for r in m2m_rels],
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: Bidirectional relationships
        # ====================================================================
        bi_rels = [r for r in self.relationships 
                   if str(r.get("cross_filtering_behavior", "")).lower() in {"bothdirections", "both"}]
        
        if bi_rels:
            penalty_value = min(
                self.rules["penalties"]["bidirectional"]["max"],
                len(bi_rels) * self.rules["penalties"]["bidirectional"]["per_relationship"]
            )
            self._apply_penalty(
                "bidirectional",
                penalty_value,
                self.rules["penalties"]["bidirectional"]["label"],
                affected=[f"{r.get('from_table')} ←→ {r.get('to_table')}" for r in bi_rels],
                severity="INFO"
            )
        
        # ====================================================================
        # Penalty: Inactive relationships
        # ====================================================================
        inactive_rels = [r for r in self.relationships if not r.get("is_active", True)]
        
        if inactive_rels:
            penalty_value = min(
                self.rules["penalties"]["inactive_relationships"]["max"],
                len(inactive_rels) * self.rules["penalties"]["inactive_relationships"]["per_relationship"]
            )
            self._apply_penalty(
                "inactive_relationships",
                penalty_value,
                self.rules["penalties"]["inactive_relationships"]["label"],
                affected=[f"{r.get('from_table')} → {r.get('to_table')}" for r in inactive_rels],
                severity="INFO"
            )
        
        # ====================================================================
        # Penalty: String-typed keys
        # ====================================================================
        string_key_tables = [t for t in self.tables if t.get("has_string_keys", 0) > 0]
        
        if string_key_tables:
            penalty_value = min(
                self.rules["penalties"]["string_keys"]["max"],
                len(string_key_tables) * self.rules["penalties"]["string_keys"]["per_table"]
            )
            self._apply_penalty(
                "string_keys",
                penalty_value,
                self.rules["penalties"]["string_keys"]["label"],
                affected=string_key_tables,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: Calculated columns in facts
        # ====================================================================
        calc_in_facts = sum(
            t.get("calculated_columns", 0) for t in self.tables
            if self.classifications.get(t["name"]) == "FACT"
        )
        
        if calc_in_facts > 0:
            penalty_value = min(
                self.rules["penalties"]["calculated_columns_in_facts"]["max"],
                calc_in_facts * self.rules["penalties"]["calculated_columns_in_facts"]["per_column"]
            )
            self._apply_penalty(
                "calculated_columns_in_facts",
                penalty_value,
                self.rules["penalties"]["calculated_columns_in_facts"]["label"],
                affected=fact_tables,
                severity="WARNING"
            )
        
        # ====================================================================
        # Penalty: Low confidence classifications
        # ====================================================================
        low_conf_tables = []
        table_classifications = self.analysis.get("table_classifications", [])
        
        if isinstance(table_classifications, list):
            # New format: list of classification objects
            for item in table_classifications:
                if isinstance(item, dict):
                    table_name = item.get("table_name", "UNKNOWN")
                    confidence = item.get("confidence", 1.0)
                    table_type = self.classifications.get(table_name, "UNKNOWN")
                    
                    if confidence < self.rules["penalties"]["low_confidence_classification"]["threshold"] \
                       and table_type not in self.rules["penalties"]["low_confidence_classification"]["exclude_types"]:
                        low_conf_tables.append(table_name)
        else:
            # Fallback for old format
            for t, info in self.analysis.items():
                if isinstance(info, dict) and info.get("confidence", 1.0) < self.rules["penalties"]["low_confidence_classification"]["threshold"] \
                   and self.classifications.get(t, "UNKNOWN") not in self.rules["penalties"]["low_confidence_classification"]["exclude_types"]:
                    low_conf_tables.append(t)
        
        if low_conf_tables:
            penalty_value = min(
                self.rules["penalties"]["low_confidence_classification"]["max"],
                len(low_conf_tables) * self.rules["penalties"]["low_confidence_classification"]["per_table"]
            )
            self._apply_penalty(
                "low_confidence_classification",
                penalty_value,
                self.rules["penalties"]["low_confidence_classification"]["label"],
                affected=low_conf_tables,
                severity="INFO"
            )
        
        # ====================================================================
        # Bonuses
        # ====================================================================
        
        # Bonus: Clean dimensional model
        if fact_tables and dimension_tables and total_relationships > 0:
            self._apply_bonus(
                "clean_dimensional_model",
                self.rules["bonuses"]["clean_dimensional_model"]["value"],
                self.rules["bonuses"]["clean_dimensional_model"]["label"]
            )
        
        # Bonus: Bridge tables present
        if bridge_tables:
            bonus_value = min(
                self.rules["bonuses"]["bridge_tables_present"]["max"],
                len(bridge_tables) * self.rules["bonuses"]["bridge_tables_present"]["per_table"]
            )
            self._apply_bonus(
                "bridge_tables_present",
                bonus_value,
                self.rules["bonuses"]["bridge_tables_present"]["label"]
            )
        
        # Bonus: High classification confidence
        avg_confidence = self._calculate_avg_confidence()
        threshold = self.rules.get("bonuses", {}).get("high_classification_confidence", {}).get("threshold", 0.85)
        if avg_confidence >= threshold:
            self._apply_bonus(
                "high_classification_confidence",
                self.rules["bonuses"]["high_classification_confidence"]["value"],
                self.rules["bonuses"]["high_classification_confidence"]["label"]
            )
        
        # ====================================================================
        # Apply schema ceiling
        # ====================================================================
        schema_type = self._detect_schema_type()
        schema_ceilings = self.rules.get("schema_ceilings", {})
        schema_ceiling = schema_ceilings.get(schema_type, schema_ceilings.get("UNKNOWN", 80))
        self._apply_ceiling(schema_ceiling)
        self.breakdown["schema_type_ceiling"] = schema_ceiling
        
        # ====================================================================
        # Final clamp
        # ====================================================================
        self._clamp_score()
        
        return self._make_dimension_score()
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _find_isolated_tables(self) -> List[str]:
        """Find tables with no relationships."""
        related_tables = set()
        for rel in self.relationships:
            related_tables.add(rel.get("from_table"))
            related_tables.add(rel.get("to_table"))
        
        return [t["name"] for t in self.tables if t["name"] not in related_tables]
    
    def _count_shared_dimensions(self, fact_tables: List[str]) -> int:
        """Count dimensions connected to multiple fact tables."""
        dim_usage = Counter()
        
        for rel in self.relationships:
            from_table = rel.get("from_table")
            to_table = rel.get("to_table")
            from_type = self.classifications.get(from_table, "UNKNOWN")
            to_type = self.classifications.get(to_table, "UNKNOWN")
            
            if from_table in fact_tables and to_type == "DIMENSION":
                dim_usage[to_table] += 1
            elif to_table in fact_tables and from_type == "DIMENSION":
                dim_usage[from_table] += 1
        
        return sum(1 for _, count in dim_usage.items() if count >= 2)
    
    def _calculate_avg_confidence(self) -> float:
        """Calculate average classification confidence."""
        confidences = []
        
        # Handle new format: table_classifications list
        table_classifications = self.analysis.get("table_classifications", [])
        if isinstance(table_classifications, list):
            for item in table_classifications:
                if isinstance(item, dict):
                    confidences.append(item.get("confidence", 0.5))
        else:
            # Fallback for old format
            for table_info in self.analysis.values():
                if isinstance(table_info, dict):
                    confidences.append(table_info.get("confidence", 0.5))
        
        return sum(confidences) / len(confidences) if confidences else 0.5
    
    def _detect_schema_type(self) -> str:
        """Detect schema type based on topology."""
        total_tables = len(self.tables)
        total_relationships = len(self.relationships)
        
        if total_relationships == 0:
            return "FLAT" if total_tables <= 2 else "DISCONNECTED"
        
        fact_tables = [t for t, c in self.classifications.items() if c == "FACT"]
        fact_count = len(fact_tables)
        
        # Count relationship types
        dim_to_dim = 0
        fact_to_dim = 0
        
        for rel in self.relationships:
            from_type = self.classifications.get(rel.get("from_table"), "UNKNOWN")
            to_type = self.classifications.get(rel.get("to_table"), "UNKNOWN")
            
            if from_type == "DIMENSION" and to_type == "DIMENSION":
                dim_to_dim += 1
            elif (from_type == "FACT" and to_type == "DIMENSION") or (from_type == "DIMENSION" and to_type == "FACT"):
                fact_to_dim += 1
        
        if fact_count >= 2 and fact_to_dim >= fact_count:
            return "GALAXY"
        
        if dim_to_dim > 0 and fact_count >= 1:
            return "SNOWFLAKE"
        
        if fact_count == 1 and fact_to_dim >= 2:
            return "STAR"
        
        if fact_count == 0 and total_relationships > 0:
            return "DIMENSIONAL"
        
        return "UNKNOWN"
    
    def _make_dimension_score(self) -> DimensionScore:
        """Create DimensionScore object."""
        return DimensionScore(
            name="MODEL",
            score=max(0, min(100, self.score)),
            weight=self.weight,
            weighted=round(self.score * self.weight, 2),
            issues=self.issues,
            bonuses_applied=self.bonuses_applied,
            penalties_applied=self.penalties_applied,
            breakdown=self.breakdown
        )
