from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "2.0.0"
LOCAL_DATE_RE = re.compile(r"^LocalDateTable_[0-9A-Fa-f-]+$")
DATE_TEMPLATE_RE = re.compile(r"^DateTableTemplate_[0-9A-Fa-f-]+$")
SEVERITY = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _stable(prefix: str, *parts: str) -> str:
    key = "\0".join(str(x) for x in parts)
    return prefix + "_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "yes"}


def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return _unquote(value)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_top_blocks(text: str, keywords: Sequence[str]) -> List[Tuple[str, str, int, int, int]]:
    """Return top-level-ish TMDL blocks using declaration indentation."""
    key_pattern = "|".join(re.escape(x) for x in keywords)
    pattern = re.compile(rf"(?m)^(?P<indent>[ \t]*)(?P<kind>{key_pattern})\s+(?P<name>'(?:[^']|'')+'|[^\n=]+?)(?:\s*=.*)?\s*$")
    matches = list(pattern.finditer(text))
    blocks = []
    for i, match in enumerate(matches):
        indent = len(match.group("indent").expandtabs(4))
        end = len(text)
        for later in matches[i + 1:]:
            later_indent = len(later.group("indent").expandtabs(4))
            if later_indent <= indent:
                end = later.start()
                break
        blocks.append((match.group("kind"), _unquote(match.group("name").strip()), match.start(), match.end(), end))
    return blocks


