#!/usr/bin/env python3
"""
Power BI Analysis & Optimization Engine v2 — Unified Entry Point

Generates comprehensive reports from ALL parser JSON outputs:
  1. EDA Report — Data model structure, quality, unused assets
  2. DAX Optimization Guide — Measure complexity, best practices
  3. Performance Analysis — Bottlenecks, cardinality issues
  4. Data Quality Report — Column usage, unused measures, orphaned assets

Uses local Ollama (Phi3, Qwen) with enriched context for expert analysis.

Usage:
    python ollama_generator.py [project_name] [model] [temperature] [max_tokens]

Examples:
    python ollama_generator.py                                 # First project, defaults
    python ollama_generator.py Americas                        # Target project
    python ollama_generator.py Americas phi3:14b               # With model
    python ollama_generator.py Americas phi3:14b 0.1 2000      # Full control
    python ollama_generator.py --list                          # List projects

Environment Variables:
    OLLAMA_MODEL       Default model (phi3:14b)
    OLLAMA_TEMP        Temperature 0.0-1.0 (default: 0.1)
    OLLAMA_TOKENS      Max tokens (default: 2000)
"""

import json
import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    from ollama_client import generate_with_retry, check_connection, DEFAULT_MODEL
except ImportError:
    print("❌ ollama_client.py not found in the same directory.")
    sys.exit(1)

# Lock for thread-safe printing
print_lock = threading.Lock()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PATH DETECTION — Auto-find directories
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_root_dir() -> Path:
    """Find powerbi-project root directory."""
    cwd = Path.cwd()
    
    # Strategy 1: Check scripts directory (we're likely here)
    if (cwd / "ollama_generator.py").exists():
        return cwd.parent
    
    # Strategy 2: Parent of scripts
    if (cwd.parent / "main.py").exists():
        return cwd.parent
    
    # Strategy 3: Search upward
    for parent in cwd.parents:
        if (parent / "main.py").exists() and (parent / "scripts").exists():
            return parent
    
    # Strategy 4: Common locations
    candidates = [
        Path.home() / "Downloads" / "Programación" / "powerbi-project",
        cwd / "powerbi-project",
        cwd.parent / "powerbi-project",
    ]
    
    for candidate in candidates:
        if (candidate / "main.py").exists():
            return candidate
    
    return cwd.parent


def find_projects_dir(root: Path) -> Path:
    """Find where projects are stored."""
    candidates = [
        root / "powerbi-project",
        root / "RecursosFuente",
    ]
    
    for candidate in candidates:
        if candidate.exists() and list(candidate.glob("*/data")):
            return candidate
    
    return root / "powerbi-project"


def find_project_data_dir(project_name: Optional[str] = None, root: Optional[Path] = None) -> Optional[Path]:
    """Find data directory for project."""
    if root is None:
        root = find_root_dir()
    
    projects_dir = find_projects_dir(root)
    
    if not projects_dir.exists():
        return None
    
    project_dirs = [
        d for d in projects_dir.iterdir() 
        if d.is_dir() and (d / "data").exists()
    ]
    
    if not project_dirs:
        return None
    
    if project_name is None:
        return project_dirs[0] / "data"
    
    for proj_dir in project_dirs:
        if project_name.lower() in proj_dir.name.lower():
            return proj_dir / "data"
    
    return None


