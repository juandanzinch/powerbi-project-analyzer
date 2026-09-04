#!/usr/bin/env python3
"""
Base class for documentation generators with shared utilities.

Provides:
- Data loading from JSON intermediates
- Common helper methods for escaping, analyzing unused items
- Column usage analysis
- Measures analysis
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocPaths:
    """Manages directory structure for outputs."""
    output_dir: Path

    @property
    def data_dir(self) -> Path:
        return self.output_dir / "data"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def graphs_dir(self) -> Path:
        return self.output_dir / "graphs"


class BaseDocumentationGenerator:
    """
    Base class for documentation generators.
    
    Provides:
    - Data loading from JSON intermediates
    - Helper methods for common operations
    - Analysis utilities (unused detection, column usage, etc.)
    """

    def __init__(self, output_dir: Path, pbip_name: str):
        self.paths = DocPaths(output_dir=Path(output_dir))
        self.pbip_name = pbip_name

        # Ensure expected folders exist
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.reports_dir.mkdir(parents=True, exist_ok=True)

        # Loaded data
        self.tables_raw: Any = []
        self.relationships_raw: Any = []
        self.measures_raw: Any = []
        self.pages_raw: Any = []
        self.datasources_raw: Any = []
        self.column_usage_raw: Any = []
        self.analysis_data: dict[str, Any] = {}
        self.unused_measures_raw: Any = {}

    # ============================
    # Data Loading
    # ============================
    
    def load_all_data(self) -> None:
        """Load all JSON intermediates from data/ directory."""
        self.tables_raw = self._load_json("tables.json", default=[])
        self.relationships_raw = self._load_json("relationships.json", default=[])
        self.measures_raw = self._load_json("measures.json", default=[])
        self.pages_raw = self._load_json("pages.json", default=[])
        self.datasources_raw = self._load_json("datasources.json", default=[])
        self.column_usage_raw = self._load_json("column_usage.json", default=[])
        self.analysis_data = self._load_json("classifications.json", default={})
        self.unused_measures_raw = self._load_json("unused_measures.json", default={})

        # Normalize data structures
        self.tables_data = self._as_list(self.tables_raw, "tables")
        self.relationships_data = self._as_list(self.relationships_raw, "relationships")
        self.measures_data = self._as_list(self.measures_raw, "measures")
        self.pages_data = self._as_list(self.pages_raw, "pages")
        self.column_usage_data = self._as_list(self.column_usage_raw, "column_usage")
        self.datasources_data = self._as_list(self.datasources_raw, "datasources")

    def _load_json(self, filename: str, default: Any) -> Any:
        """Load JSON file from data directory."""
        path = self.paths.data_dir / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return default

    def _as_list(self, data: Any, key: str) -> list[dict[str, Any]]:
        """
        Normalize parser outputs to list format.
        
        Supports:
        - Old contract: [...]
        - New contract: {"key": [...]}
        - Invalid/missing data: []
        """
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            values = data.get(key, [])
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]

        return []

    # ============================
    # Common Helpers
    # ============================

    def _escape_md_cell(self, value: Any) -> str:
        """Escape markdown table cell content."""
        text = "" if value is None else str(value)
        return text.replace("\n", " ").replace("|", "\\|").strip()

    def _get_summary(self, raw_data: Any) -> dict[str, Any]:
        """Extract summary section from structured parser outputs."""
        if isinstance(raw_data, dict):
            summary = raw_data.get("summary", {})
            if isinstance(summary, dict):
                return summary
        return {}

    def _get_issues(self, raw_data: Any) -> list[str]:
        """Extract issues section from structured parser outputs."""
        if isinstance(raw_data, dict):
            issues = raw_data.get("issues", [])
            if isinstance(issues, list):
                return [str(issue) for issue in issues]
        return []

    def _get_recommendations(self, raw_data: Any) -> list[str]:
        """Extract recommendations section from structured parser outputs."""
        if isinstance(raw_data, dict):
            recommendations = raw_data.get("recommendations", [])
            if isinstance(recommendations, list):
                return [str(item) for item in recommendations]
        return []

    # ============================
    # Table Column Usage
    # ============================

    def _get_table_usage_rows(self) -> list[dict[str, Any]]:
        """Return per-table usage rows from column_usage.json."""
        if isinstance(self.column_usage_data, dict):
            rows = self.column_usage_data.get("table_usage", [])
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def _get_table_usage_summary(self) -> dict[str, Any]:
        """Return table usage summary from column_usage.json."""
        if isinstance(self.column_usage_data, dict):
            summary = self.column_usage_data.get("summary", {})
            if isinstance(summary, dict):
                return summary
        return {}

    # ============================
    # Column Usage Analysis
    # ============================

    def _get_unused_columns_by_table(self, table_name: str) -> list[dict[str, Any]]:
        """Get unused columns for a specific table."""
        for table_usage in self.column_usage_data:
            if table_usage.get("table_name", "") == table_name:
                columns = table_usage.get("columns", [])
                return [c for c in columns if not c.get("is_used", True)]
        return []

    def _get_total_unused_columns(self) -> int:
        """Count total unused columns across all tables."""
        total = 0
        for table_usage in self.column_usage_data:
            total += table_usage.get("unused_columns", 0)
        return total

    def _get_column_usage_summary(self) -> dict[str, Any]:
        """Get overall column usage statistics."""
        total_columns = 0
        used_columns = 0
        unused_columns = 0
        tables_with_unused_cols = 0

        for table_usage in self.column_usage_data:
            total_columns += table_usage.get("total_columns", 0)
            used_columns += table_usage.get("used_columns", 0)
            unused_columns += table_usage.get("unused_columns", 0)
            
            if table_usage.get("unused_columns", 0) > 0:
                tables_with_unused_cols += 1

        overall_usage_pct = 0
        if total_columns > 0:
            overall_usage_pct = round(100 * used_columns / total_columns)

        return {
            "total_columns": total_columns,
            "used_columns": used_columns,
            "unused_columns": unused_columns,
            "usage_percentage": overall_usage_pct,
            "tables_with_unused": tables_with_unused_cols
        }

    def _get_tables_by_usage_percentage(self, limit: int = 5) -> list[tuple[str, int, int]]:
        """
        Get tables sorted by column usage percentage (lowest first).
        Returns: [(table_name, usage_percentage, unused_count), ...]
        """
        tables = []
        for table_usage in self._get_table_usage_rows():
            name = table_usage.get("table_name", "Unknown")
            usage_pct = table_usage.get("usage_percentage", 100)
            unused_cnt = table_usage.get("unused_columns", 0)
            tables.append((name, usage_pct, unused_cnt))
        
        tables.sort(key=lambda x: (x[1], -x[2]))
        return tables[:limit]

    # ============================
    # Measures Analysis
    # ============================

    def _get_measures_summary(self) -> dict[str, Any]:
        """Get overall measures statistics from unused_measures.json."""
        analysis = {}
        if isinstance(self.unused_measures_raw, dict):
            analysis = self.unused_measures_raw.get("analysis", {})
        
        return {
            "total_measures": analysis.get("total_measures", len(self.measures_data)),
            "used_measures": analysis.get("used_measures", 0),
            "unused_measures": analysis.get("unused_measures", 0),
            "unused_percentage": analysis.get("unused_percentage", 0.0),
        }

    def _get_unused_measures_list(self) -> list[dict[str, Any]]:
        """Get list of unused measures (cleanup candidates)."""
        if not isinstance(self.unused_measures_raw, dict):
            return []
        
        cleanup = self.unused_measures_raw.get("analysis", {})
        candidates = cleanup.get("cleanup_candidates", [])
        
        if isinstance(candidates, list):
            return [item for item in candidates if isinstance(item, dict)]
        
        return []

    def _get_unused_measures_by_complexity(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get unused measures sorted by complexity (highest first)."""
        unused = self._get_unused_measures_list()
        unused_sorted = sorted(unused, key=lambda x: x.get("complexity", 0), reverse=True)
        return unused_sorted[:limit]

    def _get_measures_by_table(self) -> dict[str, list[dict[str, Any]]]:
        """Group all measures by table."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for measure in self.measures_data:
            table = measure.get("table", "Unknown")
            grouped.setdefault(table, []).append(measure)
        return grouped
