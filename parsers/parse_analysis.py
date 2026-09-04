#!/usr/bin/env python3
"""Parser for Power BI model analysis (parsing, classification, topology only)."""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter, deque


NUMERIC_TYPES = {"double", "int64", "int32", "decimal", "currency"}
STRING_TYPES = {"string"}
DATE_TYPES = {"dateTime", "date"}
BOOLEAN_TYPES = {"boolean"}


class AnalysisParser:
    def __init__(self, tmdl_dir: str):
        self.tmdl_dir = Path(tmdl_dir)
        self.tables: Dict[str, Dict[str, Any]] = {}
        self.relationships: List[Dict[str, Any]] = []
        self.table_profiles: Dict[str, Dict[str, Any]] = {}

    def parse(self) -> Dict[str, Any]:
        """
        Perform Power BI semantic model analysis: parsing, classification, and topology.
        
        Responsibilities (Parser Only):
        - Extract table definitions, columns, measures from TMDL
        - Classify tables as FACT, DIMENSION, BRIDGE, CALCULATION, PARAMETER
        - Detect schema type from relationship topology
        - Report isolated tables and components
        
        Delegated Responsibilities (ScoringEngine):
        - Compliance scoring and issue generation
        - Severity levels (CRITICAL, WARNING, INFO)
        - Penalty calculations and breakdowns
        
        Output: classifications.json with topology info (no compliance data).
        """
        self._parse_all_data()

        self.table_profiles = self._build_table_profiles()
        classifications = self._classify_tables()
        relationship_analysis = self._analyze_relationships(classifications)
        model_metrics = self._generate_model_metrics(classifications, relationship_analysis)

        return {
            "table_classifications": classifications,
            "relationship_analysis": relationship_analysis,
            "model_metrics": model_metrics,
            "summary": self._generate_summary(classifications, relationship_analysis, model_metrics)
        }

    # =========================================================================
    # Parsing
    # =========================================================================

    def _parse_all_data(self) -> None:
        """Parse tables, columns, measures and relationships from TMDL."""
        tables_dir = self.tmdl_dir / "tables"
        if not tables_dir.exists():
            raise FileNotFoundError(f"Tables directory not found: {tables_dir}")
        for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
            table_name = tmdl_file.stem
            
            # Skip internal Power BI tables
            if self._is_internal_table(table_name):
                continue
                
            content = tmdl_file.read_text(encoding="utf-8")
            self.tables[table_name] = {
                "columns": self._extract_columns(content),
                "measures": self._extract_measures(content),
                "has_datatable": "DATATABLE" in content.upper(),
                "raw_size_chars": len(content)
            }
        self._parse_relationships()

    def _extract_columns(self, content: str) -> List[Dict[str, Any]]:
        """Extract columns from TMDL content."""
        columns = []
        col_pattern = r"column\s+(['\"]?)([^'\"\n]+)\1\s*\n((?:\t[^\n]*\n|\s{2,}[^\n]*\n)*?)"

        for match in re.finditer(col_pattern, content):
            col_name = match.group(2).strip()
            col_block = match.group(3)

            datatype = re.search(r"dataType:\s*(\w+)", col_block)
            is_calculated = bool(re.search(r"expression\s*=", col_block, re.IGNORECASE))
            is_concatenated = bool(
                re.search(r"CONCATENATE\s*\(|CONCAT\s*\(", col_block, re.IGNORECASE) or
                re.search(r"[^=!<>]\s*&\s*[^=&]", col_block)
            )

            columns.append({
                "name": col_name,
                "dataType": datatype.group(1) if datatype else "string",
                "isHidden": bool(re.search(r"isHidden:\s*true", col_block, re.IGNORECASE)),
                "summarizeBy": (m.group(1) if (m := re.search(r"summarizeBy:\s*(\w+)", col_block)) else None),
                "is_calculated": is_calculated,
                "is_concatenated": is_concatenated,
                "is_text_concatenated_key": is_concatenated and datatype and datatype.group(1) in STRING_TYPES
            })

        return columns

    def _extract_measures(self, content: str) -> List[str]:
        """Extract measure names from TMDL content."""
        return [
            m.group(2).strip()
            for m in re.finditer(r"measure\s+(['\"]?)([^'\"\n=]+)\1\s*(?:=|$)", content)
            if m.group(2).strip()
        ]

    def _parse_relationships(self) -> None:
        """Parse relationships from relationships.tmdl."""
        rel_file = self.tmdl_dir / "relationships.tmdl"
        if not rel_file.exists():
            return
        for block in re.split(r"\n\s*relationship\s+", rel_file.read_text(encoding="utf-8")):
            if not block.strip():
                continue
            from_col = re.search(r"fromColumn:\s*([^\n]+)", block)
            to_col = re.search(r"toColumn:\s*([^\n]+)", block)
            if not (from_col and to_col):
                continue
            from_table, from_column = self._parse_table_column(from_col.group(1).strip())
            to_table, to_column = self._parse_table_column(to_col.group(1).strip())
            if not (from_table and to_table):
                continue
            self.relationships.append({
                "from_table": from_table, "from_column": from_column, "to_table": to_table, "to_column": to_column,
                "from_cardinality": (m.group(1) if (m := re.search(r"fromCardinality:\s*(\w+)", block)) else "many"),
                "to_cardinality": (m.group(1) if (m := re.search(r"toCardinality:\s*(\w+)", block)) else "one"),
                "cross_filtering_behavior": (m.group(1) if (m := re.search(r"crossFilteringBehavior:\s*(\w+)", block)) else "singleDirection"),
                "is_active": self._parse_bool((m.group(1) if (m := re.search(r"isActive:\s*(\w+)", block)) else "true"))
            })

    def _parse_table_column(self, spec: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse TMDL table/column reference."""
        spec = spec.strip()
        bracket = re.match(r"(.+)\[(.+)\]", spec)
        if bracket:
            return bracket.group(1).strip().strip("'\"[]"), bracket.group(2).strip().strip("'\"[]")
        parts = spec.split(".")
        if len(parts) >= 2:
            return parts[0].strip().strip("'\"[]"), ".".join(parts[1:]).strip().strip("'\"[]")
        return None, None

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return value.strip().lower() == "true"

    # =========================================================================
    # Profiling
    # =========================================================================

    def _build_table_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Build table-level profile metrics."""
        profiles = {}
        for table_name, table_data in self.tables.items():
            cols = table_data["columns"]
            rel_from = [r for r in self.relationships if r["from_table"] == table_name]
            rel_to = [r for r in self.relationships if r["to_table"] == table_name]
            col_count = len(cols)
            profiles[table_name] = {
                "columns": col_count,
                "measures": len(table_data["measures"]),
                "numeric_columns": sum(1 for c in cols if c["dataType"] in NUMERIC_TYPES),
                "string_columns": sum(1 for c in cols if c["dataType"] in STRING_TYPES),
                "date_columns": sum(1 for c in cols if c["dataType"] in DATE_TYPES),
                "boolean_columns": sum(1 for c in cols if c["dataType"] in BOOLEAN_TYPES),
                "calculated_columns": sum(1 for c in cols if c.get("is_calculated", False)),
                "concatenated_columns": sum(1 for c in cols if c.get("is_concatenated", False)),
                "text_concatenated_keys": sum(1 for c in cols if c.get("is_text_concatenated_key", False)),
                "relationships_from": len(rel_from), "relationships_to": len(rel_to),
                "total_relationships": len(rel_from) + len(rel_to),
                "has_datatable": table_data.get("has_datatable", False),
                "name_tokens": self._tokenize_name(table_name.lower()),
                "is_isolated": len(rel_from) + len(rel_to) == 0,
                "numeric_ratio": round(sum(1 for c in cols if c["dataType"] in NUMERIC_TYPES) / col_count, 4) if col_count else 0,
                "string_ratio": round(sum(1 for c in cols if c["dataType"] in STRING_TYPES) / col_count, 4) if col_count else 0,
                "date_ratio": round(sum(1 for c in cols if c["dataType"] in DATE_TYPES) / col_count, 4) if col_count else 0,
                "calculated_ratio": round(sum(1 for c in cols if c.get("is_calculated", False)) / col_count, 4) if col_count else 0
            }
        return profiles

    @staticmethod
    def _tokenize_name(name: str) -> List[str]:
        tokens = re.split(r"[\s_\-\.]+", name.lower())
        return [t for t in tokens if t]

    @staticmethod
    def _is_internal_table(table_name: str) -> bool:
        """
        Filter out Power BI internal/system-generated tables.
        These tables are auto-generated by Power BI and don't represent user data.
        """
        # Power BI internal table patterns
        internal_patterns = [
            r"^DateTableTemplate_",  # Auto-generated date tables
            r"^LocalDateTable_",      # Temporal internal tables
        ]
        return any(re.match(pattern, table_name) for pattern in internal_patterns)

    # -------------------------------------------------------------------------
    # Table Classification
    # -------------------------------------------------------------------------

    def _classify_tables(self) -> List[Dict[str, Any]]:
        """
        Classify all tables using weighted scoring.
        Filters out internal/system-generated tables from Power BI.
        """
        classifications = []

        for table_name in sorted(self.tables.keys()):
            # Skip internal Power BI tables
            if self._is_internal_table(table_name):
                continue
            classifications.append(self._classify_single_table(table_name))

        return classifications

    def _classify_single_table(self, table_name: str) -> Dict[str, Any]:
        """Classify table: FACT, DIMENSION, BRIDGE, CALCULATION, PARAMETER."""
        profile = self.table_profiles[table_name]
        tokens = profile["name_tokens"]
        columns = self.tables[table_name]["columns"]
        scores = {"FACT": 0, "DIMENSION": 0, "BRIDGE": 0, "CALCULATION": 0, "PARAMETER": 0}
        evidence = defaultdict(list)

        # Name patterns
        name_patterns = {
            "FACT": (["fact", "facts", "transaction", "transactions", "sales", "spend", "ledger"], 35),
            "DIMENSION": (["dim", "dimension", "master", "catalog", "lookup", "calendar", "date", "time", "period", "fiscal"], 30),
            "BRIDGE": (["bridge", "map", "mapping", "xref", "link"], 35),
            "PARAMETER": (["parameter", "param", "selector", "slicer"], 35),
            "CALCULATION": (["measure", "measures", "calculation", "calculations", "kpi", "metrics"], 35),
        }
        
        for cls, (patterns, score_add) in name_patterns.items():
            if any(t in tokens for t in patterns):
                scores[cls] += score_add

        # Structure patterns
        if profile["measures"] >= 10 and profile["columns"] <= 2:
            scores["CALCULATION"] += 50
        if profile["measures"] >= 5 and profile["columns"] <= 1:
            scores["CALCULATION"] += 35
        if profile["has_datatable"] and profile["columns"] <= 5:
            scores["PARAMETER"] += 25
        if profile["columns"] <= 3 and profile["is_isolated"]:
            scores["PARAMETER"] += 20
        if profile["numeric_columns"] >= 2 and profile["relationships_from"] >= 2:
            scores["FACT"] += 25
        if profile["relationships_from"] >= 3:
            scores["FACT"] += 20
        if profile["relationships_to"] >= 2 and profile["relationships_from"] == 0:
            scores["DIMENSION"] += 25
        if profile["date_columns"] >= 2:
            scores["DIMENSION"] += 25

        # Penalize weak patterns
        if profile["calculated_columns"] >= 3 and profile["relationships_from"] >= 2:
            scores["FACT"] -= 15
        if profile["text_concatenated_keys"] > 0:
            scores["FACT"] -= 10
            scores["DIMENSION"] -= 8
        if profile["relationships_from"] >= 2 and profile["calculated_columns"] == 0 and profile["text_concatenated_keys"] == 0:
            scores["FACT"] += 10

        # Robust fact detection
        fact_score, fact_evidence = self._score_as_fact(table_name, profile, columns)
        if fact_score > 0:
            scores["FACT"] += fact_score
            evidence["FACT"].extend(fact_evidence)

        if max(scores.values()) == 0:
            scores["DIMENSION"] = 10

        classification = max(scores, key=scores.get)
        best_score = scores[classification]
        confidence = self._calculate_confidence(best_score, sum(scores.values()))

        return {
            "table_name": table_name,
            "classification": classification,
            "confidence": confidence,
            "reasoning": "; ".join(evidence.get(classification, ["N/A"])),
            "scores": scores,
            "metadata": profile
        }

    def _score_as_fact(self, table_name: str, profile: Dict[str, Any], columns: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
        """Detect fact tables via cardinality, isolation, and measure columns."""
        score = 0
        evidence = []
        outgoing_rels = [r for r in self.relationships if r["from_table"] == table_name and r.get("is_active", True)]
        if len(outgoing_rels) >= 4 and all(r.get("from_cardinality", "many") == "many" for r in outgoing_rels):
            score += 50
            evidence.append(f"Cardinality pattern: {len(outgoing_rels)} 'many' side relationships")
        if profile["relationships_to"] == 0 and profile["relationships_from"] >= 3:
            score += 45
            evidence.append(f"Isolation: no incoming, {profile['relationships_from']} outgoing")
        measure_cols = [c for c in columns if c["dataType"] in NUMERIC_TYPES and c.get("summarizeBy") and str(c.get("summarizeBy", "")).lower() != "none"]
        if len(measure_cols) >= 3:
            score += 40
            evidence.append(f"Measure columns: {len(measure_cols)} numeric with summarizeBy")
        return score, evidence

    @staticmethod
    def _calculate_confidence(best_score: int, total_score: int) -> float:
        """
        Convert classification score into confidence between 0 and 1.
        """
        if total_score <= 0:
            return 0.3

        relative_confidence = best_score / total_score

        if best_score >= 70:
            base = 0.9
        elif best_score >= 50:
            base = 0.8
        elif best_score >= 30:
            base = 0.65
        elif best_score >= 15:
            base = 0.5
        else:
            base = 0.35

        confidence = (base + relative_confidence) / 2
        return round(min(max(confidence, 0.3), 0.98), 2)

    # -------------------------------------------------------------------------
    # Relationship Analysis
    # -------------------------------------------------------------------------

    def _analyze_relationships(self, classifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze relationship topology and schema type."""
        graph = defaultdict(set)
        for table in self.tables:
            graph[table] = set()
        for rel in self.relationships:
            graph[rel["from_table"]].add(rel["to_table"])
            graph[rel["to_table"]].add(rel["from_table"])
        components = self._find_components(graph)
        isolated_tables = sorted([list(c)[0] for c in components if len(c) == 1])
        classification_map = {c["table_name"]: c["classification"] for c in classifications}
        avg_confidence = round(sum(c["confidence"] for c in classifications) / len(classifications), 3) if classifications else 0.5
        schema_type = self._detect_schema_type(classification_map, components)
        return {
            "total_tables": len(self.tables),
            "total_relationships": len(self.relationships),
            "active_relationships": sum(1 for r in self.relationships if r.get("is_active", True)),
            "inactive_relationships": sum(1 for r in self.relationships if not r.get("is_active", True)),
            "schema_type": schema_type,
            "average_classification_confidence": avg_confidence,
            "components": len(components),
            "component_details": [sorted(list(c)) for c in components],
            "isolated_tables": isolated_tables,
            "relationships": self.relationships
        }

    def _find_components(self, graph: Dict[str, set]) -> List[set]:
        """Find connected components using BFS."""
        visited = set()
        components = []
        for table in self.tables.keys():
            if table in visited:
                continue
            component = set()
            queue = deque([table])
            visited.add(table)
            while queue:
                node = queue.popleft()
                component.add(node)
                for neighbor in graph[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(component)
        return components

    def _detect_schema_type(self, classification_map: Dict[str, str], components: List[set]) -> str:
        """Detect schema type from relationship topology."""
        total_tables = len(self.tables)
        total_relationships = len(self.relationships)
        if total_tables == 0:
            return "UNKNOWN"
        if total_relationships == 0:
            return "FLAT" if total_tables <= 2 else "DISCONNECTED"
        fact_tables = [t for t, c in classification_map.items() if c == "FACT"]
        fact_count = len(fact_tables)
        dim_to_dim = sum(1 for r in self.relationships if classification_map.get(r["from_table"]) == "DIMENSION" and classification_map.get(r["to_table"]) == "DIMENSION")
        fact_to_dim = sum(1 for r in self.relationships if (classification_map.get(r["from_table"]) == "FACT" and classification_map.get(r["to_table"]) == "DIMENSION") or (classification_map.get(r["from_table"]) == "DIMENSION" and classification_map.get(r["to_table"]) == "FACT"))
        if fact_count >= 2 and fact_to_dim >= fact_count:
            return "GALAXY"
        if dim_to_dim > 0 and fact_count >= 1:
            return "SNOWFLAKE"
        if fact_count == 1 and fact_to_dim >= 2:
            return "STAR"
        if fact_count == 0 and total_relationships > 0:
            return "DIMENSIONAL"
        return "UNKNOWN"

    # =========================================================================
    # Metrics & Summary
    # =========================================================================

    def _generate_model_metrics(self, classifications: List[Dict[str, Any]], relationship_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate model metrics."""
        total_columns = sum(c["metadata"]["columns"] for c in classifications)
        total_measures = sum(c["metadata"]["measures"] for c in classifications)
        return {"total_tables": len(classifications), "total_columns": total_columns, "total_measures": total_measures, "total_relationships": relationship_analysis["total_relationships"], "avg_columns_per_table": round(total_columns / len(classifications), 2) if classifications else 0, "classification_distribution": dict(Counter(c["classification"] for c in classifications)), "schema_type": relationship_analysis["schema_type"]}

    def _generate_summary(self, classifications: List[Dict[str, Any]], relationship_analysis: Dict[str, Any], model_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics."""
        counts = Counter(c["classification"] for c in classifications)
        return {"fact_tables": counts.get("FACT", 0), "dimension_tables": counts.get("DIMENSION", 0), "calculation_tables": counts.get("CALCULATION", 0), "bridge_tables": counts.get("BRIDGE", 0), "parameter_tables": counts.get("PARAMETER", 0), "unknown_tables": counts.get("UNKNOWN", 0), "total_measures": model_metrics["total_measures"], "total_columns": model_metrics["total_columns"], "schema_type": relationship_analysis["schema_type"]}


def parse_analysis(tmdl_dir: str, output_file: str = None) -> Dict[str, Any]:
    """Main function to parse Power BI semantic model analysis."""
    parser = AnalysisParser(tmdl_dir)
    analysis = parser.parse()
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
    return analysis


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python parse_analysis.py <tmdl_dir> [output_file]")
        sys.exit(1)
    tmdl_dir = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "classifications.json"
    analysis = parse_analysis(tmdl_dir, output_file)
    print(f"✓ Analysis complete | Schema: {analysis['relationship_analysis']['schema_type']}")