def _properties(body: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", body):
        result[match.group(1)] = _clean_value(match.group(2))
    return result


def _expression_after_declaration(text: str, declaration_end: int, block_end: int) -> str:
    line_end = text.find("\n", declaration_end)
    if line_end < 0 or line_end >= block_end:
        return ""
    first_line = text[declaration_end:line_end]
    if "=" in first_line:
        return first_line.split("=", 1)[1].strip()
    body = text[line_end + 1:block_end]
    # TMDL multiline expressions are often fenced with triple backticks.
    fence = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", body, re.S)
    if fence:
        return fence.group(1).strip()
    expression = re.search(r"(?ms)^\s*expression\s*:\s*(.*?)(?=^\s*[A-Za-z_][A-Za-z0-9_]*\s*:|\Z)", body)
    return expression.group(1).strip() if expression else ""


class TableParser:
    def __init__(self, tmdl_dir: str):
        self.tmdl_dir = Path(tmdl_dir)
        self.tables: List[Dict[str, Any]] = []
        self.columns: List[Dict[str, Any]] = []
        self.measures: List[Dict[str, Any]] = []
        self.partitions: List[Dict[str, Any]] = []
        self.diagnostics: List[Dict[str, Any]] = []
        self.relationships: List[Dict[str, Any]] = []

    def parse(self, relationships: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        self.tables, self.columns, self.measures, self.partitions = [], [], [], []
        self.relationships = relationships or []
        files = self._table_files()
        if not files:
            self.diagnostics.append({"code": "TABLE_FILES_NOT_FOUND", "severity": "ERROR", "path": str(self.tmdl_dir)})
            return []
        for path in files:
            table = self._parse_file(path)
            if table:
                self.tables.append(table)
        self._apply_relationship_context()
        return self.tables

    def _table_files(self) -> List[Path]:
        tables_dir = self.tmdl_dir / "tables"
        if tables_dir.is_dir():
            return sorted(tables_dir.glob("*.tmdl"))
        return sorted(
            p for p in self.tmdl_dir.rglob("*.tmdl")
            if p.name.lower() not in {"relationships.tmdl", "model.tmdl", "database.tmdl", "cultures.tmdl", "roles.tmdl"}
            and re.search(r"(?m)^\s*table\s+", _read(p))
        )

    def _parse_file(self, path: Path) -> Optional[Dict[str, Any]]:
        text = _read(path)
        table_match = re.search(r"(?m)^\s*table\s+('(?:[^']|'')+'|[^\n]+?)\s*$", text)
        if not table_match:
            self.diagnostics.append({"code": "TABLE_DECLARATION_NOT_FOUND", "severity": "WARNING", "file": self._relative(path)})
            return None
        name = _unquote(table_match.group(1))
        table_id = _stable("table", name)
        props = _properties(text[: self._first_child_offset(text)])
        columns = self._parse_columns(text, path, table_id, name)
        measures = self._parse_measures(text, path, table_id, name)
        partitions = self._parse_partitions(text, path, table_id, name)
        annotations = self._parse_annotations(text, owner_indent=0)
        kind = self._classify_table(name, columns, measures, partitions, annotations)
        role = self._architectural_role(name, kind, columns)
        findings = self._table_findings(name, kind, columns, measures, partitions, props)
        risk = max((x["severity"] for x in findings), key=lambda x: SEVERITY.get(x, 0), default="NONE")
        data_types = Counter(c.get("data_type") or "unknown" for c in columns)
        source_types = sorted({p["source_type"] for p in partitions})
        storage_modes = sorted({p["mode"] for p in partitions})
        table = {
            "id": table_id,
            "name": name,
            "qualified_name": "'{}'".format(name.replace("'", "''")),
            "classification": {
                "table_kind": kind,
                "architectural_role": role,
                "is_measure_table": kind == "MEASURE_TABLE",
                "is_parameter": kind == "FIELD_PARAMETER",
                "is_local_date_table": kind == "LOCAL_DATE_TABLE",
                "is_date_template_table": kind == "DATE_TEMPLATE_TABLE",
                "is_date_table": role == "DATE",
                "is_disconnected": None,
            },
            "state": {"is_hidden": _bool(props.get("isHidden"), False)},
            "composition": {
                "column_count": len(columns), "measure_count": len(measures),
                "partition_count": len(partitions),
                "calculated_column_count": sum(c["is_calculated"] for c in columns),
                "hidden_column_count": sum(c["is_hidden"] for c in columns),
                "key_column_count": sum(c["is_key"] for c in columns),
            },
            "storage": {"modes": storage_modes, "source_types": source_types},
            "data_type_distribution": dict(sorted(data_types.items())),
            "column_refs": [c["id"] for c in columns],
            "measure_refs": [m["id"] for m in measures],
            "partition_refs": [p["id"] for p in partitions],
            "columns": columns,
            "measures": measures,
            "partitions": partitions,
            "annotations_summary": self._annotation_summary(annotations, columns, measures),
            "analysis": {
                "complexity_score": round(len(columns) * 0.4 + len(measures) * 0.7 + len(partitions) * 1.5 + sum(c["is_calculated"] for c in columns) * 1.2, 2),
                "risk_level": risk, "findings": findings,
            },
            "source": {"file": self._relative(path), "raw_size_chars": len(text)},
        }
        return table

    @staticmethod
    def _first_child_offset(text: str) -> int:
        positions = [m.start() for m in re.finditer(r"(?m)^\s+(?:column|measure|partition|hierarchy|annotation)\s+", text)]
        return min(positions) if positions else len(text)

    def _parse_columns(self, text: str, path: Path, table_id: str, table_name: str) -> List[Dict[str, Any]]:
        result = []
        for kind, name, start, declaration_end, end in _find_top_blocks(text, ("column",)):
            body = text[declaration_end:end]
            props = _properties(body)
            expression = _expression_after_declaration(text, declaration_end, end)
            is_calculated = bool(expression) or "sourceColumn" not in props
            column_id = _stable("column", table_name, name)
            item = {
                "id": column_id, "table_ref": table_id, "table": table_name,
                "name": name, "qualified_name": "'{}'[{}]".format(table_name.replace("'", "''"), name),
                "data_type": props.get("dataType"),
                "source_column": props.get("sourceColumn"),
                "format_string": props.get("formatString"),
                "summarize_by": props.get("summarizeBy"),
                "data_category": props.get("dataCategory"),
                "description": props.get("description"),
                "lineage_tag": props.get("lineageTag"),
                "source_lineage_tag": props.get("sourceLineageTag"),
                "is_calculated": is_calculated,
                "is_hidden": _bool(props.get("isHidden"), False),
                "is_key": _bool(props.get("isKey"), False),
                "semantic_role": self._semantic_role(name, props),
                "expression": expression,
                "annotations": self._parse_annotations(body),
                "source": {"file": self._relative(path), "line": _line_number(text, start)},
            }
            result.append(item); self.columns.append(item)
        return result

    def _parse_measures(self, text: str, path: Path, table_id: str, table_name: str) -> List[Dict[str, Any]]:
        result = []
        for kind, name, start, declaration_end, end in _find_top_blocks(text, ("measure",)):
            body = text[declaration_end:end]
            props = _properties(body)
            expression = _expression_after_declaration(text, declaration_end, end)
            measure_id = _stable("measure", table_name, name)
            item = {
                "id": measure_id, "table_ref": table_id, "table": table_name,
                "name": name, "qualified_name": "'{}'[{}]".format(table_name.replace("'", "''"), name),
                "format_string": props.get("formatString"),
                "display_folder": props.get("displayFolder"),
                "description": props.get("description"),
                "lineage_tag": props.get("lineageTag"),
                "is_hidden": _bool(props.get("isHidden"), False),
                "expression_available": bool(expression),
                "expression_preview": expression[:500] if expression else "",
                "annotations": self._parse_annotations(body),
                "source": {"file": self._relative(path), "line": _line_number(text, start)},
            }
            result.append(item); self.measures.append(item)
        return result

    def _parse_partitions(self, text: str, path: Path, table_id: str, table_name: str) -> List[Dict[str, Any]]:
        result = []
        for kind, name, start, declaration_end, end in _find_top_blocks(text, ("partition",)):
            body = text[declaration_end:end]
            props = _properties(body)
            expression = _expression_after_declaration(text, declaration_end, end)
            mode = str(props.get("mode") or "import").lower()
            source_type = self._partition_source_type(body + "\n" + expression)
            partition_id = _stable("partition", table_name, name)
            item = {
                "id": partition_id, "table_ref": table_id, "table": table_name,
                "name": name, "mode": mode, "source_type": source_type,
                "has_m_expression": source_type in {"POWER_QUERY", "SQL", "DATABRICKS", "FABRIC", "EXCEL", "CSV_TEXT", "WEB_SHAREPOINT"},
                "has_datatable": bool(re.search(r"\bDATATABLE\s*\(", expression, re.I)),
                "is_calculated": source_type in {"DAX_CALCULATED", "FIELD_PARAMETER"},
                "expression_available": bool(expression),
                "source_preview": re.sub(r"\s+", " ", expression)[:500],
                "source": {"file": self._relative(path), "line": _line_number(text, start)},
            }
            result.append(item); self.partitions.append(item)
        return result

    @staticmethod
    def _partition_source_type(text: str) -> str:
        low = text.lower()
        if "nameof(" in low and re.search(r"source\s*=\s*\{", low): return "FIELD_PARAMETER"
        if re.search(r"\b(?:calendar|calendarauto|datatable|generate|selectcolumns|union)\s*\(", text, re.I) and "let" not in low: return "DAX_CALCULATED"
        if "databricks.catalogs" in low: return "DATABRICKS"
        if "sql.database" in low: return "FABRIC" if "fabric.microsoft.com" in low else "SQL"
        if "excel.workbook" in low: return "EXCEL"
        if "csv.document" in low: return "CSV_TEXT"
        if "sharepoint." in low or "web.contents" in low: return "WEB_SHAREPOINT"
        if re.search(r"\bsource\s*=\s*let\b", low) or "table.fromrows" in low: return "POWER_QUERY"
        if re.search(r"\bsource\s*=", low): return "UNKNOWN"
        return "NONE"

    def _classify_table(self, name: str, columns: Sequence[Mapping[str, Any]], measures: Sequence[Mapping[str, Any]], partitions: Sequence[Mapping[str, Any]], annotations: Sequence[Mapping[str, Any]]) -> str:
        if LOCAL_DATE_RE.match(name): return "LOCAL_DATE_TABLE"
        if DATE_TEMPLATE_RE.match(name) or any(a.get("name") == "__PBI_TemplateDateTable" for a in annotations): return "DATE_TEMPLATE_TABLE"
        if any(p["source_type"] == "FIELD_PARAMETER" for p in partitions): return "FIELD_PARAMETER"
        if measures and (not columns or len(columns) <= 1) and all(p["source_type"] in {"POWER_QUERY", "NONE", "UNKNOWN"} for p in partitions): return "MEASURE_TABLE"
        modes = {p["mode"] for p in partitions}
        sources = {p["source_type"] for p in partitions}
        if len(modes) > 1 or ({"import", "directquery"} <= modes): return "HYBRID_TABLE"
        if sources and sources <= {"DAX_CALCULATED"}: return "CALCULATED_TABLE"
        if "directquery" in modes: return "DIRECTQUERY_TABLE"
        if partitions: return "IMPORTED_TABLE"
        return "UNKNOWN"

    @staticmethod
    def _architectural_role(name: str, kind: str, columns: Sequence[Mapping[str, Any]]) -> str:
        low = name.lower()
        if kind in {"LOCAL_DATE_TABLE", "DATE_TEMPLATE_TABLE"} or "calendar" in low or low in {"date", "dates"}: return "DATE"
        if kind == "MEASURE_TABLE": return "MEASURES"
        if kind == "FIELD_PARAMETER" or "parameter" in low: return "PARAMETER"
        if any(x in low for x in ("mapping", "bridge", "xref")): return "BRIDGE"
        if any(x in low for x in ("fact", "transaction", "statement", "statistics", "profile")) or len(columns) >= 25: return "FACT"
        if any(x in low for x in ("dim_", "dimension", "hierarchy", "reference", "lookup")): return "DIMENSION"
        return "AUXILIARY"

    def _table_findings(self, name: str, kind: str, columns: Sequence[Mapping[str, Any]], measures: Sequence[Mapping[str, Any]], partitions: Sequence[Mapping[str, Any]], props: Mapping[str, Any]) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        if len(columns) >= 75: findings.append({"code": "TAB001", "severity": "MEDIUM", "message": "Wide table with at least 75 columns."})
        if len(measures) >= 100: findings.append({"code": "TAB002", "severity": "MEDIUM", "message": "High concentration of measures in one table."})
        if kind in {"LOCAL_DATE_TABLE", "DATE_TEMPLATE_TABLE"}: findings.append({"code": "TAB003", "severity": "LOW", "message": "Automatic date table metadata detected."})
        if columns and not any(c["is_hidden"] for c in columns) and len(columns) >= 20: findings.append({"code": "TAB004", "severity": "LOW", "message": "Large table has no hidden columns; review report-facing metadata."})
        if columns and not any(c["is_key"] for c in columns) and self._architectural_role(name, kind, columns) in {"DIMENSION", "DATE"}: findings.append({"code": "TAB005", "severity": "LOW", "message": "Dimension-like table has no declared key column."})
        if any(p["source_type"] == "UNKNOWN" for p in partitions): findings.append({"code": "TAB006", "severity": "LOW", "message": "Partition source type could not be classified."})
        if len(partitions) > 1: findings.append({"code": "TAB007", "severity": "LOW", "message": "Table contains multiple partitions; review consistency of storage and source definitions."})
        missing_expr = sum(not m["expression_available"] for m in measures)
        if missing_expr: findings.append({"code": "TAB008", "severity": "MEDIUM", "message": "One or more measures have no parsed expression.", "count": missing_expr})
        return findings

    @staticmethod
    def _semantic_role(name: str, props: Mapping[str, Any]) -> str:
        if _bool(props.get("isKey"), False): return "KEY"
        dtype = str(props.get("dataType") or "").lower()
        category = str(props.get("dataCategory") or "").lower()
        low = name.lower()
        if dtype == "boolean" or low.startswith("is") or low.endswith("flag"): return "FLAG"
        if dtype in {"datetime", "date"} or "date" in category: return "DATE"
        if dtype in {"int64", "double", "decimal", "currency"}: return "NUMERIC"
        return "ATTRIBUTE"

    @staticmethod
    def _parse_annotations(text: str, owner_indent: int = 0) -> List[Dict[str, Any]]:
        result = []
        for match in re.finditer(r"(?m)^\s*annotation\s+('(?:[^']|'')+'|[^=\n]+?)\s*=\s*(.*?)\s*$", text):
            result.append({"name": _unquote(match.group(1).strip()), "value": _clean_value(match.group(2))})
        return result

    @staticmethod
    def _annotation_summary(table_annotations: Sequence[Mapping[str, Any]], columns: Sequence[Mapping[str, Any]], measures: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        grouped: Dict[str, Dict[str, Any]] = {}
        all_items = list(table_annotations)
        for obj in list(columns) + list(measures): all_items.extend(obj.get("annotations", []))
        for annotation in all_items:
            name, value = str(annotation.get("name")), annotation.get("value")
            item = grouped.setdefault(name, {"count": 0, "values": []})
            item["count"] += 1
            if value not in item["values"]: item["values"].append(value)
        return dict(sorted(grouped.items()))

    def _apply_relationship_context(self) -> None:
        connected: Counter[str] = Counter()
        for rel in self.relationships:
            if "from" in rel:
                a = rel.get("from", {}).get("table"); b = rel.get("to", {}).get("table")
            else:
                a = rel.get("from_table"); b = rel.get("to_table")
            if a: connected[a] += 1
            if b: connected[b] += 1
        if not self.relationships: return
        for table in self.tables:
            table["classification"]["is_disconnected"] = connected[table["name"]] == 0
            table["analysis"]["relationship_count"] = connected[table["name"]]
            if connected[table["name"]] == 0 and table["classification"]["table_kind"] not in {"MEASURE_TABLE", "FIELD_PARAMETER"}:
                table["analysis"]["findings"].append({"code": "TAB009", "severity": "INFO", "message": "Table is disconnected from the supplied relationship graph; this may be intentional."})

    def summary(self) -> Dict[str, Any]:
        kinds = Counter(t["classification"]["table_kind"] for t in self.tables)
        roles = Counter(t["classification"]["architectural_role"] for t in self.tables)
        modes = Counter(mode for t in self.tables for mode in t["storage"]["modes"])
        sources = Counter(source for t in self.tables for source in t["storage"]["source_types"])
        risks = Counter(t["analysis"]["risk_level"] for t in self.tables)
        return {
            "table_count": len(self.tables), "column_count": len(self.columns),
            "measure_count": len(self.measures), "partition_count": len(self.partitions),
            "calculated_column_count": sum(c["is_calculated"] for c in self.columns),
            "hidden_table_count": sum(t["state"]["is_hidden"] for t in self.tables),
            "hidden_column_count": sum(c["is_hidden"] for c in self.columns),
            "local_date_table_count": kinds.get("LOCAL_DATE_TABLE", 0),
            "date_template_table_count": kinds.get("DATE_TEMPLATE_TABLE", 0),
            "field_parameter_count": kinds.get("FIELD_PARAMETER", 0),
            "measure_table_count": kinds.get("MEASURE_TABLE", 0),
            "tables_by_kind": dict(sorted(kinds.items())),
            "tables_by_role": dict(sorted(roles.items())),
            "tables_by_storage_mode": dict(sorted(modes.items())),
            "tables_by_source_type": dict(sorted(sources.items())),
            "tables_by_risk": dict(sorted(risks.items())),
        }

    def canonical_tables(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "artifact": "tables",
            "analysis_scope": {
                "table_metadata": {"status": "analyzed"},
                "columns": {"status": "analyzed"},
                "partitions": {"status": "analyzed"},
                "column_usage": {"status": "not_analyzed", "artifact": "column_usage.json"},
                "relationships": {"status": "analyzed" if self.relationships else "not_supplied"},
            },
            "summary": self.summary(), "tables": self.tables,
            "diagnostics": {"count": len(self.diagnostics), "items": self.diagnostics},
        }

    def _relative(self, path: Path) -> str:
        try: return path.relative_to(self.tmdl_dir).as_posix()
        except ValueError: return path.name


def _compact_table(table: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": table["id"], "name": table["name"],
        "table_kind": table["classification"]["table_kind"],
        "architectural_role": table["classification"]["architectural_role"],
        "is_hidden": table["state"]["is_hidden"],
        "is_disconnected": table["classification"]["is_disconnected"],
        "composition": table["composition"], "storage": table["storage"],
        "risk_level": table["analysis"]["risk_level"],
        "finding_codes": [f["code"] for f in table["analysis"]["findings"]],
        "source_file": table["source"]["file"],
    }


def parse_tables(tmdl_dir: str, output_file: Optional[str] = None, relationships: Optional[List[Dict[str, Any]]] = None, measures: Optional[List[Dict[str, Any]]] = None, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse TMDL tables and optionally emit canonical and GenAI artifacts.

    ``measures`` is accepted for backward compatibility. The parser creates its
    own stable measure references; detailed DAX analysis remains in measures.json.
    """
    parser = TableParser(tmdl_dir)
    tables = parser.parse(relationships=relationships)
    canonical = parser.canonical_tables()
    base = Path(output_dir) if output_dir else None
    target = Path(output_file) if output_file else (base / "tables.json" if base else None)
    if target: _write(target, canonical if base else tables)
    if base:
        _write(base / "columns.json", {"schema_version": SCHEMA_VERSION, "artifact": "columns", "summary": {"column_count": len(parser.columns)}, "columns": parser.columns})
        _write(base / "partitions.json", {"schema_version": SCHEMA_VERSION, "artifact": "partitions", "summary": {"partition_count": len(parser.partitions)}, "partitions": parser.partitions})
        _write(base / "diagnostics" / "tables_parser_diagnostics.json", canonical["diagnostics"])
        compact_tables = [_compact_table(t) for t in tables]
        _write(base / "data_to_genai" / "tables.json", {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "tables", "summary": parser.summary(), "tables": compact_tables, "priority_review": [t for t in compact_tables if SEVERITY.get(t["risk_level"], 0) >= SEVERITY["MEDIUM"]]})
        _write(base / "data_to_genai" / "columns.json", {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "columns", "columns": [{k: c.get(k) for k in ("id", "table_ref", "table", "name", "qualified_name", "data_type", "semantic_role", "is_calculated", "is_hidden", "is_key")} for c in parser.columns]})
        _write(base / "data_to_genai" / "partitions.json", {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "partitions", "partitions": [{k: p.get(k) for k in ("id", "table_ref", "table", "name", "mode", "source_type", "has_m_expression", "has_datatable", "is_calculated")} for p in parser.partitions]})
        for table in tables:
            _write(base / "data_to_genai" / "table_details" / f"{table['id']}.json", {"schema_version": f"{SCHEMA_VERSION}-ai-detail", "artifact": "table_detail", "table": table})
    return tables


def get_table_list(result: Any) -> List[Dict[str, Any]]:
    """Return tables from either the legacy list or canonical artifact."""
    if isinstance(result, list): return [x for x in result if isinstance(x, dict)]
    if isinstance(result, Mapping):
        value = result.get("tables", [])
        return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
    return []


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse Power BI TMDL tables")
    cli.add_argument("tmdl_dir")
    cli.add_argument("output_file", nargs="?", default=None)
    cli.add_argument("--output-dir", default=None)
    args = cli.parse_args()
    result = parse_tables(args.tmdl_dir, args.output_file, output_dir=args.output_dir)
    print(f"Parsed {len(result)} tables")
