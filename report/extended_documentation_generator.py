#!/usr/bin/env python3
"""
Extended Documentation Generator.

Produces: powerbi_analysis_TIMESTAMP.md (comprehensive analysis)
- Executive overview with statistics
- Model complexity analysis with charts
- Tables summary and classifications
- Detailed relationships analysis
- Measures overview with utilization
- Columns details by table
- Report pages analysis
- Table column usage by table
- Data quality assessment
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from .base_documentation_generator import BaseDocumentationGenerator


class ExtendedDocumentationGenerator(BaseDocumentationGenerator):
    """Generates comprehensive powerbi_analysis_TIMESTAMP.md."""

    def __init__(self, output_dir: Path, pbip_name: str):
        super().__init__(output_dir, pbip_name)

    def generate(self) -> tuple[str, str]:
        """
        Generate extended documentation.
        
        Returns:
            Tuple of (content, filename)
        """
        self.load_all_data()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"powerbi_analysis_{timestamp}.md"
        
        content = self._build_document()
        return content, filename

    def _build_document(self) -> str:
        """Build the complete extended documentation."""
        doc: list[str] = []

        doc.extend(self._section_header())
        doc.extend(self._section_toc())
        doc.extend(self._section_executive_overview())
        doc.extend(self._section_model_complexity())
        doc.extend(self._section_tables_summary())
        doc.extend(self._section_detailed_classifications())
        doc.extend(self._section_relationships_analysis())
        doc.extend(self._section_measures_overview())
        doc.extend(self._section_columns_details())
        doc.extend(self._section_report_pages())
        doc.extend(self._section_column_usage_analysis())
        doc.extend(self._section_data_quality())

        return "\n".join(doc)

    def _section_header(self) -> list[str]:
        """Header section."""
        return [
            "# Power BI Semantic Model - Comprehensive Analysis",
            f"**Project:** {self.pbip_name}",
            f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "---",
            ""
        ]

    def _section_toc(self) -> list[str]:
        """Table of contents section."""
        return [
            "## Table of Contents",
            "1. [Executive Overview](#executive-overview)",
            "2. [Model Complexity Analysis](#model-complexity-analysis)",
            "3. [Tables Summary](#tables-summary)",
            "4. [Detailed Table Classifications](#detailed-table-classifications)",
            "5. [Relationships Analysis](#relationships-analysis)",
            "6. [Measures Overview](#measures-overview)",
            "7. [Columns Details](#columns-details)",
            "8. [Report Pages](#report-pages)",
            "9. [Table Column Usage](#table-column-usage)",
            "10. [Data Quality](#data-quality)",
            ""
        ]

    def _section_executive_overview(self) -> list[str]:
        """Executive overview section."""
        lines = ["---", "## Executive Overview", ""]

        summary = self.analysis_data.get("summary", {}) if isinstance(self.analysis_data, dict) else {}
        rel_analysis = self.analysis_data.get("relationship_analysis", {}) if isinstance(self.analysis_data, dict) else {}

        lines.extend(self._subsection_model_statistics(summary))
        lines.extend(self._subsection_table_distribution(summary))
        lines.extend(self._subsection_model_health(rel_analysis))

        return lines

    def _subsection_model_statistics(self, summary: dict[str, Any]) -> list[str]:
        """Model statistics subsection."""
        return [
            "### Model Statistics",
            "",
            f"- **Total Tables:** {summary.get('total_tables', len(self.tables_data))}",
            f"- **Total Relationships:** {len(self.relationships_data)}",
            f"- **Total Measures:** {summary.get('total_measures', len(self.measures_data))}",
            f"- **Schema Type:** {summary.get('schema_type', 'N/A')}",
            f"- **Report Pages:** {len(self.pages_data)}",
            ""
        ]

    def _subsection_table_distribution(self, summary: dict[str, Any]) -> list[str]:
        """Table distribution subsection."""
        return [
            "### Table Distribution",
            "",
            f"- **Fact Tables:** {summary.get('fact_tables', 0)}",
            f"- **Dimension Tables:** {summary.get('dimension_tables', 0)}",
            f"- **Bridge Tables:** {summary.get('bridge_tables', 0)}",
            f"- **Calculation Tables:** {summary.get('calculation_tables', 0)}",
            f"- **Parameter Tables:** {summary.get('parameter_tables', 0)}",
            ""
        ]

    def _subsection_model_health(self, rel_analysis: dict[str, Any]) -> list[str]:
        """Model health subsection."""
        usage_summary = self._get_table_usage_summary()
        return [
            "### Model Health",
            "",
            f"- **Total Columns:** {usage_summary.get('total_columns', 0)}",
            f"- **Columns Used in Measures:** {usage_summary.get('columns_used_in_measures', 0)}",
            f"- **Columns Used in Pages:** {usage_summary.get('columns_used_in_pages', 0)}",
            f"- **Unused Columns:** {usage_summary.get('total_unused', 0)}",
            ""
        ]

    def _section_model_complexity(self) -> list[str]:
        """Model complexity analysis section."""
        lines = ["---", "## Model Complexity Analysis", "", "### Visual Representations", ""]

        charts = [
            ("relationship_graph.png", "Relationship Diagram"),
            ("schema_type_donut.png", "Table Type Distribution"),
            ("complexity_heatmap.png", "Model Complexity Heatmap"),
            ("datatype_distribution.png", "Data Type Distribution"),
            ("measure_dependency.png", "Measure Dependencies"),
        ]

        for chart_file, chart_title in charts:
            chart_path = self.paths.graphs_dir / chart_file
            if chart_path.exists():
                lines.append(f"#### {chart_title}")
                lines.append(f"![{chart_title}](../graphs/{chart_file})")
                lines.append("")

        return lines

    def _section_tables_summary(self) -> list[str]:
        """Tables summary section."""
        lines = ["---", "## Tables Summary", ""]

        if self.tables_data:
            lines.append("| Table | Columns | Measures | Data Types |")
            lines.append("|-------|---------|----------|------------|")

            for table in sorted(self.tables_data, key=lambda x: x.get("name", "")):
                data_types = set()
                for col in table.get("columns", []) or []:
                    if not col.get("is_calculated", False):
                        data_types.add(col.get("dataType", "Unknown"))
                data_types_str = ", ".join(sorted(data_types)) if data_types else "N/A"

                lines.append(
                    f"| {table.get('name','Unknown')} | {table.get('column_count',0)} | "
                    f"{table.get('measure_count',0)} | {data_types_str} |"
                )
            lines.append("")

        return lines

    def _section_detailed_classifications(self) -> list[str]:
        """Detailed table classifications section."""
        lines = ["---", "## Detailed Table Classifications", ""]

        classifications = self.analysis_data.get("table_classifications", []) if isinstance(self.analysis_data, dict) else []
        if classifications:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cls in classifications:
                grouped.setdefault(cls.get("classification", "UNKNOWN"), []).append(cls)

            for table_type in ["FACT", "DIMENSION", "BRIDGE", "CALCULATION", "PARAMETER"]:
                if table_type in grouped:
                    tables_of_type = grouped[table_type]
                    lines.append(f"### {table_type} Tables ({len(tables_of_type)})")
                    lines.append("")
                    for table in sorted(tables_of_type, key=lambda x: x.get("table_name", "")):
                        lines.append(f"#### {table.get('table_name','Unknown')}")
                        lines.append(f"- **Classification:** {table.get('classification','UNKNOWN')}")
                        lines.append(f"- **Confidence:** {table.get('confidence','N/A')}")
                        lines.append(f"- **Reasoning:** {(table.get('reasoning','') or '').replace('|','\\|')}")
                        metadata = table.get("metadata", {}) or {}
                        lines.append(f"- **Columns:** {metadata.get('columns', 0)}")
                        lines.append(f"- **Numeric Columns:** {metadata.get('numeric_columns', 0)}")
                        lines.append(f"- **String Columns:** {metadata.get('string_columns', 0)}")
                        lines.append(f"- **Date Columns:** {metadata.get('date_columns', 0)}")
                        lines.append(f"- **Measures:** {metadata.get('measures', 0)}")
                        lines.append("")
        else:
            lines.append("No classifications found in classifications.json.")
            lines.append("")

        return lines

    def _section_relationships_analysis(self) -> list[str]:
        """Relationships analysis section."""
        lines = ["---", "## Relationships Analysis", ""]

        if self.relationships_data:
            lines.append(f"**Total Relationships:** {len(self.relationships_data)}")
            lines.append("")
            lines.append("| From Table | From Column | To Table | To Column | Cardinality |")
            lines.append("|------------|------------|----------|-----------|-------------|")
            for rel in self.relationships_data:
                lines.append(
                    f"| {rel.get('from_table','')} | {rel.get('from_column','')} | "
                    f"{rel.get('to_table','')} | {rel.get('to_column','')} | {rel.get('cardinality','')} |"
                )
            lines.append("")
        else:
            lines.append("No relationships defined in the model.")
            lines.append("")

        return lines

    def _section_measures_overview(self) -> list[str]:
        """Measures overview section."""
        lines = ["---", "## Measures Overview", ""]
        
        measures_summary = self._get_measures_summary()
        
        if self.measures_data or measures_summary.get("total_measures", 0) > 0:
            lines.extend(self._subsection_measures_summary(measures_summary))
            lines.extend(self._subsection_used_measures())
            lines.extend(self._subsection_unused_measures())

        return lines

    def _subsection_measures_summary(self, measures_summary: dict[str, Any]) -> list[str]:
        """Measures summary subsection."""
        total = measures_summary.get("total_measures", len(self.measures_data))
        used = measures_summary.get("used_measures", 0)
        unused = measures_summary.get("unused_measures", 0)
        unused_pct = measures_summary.get("unused_percentage", 0.0)
        
        lines = ["### Measures Summary", "", f"**Total Measures:** {total}", ""]
        
        if used > 0 or unused > 0:
            lines.extend([
                "| Status | Count | Percentage |",
                "|--------|-------|-----------|",
                f"| Used | {used} | {100 - unused_pct:.1f}% |",
                f"| Unused (Cleanup Candidates) | {unused} | {unused_pct:.1f}% |",
                ""
            ])
        
        return lines

    def _subsection_used_measures(self) -> list[str]:
        """Used measures subsection."""
        lines = []

        if self.measures_data:
            measures_summary_data = self._get_summary(self.measures_raw)
            avg_complexity = measures_summary_data.get("average_complexity_score")
            
            lines.append("### Used Measures")
            lines.append("")
            
            if avg_complexity is not None:
                lines.append(f"**Average Complexity Score:** {avg_complexity}/10")
                lines.append("")
            
            lines.append("| Table | Measure Name | Complexity | Dependencies | DAX Preview |")
            lines.append("|-------|--------------|-----------|---------------|-------------|")

            for measure in sorted(self.measures_data, key=lambda x: (x.get("table", ""), x.get("name", ""))):
                table_name = self._escape_md_cell(measure.get("table", "Unknown"))
                measure_name = self._escape_md_cell(measure.get("name", "Unknown"))

                complexity = measure.get("complexity_score", measure.get("complexity", 0))
                complexity_level = measure.get("complexity_level", "")
                complexity_display = f"{complexity_level} {complexity}/10" if complexity_level else f"{complexity}/10"

                # Dependencies
                deps = measure.get("dependencies", [])
                if isinstance(deps, list) and deps:
                    deps_str = ", ".join(deps[:2])
                    if len(deps) > 2:
                        deps_str += f", +{len(deps) - 2}"
                else:
                    deps_str = "None"

                dax = (
                    measure.get("expression_preview")
                    or measure.get("expression", "")
                    or ""
                )
                dax = self._escape_md_cell(dax)
                dax_snippet = (dax[:60] + "...") if len(dax) > 60 else dax

                lines.append(f"| {table_name} | {measure_name} | {complexity_display} | {deps_str} | {dax_snippet} |")

            lines.append("")
        
        return lines

    def _subsection_unused_measures(self) -> list[str]:
        """Unused measures subsection."""
        lines = []

        top_unused = self._get_unused_measures_by_complexity(limit=10)
        if top_unused:
            lines.extend([
                "### Unused Measures - Cleanup Candidates",
                "",
                "These measures are not referenced by any visual or other measures and are candidates for cleanup:",
                "",
                "| Table | Measure Name | Complexity | Reason |",
                "|-------|--------------|-----------|--------|",
            ])
            
            for measure in top_unused:
                name = self._escape_md_cell(measure.get("name", "Unknown"))
                table = self._escape_md_cell(measure.get("table", "Unknown"))
                complexity = measure.get("complexity", 0)
                reason = self._escape_md_cell(measure.get("reason", "Not in use"))
                lines.append(f"| {table} | {name} | {complexity:.2f}/10 | {reason} |")
            
            lines.extend([
                "",
                "**Recommendation:** Review and remove unused measures to reduce model complexity and improve maintainability.",
                ""
            ])
        
        return lines

    def _section_columns_details(self) -> list[str]:
        """Columns details section."""
        lines = ["---", "## Columns Details", ""]

        if self.tables_data:
            for table in sorted(self.tables_data, key=lambda x: x.get("name", "")):
                cols = table.get("columns", []) or []
                if not cols:
                    continue

                lines.append(f"### {table.get('name','Unknown')}")
                lines.append("")
                lines.append("| Column Name | Data Type | Calculated | Key |")
                lines.append("|------------|-----------|-----------|-----|")

                for col in cols:
                    col_name = col.get("name", "Unknown")
                    data_type = col.get("dataType", "Unknown")
                    is_calc = "✓" if col.get("is_calculated", False) else ""
                    is_key = "✓" if col.get("is_key", False) else ""
                    lines.append(f"| {col_name} | {data_type} | {is_calc} | {is_key} |")
                lines.append("")

        return lines

    def _section_report_pages(self) -> list[str]:
        """Report pages section."""
        lines = ["---", "## Report Pages", ""]

        if self.pages_data:
            pages_summary = self._get_summary(self.pages_raw)
            total_pages = pages_summary.get("total_pages", len(self.pages_data))
            total_visuals = pages_summary.get("total_visuals", sum(p.get("visuals_count", 0) for p in self.pages_data))

            lines.append(f"**Total Pages:** {total_pages}")
            lines.append(f"**Total Visuals:** {total_visuals}")
            lines.append("")

            # Check for visual categories
            total_charts = 0
            total_tables = 0
            total_slicers = 0
            has_category_data = False

            for page in self.pages_data:
                if page.get("chart_count") is not None:
                    has_category_data = True
                    total_charts += page.get("chart_count", 0)
                    total_tables += page.get("table_count", 0)
                    total_slicers += page.get("slicer_count", 0)

            # Show category summary if available
            if has_category_data:
                lines.extend([
                    "### Visual Categories Summary",
                    "",
                    "| Category | Count |",
                    "|----------|-------|",
                    f"| Charts | {total_charts} |",
                    f"| Tables | {total_tables} |",
                    f"| Slicers | {total_slicers} |",
                    "",
                    "### Report Pages Detail",
                    "",
                    "| Page Name | Total Visuals | Charts | Tables | Slicers | Complexity |",
                    "|-----------|---------------|--------|--------|---------|------------|",
                ])
                
                for page in self.pages_data:
                    page_name = self._escape_md_cell(page.get('display_name', 'Unknown'))
                    total_vis = page.get('visuals_count', 0)
                    charts = page.get('chart_count', 0) if page.get('chart_count') is not None else '—'
                    tables = page.get('table_count', 0) if page.get('table_count') is not None else '—'
                    slicers = page.get('slicer_count', 0) if page.get('slicer_count') is not None else '—'
                    complexity = self._escape_md_cell(page.get('page_complexity_level', 'N/A'))
                    
                    lines.append(f"| {page_name} | {total_vis} | {charts} | {tables} | {slicers} | {complexity} |")
            else:
                # Fallback: show only total visuals per page
                lines.extend([
                    "| Page Name | Visualizations |",
                    "|-----------|-----------------|",
                ])
                for page in self.pages_data:
                    page_name = self._escape_md_cell(page.get('display_name', 'Unknown'))
                    total_vis = page.get('visuals_count', 0)
                    lines.append(f"| {page_name} | {total_vis} |")
            
            lines.append("")
        else:
            lines.append("No report pages found.")
            lines.append("")

        return lines

    def _section_unused_analysis(self) -> list[str]:
        """Backward-compatible wrapper for the table column usage section."""
        return self._section_column_usage_analysis()

    def _section_column_usage_analysis(self) -> list[str]:
        """Table column usage analysis section."""
        lines = ["---", "## Table Column Usage", ""]

        summary = self._get_table_usage_summary()
        rows = self._get_table_usage_rows()

        lines.extend([
            "### Summary",
            "",
            f"- **Total Columns:** {summary.get('total_columns', 0)}",
            f"- **Columns Used in Measures:** {summary.get('columns_used_in_measures', 0)}",
            f"- **Columns Used in Pages:** {summary.get('columns_used_in_pages', 0)}",
            f"- **Total Unique Columns Used:** {summary.get('total_unique_columns_used', 0)}",
            f"- **Unused Columns:** {summary.get('total_unused', 0)}",
            f"- **Average Table Usage:** {summary.get('average_table_usage_percentage', 0)}%",
            f"- **Tables with Full Usage:** {summary.get('tables_with_full_usage', 0)}",
            ""
        ])

        if rows:
            lines.extend([
                "### Column Usage by Table",
                "",
                "| Table Name | Used | Total | Usage % | Calc Cols | Measures | Details |",
                "|------------|------|-------|---------|-----------|----------|---------|",
            ])

            for row in sorted(rows, key=lambda x: (x.get("usage_percentage", 0), -x.get("unused_columns", 0))):
                details = []
                if row.get("has_measures"):
                    details.append("measures")
                if row.get("has_calculated_columns"):
                    details.append("calculated columns")
                if row.get("table_kind"):
                    details.append(str(row.get("table_kind")))
                detail_text = ", ".join(details) if details else ""

                lines.append(
                    f"| {row.get('table_name','Unknown')} | {row.get('used_columns',0)} | {row.get('total_columns',0)} | {row.get('usage_percentage',0)}% | {row.get('calculated_column_count',0)} | {row.get('measure_count',0)} | {detail_text} |"
                )
            lines.append("")

        return lines

    def _section_data_quality(self) -> list[str]:
        """Data quality section."""
        lines = ["---", "## Data Quality", ""]

        summary = self.analysis_data.get("summary", {}) if isinstance(self.analysis_data, dict) else {}
        rel_analysis = self.analysis_data.get("relationship_analysis", {}) if isinstance(self.analysis_data, dict) else {}

        lines.append(f"- **Schema Type:** {rel_analysis.get('schema_type', 'N/A')}")
        
        isolated_tables = rel_analysis.get("isolated_tables", [])
        if isinstance(isolated_tables, list):
            orphaned_count = len(isolated_tables)
        else:
            orphaned_count = rel_analysis.get("orphaned_tables", 0)

        lines.append(f"- **Orphaned / Isolated Tables:** {orphaned_count}")
        
        analysis_issues = rel_analysis.get("issues", [])
        analysis_recommendations = rel_analysis.get("recommendations", [])

        if analysis_issues:
            lines.extend(["", "### Detected Issues", ""])
            for issue in analysis_issues:
                if isinstance(issue, dict):
                    code = issue.get("code", "ISSUE")
                    message = issue.get("message", issue.get("description", ""))
                    lines.append(f"- **{code}:** {message}")
                else:
                    lines.append(f"- {issue}")
            lines.append("")

        if analysis_recommendations:
            lines.extend(["### Recommendations", ""])
            for recommendation in list(analysis_recommendations):
                lines.append(f"- {recommendation}")
            lines.append("")

        usage_summary = self._get_table_usage_summary()
        lines.extend([
            "### Table Usage Snapshot",
            "",
            f"- **Total Columns:** {usage_summary.get('total_columns', 0)}",
            f"- **Used Columns:** {usage_summary.get('total_unique_columns_used', 0)}",
            f"- **Unused Columns:** {usage_summary.get('total_unused', 0)}",
            f"- **Average Table Usage:** {usage_summary.get('average_table_usage_percentage', 0)}%",
            ""
        ])

        return lines
