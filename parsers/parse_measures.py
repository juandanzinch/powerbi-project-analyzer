from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "2.0.0"
SEVERITY_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Broad catalog for scoring. Function extraction is open-ended and does not
# discard functions absent from this catalog.
DAX_FUNCTION_WEIGHTS: Dict[str, float] = {
    "SUM": 1, "COUNT": 1, "AVERAGE": 1, "MIN": 1, "MAX": 1,
    "SELECTEDVALUE": 1.5, "COALESCE": 1.5, "ISBLANK": 1,
    "SUMX": 3, "AVERAGEX": 3, "COUNTX": 3, "MAXX": 3, "MINX": 3,
    "RANKX": 4, "CALCULATE": 3, "CALCULATETABLE": 3,
    "ALL": 2, "ALLEXCEPT": 2, "ALLSELECTED": 2, "KEEPFILTERS": 2,
    "FILTER": 3, "REMOVEFILTERS": 2, "RELATED": 2, "RELATEDTABLE": 2,
    "USERELATIONSHIP": 3, "CROSSFILTER": 3, "TREATAS": 3,
    "TOTALYTD": 3, "TOTALQTD": 3, "TOTALMTD": 3,
    "SAMEPERIODLASTYEAR": 3, "PREVIOUSYEAR": 3, "PREVIOUSMONTH": 3,
    "PARALLELPERIOD": 4, "DATEADD": 3, "DATESYTD": 3,
    "VALUES": 2, "DISTINCT": 2, "TOPN": 3, "ADDCOLUMNS": 4,
    "SELECTCOLUMNS": 3, "SUMMARIZE": 4, "UNION": 3, "ROW": 2,
    "CONCATENATEX": 3, "IF": 2, "IFERROR": 2, "SWITCH": 3,
    "DIVIDE": 1, "FORMAT": 2, "DATE": 1, "YEAR": 1, "MONTH": 1,
    "DAY": 1, "EDATE": 2, "EOMONTH": 2, "DATEDIFF": 2,
}
KEYWORDS = {"VAR", "RETURN", "TRUE", "FALSE", "BLANK", "ASC", "DESC", "IN"}
FUNCTION_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
QUALIFIED_COLUMN_RE = re.compile(
    r"(?:'(?P<qt>(?:[^']|'')+)'|(?P<ut>[A-Za-z_][\w .-]*?))\s*\[(?P<col>[^\]]+)\]"
)
BRACKET_RE = re.compile(r"\[(?P<name>[^\]]+)\]")
MEASURE_START_RE = re.compile(r"(?m)^\s*measure\s+(?P<name>'(?:[^']|'')+'|[^=\n]+?)\s*=\s*")
TABLE_DECL_RE = re.compile(r"(?m)^\s*table\s+(?P<name>'(?:[^']|'')+'|[^\n]+?)\s*$")
PROPERTY_RE = re.compile(
    r"(?m)^\s*(?P<key>description|displayFolder|formatString|lineageTag|isHidden|formatStringDefinition|annotation\s+[^=\n]+|changedProperty)\s*(?:=|:)\s*(?P<value>.*)$",
    re.IGNORECASE,
)
LOCAL_VIRTUAL_COLUMNS = {"AnchorDate", "StartDate", "EndDate", "Label", "Sort", "PeriodKind"}


