from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "2.0.0"

CHART_TYPES = {
    "columnChart", "lineChart", "areaChart", "barChart", "scatterChart",
    "bubbleChart", "donutChart", "pieChart", "waterfallChart", "ribbonChart",
    "gaugeChart", "lineClusteredColumnComboChart", "lineStackedColumnComboChart",
    "columnClusteredLineChart", "columnStackedLineChart", "comboChart",
    "clusteredBarChart", "stackedBarChart", "clusteredColumnChart",
    "stackedColumnChart", "stackedAreaChart", "clusteredAreaChart", "funnelChart",
    "treemap", "treemapChart", "radialGaugeChart", "smallMultiple",
}
TABLE_TYPES = {"table", "tableEx", "pivotTable", "matrix"}
SLICER_TYPES = {"slicer", "ChicletSlicer1448559807354", "timeSlicer", "advancedSlicerVisual"}
BUTTON_TYPES = {"actionButton", "button", "pageNavigator", "bookmarkNavigator"}
TEXT_TYPES = {"textbox", "shape"}
CARD_TYPES = {"cardVisual", "card", "multiRowCard", "KPI"}
OTHER_KNOWN_TYPES = {"image", "gauge", "advancedtoggleswitch"}

TYPE_LABELS = {
    "columnChart": "Column Chart", "lineChart": "Line Chart",
    "areaChart": "Area Chart", "barChart": "Bar Chart",
    "waterfallChart": "Waterfall Chart", "scatterChart": "Scatter Plot",
    "bubbleChart": "Bubble Chart", "pieChart": "Pie Chart",
    "donutChart": "Donut Chart", "ribbonChart": "Ribbon Chart",
    "gaugeChart": "Gauge", "pivotTable": "Matrix", "tableEx": "Table",
    "lineClusteredColumnComboChart": "Line and Column Chart",
}


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "\0".join(str(x) for x in parts)
    return f"{prefix}_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _iter_nodes(value: Any, path: Tuple[str, ...] = ()) -> Iterable[Tuple[Tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _iter_nodes(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_nodes(child, path + (str(index),))


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


class PageParser:
    def __init__(self, pbip_root: str, project_name: Optional[str] = None):
        self.pbip_root = Path(pbip_root)
        self.project_name = project_name
        self.report_dir = self._find_report_dir()
        self.pages: List[Dict[str, Any]] = []
        self.visuals: List[Dict[str, Any]] = []
        self.diagnostics: List[Dict[str, Any]] = []

    def _find_report_dir(self) -> Path:
        root = self.pbip_root
        if root.name == "definition" and root.parent.name.endswith(".Report"):
            return root
        if root.name.endswith(".Report"):
            return root / "definition"
        if self.project_name:
            exact = root / f"{self.project_name}.Report" / "definition"
            if exact.is_dir():
                return exact
        reports = sorted(p for p in root.glob("*.Report") if p.is_dir()) if root.is_dir() else []
        if len(reports) == 1:
            return reports[0] / "definition"
        if len(reports) > 1:
            self.diagnostics.append({
                "code": "MULTIPLE_REPORT_FOLDERS", "severity": "WARNING",
                "message": "Multiple .Report folders found. Supply project_name for deterministic selection.",
                "candidates": [str(x) for x in reports],
            })
        return root / "Report" / "definition"

    def parse(self) -> List[Dict[str, Any]]:
        self.pages = []
        self.visuals = []
        if not self.report_dir.is_dir():
            self.diagnostics.append({"code": "REPORT_DIR_NOT_FOUND", "severity": "ERROR", "path": str(self.report_dir)})
            return []
        pages_dir = self.report_dir / "pages"
        if not pages_dir.is_dir():
            self.diagnostics.append({"code": "PAGES_DIR_NOT_FOUND", "severity": "ERROR", "path": str(pages_dir)})
            return []
        order = self._get_page_order(pages_dir)
        for ordinal, page_name in enumerate(order):
            page = self._parse_page(pages_dir, page_name, ordinal)
            if page:
                self.pages.append(page)
        return self.pages

    def _get_page_order(self, pages_dir: Path) -> List[str]:
        metadata = _read_json(pages_dir / "pages.json")
        order: List[str] = []
        if isinstance(metadata, Mapping):
            candidate = metadata.get("pageOrder", [])
            if isinstance(candidate, list):
                order = [str(x) for x in candidate if x]
        elif isinstance(metadata, list):
            for item in metadata:
                if isinstance(item, Mapping):
                    value = _first(item, "name", "id", "page_id")
                    if value: order.append(str(value))
        folders = sorted(d.name for d in pages_dir.iterdir() if d.is_dir() and d.name not in {"bookmarks"})
        known = set(order)
        missing = [x for x in folders if x not in known]
        if missing:
            order.extend(missing)
            self.diagnostics.append({
                "code": "PAGE_FOLDERS_NOT_IN_ORDER", "severity": "INFO", "pages": missing,
            })
        if not order:
            order = folders
        # Preserve declared order, unlike the previous implementation.
        return list(dict.fromkeys(order))

    def _parse_page(self, pages_dir: Path, page_name: str, ordinal: int) -> Optional[Dict[str, Any]]:
        page_dir = pages_dir / page_name
        if not page_dir.is_dir():
            self.diagnostics.append({"code": "PAGE_FOLDER_MISSING", "severity": "WARNING", "page": page_name})
            return None
        raw_page = _read_json(page_dir / "page.json")
        if not isinstance(raw_page, Mapping):
            raw_page = {}
            self.diagnostics.append({"code": "PAGE_JSON_INVALID", "severity": "WARNING", "page": page_name})
        display_name = str(_first(raw_page, "displayName", "display_name") or page_name)
        page_id = str(_first(raw_page, "name", "id") or page_name)
        stable_page_id = _stable_id("page", page_id)
        page_type = self._page_type(raw_page, display_name)
        width, height = self._page_dimensions(raw_page)

        visual_items: List[Dict[str, Any]] = []
        visual_dir = page_dir / "visuals"
        if visual_dir.is_dir():
            for folder in sorted(d for d in visual_dir.iterdir() if d.is_dir()):
                visual = self._parse_visual(folder, page_id, stable_page_id, display_name)
                if visual:
                    visual_items.append(visual)
                    self.visuals.append(visual)

        categories = Counter(v["category"] for v in visual_items)
        types = Counter(v["visual_type"] for v in visual_items)
        analytic = sum(v["category"] in {"CHART", "TABLE", "CARD"} for v in visual_items)
        bound = sum(bool(v["semantic_bindings"]) for v in visual_items)
        empty_analytic = sum(v["analysis"]["empty_analytic_visual"] for v in visual_items)
        unknown = sum(v["analysis"]["unknown_visual_type"] for v in visual_items)
        custom = sum(v["is_custom_visual"] for v in visual_items)
        density = self._density_score(len(visual_items), width, height)

        page = {
            "id": stable_page_id,
            "page_id": page_id,
            "display_name": display_name,
            "ordinal": ordinal,
            "page_type": page_type,
            "dimensions": {"width": width, "height": height},
            "visual_ids": [v["visual_id"] for v in visual_items],
            "visual_count": len(visual_items),
            "visuals": visual_items,
            "summary": {
                "categories": dict(sorted(categories.items())),
                "visual_types": dict(sorted(types.items())),
                "analytic_visual_count": analytic,
                "bound_visual_count": bound,
                "empty_analytic_visual_count": empty_analytic,
                "unknown_visual_count": unknown,
                "custom_visual_count": custom,
                "density_score": density,
                "complexity_score": round(len(visual_items) + analytic * 0.75 + custom * 1.5 + unknown * 2 + empty_analytic * 2.5, 2),
            },
            "metadata": {
                "is_hidden": bool(raw_page.get("visibility") == "Hidden" or raw_page.get("isHidden", False)),
                "filter_count": self._count_filters(raw_page),
            },
            "source": {"file": str(page_dir / "page.json")},
        }
        return page

    def _parse_visual(self, visual_dir: Path, page_id: str, stable_page_id: str, page_name: str) -> Optional[Dict[str, Any]]:
        visual_file = visual_dir / "visual.json"
        raw = _read_json(visual_file)
        if not isinstance(raw, Mapping):
            self.diagnostics.append({"code": "VISUAL_JSON_INVALID", "severity": "WARNING", "visual": visual_dir.name, "page": page_id})
            return None
        visual_block = raw.get("visual") if isinstance(raw.get("visual"), Mapping) else {}
        visual_type = str(_first(visual_block, "visualType", "visual_type") or _first(raw, "visualType", "visual_type") or "unknown")
        category = self._categorize_visual(visual_type)
        bindings = self._extract_semantic_bindings(raw)
        title = self._extract_title(raw)
        position = self._extract_position(raw)
        filters = self._count_filters(raw)
        is_custom = self._is_custom_visual(visual_type)
        stable_visual_id = _stable_id("visual", page_id, visual_dir.name)
        display_name = title or self._generate_visual_name(visual_type, bindings)
        empty_analytic = category in {"CHART", "TABLE", "CARD", "SLICER"} and not bindings
        unknown_type = visual_type == "unknown"

        if empty_analytic:
            self.diagnostics.append({
                "code": "ANALYTIC_VISUAL_WITHOUT_BINDINGS", "severity": "WARNING",
                "page": page_id, "visual": visual_dir.name, "visual_type": visual_type,
            })
        if unknown_type:
            self.diagnostics.append({
                "code": "UNKNOWN_VISUAL_TYPE", "severity": "WARNING", "page": page_id, "visual": visual_dir.name,
            })

        legacy_fields = list(dict.fromkeys(b["name"] for b in bindings if b.get("name") and b["name"].strip()))
        return {
            "id": stable_visual_id,
            "visual_id": visual_dir.name,
            "page_id": page_id,
            "page_ref": stable_page_id,
            "page_name": page_name,
            "visual_type": visual_type,
            "category": category,
            "is_custom_visual": is_custom,
            "display_name": display_name,
            "title": title,
            "position": position,
            "semantic_bindings": bindings,
            "fields": legacy_fields,
            "filter_count": filters,
            "analysis": {
                "empty_analytic_visual": empty_analytic,
                "unknown_visual_type": unknown_type,
                "binding_count": len(bindings),
                "measure_binding_count": sum(b["object_type"] == "measure" for b in bindings),
                "column_binding_count": sum(b["object_type"] == "column" for b in bindings),
                "conditional_formatting_binding_count": sum(b.get("usage") == "formatting" for b in bindings),
            },
            "source": {"file": str(visual_file)},
        }

    def _extract_semantic_bindings(self, raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
        found: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
        visual = raw.get("visual") if isinstance(raw.get("visual"), Mapping) else {}
        query = visual.get("query") if isinstance(visual.get("query"), Mapping) else {}
        query_state = query.get("queryState") if isinstance(query.get("queryState"), Mapping) else {}

        # Primary source: queryState projections. Keep all projections and roles.
        for role, role_value in query_state.items():
            projections = role_value.get("projections", []) if isinstance(role_value, Mapping) else []
            if not isinstance(projections, list): continue
            for item in projections:
                if not isinstance(item, Mapping): continue
                ref = str(_first(item, "nativeQueryRef", "queryRef", "name") or "").strip()
                select_ref = str(_first(item, "queryRef", "nativeQueryRef") or "").strip()
                binding = self._binding_from_reference(ref, str(role), "projection", select_ref)
                if binding: found[self._binding_key(binding)] = binding

        # Secondary source: prototypeQuery/Select carries table and object type.
        for path, node in _iter_nodes(raw):
            if not isinstance(node, Mapping): continue
            path_text = ".".join(path).lower()
            usage = "formatting" if any(x in path_text for x in ("conditional", "objects", "format")) else "query"
            binding = self._binding_from_semantic_node(node, path, usage)
            if binding:
                found[self._binding_key(binding)] = self._merge_binding(found.get(self._binding_key(binding)), binding)

        return sorted(found.values(), key=lambda x: (x["usage"], x["role"], x.get("table") or "", x["name"]))

    def _binding_from_semantic_node(self, node: Mapping[str, Any], path: Tuple[str, ...], usage: str) -> Optional[Dict[str, Any]]:
        # Power BI semantic nodes usually use Column/Measure/Aggregation wrappers.
        for wrapper, object_type in (("Measure", "measure"), ("Column", "column"), ("Hierarchy", "hierarchy"), ("Level", "hierarchy_level")):
            value = node.get(wrapper)
            if isinstance(value, Mapping):
                name = _first(value, "Property", "Name", "property", "name")
                source = value.get("Expression") or value.get("expression") or value.get("Source") or value.get("source")
                table = self._table_from_expression(source)
                if name:
                    return self._make_binding(table, str(name), object_type, self._role_from_path(path), usage, None)
        aggregation = node.get("Aggregation")
        if isinstance(aggregation, Mapping):
            expr = aggregation.get("Expression") or aggregation.get("expression")
            nested = self._binding_from_semantic_node(expr, path, usage) if isinstance(expr, Mapping) else None
            if nested:
                nested["aggregation"] = str(_first(aggregation, "Function", "function") or "").lower() or None
                return nested
        # Entity/Property form used by some visual schemas.
        entity, prop = _first(node, "Entity", "entity"), _first(node, "Property", "property")
        if entity and prop:
            object_type = str(_first(node, "ObjectType", "objectType", "Kind", "kind") or "unknown").lower()
            return self._make_binding(str(entity), str(prop), object_type, self._role_from_path(path), usage, None)
        return None

    def _binding_from_reference(self, reference: str, role: str, usage: str, query_ref: str) -> Optional[Dict[str, Any]]:
        if not reference or not reference.strip(): return None
        ref = reference.strip()
        table, name, object_type = None, ref, "unknown"
        match = re.match(r"^'((?:[^']|'')+)'\[([^]]+)\]$", ref)
        if match:
            table, name = match.group(1).replace("''", "'"), match.group(2)
        elif "." in ref:
            parts = [x for x in ref.split(".") if x]
            if len(parts) >= 2:
                prefix = parts[0].upper()
                if prefix in {"SUM", "MIN", "MAX", "COUNT", "AVERAGE", "DISTINCTCOUNT"} and len(parts) >= 3:
                    table, name, object_type = parts[-2], parts[-1], "column"
                else:
                    table, name = parts[-2], parts[-1]
        return self._make_binding(table, name, object_type, role, usage, query_ref or ref)

    @staticmethod
    def _make_binding(table: Optional[str], name: str, object_type: str, role: str, usage: str, query_ref: Optional[str]) -> Dict[str, Any]:
        return {
            "table": table, "name": name.strip(), "object_type": object_type,
            "role": role or "Unknown", "usage": usage, "query_ref": query_ref,
            "aggregation": None,
        }

    @staticmethod
    def _binding_key(binding: Mapping[str, Any]) -> Tuple[str, str, str, str, str]:
        return (str(binding.get("table") or ""), str(binding.get("name") or ""), str(binding.get("object_type") or ""), str(binding.get("role") or ""), str(binding.get("usage") or ""))

    @staticmethod
    def _merge_binding(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
        if not old: return new
        result = dict(old)
        for key, value in new.items():
            if result.get(key) in (None, "", "unknown") and value not in (None, "", "unknown"):
                result[key] = value
        return result

    @staticmethod
    def _table_from_expression(value: Any) -> Optional[str]:
        if isinstance(value, Mapping):
            source_ref = value.get("SourceRef") or value.get("sourceRef")
            if isinstance(source_ref, Mapping):
                entity = _first(source_ref, "Entity", "entity", "Source", "source")
                return str(entity) if entity else None
            entity = _first(value, "Entity", "entity")
            if entity: return str(entity)
            for child in value.values():
                table = PageParser._table_from_expression(child)
                if table: return table
        elif isinstance(value, list):
            for child in value:
                table = PageParser._table_from_expression(child)
                if table: return table
        return None

    @staticmethod
    def _role_from_path(path: Sequence[str]) -> str:
        known = {"values", "rows", "columns", "category", "series", "y", "x", "size", "tooltips", "gradient", "details", "play", "smallmultiples"}
        for item in reversed(path):
            if item.lower() in known: return item
        return "Unknown"

    @staticmethod
    def _extract_title(raw: Mapping[str, Any]) -> Optional[str]:
        for path, node in _iter_nodes(raw):
            if not isinstance(node, Mapping): continue
            lower = [x.lower() for x in path]
            if "title" not in lower: continue
            for key in ("expr", "value", "text", "literal"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().strip("'").strip('"')
                if isinstance(value, Mapping):
                    literal = value.get("Literal") or value.get("literal")
                    if isinstance(literal, Mapping):
                        val = _first(literal, "Value", "value")
                        if isinstance(val, str): return val.strip().strip("'").strip('"')
        return None

    @staticmethod
    def _extract_position(raw: Mapping[str, Any]) -> Dict[str, Optional[float]]:
        layouts = raw.get("layouts")
        candidate: Mapping[str, Any] = {}
        if isinstance(layouts, list) and layouts and isinstance(layouts[0], Mapping): candidate = layouts[0]
        elif isinstance(raw.get("position"), Mapping): candidate = raw["position"]
        result: Dict[str, Optional[float]] = {}
        for output, keys in {"x": ("x",), "y": ("y",), "width": ("width", "w"), "height": ("height", "h"), "z": ("z", "zIndex")}.items():
            value = _first(candidate, *keys)
            try: result[output] = round(float(value), 3) if value is not None else None
            except (TypeError, ValueError): result[output] = None
        return result

    @staticmethod
    def _page_dimensions(raw: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        width, height = _first(raw, "width"), _first(raw, "height")
        try: width = float(width) if width is not None else None
        except (TypeError, ValueError): width = None
        try: height = float(height) if height is not None else None
        except (TypeError, ValueError): height = None
        return width, height

    @staticmethod
    def _page_type(raw: Mapping[str, Any], display_name: str) -> str:
        low = display_name.lower()
        if raw.get("pageType") == "Tooltip" or "tooltip" in low: return "TOOLTIP"
        if raw.get("visibility") == "Hidden" or raw.get("isHidden") is True: return "HIDDEN"
        if "drillthrough" in low: return "DRILLTHROUGH"
        return "STANDARD"

    @staticmethod
    def _count_filters(raw: Mapping[str, Any]) -> int:
        count = 0
        for path, node in _iter_nodes(raw):
            if path and path[-1].lower() in {"filters", "filter"}:
                if isinstance(node, list): count += len(node)
                elif isinstance(node, Mapping) and node: count += 1
        return count

    @staticmethod
    def _categorize_visual(visual_type: str) -> str:
        if visual_type in CHART_TYPES: return "CHART"
        if visual_type in TABLE_TYPES: return "TABLE"
        if visual_type in SLICER_TYPES: return "SLICER"
        if visual_type in BUTTON_TYPES: return "BUTTON"
        if visual_type in TEXT_TYPES: return "TEXT"
        if visual_type in CARD_TYPES: return "CARD"
        if visual_type == "image": return "IMAGE"
        if visual_type in {"gauge", "advancedtoggleswitch"}: return "OTHER"
        if visual_type.lower().startswith("htmlcontent"): return "CUSTOM_VISUAL"
        return "OTHER"

    @staticmethod
    def _is_custom_visual(visual_type: str) -> bool:
        if visual_type in CHART_TYPES | TABLE_TYPES | SLICER_TYPES | BUTTON_TYPES | TEXT_TYPES | CARD_TYPES | OTHER_KNOWN_TYPES:
            return False
        return visual_type != "unknown"

    @staticmethod
    def _generate_visual_name(visual_type: str, bindings: Sequence[Mapping[str, Any]]) -> str:
        base = TYPE_LABELS.get(visual_type) or re.sub(r"(?<!^)(?=[A-Z])", " ", visual_type).strip().title()
        meaningful = []
        for binding in bindings:
            name = str(binding.get("name") or "").strip()
            if name and name not in meaningful: meaningful.append(name)
        return f"{base}: {', '.join(meaningful[:2])}" if meaningful else base

    @staticmethod
    def _density_score(count: int, width: Optional[float], height: Optional[float]) -> Optional[float]:
        if not width or not height: return None
        # Normalized to a standard 1280x720 page and capped for readability.
        return round(min(100.0, count / ((width * height) / (1280 * 720)) * 2.5), 2)

    def canonical_pages(self) -> Dict[str, Any]:
        categories = Counter(v["category"] for v in self.visuals)
        types = Counter(v["visual_type"] for v in self.visuals)
        return {
            "schema_version": SCHEMA_VERSION, "artifact": "pages",
            "analysis_scope": {
                "page_metadata": {"status": "analyzed"},
                "visual_metadata": {"status": "analyzed"},
                "semantic_bindings": {"status": "analyzed"},
                "bookmarks": {"status": "not_analyzed"},
                "interactions": {"status": "not_analyzed"},
            },
            "summary": {
                "page_count": len(self.pages), "visual_count": len(self.visuals),
                "pages_by_type": dict(sorted(Counter(p["page_type"] for p in self.pages).items())),
                "visuals_by_category": dict(sorted(categories.items())),
                "visuals_by_type": dict(sorted(types.items())),
                "empty_analytic_visual_count": sum(v["analysis"]["empty_analytic_visual"] for v in self.visuals),
                "unknown_visual_count": sum(v["analysis"]["unknown_visual_type"] for v in self.visuals),
                "custom_visual_count": sum(v["is_custom_visual"] for v in self.visuals),
                "semantic_binding_count": sum(len(v["semantic_bindings"]) for v in self.visuals),
            },
            "pages": self.pages,
            "diagnostics": {"count": len(self.diagnostics), "items": self.diagnostics},
        }

    def canonical_visuals(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "artifact": "visuals",
            "summary": {"visual_count": len(self.visuals)}, "visuals": self.visuals,
        }


def _genai_outputs(parser: PageParser) -> Tuple[Dict[str, Any], Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    page_index, visual_index, details, priority = [], [], [], []
    for page in parser.pages:
        page_index.append({
            "id": page["id"], "page_id": page["page_id"], "display_name": page["display_name"],
            "ordinal": page["ordinal"], "page_type": page["page_type"],
            "visual_count": page["visual_count"], "summary": page["summary"],
        })
        reasons = []
        if page["visual_count"] >= 50: reasons.append("HIGH_VISUAL_COUNT")
        if page["summary"]["empty_analytic_visual_count"]: reasons.append("EMPTY_ANALYTIC_VISUALS")
        if page["summary"]["unknown_visual_count"]: reasons.append("UNKNOWN_VISUALS")
        if page["summary"]["custom_visual_count"]: reasons.append("CUSTOM_VISUALS")
        if reasons: priority.append({"id": page["id"], "display_name": page["display_name"], "reason_codes": reasons})
        details.append((page["id"] + ".json", {
            "schema_version": f"{SCHEMA_VERSION}-ai-detail", "artifact": "page_detail", "page": page,
        }))
    for visual in parser.visuals:
        visual_index.append({
            "id": visual["id"], "visual_id": visual["visual_id"], "page_ref": visual["page_ref"],
            "page_name": visual["page_name"], "visual_type": visual["visual_type"],
            "category": visual["category"], "display_name": visual["display_name"],
            "binding_count": visual["analysis"]["binding_count"],
            "fields": [
                {k: b.get(k) for k in ("table", "name", "object_type", "role", "usage")}
                for b in visual["semantic_bindings"]
            ],
            "flags": [key for key in ("empty_analytic_visual", "unknown_visual_type") if visual["analysis"][key]],
        })
    pages_ai = {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "pages", "pages": page_index, "priority_review": priority}
    visuals_ai = {"schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "visuals", "visuals": visual_index}
    return pages_ai, visuals_ai, details


def parse_pages(pbip_root: str, output_file: Optional[str] = None, project_name: Optional[str] = None, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse report pages and optionally write canonical/GenAI artifacts."""
    parser = PageParser(pbip_root, project_name)
    pages = parser.parse()
    canonical = parser.canonical_pages()
    base = Path(output_dir) if output_dir else None
    canonical_path = Path(output_file) if output_file else (base / "pages.json" if base else None)
    if canonical_path: _write_json(canonical_path, canonical if output_dir else pages)
    if base:
        _write_json(base / "visuals.json", parser.canonical_visuals())
        _write_json(base / "diagnostics" / "pages_parser_diagnostics.json", canonical["diagnostics"])
        pages_ai, visuals_ai, details = _genai_outputs(parser)
        _write_json(base / "data_to_genai" / "pages.json", pages_ai)
        _write_json(base / "data_to_genai" / "visuals.json", visuals_ai)
        for filename, payload in details:
            _write_json(base / "data_to_genai" / "page_details" / filename, payload)
    return pages


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse Power BI PBIP pages and visuals")
    cli.add_argument("pbip_root")
    cli.add_argument("output_file", nargs="?", default=None)
    cli.add_argument("--project-name", default=None)
    cli.add_argument("--output-dir", default=None)
    args = cli.parse_args()
    result = parse_pages(args.pbip_root, args.output_file, args.project_name, args.output_dir)
    print(f"Parsed {len(result)} pages")
