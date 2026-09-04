# Project Structure & Architecture

## Directory Layout

```
powerbi-project/
│
├── main.py                         # Master orchestrator - entry point
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Package configuration
│
├── README.md                       # 📖 Installation & launch methods
├── ARCHITECTURE.md                 # 📋 Project structure (this file)
├── DOCUMENTATION_STRUCTURE.md      # 📄 Output format reference
│
├── run.bat                         # Windows launcher
├── run.sh                          # Linux/macOS launcher
│
├── parsers/                        # TMDL & JSON parsers
│   ├── parse_analysis.py           # Table classification & analysis
│   ├── parse_datasources.py        # Data source extraction
│   ├── parse_measures.py           # DAX measures & complexity
│   ├── parse_pages.py              # Report pages & visuals
│   ├── parse_relationships.py      # Relationship definitions
│   └── parse_tables.py             # Table structures & columns
│
├── visualizers/                    # PNG visualization generators
│   ├── complexity_heatmap.py       # Complexity matrix heatmap
│   ├── datatype_distribution.py    # Data type bar chart
│   ├── measure_dependency.py       # DAX dependency DAG
│   ├── relationship_graph.py       # Network relationship diagram
│   ├── schema_distribution.py      # Table type donut chart
│   └── __init__.py
│
├── scripts/                        # Utility & AI scripts
│   ├── ollama_client.py            # Ollama HTTP client
│   ├── ollama_generator.py         # AI-enhanced documentation
│   ├── check_classification.py     # Validate classifications
│   ├── check_types.py              # Data type validation
│   ├── inspect_tmdl.py             # TMDL file inspection
│   └── __init__.py
│
└── reports/                        # 📊 Generated outputs (per project)
    └── ProjectName/
        ├── data/
        │   ├── tables.json                 # Table metadata
        │   ├── relationships.json          # Relationship definitions
        │   ├── measures.json               # DAX measures
        │   ├── pages.json                  # Report pages
        │   ├── datasources.json            # Data connections
        │   ├── classifications.json        # Table classifications (FACT, DIMENSION, etc.)
        │   ├── column_usage.json           # Column usage analysis
        │   ├── unused_measures.json        # Unused measures report
        │   └── scoring_result.json         # Model health score
        │
        ├── reports/
        │   ├── TECHNICAL_DOCUMENTATION.md      # Executive summary
        │   ├── powerbi_analysis_TIMESTAMP.md   # Comprehensive analysis
        │   └── compliance_report.md            # Compliance audit report
        │
        └── graphs/
            ├── relationship_graph.png           # Network visualization
            ├── relationship_graph.html          # Interactive version
            ├── measure_dependency.png           # DAX dependency graph
            ├── complexity_heatmap.png          # Complexity matrix
            ├── schema_type_donut.png           # Table type distribution
            └── datatype_distribution.png       # Column data types
```

---

## Data Flow Pipeline

```
RecursosFuente/ (.pbip files)
    │
    ├── OnlineBaseline.pbip
    │   ├── SemanticModel/
    │   │   └── definition/ (TMDL files)
    │   │       ├── database.tmdl
    │   │       ├── model.tmdl
    │   │       ├── relationships.tmdl
    │   │       ├── expressions.tmdl
    │   │       ├── cultures/
    │   │       ├── roles/
    │   │       └── tables/ (individual .tmdl files)
    │   └── Report/
    │       └── definition/ (JSON pages)
    │
    └── DataSources (CSV, databases, etc.)
            ↓
        [STEP 1: PARSING]
        ├── parse_tables.py       → tables.json
        ├── parse_measures.py     → measures.json
        ├── parse_relationships.py → relationships.json
        ├── parse_pages.py        → pages.json
        ├── parse_datasources.py  → datasources.json
        ├── parse_analysis.py     → classifications.json
        └── column_analyzer.py    → column_usage.json
            ↓
        [STEP 2: SCORING]
        └── scoring_engine.py     → scoring_result.json
            ↓
        [STEP 3: DOCUMENTATION]
        ├── technical_documentation_generator.py
        ├── extended_documentation_generator.py
        └── compliance_report_generator.py
            ↓
        [STEP 4: VISUALIZATIONS]
        ├── relationship_graph.py       → PNG + HTML
        ├── measure_dependency.py       → PNG
        ├── complexity_heatmap.py       → PNG
        ├── schema_distribution.py      → PNG
        └── datatype_distribution.py    → PNG
            ↓
        [OPTIONAL STEP 5: AI ENHANCEMENT]
        └── ollama_generator.py
            ├── Classify tables with AI
            ├── Describe measures
            └── Generate AI_DOCUMENTATION.md
            ↓
        [OUTPUT] reports/ProjectName/
        ├── data/ (JSON files)
        ├── reports/ (Markdown docs)
        └── graphs/ (Visualizations)
```

---

## Execution Modes

### Mode 1: Single Project
```bash
python main.py path/to/project.pbip
```
Analyzes one Power BI project.

### Mode 2: Batch Processing (All Projects)
```bash
python main.py path/to/folder/
```
Finds and analyzes all `.pbip` files recursively.

### Mode 3: Current Directory
```bash
python main.py .
```
Analyzes projects in current folder.

### Mode 4: Platform Wrappers
```bash
run.bat path/to/project.pbip      # Windows
./run.sh path/to/project.pbip     # Linux/macOS
```
Handles special characters in paths.

---

## Key Components Explained

