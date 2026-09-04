from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

SCHEMA_VERSION = "2.0.0"
SEVERITY = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
SENSITIVE_NAME_RE = re.compile(r"(?i)(token|password|secret|credential|accountkey|apikey|accesskey)")
VERSIONED_FILE_RE = re.compile(r"(?i)(?:^|[ _.-])v(?:ersion)?[ _.-]?\d+(?:[._-]\d+)*")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _stable(prefix: str, *parts: Any) -> str:
    key = "\0".join(str(x or "") for x in parts)
    return prefix + "_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _normalize_file(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _strings(text: str) -> List[str]:
    values = []
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', text):
        try:
            values.append(json.loads('"' + match.group(1) + '"'))
        except json.JSONDecodeError:
            values.append(match.group(1))
    return values


def _balanced_call(text: str, start: int) -> Tuple[str, int]:
    open_at = text.find("(", start)
    if open_at < 0:
        return "", start
    depth, in_string, i = 0, False, open_at
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
        i += 1
    return text[start:], len(text)


def _named_expressions(text: str) -> List[Tuple[Optional[str], str, int]]:
    """Split expressions.tmdl when possible; otherwise return one anonymous block."""
    matches = list(re.finditer(r"(?m)^\s*expression\s+('(?:[^']|'')+'|[^=\n]+?)\s*=", text))
    if not matches:
        return [(None, text, 0)]
    result = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        name = match.group(1).strip()
        if name.startswith("'") and name.endswith("'"):
            name = name[1:-1].replace("''", "'")
        result.append((name, text[match.end():end], match.start()))
    return result


class DataSourceParser:
    def __init__(self, tmdl_dir: str, environment_mapping: Optional[Mapping[str, str]] = None):
        self.tmdl_dir = Path(tmdl_dir)
        self.environment_mapping = {str(k).lower(): str(v) for k, v in (environment_mapping or {}).items()}
        self.connections: Dict[str, Dict[str, Any]] = {}
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.usages: Dict[str, Dict[str, Any]] = {}
        self.diagnostics: List[Dict[str, Any]] = []
        self.table_ids: Dict[str, str] = {}
        self.partition_ids: Dict[str, str] = {}

    def parse(self, tables: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        self.connections, self.resources, self.usages, self.diagnostics = {}, {}, {}, []
        self._index_tables(tables or [])
        files = self._files()
        if not files:
            self.diagnostics.append({"code": "DS000", "severity": "ERROR", "message": "No TMDL files were found.", "path": str(self.tmdl_dir)})
        for path in files:
            text = _read(path)
            blocks = _named_expressions(text) if path.name.lower() == "expressions.tmdl" else [(None, text, 0)]
            for expression_name, block, offset in blocks:
                self._scan_block(path, text, block, offset, expression_name)
        self._finalize()
        return self.canonical()

    def _files(self) -> List[Path]:
        return sorted(self.tmdl_dir.rglob("*.tmdl")) if self.tmdl_dir.exists() else []

    def _index_tables(self, tables: Sequence[Mapping[str, Any]]) -> None:
        self.table_ids, self.partition_ids = {}, {}
        for table in tables:
            name = table.get("name")
            if name:
                self.table_ids[str(name)] = str(table.get("id") or _stable("table", name))
            for partition in table.get("partitions", []) if isinstance(table.get("partitions"), list) else []:
                if isinstance(partition, Mapping) and partition.get("name"):
                    self.partition_ids[f"{name}\0{partition['name']}"] = str(partition.get("id") or _stable("partition", name, partition["name"]))

    def _scan_block(self, path: Path, full_text: str, block: str, offset: int, expression_name: Optional[str]) -> None:
        detectors = [
            ("Databricks.Catalogs", "AZURE_DATABRICKS"),
            ("Sql.Database", "SQL_DATABASE"),
            ("SharePoint.Files", "SHAREPOINT_ONLINE"),
            ("SharePoint.Contents", "SHAREPOINT_ONLINE"),
            ("Web.Contents", "WEB"),
            ("Excel.Workbook", "EXCEL_CONTENT"),
            ("Csv.Document", "CSV_CONTENT"),
        ]
        calls: List[Dict[str, Any]] = []
        for connector, kind in detectors:
            for match in re.finditer(re.escape(connector) + r"\s*\(", block, re.I):
                call, end = _balanced_call(block, match.start())
                if call:
                    calls.append({"connector": connector, "kind": kind, "call": call, "start": match.start(), "end": end})
        calls.sort(key=lambda x: x["start"])
        # Physical calls only. Wrappers are attached to the nearest physical call.
        for call in calls:
            if call["kind"] in {"EXCEL_CONTENT", "CSV_CONTENT"}:
                continue
            record = self._classify_call(call, block)
            if not record:
                continue
            wrappers = [x for x in calls if x["kind"] in {"EXCEL_CONTENT", "CSV_CONTENT"} and x["start"] <= call["start"] <= x["end"]]
            if wrappers:
                wrapper = min(wrappers, key=lambda x: x["end"] - x["start"])
                record["content_connector"] = wrapper["connector"]
                record["resource_type"] = "EXCEL_WORKBOOK" if wrapper["kind"] == "EXCEL_CONTENT" else "CSV_FILE"
            native = self._native_query_for(call, block)
            record["query_execution"] = "VALUE_NATIVE_QUERY" if native else "STANDARD"
            record["has_native_query"] = bool(native)
            record["native_query_preview"] = self._redact_sql_preview(native)
            source_file = _normalize_file(path, self.tmdl_dir)
            table_name = self._table_name(path, full_text)
            partition_name = self._partition_name(full_text, offset + call["start"])
            self._register(record, source_file, expression_name, table_name, partition_name, offset + call["start"], full_text)

    def _classify_call(self, call: Mapping[str, Any], block: str) -> Optional[Dict[str, Any]]:
        strings = _strings(str(call["call"]))
        connector, kind = str(call["connector"]), str(call["kind"])
        if kind == "AZURE_DATABRICKS":
            host = strings[0] if strings else None
            http_path = strings[1] if len(strings) > 1 else None
            catalog_match = re.search(r"(?i)\bCatalog\s*=\s*\"([^\"]+)\"", str(call["call"]))
            catalog = catalog_match.group(1) if catalog_match else None
            return {
                "provider": "AZURE_DATABRICKS", "connector": "Databricks.Catalogs",
                "access_connector": "Databricks.Catalogs", "content_connector": None,
                "location": {"host": host, "endpoint_type": "SQL_WAREHOUSE" if http_path and "/warehouses/" in http_path else "UNKNOWN", "http_path": http_path},
                "resource_type": "CATALOG", "resource": {"catalog": catalog}, "confidence": 1.0,
            }
        if kind == "SQL_DATABASE":
            server, database = (strings + [None, None])[:2]
            provider = "MICROSOFT_FABRIC_WAREHOUSE" if server and server.lower().endswith(".datawarehouse.fabric.microsoft.com") else "SQL_SERVER"
            return {
                "provider": provider, "connector": "Sql.Database", "access_connector": "Sql.Database", "content_connector": None,
                "location": {"server": server}, "resource_type": "DATABASE", "resource": {"database": database}, "confidence": 1.0,
            }
        if kind in {"SHAREPOINT_ONLINE", "WEB"}:
            url = strings[0] if strings else None
            parsed = urlparse(url) if url else None
            host = parsed.hostname if parsed else None
            provider = "SHAREPOINT_ONLINE" if host and host.lower().endswith(".sharepoint.com") else ("WEB" if kind == "WEB" else "SHAREPOINT_ONLINE")
            path = unquote(parsed.path) if parsed else None
            site_match = re.match(r"(/sites/[^/]+|/teams/[^/]+)", path or "", re.I)
            name = PurePosixPath(path or "").name or None
            ext = PurePosixPath(name).suffix.lower() if name else None
            return {
                "provider": provider, "connector": connector, "access_connector": connector, "content_connector": None,
                "location": {"scheme": parsed.scheme if parsed else None, "host": host, "site": site_match.group(1) if site_match else None, "path": path},
                "resource_type": "WEB_RESOURCE", "resource": {"name": name, "extension": ext}, "confidence": 1.0 if host else 0.65,
            }
        return None

    @staticmethod
    def _native_query_for(call: Mapping[str, Any], block: str) -> Optional[str]:
        for match in re.finditer(r"Value\.NativeQuery\s*\(", block, re.I):
            native, _ = _balanced_call(block, match.start())
            if call["start"] >= match.start() and call["start"] <= match.start() + len(native):
                return native
        return None

    @staticmethod
    def _redact_sql_preview(native: Optional[str]) -> Optional[str]:
        if not native:
            return None
        strings = _strings(native)
        sql = max(strings, key=len, default="")
        if not re.search(r"(?i)\b(select|with|exec|call)\b", sql):
            return "NATIVE_QUERY_PRESENT"
        verbs = re.findall(r"(?i)\b(select|with|from|join|where|group\s+by|order\s+by)\b", sql)
        return "NATIVE_QUERY:" + ",".join(dict.fromkeys(x.upper() for x in verbs[:8]))

    def _register(self, record: Dict[str, Any], source_file: str, expression_name: Optional[str], table_name: Optional[str], partition_name: Optional[str], absolute_offset: int, full_text: str) -> None:
        provider = record["provider"]
        location = record["location"]
        connection_key = self._connection_key(provider, location)
        connection_id = _stable("connection", connection_key)
        connection = self.connections.setdefault(connection_key, {
            "id": connection_id, "provider": provider, "connector": record["connector"],
            "access_connector": record["access_connector"], "location": location,
            "classification": self._connection_classification(provider),
            "environment": self._environment(record),
            "analysis": {"risk_level": "NONE", "findings": []},
            "resource_refs": [], "usage_refs": [], "occurrence_count": 0,
        })
        if record.get("content_connector") and record["content_connector"] not in connection.setdefault("content_connectors", []):
            connection["content_connectors"].append(record["content_connector"])

        resource = dict(record["resource"])
        if record.get("content_connector"):
            resource["content_connector"] = record["content_connector"]
        resource_key = self._resource_key(connection_id, record["resource_type"], resource)
        resource_id = _stable("resource", resource_key)
        resource_obj = self.resources.setdefault(resource_key, {
            "id": resource_id, "connection_ref": connection_id,
            "resource_type": record["resource_type"], "details": resource,
            "query_mode": "NATIVE_QUERY" if record["has_native_query"] else "STANDARD",
            "native_query_preview": record["native_query_preview"],
            "usage_refs": [], "usage_count": 0,
            "analysis": {"risk_level": "NONE", "findings": []},
        })
        table_ref = self.table_ids.get(table_name or "") or (_stable("table", table_name) if table_name else None)
        partition_ref = self.partition_ids.get(f"{table_name}\0{partition_name}") if table_name and partition_name else None
        if table_name and partition_name and not partition_ref:
            partition_ref = _stable("partition", table_name, partition_name)
        expression_ref = _stable("expression", expression_name) if expression_name else None
        usage_key = "\0".join(str(x or "") for x in (resource_id, source_file, expression_name, table_name, partition_name))
        usage_id = _stable("datasource_usage", usage_key)
        usage = self.usages.setdefault(usage_key, {
            "id": usage_id, "connection_ref": connection_id, "resource_ref": resource_id,
            "table_ref": table_ref, "table_name": table_name,
            "partition_ref": partition_ref, "partition_name": partition_name,
            "expression_ref": expression_ref, "expression_name": expression_name,
            "source_file": source_file, "occurrence_count": 0,
            "source_lines": [],
        })
        line = full_text.count("\n", 0, absolute_offset) + 1
        usage["occurrence_count"] += 1
        if line not in usage["source_lines"]:
            usage["source_lines"].append(line)
        connection["occurrence_count"] += 1
        resource_obj["usage_count"] += 1
        for container, key, value in ((connection, "resource_refs", resource_id), (connection, "usage_refs", usage_id), (resource_obj, "usage_refs", usage_id)):
            if value not in container[key]: container[key].append(value)

    def _finalize(self) -> None:
        providers = {c["provider"] for c in self.connections.values()}
        if len(providers) > 1:
            self.diagnostics.append({"code": "DS006", "severity": "INFO", "message": "Multiple source providers are used by the model.", "providers": sorted(providers)})
        for connection in self.connections.values():
            findings = connection["analysis"]["findings"]
            provider = connection["provider"]
            if provider == "SHAREPOINT_ONLINE":
                findings.append({"code": "DS004", "severity": "LOW", "message": "Web-hosted file or resource detected in SharePoint Online."})
                if connection["access_connector"].lower() == "web.contents":
                    findings.append({"code": "DS005", "severity": "LOW", "message": "Web.Contents is used for a SharePoint Online resource; review authentication and portability."})
            if self._contains_sensitive(connection):
                findings.append({"code": "DS008", "severity": "HIGH", "message": "Potential secret-like connection attribute detected. Values should not be persisted or sent to GenAI."})
            connection["analysis"]["risk_level"] = self._risk(findings)
        for resource in self.resources.values():
            findings = resource["analysis"]["findings"]
            if resource["query_mode"] == "NATIVE_QUERY":
                findings.append({"code": "DS007", "severity": "MEDIUM", "message": "Native query detected; review portability, parameters and query-folding assumptions."})
            filename = str(resource.get("details", {}).get("name") or "")
            if filename and VERSIONED_FILE_RE.search(filename):
                findings.append({"code": "DS009", "severity": "MEDIUM", "message": "Version-like file name detected; refresh may break when the file is replaced under a different name."})
            resource["analysis"]["risk_level"] = self._risk(findings)
        for usage in self.usages.values():
            if not usage["table_ref"] and not usage["expression_ref"]:
                self.diagnostics.append({"code": "DS010", "severity": "LOW", "message": "Datasource usage could not be linked to a table, partition or named expression.", "source_file": usage["source_file"]})

    @staticmethod
    def _risk(findings: Sequence[Mapping[str, Any]]) -> str:
        return max((str(x.get("severity", "NONE")) for x in findings), key=lambda x: SEVERITY.get(x, 0), default="NONE")

    @staticmethod
    def _contains_sensitive(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(SENSITIVE_NAME_RE.search(str(k)) or DataSourceParser._contains_sensitive(v) for k, v in value.items())
        if isinstance(value, list): return any(DataSourceParser._contains_sensitive(x) for x in value)
        return False

    @staticmethod
    def _connection_key(provider: str, location: Mapping[str, Any]) -> str:
        important = [provider, location.get("host"), location.get("server"), location.get("site"), location.get("endpoint_type")]
        return "|".join(str(x or "").lower().rstrip("/") for x in important)

    @staticmethod
    def _resource_key(connection_id: str, resource_type: str, details: Mapping[str, Any]) -> str:
        return connection_id + "|" + resource_type + "|" + json.dumps(details, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _connection_classification(provider: str) -> Dict[str, Any]:
        cloud = provider in {"AZURE_DATABRICKS", "MICROSOFT_FABRIC_WAREHOUSE", "SHAREPOINT_ONLINE", "WEB"}
        return {
            "is_cloud": cloud,
            "is_on_premises": False if cloud else None,
            "is_file_based": provider == "SHAREPOINT_ONLINE",
            "is_database": provider in {"AZURE_DATABRICKS", "MICROSOFT_FABRIC_WAREHOUSE", "SQL_SERVER"},
            "requires_gateway_assessment": provider == "SQL_SERVER",
        }

    def _environment(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        labels = [record.get("resource", {}).get("catalog"), record.get("resource", {}).get("database")]
        label = next((str(x) for x in labels if x), None)
        mapped = self.environment_mapping.get(label.lower()) if label else None
        return {"detected_label": label, "classification": mapped or "UNKNOWN", "detection_confidence": 1.0 if mapped else 0.0}

    @staticmethod
    def _table_name(path: Path, text: str) -> Optional[str]:
        if path.parent.name.lower() != "tables": return None
        match = re.search(r"(?m)^\s*table\s+('(?:[^']|'')+'|[^\n]+?)\s*$", text)
        if not match: return path.stem
        value = match.group(1).strip()
        return value[1:-1].replace("''", "'") if value.startswith("'") and value.endswith("'") else value

    @staticmethod
    def _partition_name(text: str, offset: int) -> Optional[str]:
        matches = list(re.finditer(r"(?m)^\s*partition\s+('(?:[^']|'')+'|[^=\n]+?)\s*=", text[:offset + 1]))
        if not matches: return None
        value = matches[-1].group(1).strip()
        return value[1:-1].replace("''", "'") if value.startswith("'") and value.endswith("'") else value

    def summary(self) -> Dict[str, Any]:
        connections = list(self.connections.values()); resources = list(self.resources.values()); usages = list(self.usages.values())
        providers = Counter(x["provider"] for x in connections)
        return {
            "connection_count": len(connections), "resource_count": len(resources), "usage_count": len(usages),
            "cloud_connection_count": sum(x["classification"]["is_cloud"] for x in connections),
            "on_premises_connection_count": sum(x["classification"]["is_on_premises"] is True for x in connections),
            "native_query_resource_count": sum(x["query_mode"] == "NATIVE_QUERY" for x in resources),
            "file_resource_count": sum(x["resource_type"] in {"CSV_FILE", "EXCEL_WORKBOOK"} for x in resources),
            "providers": dict(sorted(providers.items())),
            "has_m_queries": bool(connections),
            "has_file_based_sources": any(x["classification"]["is_file_based"] for x in connections),
            "has_cloud_sources": any(x["classification"]["is_cloud"] for x in connections),
            "has_on_premises_sources": any(x["classification"]["is_on_premises"] is True for x in connections),
            "has_database_sources": any(x["classification"]["is_database"] for x in connections),
        }

    def canonical(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "artifact": "datasources",
            "analysis_scope": {
                "physical_connections": {"status": "analyzed"},
                "resources": {"status": "analyzed"},
                "usages": {"status": "analyzed"},
                "credentials": {"status": "not_accessed"},
                "gateway_configuration": {"status": "not_available"},
                "privacy_levels": {"status": "not_available"},
            },
            "summary": self.summary(),
            "connections": sorted(self.connections.values(), key=lambda x: x["id"]),
            "resources": sorted(self.resources.values(), key=lambda x: x["id"]),
            "usages": sorted(self.usages.values(), key=lambda x: x["id"]),
            "diagnostics": {"count": len(self.diagnostics), "items": self.diagnostics},
        }

    def legacy(self) -> Dict[str, Any]:
        items = []
        for resource in sorted(self.resources.values(), key=lambda x: x["id"]):
            connection = next(x for x in self.connections.values() if x["id"] == resource["connection_ref"])
            refs = [x for x in self.usages.values() if x["resource_ref"] == resource["id"]]
            items.append({
                "id": resource["id"].replace("resource_", ""),
                "type": connection["provider"], "connector": connection["connector"],
                "confidence": 1.0,
                "detection_reason": "Canonical physical-source detection",
                "source_file": refs[0]["source_file"] if refs else None,
                "expression_name": refs[0]["expression_name"] if refs else None,
                "attributes": {**connection["location"], **resource["details"]},
                "definition": None,
                "privacy_note": "Connection details are normalized; credential and privacy settings were not accessed.",
                "occurrences": sum(x["occurrence_count"] for x in refs),
                "references": [{"source_file": x["source_file"], "expression_name": x["expression_name"]} for x in refs],
            })
        return {
            "datasources": items,
            "summary": {
                "total_datasources": len(items),
                "source_type_distribution": dict(sorted(Counter(x["type"] for x in items).items())),
                "connector_distribution": dict(sorted(Counter(x["connector"] for x in items).items())),
                "has_m_queries": self.summary()["has_m_queries"],
                "has_file_based_sources": self.summary()["has_file_based_sources"],
                "has_cloud_sources": self.summary()["has_cloud_sources"],
                "has_database_sources": self.summary()["has_database_sources"],
            },
            "issues": [x["message"] for x in self.diagnostics],
            "recommendations": self.recommendations(),
        }

    def recommendations(self) -> List[str]:
        recommendations = []
        if any(c["provider"] == "SHAREPOINT_ONLINE" for c in self.connections.values()):
            recommendations.append("Validate SharePoint Online authentication, privacy levels and path stability for scheduled refresh.")
        if any(r["query_mode"] == "NATIVE_QUERY" for r in self.resources.values()):
            recommendations.append("Review native-query portability, parameters and environment-specific catalog references.")
        if any(c["classification"]["requires_gateway_assessment"] for c in self.connections.values()):
            recommendations.append("Assess gateway requirements for SQL Server connections; the parser cannot inspect tenant configuration.")
        return recommendations


def _sanitized_connection(connection: Mapping[str, Any]) -> Dict[str, Any]:
    location = connection.get("location", {})
    resource_name = location.get("host") or location.get("server") or location.get("site") or "unknown"
    return {
        "id": connection["id"], "provider": connection["provider"],
        "connector": connection["connector"], "classification": connection["classification"],
        "location": {
            "host_category": connection["provider"],
            "endpoint_hash": _stable("endpoint", resource_name),
            "endpoint_type": location.get("endpoint_type"),
        },
        "environment": connection["environment"],
        "resource_count": len(connection["resource_refs"]),
        "usage_count": len(connection["usage_refs"]),
        "risk_level": connection["analysis"]["risk_level"],
        "finding_codes": [x["code"] for x in connection["analysis"]["findings"]],
    }


def _sanitized_resource(resource: Mapping[str, Any]) -> Dict[str, Any]:
    details = resource.get("details", {})
    return {
        "id": resource["id"], "connection_ref": resource["connection_ref"],
        "resource_type": resource["resource_type"],
        "resource_name": details.get("name"), "extension": details.get("extension"),
        "query_mode": resource["query_mode"], "usage_count": resource["usage_count"],
        "risk_level": resource["analysis"]["risk_level"],
        "finding_codes": [x["code"] for x in resource["analysis"]["findings"]],
    }


def parse_datasources(tmdl_dir: str, output_file: Optional[str] = None, output_dir: Optional[str] = None, tables: Optional[Sequence[Mapping[str, Any]]] = None, environment_mapping: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    parser = DataSourceParser(tmdl_dir, environment_mapping=environment_mapping)
    canonical = parser.parse(tables=tables)
    base = Path(output_dir) if output_dir else None
    target = Path(output_file) if output_file else (base / "datasources.json" if base else None)
    if target: _write(target, canonical if base else parser.legacy())
    if base:
        _write(base / "datasource_connections.json", {"schema_version": SCHEMA_VERSION, "artifact": "datasource_connections", "connections": canonical["connections"]})
        _write(base / "datasource_resources.json", {"schema_version": SCHEMA_VERSION, "artifact": "datasource_resources", "resources": canonical["resources"]})
        _write(base / "datasource_usages.json", {"schema_version": SCHEMA_VERSION, "artifact": "datasource_usages", "usages": canonical["usages"]})
        _write(base / "diagnostics" / "datasources_parser_diagnostics.json", canonical["diagnostics"])
        ai_connections = [_sanitized_connection(x) for x in canonical["connections"]]
        ai_resources = [_sanitized_resource(x) for x in canonical["resources"]]
        _write(base / "data_to_genai" / "datasources.json", {
            "schema_version": f"{SCHEMA_VERSION}-ai", "artifact": "datasources",
            "summary": canonical["summary"], "connections": ai_connections,
            "resources": ai_resources,
            "usages": [{k: x.get(k) for k in ("id", "connection_ref", "resource_ref", "table_ref", "partition_ref", "expression_ref", "source_file")} for x in canonical["usages"]],
            "priority_review": [x for x in ai_connections + ai_resources if SEVERITY.get(x["risk_level"], 0) >= SEVERITY["MEDIUM"]],
        })
        for connection in canonical["connections"]:
            resources = [x for x in canonical["resources"] if x["connection_ref"] == connection["id"]]
            usage_ids = {u for x in resources for u in x["usage_refs"]}
            usages = [x for x in canonical["usages"] if x["id"] in usage_ids]
            _write(base / "data_to_genai" / "datasource_details" / f"{connection['id']}.json", {
                "schema_version": f"{SCHEMA_VERSION}-ai-detail", "artifact": "datasource_detail",
                "connection": connection, "resources": resources, "usages": usages,
            })
    return canonical if base else parser.legacy()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Parse and normalize Power BI TMDL data sources")
    cli.add_argument("tmdl_dir")
    cli.add_argument("output_file", nargs="?", default=None)
    cli.add_argument("--output-dir", default=None)
    args = cli.parse_args()
    result = parse_datasources(args.tmdl_dir, args.output_file, args.output_dir)
    summary = result.get("summary", {})
    print(f"Parsed {summary.get('connection_count', summary.get('total_datasources', 0))} datasource connections")