def list_projects(root: Optional[Path] = None):
    """List available projects."""
    if root is None:
        root = find_root_dir()
    
    projects_dir = find_projects_dir(root)
    project_dirs = [
        d for d in projects_dir.iterdir() 
        if d.is_dir() and (d / "data").exists()
    ]
    
    print(f"\nAvailable projects in {projects_dir}:\n")
    for proj_dir in project_dirs:
        count = len(list((proj_dir / "data").glob("*.json")))
        print(f"  📁 {proj_dir.name}")
        print(f"     Data files: {count}\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SYSTEM PROMPTS — domain-specific, context-aware
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYSTEM_EDA = """You are a Power BI data architect analyzing semantic model health.
Evaluate structure, quality, and efficiency. Consider unused assets, orphaned columns, and optimization opportunities.
Be prescriptive with actionable insights. Use Markdown format."""

SYSTEM_DAX = """You are a senior DAX optimization specialist with 10+ years experience.
Analyze DAX expressions for inefficiencies, variable caching, context transitions, and unused measures.
Consider both performance AND maintainability. Provide specific refactoring examples."""

SYSTEM_PERF = """You are a Power BI performance engineer specializing in model optimization.
Identify critical bottlenecks: unused assets, cardinality problems, relationship complexity.
Prioritize by impact and effort. Recommend removal vs refactoring vs redesign."""

SYSTEM_QUALITY = """You are a data quality auditor for Power BI models.
Analyze column usage patterns, data completeness, and model maintainability.
Focus on technical debt: orphaned columns, unused measures, disconnected tables."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JSON LOADER — ALL SOURCES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load(path: Path) -> Any:
    """Load JSON file safely."""
    if not path.exists():
        print(f"    [MISSING] {path.name}")
        return [] if path.stem not in ["analysis", "unused_measures", "column_usage"] else {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"    [ERROR] {path.name}: {e}")
        return [] if path.stem not in ["analysis", "unused_measures", "column_usage"] else {}


def load_all(data_dir: str) -> Dict[str, Any]:
    """Load ALL parser outputs — required and optional."""
    base = Path(data_dir)
    print(f"\n[1/5] Loading analysis data from: {base.resolve()}\n")

    data = {
        # Required
        "tables":        _load(base / "tables.json"),
        "relationships": _load(base / "relationships.json"),
        "measures":      _load(base / "measures.json"),
        "pages":         _load(base / "pages.json"),
        "analysis":      _load(base / "classifications.json"),
        # Optional but important
        "column_usage":  _load(base / "column_usage.json"),
        "unused_measures": _load(base / "unused_measures.json"),
    }

    # Improved debug output
    for key, value in data.items():
        if isinstance(value, list):
            status = f"[OK] {len(value)} items" if value else "[EMPTY] 0 items"
            print(f"  {key:<20} {status}")
        elif isinstance(value, dict):
            if value:
                size = len(value)
                details = f"({size} keys)" if key not in ["analysis"] else "(loaded)"
                print(f"  {key:<20} [OK] {details}")
            else:
                print(f"  {key:<20} [EMPTY] {{}}")
        else:
            print(f"  {key:<20} [UNKNOWN] {type(value).__name__}")

    return data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATA AGGREGATORS — ENRICHED CONTEXT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_eda_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute EDA metrics from ALL available sources."""
    tables = data["tables"]
    relationships = data["relationships"]
    measures = data["measures"]
    analysis = data["analysis"]
    column_usage = data["column_usage"]

    # Table stats
    total_cols = sum(len(t.get("columns", [])) for t in tables)
    
    # Type distribution
    type_dist = defaultdict(int)
    for t in tables:
        for col in t.get("columns", []):
            type_dist[col.get("dataType", "unknown")] += 1

    # Table classifications from classifications.json
    table_classes = defaultdict(int)
    for tc in analysis.get("table_classifications", []):
        table_classes[tc.get("classification", "UNKNOWN")] += 1

    # Column usage from column_usage.json
    total_unused_cols = sum(cu.get("unused_columns", 0) for cu in column_usage)
    total_used_cols = sum(cu.get("used_columns", 0) for cu in column_usage)
    tables_with_unused = len([cu for cu in column_usage if cu.get("unused_columns", 0) > 0])

    # Relationships
    active_rels = [r for r in relationships if r.get("is_active", True)]
    inactive_rels = [r for r in relationships if not r.get("is_active", True)]

    # Measures — unused from unused_measures.json
    unused_meas_analysis = data.get("unused_measures", {})
    if isinstance(unused_meas_analysis, dict):
        unused_meas_analysis = unused_meas_analysis.get("analysis", {})
    
    total_measures = len(measures)
    used_measures = unused_meas_analysis.get("used_measures", 0)
    unused_measures = unused_meas_analysis.get("unused_measures", 0)

    complexities = [m.get("complexity_score", 0) for m in measures if not m.get("is_stub", False)]
    avg_complexity = round(statistics.mean(complexities), 2) if complexities else 0
    max_complexity = max(complexities) if complexities else 0

    return {
        "tables": {
            "total": len(tables),
            "by_type": dict(table_classes),
            "total_columns": total_cols,
            "avg_columns_per_table": round(total_cols / len(tables), 1) if tables else 0,
        },
        "columns": {
            "total": total_cols,
            "by_type": dict(type_dist),
            "used": total_used_cols,
            "unused": total_unused_cols,
            "usage_percentage": round(total_used_cols / max(total_cols, 1) * 100, 1),
            "tables_with_unused": tables_with_unused,
        },
        "relationships": {
            "total": len(relationships),
            "active": len(active_rels),
            "inactive": len(inactive_rels),
        },
        "measures": {
            "total": total_measures,
            "used": used_measures,
            "unused": unused_measures,
            "utilization_percentage": round(used_measures / max(total_measures, 1) * 100, 1),
            "avg_complexity": avg_complexity,
            "max_complexity": max_complexity,
        },
    }


def compute_dax_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze DAX patterns and unused measure details."""
    measures = data["measures"]
    unused_data = data.get("unused_measures", {})
    
    if isinstance(unused_data, dict):
        unused_data = unused_data.get("analysis", {})

    # Function usage
    func_usage = defaultdict(int)
    for m in measures:
        expr = m.get("expression", "")
        for fn in ["CALCULATE", "FILTER", "ALL", "RELATED", "SUMX", "VAR", 
                   "IF", "AND", "OR", "DIVIDE", "SWITCH", "SAMEPERIODLASTYEAR"]:
            if fn in expr.upper():
                func_usage[fn] += 1

    # High-complexity measures
    complex_measures = sorted(
        [m for m in measures if not m.get("is_stub", False)],
        key=lambda x: x.get("complexity_score", 0),
        reverse=True
    )[:5]

    # Measures with dependencies
    measures_with_deps = [m for m in measures if m.get("dependencies")]

    # Patterns
    uses_var = sum(1 for m in measures if "VAR " in m.get("expression", ""))
    uses_calculate = sum(1 for m in measures if "CALCULATE(" in m.get("expression", ""))

    # Get unused measure candidates (top offenders)
    cleanup_candidates = unused_data.get("cleanup_candidates", [])[:10]
    
    return {
        "high_complexity": complex_measures,
        "with_dependencies": len(measures_with_deps),
        "patterns": {
            "uses_calculate": uses_calculate,
            "uses_var": uses_var,
        },
        "most_used_functions": sorted(func_usage.items(), key=lambda x: x[1], reverse=True)[:8],
        "unused_candidates": cleanup_candidates,
        "unused_count": unused_data.get("unused_measures", 0),
    }


def compute_performance_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Identify performance and structural bottlenecks."""
    tables = data["tables"]
    relationships = data["relationships"]
    column_usage = data["column_usage"]

    # Relationship degree
    degree = defaultdict(int)
    for r in relationships:
        if r.get("is_active", True):
            degree[r["from_table"]] += 1
            degree[r["to_table"]] += 1

    hub_tables = sorted(degree.items(), key=lambda x: x[1], reverse=True)[:5]

    # Tables with most unused columns
    unused_heavy = sorted(
        [(cu["table_name"], cu["unused_columns"]) for cu in column_usage],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    # Large tables
    large_tables = sorted(
        [(t["name"], len(t.get("columns", []))) for t in tables],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    # Cardinality
    active_rels = [r for r in relationships if r.get("is_active", True)]
    many_to_many = [r for r in active_rels if r.get("cardinality") == "many_to_many"]
    both_dir = [r for r in active_rels if r.get("cross_filter_direction") == "Both"]

    # Isolated tables
    isolated = [
        t["name"] for t in tables
        if not any(
            r["from_table"] == t["name"] or r["to_table"] == t["name"]
            for r in relationships
        )
    ]

    return {
        "hub_tables": hub_tables,
        "large_tables": large_tables,
        "tables_with_unused_columns": unused_heavy,
        "cardinality_issues": {
            "many_to_many": len(many_to_many),
            "bidirectional_filters": len(both_dir),
        },
        "isolated_tables": len(isolated),
        "inactive_relationships": len([r for r in relationships if not r.get("is_active", True)]),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLM-BASED ANALYZERS — ENRICHED PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_eda_report(metrics: Dict[str, Any], pages: List[Dict], model: str, temperature: float = 0.1) -> str:
    """Generate EDA report with column usage insights."""
    with print_lock:
        print("  [EDA] Generating exploratory analysis...")

    pages_count = len(pages)
    total_visuals = sum(p.get("visuals_count", 0) for p in pages)

    prompt = f"""Analyze this Power BI semantic model structure and data quality:

**Model Composition:**
- {metrics['tables']['total']} tables: {dict(metrics['tables']['by_type'])}
- {metrics['columns']['total']} total columns ({metrics['columns']['usage_percentage']}% used, {metrics['columns']['unused']} unused)
- {metrics['relationships']['total']} relationships ({metrics['relationships']['active']} active)
- {pages_count} report pages with {total_visuals} visuals

**Column Usage Health:**
- {metrics['columns']['tables_with_unused']} tables have unused columns
- Unused column percentage: {round(metrics['columns']['unused']/max(metrics['columns']['total'], 1)*100, 1)}%

**Measure Utilization:**
- {metrics['measures']['total']} measures ({metrics['measures']['utilization_percentage']}% utilized)
- {metrics['measures']['unused']} unused measures (cleanup candidates)
- Complexity range: {metrics['measures']['avg_complexity']} avg, {metrics['measures']['max_complexity']} max

**Column Type Distribution:**
{json.dumps(metrics['columns']['by_type'], indent=2)}

Write 3 paragraphs analyzing:
1. **Data model health** — structure efficiency and asset utilization
2. **Technical debt** — orphaned columns, unused measures, disconnected assets
3. **Optimization opportunities** — quick wins and major improvements needed

Be specific with numbers. Focus on actionable insights for cleanup and optimization."""

    return generate_with_retry(
        prompt=prompt,
        system=SYSTEM_EDA,
        model=model,
        temperature=temperature
    )


def generate_dax_optimization(dax_metrics: Dict[str, Any], model: str, temperature: float = 0.1) -> str:
    """Generate DAX optimization with unused measure analysis."""
    with print_lock:
        print("  [DAX] Analyzing DAX expressions & unused measures...")

    top_complex = dax_metrics["high_complexity"][:3]
    complex_details = "\n".join([
        f"- **{m['name']}** (complexity: {m['complexity_score']}): {m['expression'][:100].strip()}..."
        for m in top_complex
    ])

    unused_details = "\n".join([
        f"- {c['name']} ({c['table']}): complexity {c['complexity']}"
        for c in dax_metrics["unused_candidates"][:5]
    ])

    functions_str = ", ".join([f"{fn}({count})" for fn, count in dax_metrics['most_used_functions']])

    prompt = f"""Optimize Power BI DAX measures and identify cleanup targets:

**Measure Utilization:**
- {dax_metrics['unused_count']} unused measures ({round(dax_metrics['unused_count']/max(dax_metrics['unused_count']+len(dax_metrics['high_complexity']), 1)*100, 1)}% of model)
- {dax_metrics['with_dependencies']} measures have cross-measure dependencies
- {dax_metrics['patterns']['uses_var']} measures use VAR (good: {round(dax_metrics['patterns']['uses_var']/max(len(dax_metrics['high_complexity']), 1)*100, 1)}%)
- {dax_metrics['patterns']['uses_calculate']} measures use CALCULATE

**Top DAX Functions:**
{functions_str}

**Most Complex Measures (optimization targets):**
{complex_details}

**Top Unused Measure Candidates (removal candidates):**
{unused_details}

Provide 4 actionable recommendations:
1. **Unused measure cleanup** — which to remove and why
2. **High-complexity refactoring** — specific optimization patterns
3. **Variable strategy** — best practices for VAR usage
4. **Dependency simplification** — reduce cross-measure coupling

Include concrete DAX examples."""

    return generate_with_retry(
        prompt=prompt,
        system=SYSTEM_DAX,
        model=model,
        temperature=temperature
    )


def generate_performance_analysis(perf_metrics: Dict[str, Any], model: str, temperature: float = 0.1) -> str:
    """Generate performance analysis with unused asset focus."""
    with print_lock:
        print("  [Performance] Analyzing model bottlenecks...")

    hub_details = "\n".join([
        f"- {name}: {degree} connections"
        for name, degree in perf_metrics["hub_tables"]
    ])

    unused_col_details = "\n".join([
        f"- {name}: {count} unused columns"
        for name, count in perf_metrics["tables_with_unused_columns"]
    ])

    prompt = f"""Identify critical performance and maintenance bottlenecks:

**Structural Issues:**
- {perf_metrics['cardinality_issues']['many_to_many']} many-to-many relationships
- {perf_metrics['cardinality_issues']['bidirectional_filters']} bidirectional filters
- {perf_metrics['inactive_relationships']} inactive relationships
- {perf_metrics['isolated_tables']} isolated tables (no relationships)

**Hub Tables (connection bottlenecks):**
{hub_details}

**Tables with Most Unused Columns (data model bloat):**
{unused_col_details}

Provide a 5-point optimization roadmap:
1. **CRITICAL** — Must fix first (impact vs effort)
2. **Column cleanup** — Which unused columns to remove by table
3. **Relationship issues** — Cardinality problems and solutions
4. **Hub table optimization** — Break complex hubs or use roles
5. **Model simplification** — Remove isolated tables and orphaned assets

Estimate effort level (quick/medium/large) for each recommendation."""

    return generate_with_retry(
        prompt=prompt,
        system=SYSTEM_PERF,
        model=model,
        temperature=temperature
    )


def generate_data_quality_report(data: Dict[str, Any], column_usage: List[Dict], model: str, temperature: float = 0.1) -> str:
    """Generate data quality audit from column_usage.json."""
    with print_lock:
        print("  [Quality] Auditing data quality & coverage...")

    # Aggregate column usage stats
    total_tables = len(column_usage)
    tables_with_issues = len([cu for cu in column_usage if cu.get("unused_columns", 0) > 0])
    total_unused = sum(cu.get("unused_columns", 0) for cu in column_usage)

    # Find worst offenders
    worst_tables = sorted(
        column_usage,
        key=lambda x: x.get("unused_columns", 0),
        reverse=True
    )[:5]

    worst_details = "\n".join([
        f"- {t['table_name']}: {t['unused_columns']}/{t['total_columns']} unused ({round(t.get('unused_columns', 0)/max(t['total_columns'], 1)*100, 1)}%)"
        for t in worst_tables
    ])

    prompt = f"""Audit data model completeness and column usage health:

**Coverage Analysis:**
- {total_tables} tables analyzed
- {tables_with_issues} tables have unused columns
- {total_unused} total unused columns across model
- Average usage: {round(sum(cu.get('used_columns', 0) for cu in column_usage)/max(sum(cu.get('total_columns', 0) for cu in column_usage), 1)*100, 1)}%

**Tables with Highest Column Waste:**
{worst_details}

**Context:**
- Unused columns increase: storage, ETL processing, refresh time, user confusion
- Hidden columns still impact performance
- Orphaned columns often indicate incomplete deprecation

Write 3 actionable recommendations:
1. **Priority columns to remove** — with business impact assessment
2. **Documentation improvements** — clearly mark deprecated vs intentionally hidden
3. **Governance rules** — prevent future column accumulation

Focus on business value of cleanup, not just technical metrics."""

    return generate_with_retry(
        prompt=prompt,
        system=SYSTEM_QUALITY,
        model=model,
        temperature=temperature
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN ORCHESTRATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_analysis(
    data_dir: str,
    output_dir: str,
    project_name: str = "Power BI Model",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 2000
) -> Dict[str, Path]:
    """Generate comprehensive analysis from ALL data sources."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 1. Load ALL data
    data = load_all(data_dir)

    # 2. Compute metrics
    print("\n[2/5] Computing analysis metrics...\n")
    eda_metrics = compute_eda_metrics(data)
    dax_metrics = compute_dax_metrics(data)
    perf_metrics = compute_performance_metrics(data)

    # 3. Generate reports (PARALLEL)
    print("\n[3/5] Generating LLM-based reports (parallel)...\n")

    reports = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(generate_eda_report, eda_metrics, data["pages"], model, temperature): "eda",
            executor.submit(generate_dax_optimization, dax_metrics, model, temperature): "dax",
            executor.submit(generate_performance_analysis, perf_metrics, model, temperature): "perf",
            executor.submit(generate_data_quality_report, data, data["column_usage"], model, temperature): "quality",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                reports[key] = future.result(timeout=300)  # 5 min timeout per report
            except Exception as e:
                with print_lock:
                    print(f"  [ERROR] {key.upper()} generation failed: {e}")
                reports[key] = f"Failed to generate {key} report: {str(e)}"
    
    eda_report = reports.get("eda", "")
    dax_report = reports.get("dax", "")
    perf_report = reports.get("perf", "")
    quality_report = reports.get("quality", "")

    # 4. Assemble documents
    print("\n[4/5] Assembling comprehensive documentation...")

    # EDA Report
    eda_doc = f"""# {project_name} — Exploratory Data Analysis & Asset Utilization

{eda_report}

## Key Metrics

| Metric | Value |
|--------|-------|
| Tables | {eda_metrics['tables']['total']} |
| Total Columns | {eda_metrics['columns']['total']} |
| Column Usage | {eda_metrics['columns']['usage_percentage']}% |
| Unused Columns | {eda_metrics['columns']['unused']} |
| Active Relationships | {eda_metrics['relationships']['active']} |
| Total Measures | {eda_metrics['measures']['total']} |
| Measure Utilization | {eda_metrics['measures']['utilization_percentage']}% |
| Unused Measures | {eda_metrics['measures']['unused']} |
"""

    eda_path = output_path / "01_EDA_REPORT.md"
    with open(eda_path, "w", encoding="utf-8") as f:
        f.write(eda_doc)

    # DAX Optimization Report
    dax_doc = f"""# {project_name} — DAX Optimization & Measure Cleanup

{dax_report}
"""

    dax_path = output_path / "02_DAX_OPTIMIZATION.md"
    with open(dax_path, "w", encoding="utf-8") as f:
        f.write(dax_doc)

    # Performance Analysis Report
    perf_doc = f"""# {project_name} — Performance Analysis & Bottleneck Resolution

{perf_report}
"""

    perf_path = output_path / "03_PERFORMANCE_ANALYSIS.md"
    with open(perf_path, "w", encoding="utf-8") as f:
        f.write(perf_doc)

    # Data Quality Report
    quality_doc = f"""# {project_name} — Data Quality Audit & Column Coverage

{quality_report}
"""

    quality_path = output_path / "04_DATA_QUALITY.md"
    with open(quality_path, "w", encoding="utf-8") as f:
        f.write(quality_doc)

    print("\n[5/5] Documentation complete.\n")

    return {
        "eda": eda_path,
        "dax": dax_path,
        "performance": perf_path,
        "quality": quality_path,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    print("=" * 80)
    print("  Power BI Analysis & Optimization Engine v2")
    print("="*80)

    # Find root
    root = find_root_dir()
    
    # Parse arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        list_projects(root)
        sys.exit(0)

    project_name = sys.argv[1] if len(sys.argv) > 1 else None
    model_name = sys.argv[2] if len(sys.argv) > 2 else os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    temperature = float(sys.argv[3]) if len(sys.argv) > 3 else float(os.getenv("OLLAMA_TEMP", "0.1"))
    max_tokens = int(sys.argv[4]) if len(sys.argv) > 4 else int(os.getenv("OLLAMA_TOKENS", "2000"))

    # Find project data
    data_dir = find_project_data_dir(project_name, root)
    if not data_dir:
        print("\n❌ Project not found")
        print("\nTry: python ollama_generator.py --list")
        sys.exit(1)

    project_name = data_dir.parent.name
    output_dir = root / "ai_analysis_output"

    print(f"\n[Project]   {project_name}")
    print(f"[Data]      {data_dir}")
    print(f"[Output]    {output_dir}")
    print(f"[Model]     {model_name}")
    print(f"[Temp]      {temperature}")
    print(f"[Tokens]    {max_tokens}\n")

    if not check_connection(model_name):
        print(f"\n❌ Start Ollama:")
        print(f"   ollama serve")
        print(f"   ollama pull {model_name}")
        sys.exit(1)

    print(f"[OK] Ollama connected — {model_name}\n")

    try:
        results = generate_analysis(
            data_dir=str(data_dir),
            output_dir=str(output_dir),
            project_name=project_name,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens
        )

        print("\n" + "="*80)
        print("  ✅ ANALYSIS COMPLETE")
        print("="*80)
        for key, path in results.items():
            print(f"\n  📄 {key.upper()}")
            print(f"     {path.resolve()}")

        print("\n" + "="*80)

    except FileNotFoundError as e:
        print(f"\n❌ File not found: {e}")
        sys.exit(1)
    except ConnectionError as e:
        print(f"\n❌ Ollama error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise