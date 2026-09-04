from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "2.0.0"
SEVERITY = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
LOCAL_DATE_RE = re.compile(r"^LocalDateTable_[0-9A-Fa-f-]+$")
REL_START_RE = re.compile(r"(?m)^\s*relationship\s+([^\s\n]+)\s*$")
PROP_RE = re.compile(r"(?m)^\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$")
TABLE_RE = re.compile(r"(?m)^\s*table\s+('(?:[^']|'')+'|[^\n]+?)\s*$")
COLUMN_RE = re.compile(r"(?m)^\s*column\s+('(?:[^']|'')+'|[^=\n]+?)(?:\s*=|\s*$)")


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


def _qcolumn(table: str, column: str) -> str:
    return "'{}'[{}]".format(table.replace("'", "''"), column)


def _stable_id(table1: str, col1: str, table2: str, col2: str) -> str:
    key = "\0".join((table1, col1, table2, col2))
    return "relationship_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "yes"}


def _parse_column_reference(value: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse TMDL table.column references while respecting quoted identifiers."""
    raw = value.strip()
    if not raw:
        return None, None, "EMPTY_REFERENCE"
    # Canonical DAX-like form: 'Table'[Column]
    match = re.fullmatch(r"'((?:[^']|'')+)'\[([^]]+)\]", raw)
    if match:
        return match.group(1).replace("''", "'"), match.group(2), None
    # TMDL form: 'Table Name'.'Column Name', Table.'Column', Table.Column.
    in_quote = False
    split_at = None
    i = 0
    while i < len(raw):
        char = raw[i]
        if char == "'":
            if in_quote and i + 1 < len(raw) and raw[i + 1] == "'":
                i += 2
                continue
            in_quote = not in_quote
        elif char == "." and not in_quote:
            split_at = i
            break
        i += 1
    if split_at is None:
        return None, None, "UNPARSABLE_REFERENCE"
    table = _unquote(raw[:split_at].strip().rstrip("'"))
    column = _unquote(raw[split_at + 1:].strip().lstrip("'"))
    if not table or not column:
        return None, None, "UNPARSABLE_REFERENCE"
    warning = "UNBALANCED_QUOTES" if raw.count("'") % 2 else None
    return table, column, warning


class RelationshipParser:
    def __init__(self, tmdl_dir: str):
        self.tmdl_dir = Path(tmdl_dir)
        self.relationships: List[Dict[str, Any]] = []
        self.issues: List[Dict[str, Any]] = []
        self.columns_by_table, self.table_metadata = self._load_model_metadata()

    def parse(self) -> List[Dict[str, Any]]:
        self.relationships = []
        files = self._relationship_files()
        if not files:
            self.issues.append({"code": "RELATIONSHIPS_FILE_NOT_FOUND", "severity": "ERROR", "path": str(self.tmdl_dir)})
            return []
        for path in files:
            text = _read(path)
            starts = list(REL_START_RE.finditer(text))
            for index, start in enumerate(starts):
                end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
                body = text[start.end():end]
                rel = self._parse_block(start.group(1), body, path, text.count("\n", 0, start.start()) + 1)
                if rel:
                    self.relationships.append(rel)
        self._enrich_graph_properties()
        return self.relationships

    def _relationship_files(self) -> List[Path]:
        preferred = self.tmdl_dir / "relationships.tmdl"
        if preferred.exists():
            return [preferred]
        return sorted(p for p in self.tmdl_dir.rglob("*.tmdl") if "relationship" in p.name.lower())

    def _load_model_metadata(self) -> Tuple[Dict[str, Set[str]], Dict[str, Dict[str, Any]]]:
        columns: Dict[str, Set[str]] = defaultdict(set)
        metadata: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self.tmdl_dir.rglob("*.tmdl")):
            if "relationship" in path.name.lower():
                continue
            text = _read(path)
            match = TABLE_RE.search(text)
            if not match:
                continue
            table = _unquote(match.group(1))
            for col in COLUMN_RE.finditer(text):
                columns[table].add(_unquote(col.group(1).strip()))
            metadata[table] = {
                "is_local_date": bool(LOCAL_DATE_RE.match(table)),
                "is_hidden": bool(re.search(r"(?m)^\s*isHidden\s*:\s*true\s*$", text, re.I)),
                "source_file": str(path),
            }
        return dict(columns), metadata

    def _parse_block(self, source_id: str, body: str, path: Path, line: int) -> Optional[Dict[str, Any]]:
        props = {m.group(1): m.group(2).strip() for m in PROP_RE.finditer(body)}
        raw_from, raw_to = props.get("fromColumn", ""), props.get("toColumn", "")
        from_table, from_column, from_warning = _parse_column_reference(raw_from)
        to_table, to_column, to_warning = _parse_column_reference(raw_to)
        if not all((from_table, from_column, to_table, to_column)):
            self.issues.append({
                "code": "RELATIONSHIP_ENDPOINT_PARSE_ERROR", "severity": "ERROR",
                "source_id": source_id, "fromColumn": raw_from, "toColumn": raw_to,
                "file": str(path), "line": line,
            })
            return None

        from_card = props.get("fromCardinality", "many").lower()
        to_card = props.get("toCardinality", "one").lower()
        behavior = props.get("crossFilteringBehavior", "singleDirection")
        security = props.get("securityFilteringBehavior")
        active = not _bool(props.get("isActive"), False) if props.get("isActive", "").lower() == "false" else True
        if "isActive" in props:
            active = _bool(props["isActive"], True)
        rely = _bool(props.get("relyOnReferentialIntegrity"), False)
        stable = _stable_id(from_table, from_column, to_table, to_column)
        pattern = self._classify_pattern(from_table, to_table, from_card, to_card)
        validation = self._validate(from_table, from_column, to_table, to_column)
        findings = self._findings(from_card, to_card, behavior, active, rely, from_table, to_table, validation)
        warnings = [x for x in (from_warning, to_warning) if x]
        if warnings:
            findings.append({"code": "REL008", "severity": "LOW", "message": "Endpoint source text contains non-canonical quoting.", "details": warnings})
        risk = max((f["severity"] for f in findings), key=lambda x: SEVERITY.get(x, 0), default="NONE")
        cardinality = self._cardinality_label(from_card, to_card)
        direction = "both" if behavior.lower() in {"bothdirections", "both"} else "single"
        return {
            "id": stable,
            "source_id": source_id,
            "from": {
                "table": from_table, "column": from_column,
                "qualified_name": _qcolumn(from_table, from_column),
                "table_type": self._table_type(from_table, from_card, to_card, side="from"),
            },
            "to": {
                "table": to_table, "column": to_column,
                "qualified_name": _qcolumn(to_table, to_column),
                "table_type": self._table_type(to_table, from_card, to_card, side="to"),
            },
            "cardinality": {"from": from_card, "to": to_card, "label": cardinality},
            "filtering": {"direction": direction, "behavior": behavior, "security_behavior": security},
            "state": {"is_active": active, "rely_on_referential_integrity": rely},
            "metadata": {"lineage_tag": props.get("lineageTag")},
            "classification": {
                "pattern": pattern,
                "is_local_date_relationship": self._is_local_date(from_table) or self._is_local_date(to_table),
                "is_parallel_relationship": False,
            },
            "validation": validation,
            "analysis": {"risk_level": risk, "findings": findings},
            "graph": {"from_degree": None, "to_degree": None, "component_id": None, "cycle_member": False},
            "raw": {"fromColumn": raw_from, "toColumn": raw_to, "properties": props},
            "source": {"file": str(path), "line": line},
        }

    def _validate(self, ft: str, fc: str, tt: str, tc: str) -> Dict[str, Optional[bool]]:
        # None means model metadata was unavailable, not validation failure.
        ft_known, tt_known = ft in self.columns_by_table, tt in self.columns_by_table
        return {
            "from_table_exists": ft_known if self.columns_by_table else None,
            "from_column_exists": fc in self.columns_by_table.get(ft, set()) if ft_known else None,
            "to_table_exists": tt_known if self.columns_by_table else None,
            "to_column_exists": tc in self.columns_by_table.get(tt, set()) if tt_known else None,
        }

    def _findings(self, fc: str, tc: str, behavior: str, active: bool, rely: bool, ft: str, tt: str, validation: Mapping[str, Optional[bool]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        many_many = fc == tc == "many"
        both = behavior.lower() in {"bothdirections", "both"}
        if many_many and both:
            result.append({"code": "REL003", "severity": "HIGH", "message": "Many-to-many relationship with bidirectional filtering."})
        elif many_many:
            result.append({"code": "REL001", "severity": "MEDIUM", "message": "Many-to-many relationship; validate bridge-table design and key uniqueness."})
        elif both:
            result.append({"code": "REL002", "severity": "MEDIUM", "message": "Bidirectional filtering can create ambiguous propagation paths."})
        if not active:
            result.append({"code": "REL004", "severity": "LOW", "message": "Inactive relationship; verify intentional use through USERELATIONSHIP or equivalent logic."})
        if self._is_local_date(ft) or self._is_local_date(tt):
            result.append({"code": "REL005", "severity": "LOW", "message": "Relationship uses an automatic local date table."})
        if any(value is False for value in validation.values()):
            result.append({"code": "REL006", "severity": "HIGH", "message": "One or more relationship endpoints were not found in model metadata."})
        if rely:
            result.append({"code": "REL007", "severity": "LOW", "message": "Referential integrity is enabled; ensure the source guarantees matching keys."})
        return result

    def _enrich_graph_properties(self) -> None:
        active = [r for r in self.relationships if r["state"]["is_active"]]
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        degrees: Counter[str] = Counter()
        pairs: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for rel in self.relationships:
            a, b = rel["from"]["table"], rel["to"]["table"]
            degrees[a] += 1; degrees[b] += 1
            pairs[tuple(sorted((a, b)))].append(rel)
        for rel in active:
            a, b = rel["from"]["table"], rel["to"]["table"]
            adjacency[a].add(b); adjacency[b].add(a)

        components: Dict[str, int] = {}
        component = 0
        for node in sorted(set(degrees)):
            if node in components: continue
            queue = deque([node]); components[node] = component
            while queue:
                current = queue.popleft()
                for neighbor in adjacency.get(current, set()):
                    if neighbor not in components:
                        components[neighbor] = component; queue.append(neighbor)
            component += 1

        cycle_nodes = self._cycle_nodes(adjacency)
        for rel in self.relationships:
            a, b = rel["from"]["table"], rel["to"]["table"]
            parallel = len(pairs[tuple(sorted((a, b)))]) > 1
            rel["classification"]["is_parallel_relationship"] = parallel
            rel["graph"] = {
                "from_degree": degrees[a], "to_degree": degrees[b],
                "component_id": components.get(a),
                "cycle_member": a in cycle_nodes and b in cycle_nodes,
            }
            if parallel:
                rel["analysis"]["findings"].append({"code": "REL009", "severity": "LOW", "message": "Multiple relationships exist between this pair of tables."})
            if rel["graph"]["cycle_member"] and rel["filtering"]["direction"] == "both":
                rel["analysis"]["findings"].append({"code": "REL010", "severity": "HIGH", "message": "Bidirectional relationship participates in an undirected table cycle."})
            rel["analysis"]["risk_level"] = max(
                (x["severity"] for x in rel["analysis"]["findings"]),
                key=lambda x: SEVERITY.get(x, 0), default="NONE"
            )

    @staticmethod
    def _cycle_nodes(graph: Mapping[str, Set[str]]) -> Set[str]:
        visited: Set[str] = set(); cycle: Set[str] = set()
        def dfs(node: str, parent: Optional[str], stack: List[str]) -> None:
            visited.add(node); stack.append(node)
            for nxt in graph.get(node, set()):
                if nxt == parent: continue
                if nxt not in visited:
                    dfs(nxt, node, stack)
                elif nxt in stack:
                    cycle.update(stack[stack.index(nxt):])
            stack.pop()
        for node in graph:
            if node not in visited: dfs(node, None, [])
        return cycle

    def table_summary(self) -> List[Dict[str, Any]]:
        data: Dict[str, Dict[str, Any]] = {}
        for rel in self.relationships:
            for endpoint, other in (("from", "to"), ("to", "from")):
                table = rel[endpoint]["table"]
                item = data.setdefault(table, {
                    "table": table, "table_type": rel[endpoint]["table_type"],
                    "relationship_count": 0, "active_count": 0, "inactive_count": 0,
                    "many_to_many_count": 0, "bidirectional_count": 0,
                    "connected_tables": set(), "degree": 0,
                })
                item["relationship_count"] += 1
                item["active_count" if rel["state"]["is_active"] else "inactive_count"] += 1
                item["many_to_many_count"] += rel["cardinality"]["label"] == "Many-to-Many"
                item["bidirectional_count"] += rel["filtering"]["direction"] == "both"
                item["connected_tables"].add(rel[other]["table"])
        result = []
        for item in data.values():
            item["connected_tables"] = sorted(item["connected_tables"])
            item["degree"] = len(item["connected_tables"])
            result.append(item)
        return sorted(result, key=lambda x: (-x["degree"], x["table"]))

    def summary(self) -> Dict[str, Any]:
        patterns = Counter(r["classification"]["pattern"] for r in self.relationships)
        risks = Counter(r["analysis"]["risk_level"] for r in self.relationships)
        findings = Counter(f["code"] for r in self.relationships for f in r["analysis"]["findings"])
        components = {r["graph"]["component_id"] for r in self.relationships}
        local_tables = {e["table"] for r in self.relationships for e in (r["from"], r["to"]) if self._is_local_date(e["table"])}
        return {
            "relationship_count": len(self.relationships),
            "active_relationship_count": sum(r["state"]["is_active"] for r in self.relationships),
            "inactive_relationship_count": sum(not r["state"]["is_active"] for r in self.relationships),
            "many_to_many_count": sum(r["cardinality"]["label"] == "Many-to-Many" for r in self.relationships),
            "bidirectional_count": sum(r["filtering"]["direction"] == "both" for r in self.relationships),
            "local_date_relationship_count": sum(r["classification"]["is_local_date_relationship"] for r in self.relationships),
            "local_date_table_count": len(local_tables),
            "referential_integrity_enabled_count": sum(r["state"]["rely_on_referential_integrity"] for r in self.relationships),
            "tables_in_graph": len({e["table"] for r in self.relationships for e in (r["from"], r["to"])}),
            "disconnected_component_count": len(components),
            "cycle_relationship_count": sum(r["graph"]["cycle_member"] for r in self.relationships),
            "relationships_by_pattern": dict(sorted(patterns.items())),
            "relationships_by_risk": dict(sorted(risks.items())),
            "findings_by_code": dict(sorted(findings.items())),
        }

    def canonical(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "artifact": "relationships",
            "analysis_scope": {
                "tmdl_metadata": {"status": "analyzed"},
                "endpoint_validation": {"status": "analyzed" if self.columns_by_table else "not_available"},
                "topology": {"status": "analyzed"},
                "measure_userelationship_usage": {"status": "not_analyzed"},
                "data_quality_uniqueness": {"status": "not_available"},
            },
            "summary": self.summary(), "relationships": self.relationships,
            "diagnostics": {"count": len(self.issues), "items": self.issues},
        }

    @staticmethod
    def _cardinality_label(from_card: str, to_card: str) -> str:
        labels = {("many", "one"): "Many-to-One", ("one", "many"): "One-to-Many", ("one", "one"): "One-to-One", ("many", "many"): "Many-to-Many"}
        return labels.get((from_card, to_card), f"{from_card.title()}-to-{to_card.title()}")

    def _is_local_date(self, table: str) -> bool:
        return bool(LOCAL_DATE_RE.match(table)) or bool(self.table_metadata.get(table, {}).get("is_local_date"))

    def _table_type(self, table: str, from_card: str, to_card: str, side: str) -> str:
        if self._is_local_date(table): return "LOCAL_DATE"
        low = table.lower()
        if "calendar" in low or low in {"date", "dates"}: return "DATE"
        if any(x in low for x in ("bridge", "mapping", "map")): return "BRIDGE"
        cardinality = from_card if side == "from" else to_card
        if cardinality == "one": return "DIMENSION"
        if cardinality == "many": return "FACT"
        return "UNKNOWN"

    def _classify_pattern(self, ft: str, tt: str, fc: str, tc: str) -> str:
        from_type = self._table_type(ft, fc, tc, "from")
        to_type = self._table_type(tt, fc, tc, "to")
        if "LOCAL_DATE" in {from_type, to_type}: return "FACT_TO_LOCAL_DATE"
        if "DATE" in {from_type, to_type}: return "FACT_TO_DATE"
        if "BRIDGE" in {from_type, to_type}: return "BRIDGE_PATTERN"
        if {from_type, to_type} == {"FACT", "DIMENSION"}: return "FACT_TO_DIMENSION"
        if from_type == to_type == "FACT": return "FACT_TO_FACT"
        if from_type == to_type == "DIMENSION": return "DIMENSION_TO_DIMENSION"
        return "UNKNOWN"


def _graph_artifact(parser: RelationshipParser) -> Dict[str, Any]:
    nodes = []
    for table in parser.table_summary():
        nodes.append({"id": table["table"], "table_type": table["table_type"], "degree": table["degree"]})
    edges = [{
        "id": r["id"], "source": r["from"]["table"], "target": r["to"]["table"],
        "active": r["state"]["is_active"], "cardinality": r["cardinality"]["label"],
        "filter_direction": r["filtering"]["direction"], "risk_level": r["analysis"]["risk_level"],
    } for r in parser.relationships]
    return {"schema_version": SCHEMA_VERSION, "artifact": "relationship_graph", "nodes": nodes, "edges": edges}


def _genai_index(parser: RelationshipParser) -> Dict[str, Any]:
    compact = []
    priority = []
    for r in parser.relationships:
        codes = [x["code"] for x in r["analysis"]["findings"]]
        compact.append({
            "id": r["id"], "from": r["from"]["qualified_name"], "to": r["to"]["qualified_name"],
            "cardinality": r["cardinality"]["label"], "filter_direction": r["filtering"]["direction"],
            "is_active": r["state"]["is_active"], "pattern": r["classification"]["pattern"],
            "risk_level": r["analysis"]["risk_level"], "finding_codes": codes,
        })
        if SEVERITY.get(r["analysis"]["risk_level"], 0) >= SEVERITY["MEDIUM"]:
            priority.append({"id": r["id"], "risk_level": r["analysis"]["risk_level"], "reason_codes": codes})
    return {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "relationships", "summary": parser.summary(), "relationships": compact, "priority_review": priority}


def parse_relationships(tmdl_dir: str, output_file: Optional[str] = None, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse relationships and optionally emit canonical and GenAI artifacts."""
    parser = RelationshipParser(tmdl_dir)
    relationships = parser.parse()
    canonical = parser.canonical()
    base = Path(output_dir) if output_dir else None
    target = Path(output_file) if output_file else (base / "relationships.json" if base else None)
    if target:
        _write(target, canonical if base else relationships)
    if base:
        _write(base / "relationship_graph.json", _graph_artifact(parser))
        _write(base / "diagnostics" / "relationships_parser_diagnostics.json", canonical["diagnostics"])
        _write(base / "data_to_genai" / "relationships.json", _genai_index(parser))
        _write(base / "data_to_genai" / "tables_relationship_summary.json", {
            "schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "tables_relationship_summary", "tables": parser.table_summary()
        })
        for relationship in relationships:
            _write(base / "data_to_genai" / "relationship_details" / f"{relationship['id']}.json", {
                "schema_version": f"{SCHEMA_VERSION}-ai-detail", "artifact": "relationship_detail", "relationship": relationship
            })
    return relationships


def get_relationship_list(result: Any) -> List[Dict[str, Any]]:
    """Return a list from legacy lists or canonical relationship artifacts."""
    if isinstance(result, list): return [x for x in result if isinstance(x, dict)]
    if isinstance(result, Mapping):
        value = result.get("relationships", [])
        return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
    return []


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse Power BI TMDL relationships")
    cli.add_argument("tmdl_dir")
    cli.add_argument("output_file", nargs="?", default=None)
    cli.add_argument("--output-dir", default=None)
    args = cli.parse_args()
    items = parse_relationships(args.tmdl_dir, args.output_file, args.output_dir)
    print(f"Parsed {len(items)} relationships")