### Parsers (`parsers/`)
- **parse_tables.py**: Extracts table names, columns, data types, and measures
- **parse_measures.py**: Extracts DAX measures and calculates complexity
- **parse_relationships.py**: Maps M:1 relationships and cardinality
- **parse_pages.py**: Lists report pages and visual definitions
- **parse_datasources.py**: Identifies data connections and sources
- **parse_analysis.py**: Classifies tables (FACT, DIMENSION, BRIDGE, etc.) with confidence scoring

**Output:** Six JSON files with structured analysis data

### Visualizers (`visualizers/`)
- **complexity_heatmap.py**: Matrix showing table complexity metrics (columns, measures, relationships)
- **datatype_distribution.py**: Bar chart of column data type distribution
- **measure_dependency.py**: Directed acyclic graph (DAG) of measure dependencies
- **relationship_graph.py**: Network visualization of table relationships (PNG + interactive HTML)
- **schema_distribution.py**: Donut chart showing FACT/DIMENSION/BRIDGE distribution

**Output:** Five PNG files (+ one HTML for interactivity)

### Documentation Generators
- **technical_documentation_generator.py**: Executive summary (5-15 pages)
  - General description
  - Table mapping by type
  - Relationships summary
  - Pages overview
  
- **extended_documentation_generator.py**: Comprehensive analysis (20-50 pages)
  - Executive overview with statistics
  - All 5 embedded visualizations
  - Detailed classifications
  - Measure analysis
  - Columns details by table
  
- **compliance_report_generator.py**: Audit-ready report
  - Model health score with grade
  - Issues by severity (CRITICAL, WARNING, INFO)
  - Recommendations
  - Penalties and bonuses breakdown

### AI Enhancement (Optional)
- **ollama_generator.py**: Orchestrates AI enrichment
  - Classifies tables using LLM
  - Generates measure descriptions
  - Creates AI-powered documentation
- **ollama_client.py**: HTTP client for local Ollama instance

---

## Data Structures

### classifications.json (Parser Output)
```json
{
  "table_classifications": [
    {
      "name": "FactSales",
      "classification": "FACT",
      "confidence": 0.95,
      "reasoning": "..."
    }
  ],
  "relationship_analysis": {
    "total_tables": 20,
    "total_relationships": 18,
    "active_relationships": 16,
    "schema_type": "STAR",
    "relationships": [
      {
        "from_table": "FactSales",
        "to_table": "DimProduct",
        "cardinality": "M:1"
      }
    ]
  },
  "summary": {
    "fact_tables": 3,
    "dimension_tables": 15,
    "bridge_tables": 1,
    "calculation_tables": 1,
    "parameter_tables": 0,
    "total_measures": 45,
    "total_columns": 120,
    "schema_type": "STAR"
  }
}
```

### scoring_result.json (Scoring Output)
```json
{
  "score": 77,
  "grade": "B",
  "total_issues": 10,
  "critical_count": 5,
  "warning_count": 4,
  "info_count": 1,
  "recommendations": [...]
}
```

---

## Workflow

### Basic Pipeline (Default)
1. User runs `python main.py <path>`
2. Parsers extract TMDL data → JSON files
3. Scoring engine calculates model health
4. Documentation generators create Markdown
5. Visualizers create PNG charts
6. Output organized in `reports/ProjectName/`

### With AI Enhancement (Optional)
1. Run basic pipeline first
2. Start Ollama: `ollama serve`
3. Run: `python scripts/ollama_generator.py <project>`
4. AI enriches JSON and generates additional documentation

---

## Dependencies

### Core (Built-in Python)
- `json`, `re`, `pathlib`, `collections`

### Analysis & Visualization
- `matplotlib` 3.7.0+
- `seaborn` 0.12.0+
- `networkx` 3.1+
- `pyyaml` (for configuration)

### Optional
- `ollama` (AI enrichment)
- `plotly`, `pyvis` (interactive visualizations)

---

## Environment Requirements

- **Python:** 3.6+
- **OS:** Windows, Linux, macOS
- **Special chars:** Use `run.bat`/`run.sh` for paths with accents or spaces

---

## Performance Notes

### Parsing Speed
- ~2-5 seconds per .pbip file (depends on model size)
- Batch processing processes files sequentially

### Visualization Generation
- ~1-2 seconds per visualization type
- All visualizers run in parallel when possible

### AI Enhancement (Optional)
- First run: ~30-60 seconds (model loading)
- Subsequent runs: ~20-40 seconds (model warm)
- Depends on: model size, temperature setting, response length

---

## Recent Updates

### ✅ Phase 5 Optimization
- Renamed `analysis.json` → `classifications.json` (parser-only output)
- Updated all visualizers to use new filename and data structure
- Fixed relationship counting in complexity heatmap
- All 5 visualizations now generate correctly

### ✅ Batch Processing
- Added support for processing entire folders recursively
- Each project gets separate `reports/ProjectName/` subfolder
- Organized output by data, reports, graphs

### ✅ AI Integration
- Ollama client for local LLM integration
- AI table classification and measure descriptions
- Enriched JSON with AI annotations

### 📋 Documentation
- Three main documentation files (README, ARCHITECTURE, DOCUMENTATION_STRUCTURE)
- Consolidated all quickstart guides
- Updated examples with current functionality

---

## File Organization Principles

1. **Separation of Concerns**: Parsers, visualizers, and generators are independent
2. **JSON Data Contracts**: Each parser outputs standard JSON structure
3. **Output Organization**: Reports organized by project name
4. **Batch-Friendly**: Can process multiple projects with single command
5. **Optional Enhancements**: AI and visualization are optional but integrated

---

## Next Steps

See [README.md](README.md) for installation and launch instructions.  
See [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md) for output format details.
