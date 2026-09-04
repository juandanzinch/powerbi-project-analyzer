from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "2.0.0"
ARTIFACT_NAME = "column_usage"
Reference = Tuple[str, str]

# Handles 'Table'[Column], Table[Column], and [Column]. The final form is
# resolved only when a reliable default table is available.
_QUALIFIED_REF = re.compile(
    r"(?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[A-Za-z_][\w .-]*?))\s*\[(?P<column>[^\]]+)\]"
)
_UNQUALIFIED_REF = re.compile(r"(?<![\w'\]])\[(?P<column>[^\]]+)\]")
_LOCAL_DATE_RE = re.compile(r"^(?:LocalDateTable|DateTableTemplate)_[0-9a-fA-F-]+$")


@dataclass(frozen=True)
class ScopeStatus:
    status: str
    reason: Optional[str] = None

    def as_dict(self) -> Dict[str, str]:
        result = {"status": self.status}
        if self.reason:
            result["reason"] = self.reason
        return result


class ColumnUsageParser:
    """Analyze references to model columns and emit canonical and AI views."""

    def __init__(self) -> None:
        self.tables: List[Dict[str, Any]] = []
        self.relationships: Optional[List[Dict[str, Any]]] = None
        self.measures: Optional[List[Dict[str, Any]]] = None
        self.pages: Optional[List[Dict[str, Any]]] = None
        self.warnings: List[Dict[str, Any]] = []

    def parse(
        self,
        tables: Optional[List[Dict[str, Any]]] = None,
        relationships: Optional[List[Dict[str, Any]]] = None,
        measures: Optional[List[Dict[str, Any]]] = None,
        pages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Return the canonical, auditable column-reference analysis.

        ``None`` means a domain was not supplied and is therefore unavailable.
        ``[]`` means it was analyzed and no objects/references were found.
        """
        self.tables = tables or []
        self.relationships = relationships
        self.measures = measures
        self.pages = pages
        self.warnings = []

        catalog, table_meta, column_meta = self._build_catalog(self.tables)
        source_refs: Dict[str, Set[Reference]] = {
            "measures": set(),
            "calculated_columns": set(),
            "calculated_tables": set(),
            "relationships": set(),
            "partitions": set(),
            "report": set(),
            "sort_by_columns": set(),
            "hierarchies": set(),
        }
        evidence: DefaultDict[Reference, DefaultDict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        if self.measures is not None:
            for measure in self.measures:
                owner = self._first_text(measure, "table", "table_name", "home_table")
                name = self._first_text(measure, "name", "measure_name") or "Unknown"
                refs = self._references_from_object(measure, catalog, owner)
                self._register(refs, "measures", {"object": name, "table": owner}, source_refs, evidence)

        # Columns, tables, partitions, sort-by columns and hierarchies are available
        # through the supplied table parser payload.
        for table in self.tables:
            table_name = str(table.get("name") or "Unknown")
            table_kind = self._table_type(table)

            for column in table.get("columns") or []:
                if not isinstance(column, Mapping):
                    continue
                column_name = str(column.get("name") or "")
                if not column_name:
                    continue
                if self._is_calculated_column(column):
                    refs = self._references_from_object(column, catalog, table_name)
                    self._register(
                        refs,
                        "calculated_columns",
                        {"object": column_name, "table": table_name},
                        source_refs,
                        evidence,
                    )
                sort_target = self._first_text(column, "sort_by_column", "sortByColumn", "sort_by")
                if sort_target:
                    refs = self._normalize_dependencies([sort_target], catalog, table_name)
                    self._register(
                        refs,
                        "sort_by_columns",
                        {"object": column_name, "table": table_name},
                        source_refs,
                        evidence,
                    )

            if table_kind == "CALCULATED_TABLE":
                refs = self._references_from_object(
                    {k: v for k, v in table.items() if k not in {"columns", "measures", "partitions"}},
                    catalog,
                    table_name,
                )
                self._register(
                    refs,
                    "calculated_tables",
                    {"object": table_name},
                    source_refs,
                    evidence,
                )

            for partition in table.get("partitions") or []:
                refs = self._references_from_object(partition, catalog, table_name)
                self._register(
                    refs,
                    "partitions",
                    {"object": self._first_text(partition, "name") or "Unknown", "table": table_name},
                    source_refs,
                    evidence,
                )

            for hierarchy in table.get("hierarchies") or []:
                refs = self._references_from_object(hierarchy, catalog, table_name)
                self._register(
                    refs,
                    "hierarchies",
                    {"object": self._first_text(hierarchy, "name") or "Unknown", "table": table_name},
                    source_refs,
                    evidence,
                )

        if self.relationships is not None:
            for relationship in self.relationships:
                refs = self._relationship_references(relationship, catalog)
                self._register(
                    refs,
                    "relationships",
                    {"object": self._first_text(relationship, "name") or "Unknown"},
                    source_refs,
                    evidence,
                )

        if self.pages is not None:
            for page in self.pages:
                page_name = self._first_text(page, "name", "display_name", "displayName") or "Unknown"
                refs = self._references_from_object(page, catalog, None)
                self._register(refs, "report", {"page": page_name}, source_refs, evidence)

        analyzed_sources = self._analyzed_sources()
        all_references: Set[Reference] = set().union(
            *(source_refs[source] for source in analyzed_sources)
        ) if analyzed_sources else set()
        catalog_refs = {(table, column) for table, columns in catalog.items() for column in columns}
        referenced = all_references & catalog_refs
        unresolved = all_references - catalog_refs
        for table, column in sorted(unresolved):
            self.warnings.append({
                "code": "REFERENCE_NOT_IN_CATALOG",
                "table": table,
                "column": column,
            })

        table_rows = self._build_table_rows(
            catalog, table_meta, column_meta, referenced, source_refs, evidence
        )
        summary = self._build_summary(catalog_refs, referenced, table_rows, source_refs)

        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": ARTIFACT_NAME,
            "semantics": {
                "reference_definition": (
                    "A column is referenced when at least one analyzed object depends on it."
                ),
                "unreferenced_definition": (
                    "No reference was detected within the declared analysis scope; this is not a deletion recommendation."
                ),
                "null_meaning": "The value is unavailable or not applicable; zero means analyzed and none found.",
            },
            "analysis_scope": self._analysis_scope(),
            "summary": summary,
            "references_by_source": {
                source: (len(source_refs[source] & catalog_refs) if source in analyzed_sources else None)
                for source in source_refs
            },
            "tables": table_rows,
            "diagnostics": {
                "warning_count": len(self.warnings),
                "warnings": self.warnings,
            },
        }

    def to_genai(self, canonical: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact, non-redundant GenAI projection."""
        compact_tables: List[Dict[str, Any]] = []
        auto_date_tables: List[Dict[str, Any]] = []

        for table in canonical.get("tables", []):
            compact = {
                "name": table["name"],
                "type": table["type"],
                "role": table["role"],
                "is_system_generated": table["is_system_generated"],
                "measure_count": table["measure_count"],
                "calculated_column_count": table["calculated_column_count"],
                "columns": {
                    "referenced": table["columns"]["referenced"],
                    "unreferenced": table["columns"]["unreferenced"],
                },
            }
            if table["columns"]["coverage_pct"] is None:
                compact["columns"]["coverage_pct"] = None
            if table["type"] == "AUTO_DATE_TABLE":
                auto_date_tables.append(compact)
            else:
                compact_tables.append(compact)

        result = {
            "schema_version": f"{SCHEMA_VERSION}-ai",
            "artifact": ARTIFACT_NAME,
            "scope": canonical["analysis_scope"],
            "summary": canonical["summary"],
            "references_by_source": canonical["references_by_source"],
            "tables": compact_tables,
        }
        if auto_date_tables:
            result["system_table_groups"] = [self._group_auto_date_tables(auto_date_tables)]
        if canonical.get("diagnostics", {}).get("warning_count"):
            result["diagnostics"] = {
                "warning_count": canonical["diagnostics"]["warning_count"],
                "review_canonical_output": True,
            }
        return result

    def _build_catalog(
        self, tables: Sequence[Dict[str, Any]]
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Dict[str, Any]], Dict[Reference, Dict[str, Any]]]:
        catalog: Dict[str, Set[str]] = defaultdict(set)
        table_meta: Dict[str, Dict[str, Any]] = {}
        column_meta: Dict[Reference, Dict[str, Any]] = {}
        for table in tables:
            name = str(table.get("name") or "Unknown")
            table_meta[name] = dict(table)
            for column in table.get("columns") or []:
                if not isinstance(column, Mapping):
                    continue
                column_name = str(column.get("name") or "")
                if column_name:
                    catalog[name].add(column_name)
                    column_meta[(name, column_name)] = dict(column)
            catalog.setdefault(name, set())
        return dict(catalog), table_meta, column_meta

    def _build_table_rows(
        self,
        catalog: Dict[str, Set[str]],
        table_meta: Dict[str, Dict[str, Any]],
        column_meta: Dict[Reference, Dict[str, Any]],
        referenced: Set[Reference],
        source_refs: Dict[str, Set[Reference]],
        evidence: Mapping[Reference, Mapping[str, List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for table_name in sorted(catalog, key=str.casefold):
            columns = catalog[table_name]
            referenced_names = sorted(
                (column for table, column in referenced if table == table_name), key=str.casefold
            )
            unreferenced_names = sorted(columns - set(referenced_names), key=str.casefold)
            total = len(columns)
            coverage = round(100 * len(referenced_names) / total, 1) if total else None
            meta = table_meta.get(table_name, {})
            rows.append({
                "name": table_name,
                "type": self._table_type(meta),
                "role": self._table_role(meta, table_name),
                "is_system_generated": self._is_system_table(meta, table_name),
                "measure_count": self._measure_count(meta),
                "calculated_column_count": self._calculated_column_count(meta),
                "columns": {
                    "total": total,
                    "referenced_count": len(referenced_names),
                    "unreferenced_count": len(unreferenced_names),
                    "coverage_pct": coverage,
                    "referenced": [
                        self._column_detail(table_name, name, column_meta, source_refs, evidence)
                        for name in referenced_names
                    ],
                    "unreferenced": unreferenced_names,
                },
            })
        return rows

    @staticmethod
    def _column_detail(
        table: str,
        column: str,
        column_meta: Dict[Reference, Dict[str, Any]],
        source_refs: Dict[str, Set[Reference]],
        evidence: Mapping[Reference, Mapping[str, List[Dict[str, Any]]]],
    ) -> Dict[str, Any]:
        ref = (table, column)
        detail: Dict[str, Any] = {
            "name": column,
            "sources": {
                source: len(evidence.get(ref, {}).get(source, []))
                for source, refs in source_refs.items()
                if ref in refs
            },
        }
        meta = column_meta.get(ref, {})
        if meta.get("data_type") or meta.get("dataType"):
            detail["data_type"] = meta.get("data_type") or meta.get("dataType")
        detail["evidence"] = {
            source: items for source, items in evidence.get(ref, {}).items() if items
        }
        return detail

    def _build_summary(
        self,
        catalog_refs: Set[Reference],
        referenced: Set[Reference],
        table_rows: Sequence[Dict[str, Any]],
        source_refs: Dict[str, Set[Reference]],
    ) -> Dict[str, Any]:
        total = len(catalog_refs)
        ref_count = len(referenced)
        applicable = [row for row in table_rows if row["columns"]["total"] > 0]
        avg = (
            round(sum(row["columns"]["coverage_pct"] for row in applicable) / len(applicable), 1)
            if applicable else None
        )
        return {
            "columns": {
                "total": total,
                "referenced": ref_count,
                "unreferenced": total - ref_count,
                "reference_coverage_pct": round(100 * ref_count / total, 1) if total else None,
            },
            "tables": {
                "total": len(table_rows),
                "with_columns": len(applicable),
                "without_columns": len(table_rows) - len(applicable),
                "fully_referenced": sum(
                    row["columns"]["coverage_pct"] == 100.0 for row in applicable
                ),
                "fully_unreferenced": sum(
                    row["columns"]["coverage_pct"] == 0.0 for row in applicable
                ),
                "avg_reference_coverage_pct": avg,
                "average_excludes_zero_column_tables": True,
            },
        }

    def _analysis_scope(self) -> Dict[str, Any]:
        table_status = "analyzed" if self.tables is not None else "not_available"
        return {
            "measures": ScopeStatus("analyzed" if self.measures is not None else "not_available").as_dict(),
            "calculated_columns": ScopeStatus(table_status).as_dict(),
            "calculated_tables": ScopeStatus(table_status).as_dict(),
            "relationships": ScopeStatus(
                "analyzed" if self.relationships is not None else "not_available"
            ).as_dict(),
            "partitions": ScopeStatus(table_status).as_dict(),
            "sort_by_columns": ScopeStatus(table_status).as_dict(),
            "hierarchies": ScopeStatus(table_status).as_dict(),
            "report": ScopeStatus(
                "analyzed" if self.pages is not None else "not_available",
                None if self.pages is not None else "No pages payload was supplied.",
            ).as_dict(),
            "roles": ScopeStatus("not_analyzed", "No roles payload is accepted by this parser version.").as_dict(),
            "perspectives": ScopeStatus(
                "not_analyzed", "No perspectives payload is accepted by this parser version."
            ).as_dict(),
        }

    def _analyzed_sources(self) -> Set[str]:
        scope = self._analysis_scope()
        return {name for name, value in scope.items() if value["status"] == "analyzed"}

    def _references_from_object(
        self,
        obj: Any,
        catalog: Dict[str, Set[str]],
        default_table: Optional[str],
    ) -> Set[Reference]:
        dependencies: List[Any] = []
        if isinstance(obj, Mapping):
            for key in (
                "column_dependencies", "columnDependencies", "dependencies",
                "referenced_columns", "referencedColumns", "fields",
            ):
                value = obj.get(key)
                if value:
                    dependencies.extend(value if isinstance(value, list) else [value])
        refs = self._normalize_dependencies(dependencies, catalog, default_table)
        refs.update(self._extract_refs_recursive(obj, catalog, default_table))
        return refs

    def _extract_refs_recursive(
        self, obj: Any, catalog: Dict[str, Set[str]], default_table: Optional[str]
    ) -> Set[Reference]:
        refs: Set[Reference] = set()
        if isinstance(obj, str):
            refs.update(self._extract_refs_from_text(obj, catalog, default_table))
        elif isinstance(obj, Mapping):
            for value in obj.values():
                refs.update(self._extract_refs_recursive(value, catalog, default_table))
        elif isinstance(obj, (list, tuple, set)):
            for value in obj:
                refs.update(self._extract_refs_recursive(value, catalog, default_table))
        return refs

    def _normalize_dependencies(
        self,
        dependencies: Iterable[Any],
        catalog: Dict[str, Set[str]],
        default_table: Optional[str],
    ) -> Set[Reference]:
        refs: Set[Reference] = set()
        for dependency in dependencies:
            if isinstance(dependency, Mapping):
                table = self._first_text(
                    dependency, "table", "table_name", "tableName", "from_table", "fromTable"
                ) or default_table
                column = self._first_text(
                    dependency, "column", "column_name", "columnName", "name", "field"
                )
                if table and column:
                    refs.add((table, column))
                else:
                    refs.update(self._extract_refs_recursive(dependency, catalog, default_table))
            elif isinstance(dependency, (list, tuple)) and len(dependency) == 2:
                refs.add((str(dependency[0]), str(dependency[1])))
            elif isinstance(dependency, str):
                parsed = self._extract_refs_from_text(dependency, catalog, default_table)
                if parsed:
                    refs.update(parsed)
                elif default_table and dependency in catalog.get(default_table, set()):
                    refs.add((default_table, dependency))
                else:
                    matches = [table for table, columns in catalog.items() if dependency in columns]
                    if len(matches) == 1:
                        refs.add((matches[0], dependency))
        return refs

    def _extract_refs_from_text(
        self, text: str, catalog: Dict[str, Set[str]], default_table: Optional[str]
    ) -> Set[Reference]:
        refs: Set[Reference] = set()
        spans: List[Tuple[int, int]] = []
        for match in _QUALIFIED_REF.finditer(text):
            table = (match.group("quoted") or match.group("plain") or "").replace("''", "'").strip()
            column = match.group("column").strip()
            if table and column:
                refs.add((table, column))
                spans.append(match.span())
        masked = list(text)
        for start, end in spans:
            masked[start:end] = " " * (end - start)
        for match in _UNQUALIFIED_REF.finditer("".join(masked)):
            column = match.group("column").strip()
            if default_table and column in catalog.get(default_table, set()):
                refs.add((default_table, column))
            else:
                candidate_tables = [table for table, columns in catalog.items() if column in columns]
                if len(candidate_tables) == 1:
                    refs.add((candidate_tables[0], column))
        return refs

    def _relationship_references(
        self, relationship: Mapping[str, Any], catalog: Dict[str, Set[str]]
    ) -> Set[Reference]:
        refs: Set[Reference] = set()
        pairs = (
            ("from_table", "from_column"), ("fromTable", "fromColumn"),
            ("to_table", "to_column"), ("toTable", "toColumn"),
        )
        for table_key, column_key in pairs:
            table = relationship.get(table_key)
            column = relationship.get(column_key)
            if table and column:
                refs.add((str(table), str(column)))
        refs.update(self._references_from_object(relationship, catalog, None))
        return refs

    @staticmethod
    def _register(
        refs: Set[Reference],
        source: str,
        context: Dict[str, Any],
        source_refs: Dict[str, Set[Reference]],
        evidence: DefaultDict[Reference, DefaultDict[str, List[Dict[str, Any]]]],
    ) -> None:
        source_refs[source].update(refs)
        for ref in refs:
            if context not in evidence[ref][source]:
                evidence[ref][source].append(context)

    @staticmethod
    def _first_text(obj: Mapping[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = obj.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _is_calculated_column(column: Mapping[str, Any]) -> bool:
        kind = str(column.get("column_kind") or column.get("kind") or "").upper()
        return bool(
            column.get("is_calculated")
            or kind in {"CALCULATED", "CALCULATED_COLUMN"}
            or column.get("expression")
            or column.get("dax_expression")
        )

    @staticmethod
    def _measure_count(table: Mapping[str, Any]) -> int:
        value = table.get("measure_count")
        return int(value) if value is not None else len(table.get("measures") or [])

    def _calculated_column_count(self, table: Mapping[str, Any]) -> int:
        value = table.get("calculated_column_count")
        if value is not None:
            return int(value)
        return sum(
            self._is_calculated_column(column)
            for column in table.get("columns") or []
            if isinstance(column, Mapping)
        )

    def _table_type(self, table: Mapping[str, Any]) -> str:
        name = str(table.get("name") or "")
        if _LOCAL_DATE_RE.match(name):
            return "AUTO_DATE_TABLE"
        raw = str(table.get("table_type") or table.get("table_kind") or table.get("kind") or "UNKNOWN").upper()
        aliases = {
            "CALCULATION": "MEASURE_CONTAINER",
            "PARAMETER": "FIELD_PARAMETER",
        }
        return aliases.get(raw, raw)

    def _table_role(self, table: Mapping[str, Any], name: str) -> str:
        explicit = table.get("role") or table.get("functional_role")
        if explicit:
            return str(explicit).upper()
        if _LOCAL_DATE_RE.match(name):
            return "DATE"
        measure_count = self._measure_count(table)
        column_count = len(table.get("columns") or [])
        if measure_count and column_count == 0:
            return "MEASURE_CONTAINER"
        if self._table_type(table) == "FIELD_PARAMETER":
            return "PARAMETER"
        return "UNKNOWN"

    @staticmethod
    def _is_system_table(table: Mapping[str, Any], name: str) -> bool:
        explicit = table.get("is_system_generated")
        return bool(explicit) if explicit is not None else bool(_LOCAL_DATE_RE.match(name))

    @staticmethod
    def _group_auto_date_tables(tables: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        referenced_patterns = {
            tuple(item["name"] for item in table["columns"]["referenced"])
            for table in tables
        }
        unreferenced_patterns = {
            tuple(table["columns"]["unreferenced"]) for table in tables
        }
        return {
            "type": "AUTO_DATE_TABLE",
            "table_count": len(tables),
            "table_names": [table["name"] for table in tables],
            "common_referenced_columns": list(next(iter(referenced_patterns)))
            if len(referenced_patterns) == 1 else None,
            "common_unreferenced_columns": list(next(iter(unreferenced_patterns)))
            if len(unreferenced_patterns) == 1 else None,
            "patterns_are_uniform": len(referenced_patterns) == 1 and len(unreferenced_patterns) == 1,
        }


def parse_column_usage(
    tables: Optional[List[Dict[str, Any]]] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
    measures: Optional[List[Dict[str, Any]]] = None,
    pages: Optional[List[Dict[str, Any]]] = None,
    output_file: Optional[str] = None,
    output_dir: Optional[str] = None,
    genai_output_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze column references and optionally write canonical and GenAI JSON.

    Compatibility:
    - ``output_file`` still writes the canonical JSON to an explicit path.

    Recommended Gen10 usage:
    - Set ``output_dir``. It writes the canonical artifact at the root and the
      optimized artifact to ``data_to_genai/column_usage.json``.
    """
    parser = ColumnUsageParser()
    canonical = parser.parse(
        tables=tables,
        relationships=relationships,
        measures=measures,
        pages=pages,
    )
    genai = parser.to_genai(canonical)

    canonical_path: Optional[Path] = Path(output_file) if output_file else None
    if output_dir:
        base = Path(output_dir)
        canonical_path = canonical_path or base / "column_usage.json"
        genai_path = Path(genai_output_file) if genai_output_file else base / "data_to_genai" / "column_usage.json"
    else:
        genai_path = Path(genai_output_file) if genai_output_file else None

    if canonical_path:
        _write_json(canonical_path, canonical)
    if genai_path:
        _write_json(genai_path, genai)

    return canonical


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False, sort_keys=False)
        file.write("\n")


if __name__ == "__main__":
    print("parse_column_usage.py - Gen10 column-reference analyzer")
    print("Call parse_column_usage(..., output_dir='<parser-output>') from main.py.")
    print("Canonical: <parser-output>/column_usage.json")
    print("GenAI:    <parser-output>/data_to_genai/column_usage.json")
