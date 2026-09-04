# Power BI Project Analyzer

> **Modular semantic model analysis for Power BI projects (.pbip)**  
> Extract and classify Power BI tables, relationships, measures, and pages into structured JSON outputs with comprehensive Markdown documentation, visualizations, and optional AI enrichment.

![Python Version](https://img.shields.io/badge/python-3.6%2B-blue)
![Visualizations](https://img.shields.io/badge/Visualizations-5%20types-brightgreen)
![AI Integration](https://img.shields.io/badge/AI%20Integration-Ollama-orange)

---

## 🎯 Features

- **📊 Table Classification**: FACT, DIMENSION, BRIDGE, CALCULATION, PARAMETER tables with confidence scores
- **🔗 Relationship Analysis**: M:1 relationships with schema compliance scoring  
- **📐 Measure Analysis**: DAX complexity scoring and dependency graphs
- **📄 Report Pages**: Inventory of report pages and visualizations
- **🗂️ Data Sources**: Identifies semantic model data sources
- **📈 5 Visualization Types**:
  - Relationship network graph + interactive HTML
  - Measure dependency DAG
  - Complexity heatmap matrix
  - Schema type distribution donut chart
  - Data type distribution bar chart
- **📝 Dual Documentation**:
  - `TECHNICAL_DOCUMENTATION.md` - Concise executive summary (5-15 pages)
  - `powerbi_analysis_*.md` - Comprehensive analysis with charts (20-50 pages)
- **🤖 Optional AI Enhancement**: Auto-classify tables and measure descriptions with Ollama
- **Zero Core Dependencies**: Pure Python for all core analysis

---

## 📦 Installation

### 1. Clone & Setup

```bash
git clone <repository-url>
cd powerbi-project
pip install -r requirements.txt
```

### 2. Verify Installation

```bash
python -c "import matplotlib, seaborn, networkx; print('✅ Core dependencies OK')"
```

### 3. Optional: AI Integration (Ollama)

For AI-enhanced table classification and measure descriptions:

```bash
# Install Ollama from https://ollama.ai
ollama pull phi3:14b          # Download model (recommended)
# OR
ollama pull qwen2:14b         # Alternative model

# In another terminal, start Ollama server
ollama serve
# Ollama will listen on http://localhost:11434
```

---

## 🚀 Usage - Multiple Ways to Launch

### **Method 1: Single Power BI Project**

```bash
python main.py ../RecursosFuente/OnlineBaseline.pbip
```

Output location: `reports/OnlineBaseline/`

### **Method 2: All Projects in a Folder (Batch Processing)**

```bash
python main.py ../RecursosFuente/
```

Processes all `.pbip` files in the folder recursively.  
Output location: `reports/` (one subfolder per project)

### **Method 3: Current Folder**

```bash
python main.py .
```

Analyzes projects in the current directory.

### **Method 4: Platform-Specific Wrappers**

**Windows:**
```bash
run.bat ../RecursosFuente/OnlineBaseline.pbip
```

**Linux/macOS:**
```bash
./run.sh ../RecursosFuente/OnlineBaseline.pbip
```

---

## 📊 Generated Outputs

### Directory Structure

```
reports/
└── ProjectName/
    ├── data/
    │   ├── tables.json               # Table metadata
    │   ├── relationships.json        # Relationship definitions
    │   ├── measures.json             # DAX measures
    │   ├── pages.json                # Report pages
    │   ├── datasources.json          # Data connections
    │   ├── classifications.json      # Table classifications
    │   ├── column_usage.json         # Column usage analysis
    │   ├── unused_measures.json      # Unused measures
    │   └── scoring_result.json       # Model health score
    │
    ├── reports/
    │   ├── TECHNICAL_DOCUMENTATION.md      # Executive summary
    │   ├── powerbi_analysis_TIMESTAMP.md   # Comprehensive analysis
    │   └── compliance_report.md            # Compliance audit
    │
    └── graphs/
        ├── relationship_graph.png           # Table network visualization
        ├── relationship_graph.html          # Interactive version
        ├── measure_dependency.png           # DAX dependency DAG
        ├── complexity_heatmap.png          # Complexity matrix
        ├── schema_type_donut.png           # Table type distribution
        └── datatype_distribution.png       # Column data type chart
```

### Documentation Files Explained

**TECHNICAL_DOCUMENTATION.md** - For executives and quick reference
- General description with key statistics
- Table mapping by type (FACT, DIMENSION, etc.)
- Tables composition table
- Relationships summary
- Pages overview
- ~5-15 pages, copy-paste ready

**powerbi_analysis_*.md** - Comprehensive analysis
- Executive overview with statistics
- 5 embedded visualizations
- Detailed table classifications
- Complete relationships analysis
- Measures overview with DAX snippets
- Columns details by table
- Data quality assessment
- ~20-50 pages, publication-ready

**compliance_report.md** - Audit and compliance
- Overall model health score
- Issues by severity (CRITICAL, WARNING, INFO)
- Penalties and bonuses breakdown
- Prioritized recommendations

For more details, see [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md).

---

## 🤖 AI Enhancement (Optional)

### Prerequisites

1. Ollama running: `ollama serve` (in separate terminal)
2. Model downloaded: `ollama pull phi3:14b`

### Generate AI-Enriched Documentation

**Option A: Auto-detect Project**
```bash
python scripts/ollama_generator.py
```
Uses the first project found in `reports/`

**Option B: Specific Project**
```bash
python scripts/ollama_generator.py Americas
```

**Option C: Custom Model & Settings**
```bash
python scripts/ollama_generator.py Americas phi3:14b 0.1
```

**Option D: Full Control**
```bash
python scripts/ollama_generator.py <project> <model> <temperature> <max_tokens>
```

### Parameters

| Parameter | Options | Default | Example |
|-----------|---------|---------|---------|
| `project` | Project name (partial) | First project | `Americas` |
| `model` | phi3:14b, qwen2:14b, llama3.1 | phi3:14b | `qwen2:14b` |
| `temperature` | 0.0-1.0 | 0.1 | `0.1` (deterministic) |
| `max_tokens` | Integer | 2000 | `4000` |

### What AI Does

1. **Classify Tables**: FACT, DIMENSION, BRIDGE, CALCULATION, PARAMETER
2. **Describe Measures**: Aggregation type, complexity assessment
3. **Generate Documentation**: AI-powered markdown with insights

### Output

- `output_ai/tables_enriched.json` - Tables with AI annotations
- `output_ai/AI_DOCUMENTATION.md` - AI-generated analysis

### Troubleshooting AI

**Problem:** "Cannot connect to Ollama"
```bash
# Terminal 1: Start Ollama server
ollama serve

# Terminal 2: Run analysis
python scripts/ollama_generator.py
```

**Problem:** "Model not found"
```bash
ollama pull phi3:14b
```

**Problem:** Slow performance
- Use faster model: `phi3:3.8b`
- Lower temperature: `0.1` (faster than 0.5)
- Check status: `ollama ps`

---

## 📖 Documentation Reference

Three comprehensive markdown documents explain the project:

1. **[README.md](README.md)** ← You are here
   - Installation and all launch methods
   - Quick start guide
   - Output descriptions

2. **[ARCHITECTURE.md](ARCHITECTURE.md)**
   - Project structure and organization
   - Data flow pipeline
   - Module descriptions
   - Component responsibilities

3. **[DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md)**
   - Output document formats explained
   - TECHNICAL_DOCUMENTATION vs powerbi_analysis comparison
   - Content samples and examples
   - Table structure descriptions

---

## ⚡ Quick Examples

### Example 1: Analyze a Single Project
```bash
python main.py ../RecursosFuente/OnlineBaseline.pbip
# Output: reports/OnlineBaseline/
```

### Example 2: Batch Process All Projects with AI Enhancement
```bash
# Generate standard reports
python main.py ../RecursosFuente/

# Then enhance with AI (terminal 2, Ollama running)
python scripts/ollama_generator.py Americas
python scripts/ollama_generator.py "Consolidated P&L"
```

### Example 3: Windows Batch Wrapper
```bash
run.bat ../RecursosFuente/OnlineBaseline.pbip
# Handles path encoding automatically
```

---

## 🔧 Troubleshooting

### Issue: Path not found
```bash
# Use absolute path
python main.py C:\Full\Path\To\RecursosFuente\
```

### Issue: Special characters in paths ("Programación")
```bash
# Use run.bat (Windows) or run.sh (Linux/Mac)
run.bat ../RecursosFuente/
```

### Issue: Missing dependencies
```bash
pip install --upgrade -r requirements.txt
```

### Issue: Visualizations not generating
```bash
# Ensure matplotlib and seaborn are installed
pip install matplotlib>=3.7.0 seaborn>=0.12.0
```

---

## 📋 Requirements

- **Python:** 3.6+
- **Core:** json, re, pathlib, collections (built-in)
- **Visualization:** matplotlib, seaborn, networkx
- **Optional AI:** Ollama (local instance)

See `requirements.txt` for complete list.

---

## 📝 License & Credits

Built with Python | Power BI Analysis | 2026
- Tables and Composition
- Relationships (table format)
- Pages

**Perfect for:**
- Stakeholder presentations
- Quick model reviews
- Non-technical audiences
- Email sharing

---

#### **2. powerbi_analysis_TIMESTAMP.pdf**
📊 **Purpose:** Comprehensive technical analysis  
📄 **Length:** 20-50 pages | Detailed with 5 embedded charts

**Contains:**
- Executive Overview with stats
- Model Complexity Analysis (with visualizations)
- Detailed Table Classifications
- Complete Relationships Analysis
- Measures Overview with DAX snippets
- Column-level inventory
- Data Quality Assessment

**Perfect for:**
- Data architects
- Deep technical reviews
- Model documentation
- Archival purposes

---

### File Structure

```
powerbi-project/
│
├── data/                          ← 📊 JSON data files (6 files)
│   ├── tables.json               # Table metadata, columns, datatypes
│   ├── relationships.json        # Model relationships with cardinality
│   ├── measures.json             # DAX measures with complexity scores
│   ├── pages.json                # Report pages and visualizations
│   ├── datasources.json          # Data source definitions
│   └── classifications.json      # Table classifications + schema analysis
│
├── reports/                       ← 📝 Markdown + PDF Documentation ✨
│   ├── TECHNICAL_DOCUMENTATION.md
│   ├── powerbi_analysis_20260427_120000.md
│
└── graphs/                        ← 📈 Visualizations (5 PNG + 1 HTML)
    ├── relationship_graph.png
    ├── relationship_graph.html
    ├── measure_dependency.png
    ├── complexity_heatmap.png
    ├── schema_type_donut.png
    └── datatype_distribution.png
```

---

## 🏗️ Architecture

```
parsers/
├── parse_tables.py         # Extract tables, columns, measures
├── parse_relationships.py  # Extract relationships with cardinality
├── parse_measures.py       # Extract measures with DAX complexity
├── parse_pages.py          # Extract report pages and visualizations
├── parse_datasources.py    # Extract data source definitions
└── parse_analysis.py       # Table classification + schema analysis

main.py                      # Orchestrator: runs all parsers + generates docs + PDF export
run.bat / run.sh             # Platform-specific convenience wrappers
```

---

## 📦 Installation & Dependencies

### Core Analysis (Always included)
- Python 3.6+
- No external dependencies - uses Python standard library only

### PDF Export ✨ NEW (Optional but recommended)
```bash
# Install full dependencies
pip install -r requirements.txt

# Or just PDF dependencies
pip install weasyprint markdown2
```

> See [PDF_EXPORT_SETUP.md](PDF_EXPORT_SETUP.md) for system-specific requirements.

### Visualizations (Optional)
- matplotlib, seaborn, networkx, plotly (included in requirements.txt)

---

## 📝 Example

```python
# main.py orchestrates the complete pipeline:
1. parse_tables.py        → tables.json
2. parse_relationships.py → relationships.json
3. parse_measures.py      → measures.json
4. parse_pages.py         → pages.json
5. parse_datasources.py   → datasources.json
6. parse_analysis.py      → classifications.json

# Then generates documentation:
7. TECHNICAL_DOCUMENTATION.md
8. powerbi_analysis_TIMESTAMP.md
```

---

## 🔍 Example Analysis Output

**Table Classification:**
- 13 tables identified
- STAR schema (1 fact + 8 dimensions + 4 isolated)
- 85/100 schema compliance score

**Relationships:**
- 10 M:1 relationships extracted
- 4 disconnected components identified

**Measures:**
- 34 measures documented
- Complexity range: 1-10 (avg complexity score: 4.2)

**Report Pages:**
- 6 pages identified
- 120 total visualizations

---

## 📋 Requirements

- Python 3.6+
- **No external dependencies** - uses Python standard library only

---

## 🛠️ Development

### Adding New Parsers

1. Create `parsers/parse_newfeature.py`
2. Implement parser class extending base pattern
3. Output to JSON file
4. Register in `main.py` DocumentationGenerator

### Testing

```bash
# Test with the included OnlineBaseline.pbip
python main.py ../RecursosFuente/OnlineBaseline.pbip
```

---

## 📄 License

MIT

---

## 📧 Support

For issues or questions, please open an issue in the repository.