def _unquote_name(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _mask_dax(text: str, mask_strings: bool = True) -> str:
    """Mask comments and optionally quoted strings while preserving positions."""
    out = list(text)
    i, n = 0, len(text)
    state = "code"
    while i < n:
        if state == "code":
            if text.startswith("//", i) or text.startswith("--", i):
                out[i:i+2] = "  "; i += 2; state = "line"
            elif text.startswith("/*", i):
                out[i:i+2] = "  "; i += 2; state = "block"
            elif text[i] == '"':
                if mask_strings: out[i] = " "
                i += 1; state = "string"
            else:
                i += 1
        elif state == "line":
            if text[i] in "\r\n": state = "code"
            else: out[i] = " "; i += 1
        elif state == "block":
            if text.startswith("*/", i):
                out[i:i+2] = "  "; i += 2; state = "code"
            else: out[i] = " "; i += 1
        else:
            if text[i] == '"':
                if i + 1 < n and text[i+1] == '"':
                    if mask_strings: out[i:i+2] = "  "
                    i += 2
                else:
                    if mask_strings: out[i] = " "
                    i += 1; state = "code"
            else:
                if mask_strings: out[i] = " "
                i += 1
    return "".join(out)


def _split_expression_and_properties(body: str) -> Tuple[str, Dict[str, Any]]:
    matches = list(PROPERTY_RE.finditer(body))
    if not matches:
        return body.strip(), {}
    expression = body[:matches[0].start()].strip()
    metadata: Dict[str, Any] = {"annotations": {}, "changed_properties": []}
    for index, match in enumerate(matches):
        key = match.group("key").strip()
        start = match.start("value")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[start:end].strip()
        low = key.lower()
        if low.startswith("annotation"):
            annotation_name = key.split(None, 1)[1].strip()
            try: metadata["annotations"][annotation_name] = json.loads(value)
            except (json.JSONDecodeError, TypeError): metadata["annotations"][annotation_name] = value
        elif low == "changedproperty":
            metadata["changed_properties"].append(value)
        else:
            normalized = {
                "displayfolder": "display_folder", "formatstring": "format_string",
                "formatstringdefinition": "format_string_definition",
                "lineagetag": "lineage_tag", "ishidden": "is_hidden",
            }.get(low, low)
            if normalized == "is_hidden": metadata[normalized] = value.lower() == "true"
            else: metadata[normalized] = value.strip().strip('"')
    if not metadata["annotations"]: metadata.pop("annotations")
    if not metadata["changed_properties"]: metadata.pop("changed_properties")
    return expression, metadata


class MeasureParser:
    def __init__(self, tmdl_dir: str):
        self.tmdl_dir = Path(tmdl_dir)
        self.columns_by_table = self._load_column_metadata()
        self.diagnostics: List[Dict[str, Any]] = []

    def parse(self, pages: Optional[List[Dict[str, Any]]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        raw = self._extract_raw_measures()
        names_by_table: Dict[str, Set[str]] = defaultdict(set)
        qualified_names: Set[str] = set()
        simple_to_qnames: Dict[str, List[str]] = defaultdict(list)
        for item in raw:
            qname = self._qname(item["table"], item["name"])
            names_by_table[item["table"]].add(item["name"])
            qualified_names.add(qname)
            simple_to_qnames[item["name"]].append(qname)

        measures = [self._analyze(item, names_by_table, simple_to_qnames) for item in raw]
        by_qname = {m["qualified_name"]: m for m in measures}
        self._build_graph(measures, by_qname)
        visual_refs = self._collect_visual_measure_refs(pages, simple_to_qnames) if pages is not None else None
        unreferenced, unused_summary = self._analyze_unreferenced(measures, visual_refs)
        summary = self._summary(measures, unused_summary, pages is not None)
        canonical = {
            "schema_version": SCHEMA_VERSION,
            "artifact": "measures",
            "analysis_scope": {
                "tmdl_metadata": {"status": "analyzed"},
                "dax_dependencies": {"status": "analyzed"},
                "dependency_graph": {"status": "analyzed"},
                "functions": {"status": "analyzed"},
                "complexity": {"status": "analyzed"},
                "antipatterns": {"status": "analyzed"},
                "report_usage": {"status": "analyzed" if pages is not None else "not_available"},
            },
            "summary": summary,
            "measures": measures,
            "diagnostics": {"warning_count": len(self.diagnostics), "warnings": self.diagnostics},
        }
        return canonical, unreferenced, summary

    def _extract_raw_measures(self) -> List[Dict[str, Any]]:
        measures: List[Dict[str, Any]] = []
        files = sorted(self.tmdl_dir.rglob("*.tmdl"))
        for path in files:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            table_match = TABLE_DECL_RE.search(text)
            file_table = _unquote_name(table_match.group("name")) if table_match else path.stem
            starts = list(MEASURE_START_RE.finditer(text))
            for index, start in enumerate(starts):
                end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
                body = text[start.end():end]
                # Stop before the next top-level table object when present.
                next_object = re.search(r"(?m)^\s*(column|partition|hierarchy|calculationItem)\s+", body)
                if next_object: body = body[:next_object.start()]
                expression, metadata = _split_expression_and_properties(body)
                name = _unquote_name(start.group("name"))
                measures.append({
                    "name": name, "table": file_table, "expression": expression,
                    "metadata": metadata, "source": {"file": str(path), "line": text.count("\n", 0, start.start()) + 1},
                })
        return measures

    def _load_column_metadata(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = defaultdict(set)
        for path in sorted(self.tmdl_dir.rglob("*.tmdl")):
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            table_match = TABLE_DECL_RE.search(text)
            table = _unquote_name(table_match.group("name")) if table_match else path.stem
            for match in re.finditer(r"(?m)^\s*column\s+('(?:[^']|'')+'|[^=\n]+?)(?:\s*=|\s*$)", text):
                result[table].add(_unquote_name(match.group(1)))
        return dict(result)

    def _analyze(self, raw: Dict[str, Any], names_by_table: Mapping[str, Set[str]], simple_to_qnames: Mapping[str, List[str]]) -> Dict[str, Any]:
        expression = raw["expression"]
        masked = _mask_dax(expression)
        functions = sorted({m.group(1).upper() for m in FUNCTION_RE.finditer(masked) if m.group(1).upper() not in KEYWORDS})
        columns: Set[Tuple[str, str]] = set()
        virtual: Set[str] = set()
        spans: List[Tuple[int, int]] = []
        for match in QUALIFIED_COLUMN_RE.finditer(masked):
            table = (match.group("qt") or match.group("ut") or "").replace("''", "'").strip()
            column = match.group("col").strip()
            columns.add((table, column)); spans.append(match.span())
        remainder = list(masked)
        for start, end in spans: remainder[start:end] = " " * (end - start)
        measure_dependencies: Set[str] = set()
        unresolved: Set[str] = set()
        for match in BRACKET_RE.finditer("".join(remainder)):
            name = match.group("name").strip()
            if name in LOCAL_VIRTUAL_COLUMNS:
                virtual.add(name); continue
            candidates = simple_to_qnames.get(name, [])
            if len(candidates) == 1: measure_dependencies.add(candidates[0])
            elif len(candidates) > 1:
                local = self._qname(raw["table"], name)
                if local in candidates: measure_dependencies.add(local)
                else: unresolved.add(name)
            else:
                owner_columns = self.columns_by_table.get(raw["table"], set())
                if name in owner_columns: columns.add((raw["table"], name))
                else: unresolved.add(name)
        column_items = [{"table": t, "name": c} for t, c in sorted(columns)]
        antipatterns = self._antipatterns(expression, masked, functions)
        expression_type = self._expression_type(expression)
        complexity = self._complexity(masked, functions, len(measure_dependencies), len(column_items), expression_type)
        metadata = {
            "description": raw["metadata"].get("description") or None,
            "display_folder": raw["metadata"].get("display_folder") or None,
            "format_string": raw["metadata"].get("format_string") or None,
            "format_string_definition": raw["metadata"].get("format_string_definition") or None,
            "lineage_tag": raw["metadata"].get("lineage_tag") or None,
            "is_hidden": bool(raw["metadata"].get("is_hidden", False)),
            "annotations": raw["metadata"].get("annotations", {}),
            "changed_properties": raw["metadata"].get("changed_properties", []),
        }
        return {
            "id": self._stable_id(raw["table"], raw["name"]),
            "qualified_name": self._qname(raw["table"], raw["name"]),
            "name": raw["name"], "table": raw["table"],
            "expression": expression, "expression_hash": hashlib.sha256(expression.encode("utf-8")).hexdigest(),
            "expression_type": expression_type, "metadata": metadata,
            "dependencies": {"measures": sorted(measure_dependencies), "columns": column_items, "virtual_columns": sorted(virtual), "unresolved": sorted(unresolved)},
            "analysis": {"functions": functions, "complexity_score": complexity, "antipatterns": antipatterns},
            "graph": {"dependency_depth": None, "dependents": [], "role": None, "cycle_member": False},
            "source": raw["source"],
        }

    def _build_graph(self, measures: List[Dict[str, Any]], by_qname: Mapping[str, Dict[str, Any]]) -> None:
        reverse: Dict[str, Set[str]] = defaultdict(set)
        for measure in measures:
            valid, unresolved = [], list(measure["dependencies"]["unresolved"])
            for dependency in measure["dependencies"]["measures"]:
                if dependency in by_qname:
                    valid.append(dependency); reverse[dependency].add(measure["qualified_name"])
                else: unresolved.append(dependency)
            measure["dependencies"]["measures"] = sorted(set(valid))
            measure["dependencies"]["unresolved"] = sorted(set(unresolved))

        state: Dict[str, int] = {}
        stack: List[str] = []
        cycle_nodes: Set[str] = set()
        def visit(node: str) -> None:
            state[node] = 1; stack.append(node)
            for dep in by_qname[node]["dependencies"]["measures"]:
                if state.get(dep, 0) == 0: visit(dep)
                elif state.get(dep) == 1:
                    cycle_nodes.update(stack[stack.index(dep):])
            stack.pop(); state[node] = 2
        for node in by_qname:
            if state.get(node, 0) == 0: visit(node)

        memo: Dict[str, int] = {}
        def depth(node: str, active: Set[str]) -> int:
            if node in memo: return memo[node]
            if node in active: return 0
            deps = by_qname[node]["dependencies"]["measures"]
            value = 0 if not deps else 1 + max(depth(dep, active | {node}) for dep in deps)
            memo[node] = value; return value

        for measure in measures:
            qname = measure["qualified_name"]
            dependents = sorted(reverse.get(qname, set()))
            deps = measure["dependencies"]["measures"]
            if not deps and dependents: role = "FOUNDATION"
            elif deps and dependents: role = "INTERMEDIATE"
            elif deps and not dependents: role = "LEAF"
            else: role = "BASE"
            measure["graph"] = {"dependency_depth": depth(qname, set()), "dependents": dependents, "role": role, "cycle_member": qname in cycle_nodes}
        if cycle_nodes:
            self.diagnostics.append({"code": "CIRCULAR_MEASURE_DEPENDENCY", "measures": sorted(cycle_nodes)})

    def _antipatterns(self, expression: str, masked: str, functions: Sequence[str]) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        expression_type = self._expression_type(expression)
        full_table_filters = len(re.findall(r"\bFILTER\s*\(\s*(?:ALL\s*\()?\s*'(?:[^']|'')+'\s*\)?\s*,", masked, re.I))
        if full_table_filters:
            findings.append({"code": "DAX001", "severity": "HIGH", "occurrences": full_table_filters, "message": "FILTER iterates a full table; review whether a narrower column/table expression is possible."})
        if expression_type == "DAX" and len(masked) > 500 and "VAR" not in masked.upper():
            findings.append({"code": "DAX003", "severity": "MEDIUM", "occurrences": 1, "message": "Long logical measure without VAR declarations."})
        if_count = len(re.findall(r"\bIF\s*\(", masked, re.I))
        if if_count >= 4:
            findings.append({"code": "DAX004", "severity": "MEDIUM", "occurrences": if_count, "message": "High IF density; review for reusable variables or SWITCH(TRUE())."})
        divisions = len(re.findall(r"(?<![/])/(?![/])", masked))
        if divisions:
            findings.append({"code": "DAX005", "severity": "LOW", "occurrences": divisions, "message": "Direct division operator detected; review DIVIDE() where the denominator can be zero."})
        return findings

    @staticmethod
    def _expression_type(expression: str) -> str:
        low = expression.lower()
        if "<style" in low or re.search(r"\.[\w-]+\s*\{[^}]+\}", expression): return "DAX_CSS"
        if any(tag in low for tag in ("<table", "<div", "<td", "<tr", "<th")): return "DAX_HTML"
        masked = _mask_dax(expression)
        if not masked.strip(): return "CONSTANT"
        if re.fullmatch(r"\s*(?:TRUE|FALSE)\s*\(\s*\)|[-+]?\d+(?:\.\d+)?\s*", masked, re.I): return "CONSTANT"
        return "DAX"

    @staticmethod
    def _complexity(masked: str, functions: Sequence[str], measure_deps: int, column_deps: int, expression_type: str) -> float:
        if expression_type in {"DAX_CSS", "CONSTANT"}: return round(1 + measure_deps * .5 + column_deps * .2, 2)
        function_score = sum(DAX_FUNCTION_WEIGHTS.get(fn, 2) for fn in functions)
        vars_count = len(re.findall(r"\bVAR\b", masked, re.I))
        return round(function_score + vars_count * .3 + measure_deps * .6 + column_deps * .2 + min(len(masked) / 1000, 20), 2)

    @staticmethod
    def _collect_visual_measure_refs(pages: Sequence[Dict[str, Any]], simple_to_qnames: Mapping[str, List[str]]) -> Set[str]:
        refs: Set[str] = set()
        def walk(obj: Any) -> None:
            if isinstance(obj, str):
                for match in BRACKET_RE.finditer(obj):
                    candidates = simple_to_qnames.get(match.group("name").strip(), [])
                    if len(candidates) == 1: refs.add(candidates[0])
            elif isinstance(obj, Mapping):
                for value in obj.values(): walk(value)
            elif isinstance(obj, list):
                for value in obj: walk(value)
        walk(pages)
        return refs

    def _analyze_unreferenced(self, measures: Sequence[Dict[str, Any]], visual_refs: Optional[Set[str]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        candidates = []
        for m in measures:
            graph_unreferenced = not m["graph"]["dependents"]
            report_status = None if visual_refs is None else m["qualified_name"] in visual_refs
            if graph_unreferenced and report_status is not True:
                if visual_refs is None: risk = "UNKNOWN"
                elif m["metadata"]["is_hidden"] and m["graph"]["role"] == "BASE": risk = "LOW"
                else: risk = "MEDIUM"
                candidates.append({"id": m["id"], "qualified_name": m["qualified_name"], "report_reference_detected": report_status, "cleanup_risk": risk, "reason": "No dependent measure or detected report reference within the analyzed scope."})
        return candidates, {"candidate_count": len(candidates), "report_analysis_status": "analyzed" if visual_refs is not None else "not_available"}

    def _summary(self, measures: Sequence[Dict[str, Any]], unused_summary: Dict[str, Any], report_analyzed: bool) -> Dict[str, Any]:
        roles = Counter(m["graph"]["role"] for m in measures)
        severity = Counter(a["severity"] for m in measures for a in m["analysis"]["antipatterns"])
        codes = Counter(a["code"] for m in measures for a in m["analysis"]["antipatterns"])
        highest = max(severity, key=lambda s: SEVERITY_ORDER.get(s, 0), default="NONE")
        unresolved = sum(len(m["dependencies"]["unresolved"]) for m in measures)
        edges = sum(len(m["dependencies"]["measures"]) for m in measures)
        return {
            "measure_count": len(measures),
            "tables_with_measures": len({m["table"] for m in measures}),
            "roles": dict(sorted(roles.items())),
            "documentation": {"with_description": sum(bool(m["metadata"]["description"]) for m in measures), "without_description": sum(not m["metadata"]["description"] for m in measures)},
            "quality": {"measures_with_antipatterns": sum(bool(m["analysis"]["antipatterns"]) for m in measures), "antipatterns_by_code": dict(sorted(codes.items())), "highest_severity": highest},
            "dependencies": {"measure_edges": edges, "max_depth": max((m["graph"]["dependency_depth"] for m in measures), default=0), "cycle_members": sum(m["graph"]["cycle_member"] for m in measures), "unresolved_references": unresolved},
            "unreferenced_assessment": unused_summary,
        }

    @staticmethod
    def _qname(table: str, name: str) -> str:
        return f"'{table.replace(chr(39), chr(39)*2)}'[{name}]"

    @staticmethod
    def _stable_id(table: str, name: str) -> str:
        return "measure_" + hashlib.sha1(f"{table}\0{name}".encode("utf-8")).hexdigest()[:12]


def _genai_projection(canonical: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    index, details, priority = [], [], []
    for m in canonical["measures"]:
        antipattern_codes = [a["code"] for a in m["analysis"]["antipatterns"]]
        item = {
            "id": m["id"], "qualified_name": m["qualified_name"],
            "role": m["graph"]["role"], "folder": m["metadata"]["display_folder"],
            "expression_type": m["expression_type"], "complexity": m["analysis"]["complexity_score"],
            "dependency_depth": m["graph"]["dependency_depth"],
            "measure_dependencies": m["dependencies"]["measures"],
            "column_dependencies": [f"'{x['table']}'[{x['name']}]" for x in m["dependencies"]["columns"]],
            "dependent_count": len(m["graph"]["dependents"]),
            "antipattern_codes": antipattern_codes,
        }
        index.append(item)
        detail = {
            "schema_version": f"{SCHEMA_VERSION}-ai-detail", "artifact": "measure_detail",
            "measure": {k: v for k, v in m.items() if k != "source"},
        }
        details.append((m["id"] + ".json", detail))
        reasons = []
        if m["analysis"]["complexity_score"] >= 50: reasons.append("HIGH_COMPLEXITY")
        if len(m["expression"]) >= 5000: reasons.append("LONG_EXPRESSION")
        if any(SEVERITY_ORDER.get(a["severity"], 0) >= 3 for a in m["analysis"]["antipatterns"]): reasons.append("HIGH_SEVERITY_ANTIPATTERN")
        if m["dependencies"]["unresolved"]: reasons.append("UNRESOLVED_REFERENCES")
        if m["graph"]["cycle_member"]: reasons.append("CIRCULAR_DEPENDENCY")
        if reasons: priority.append({"id": m["id"], "qualified_name": m["qualified_name"], "reason_codes": reasons})
    return ({"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "measures", "summary": canonical["summary"], "measures": index, "priority_review": priority}, details)


def parse_measures(tmdl_dir: str, output_file: Optional[str] = None, pages: Optional[List[Dict[str, Any]]] = None, output_dir: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Parse measures and write canonical plus GenAI outputs.

    ``output_file`` remains supported for the canonical artifact. Prefer
    ``output_dir`` to activate the complete Gen10 output structure.
    """
    parser = MeasureParser(tmdl_dir)
    canonical, unreferenced, summary = parser.parse(pages=pages)
    base = Path(output_dir) if output_dir else None
    canonical_path = Path(output_file) if output_file else (base / "measures.json" if base else None)
    if canonical_path: _write_json(canonical_path, canonical)
    if base:
        _write_json(base / "unused_measures.json", {"schema_version": SCHEMA_VERSION, "artifact": "unreferenced_measures", "semantics": "Candidates have no detected references within the analyzed scope; they are not automatic deletion recommendations.", "analysis_scope": canonical["analysis_scope"], "summary": summary["unreferenced_assessment"], "measures": unreferenced})
        ai_index, details = _genai_projection(canonical)
        _write_json(base / "data_to_genai" / "measures.json", ai_index)
        for filename, payload in details: _write_json(base / "data_to_genai" / "measure_details" / filename, payload)
        _write_json(base / "diagnostics" / "measure_parser_diagnostics.json", canonical["diagnostics"])
    # Backward-compatible return shape.
    return canonical["measures"], unreferenced, summary


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_pages_context(tmdl_dir: Path) -> Optional[List[Dict[str, Any]]]:
    definition = tmdl_dir if tmdl_dir.name == "definition" else tmdl_dir / "definition"
    semantic_model = definition.parent
    if semantic_model.name.endswith(".SemanticModel"):
        project_root = semantic_model.parent
        project_name = semantic_model.name[:-len(".SemanticModel")]
        candidates = [project_root / f"{project_name}.Report" / "definition" / "pages" / "pages.json", project_root / ".Report" / "definition" / "pages" / "pages.json"]
        for path in candidates:
            if path.exists():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, list): return [x for x in value if isinstance(x, dict)]
                except (OSError, json.JSONDecodeError): pass
    return None


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse Power BI TMDL measures for Gen10")
    cli.add_argument("tmdl_dir")
    cli.add_argument("--output-dir", default=None)
    cli.add_argument("--output-file", default=None)
    cli.add_argument("--load-pages", action="store_true")
    args = cli.parse_args()
    tmdl = Path(args.tmdl_dir)
    pages = _load_pages_context(tmdl) if args.load_pages else None
    parse_measures(str(tmdl), output_file=args.output_file, output_dir=args.output_dir, pages=pages)
