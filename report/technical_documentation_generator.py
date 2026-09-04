#!/usr/bin/env python3
"""
Technical Documentation Generator.

Produces: TECHNICAL_DOCUMENTATION.md (executive summary)
- General description and dataset endpoint
- Table mapping with classifications
- Tables composition with columns/measures
- Relationships summary
- Measures utilization
- Pages overview
- Unused tables and columns analysis
"""

from pathlib import Path
from typing import Any

from .base_documentation_generator import BaseDocumentationGenerator


class TechnicalDocumentationGenerator(BaseDocumentationGenerator):
    """Generates executive-level TECHNICAL_DOCUMENTATION.md."""

    def __init__(self, output_dir: Path, pbip_name: str):
        super().__init__(output_dir, pbip_name)

    def generate(self) -> str:
        """
        Generate technical documentation.
        
        Returns:
            Markdown content as string
        """
        self.load_all_data()
        return self._build_document()

    def _build_document(self) -> str:
        """Build the complete technical documentation."""
        doc: list[str] = []

        doc.extend(self._section_header())
        doc.extend(self._section_description())
        doc.extend(self._section_dataset_endpoint())
        doc.extend(self._section_table_mapping())
        doc.extend(self._section_tables_composition())
        doc.extend(self._section_relationships())
        doc.extend(self._section_measures())
        doc.extend(self._section_pages())
        doc.extend(self._section_pages_composition())
        doc.extend(self._section_unused_measures())
        doc.extend(self._section_table_usage())

        return "\n".join(doc)

    def _section_header(self) -> list[str]:
        """Header section."""
        from datetime import datetime
        
        lines = [
            "# Power BI Semantic Model Documentation",
            "",
            f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}",
            ""
        ]
        return lines

    def _section_description(self) -> list[str]:
        """General description section."""
        lines = ["## General Description", ""]
        lines.append(f"**Semantic Model:** {self.pbip_name}")

        summary = self.analysis_data.get("summary", {}) if isinstance(self.analysis_data, dict) else {}
        total_tables = summary.get("total_tables", len(self.tables_data))
        total_measures = summary.get("total_measures", len(self.measures_data))
        lines.append(f"**Tables:** {total_tables} | **Measures:** {total_measures}")
        lines.append("")

        return lines

    def _section_dataset_endpoint(self) -> list[str]:
        """Dataset endpoint section."""
        lines = ["## Dataset: Endpoint", ""]

        if self.datasources_data:
            for ds in self.datasources_data:
                ds_type = ds.get("type", "Unknown")
                connector = ds.get("connector")
                ds_def = ds.get("definition", "N/A")
                confidence = ds.get("confidence")
                attributes = ds.get("attributes", {}) or {}

                details = []

                if connector:
                    details.append(f"Connector: `{connector}`")

                if attributes.get("server"):
                    details.append(f"Server: `{attributes.get('server')}`")

                if attributes.get("database"):
                    details.append(f"Database: `{attributes.get('database')}`")

                if attributes.get("domain"):
                    details.append(f"Domain: `{attributes.get('domain')}`")

                if attributes.get("path"):
                    details.append(f"Path: `{attributes.get('path')}`")

                if confidence is not None:
                    details.append(f"Confidence: {confidence}")

                detail_text = f" ({'; '.join(details)})" if details else ""

                lines.append(
                    f"- **{self._escape_md_cell(ds_type)}**: "
                    f"{self._escape_md_cell(ds_def)}{detail_text}"
                )
        else:
            lines.append("- No explicit data sources defined")

        lines.append("")
        return lines

    def _section_table_mapping(self) -> list[str]:
        """Table mapping section."""
        lines = ["## Table Mapping (Semantic Model)", ""]

        classifications = self.analysis_data.get("table_classifications", []) if isinstance(self.analysis_data, dict) else []
        if classifications:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cls in classifications:
                ctype = cls.get("classification", "UNKNOWN")
                grouped.setdefault(ctype, []).append(cls)

            for table_type in ["FACT", "DIMENSION", "BRIDGE", "CALCULATION", "PARAMETER"]:
                if table_type in grouped:
                    table_list = grouped[table_type]
                    lines.append(f"**{table_type} Tables** ({len(table_list)})")
                    for t in sorted(table_list, key=lambda x: x.get("table_name", "")):
                        lines.append(f"- {t.get('table_name', 'Unknown')}")
                    lines.append("")
        else:
            lines.append("- No table classifications found in classifications.json")
            lines.append("")

        return lines

    def _section_tables_composition(self) -> list[str]:
        """Tables and composition section."""
        lines = ["## Tables and Composition", ""]
        lines.append("| Table Name | Type | Columns | Calc Cols | Measures | Description |")
        lines.append("|------------|------|---------|-----------|----------|-------------|")

        classifications = self.analysis_data.get("table_classifications", []) if isinstance(self.analysis_data, dict) else []
        if classifications:
            for cls in sorted(classifications, key=lambda x: x.get("table_name", "")):
                table_name = cls.get("table_name", "Unknown")
                table_type = cls.get("classification", "UNKNOWN")
                metadata = cls.get("metadata", {}) or {}
                columns = metadata.get("columns", 0)
                calc_columns = metadata.get("calculated_columns", 0)
                measures = metadata.get("measures", 0)
                reasoning = (cls.get("reasoning", "") or "").replace("\n", " ").replace("|", "\\|")
                lines.append(f"| {table_name} | {table_type} | {columns} | {calc_columns} | {measures} | {reasoning} |")
        else:
            # Fallback using tables.json only
            for t in sorted(self.tables_data, key=lambda x: x.get("name", "")):
                lines.append(f"| {t.get('name','Unknown')} | N/A | {t.get('column_count',0)} | {t.get('calculated_column_count',0)} | {t.get('measure_count',0)} | |")

        lines.append("")
        return lines

    def _section_relationships(self) -> list[str]:
        """Relationships section."""
        lines = []

        if self.relationships_data:
            lines.append("## Relationships")
            lines.append("")
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

        return lines

    def _section_measures(self) -> list[str]:
        """Measures section."""
        lines = []

        measures_summary = self._get_measures_summary()
        if measures_summary.get("total_measures", 0) > 0:
            lines.append("## Measures")
            lines.append("")
            lines.append(f"**Total Measures:** {measures_summary.get('total_measures', 0)}")
            lines.append("")
            
            used = measures_summary.get("used_measures", 0)
            unused = measures_summary.get("unused_measures", 0)
            unused_pct = measures_summary.get("unused_percentage", 0.0)
            
            if used > 0 or unused > 0:
                lines.append("### Measures Utilization")
                lines.append("")
                lines.append("| Category | Count | Percentage |")
                lines.append("|----------|-------|-----------|")
                lines.append(f"| Used Measures | {used} | {100 - unused_pct:.1f}% |")
                lines.append(f"| Unused Measures | {unused} | {unused_pct:.1f}% |")
                lines.append("")
                
                # Show top unused measures by complexity
                top_unused = self._get_unused_measures_by_complexity(limit=5)
                if top_unused:
                    lines.append("### Top Unused Measures (by Complexity)")
                    lines.append("")
                    lines.append("| Measure Name | Table | Complexity | Reason |")
                    lines.append("|--------------|-------|-----------|--------|")
                    for measure in top_unused:
                        name = self._escape_md_cell(measure.get("name", "Unknown"))
                        table = self._escape_md_cell(measure.get("table", "Unknown"))
                        complexity = measure.get("complexity", 0)
                        reason = self._escape_md_cell(measure.get("reason", "N/A"))
                        lines.append(f"| {name} | {table} | {complexity:.2f} | {reason} |")
                    lines.append("")
            lines.append("")

        return lines

    def _section_pages(self) -> list[str]:
        """Pages section."""
        lines = []

        if self.pages_data:
            lines.append("## Pages")
            lines.append("")
            lines.append(f"**Total Pages:** {len(self.pages_data)}")
            lines.append("")
            lines.append("| Page Name | Visualizations |")
            lines.append("|-----------|-----------------|")
            for page in self.pages_data:
                lines.append(f"| {page.get('display_name','Unknown')} | {page.get('visuals_count',0)} |")
            lines.append("")

        return lines

    def _section_pages_composition(self) -> list[str]:
        """Visual composition by page section."""
        lines = []

        if not self.pages_data:
            return lines

        lines.append("## Report Pages Composition")
        lines.append("")

        totals = {
            "charts": 0,
            "tables": 0,
            "cards": 0,
            "slicers": 0,
            "text": 0,
            "buttons": 0,
            "other": 0,
        }

        page_rows = []
        for page in self.pages_data:
            visuals = page.get("visuals", []) if isinstance(page, dict) else []
            breakdown = self._count_visuals_by_category(visuals)
            for key in totals:
                totals[key] += breakdown[key]

            page_rows.append((
                page.get("display_name", page.get("name", "Unknown")),
                len(visuals),
                breakdown,
            ))

        lines.extend([
            "### Visual Categories Summary",
            "",
            "| Category | Count |",
            "|----------|-------|",
            f"| Charts | {totals['charts']} |",
            f"| Tables | {totals['tables']} |",
            f"| Cards | {totals['cards']} |",
            f"| Slicers | {totals['slicers']} |",
            f"| Text | {totals['text']} |",
            f"| Buttons | {totals['buttons']} |",
            f"| Other | {totals['other']} |",
            "",
            "### Page-Level Composition",
            "",
            "| Page | Total | Charts | Tables | Cards | Slicers | Text | Buttons | Other |",
            "|------|-------|--------|--------|-------|---------|------|---------|-------|",
        ])

        for page_name, total_visuals, breakdown in page_rows:
            lines.append(
                f"| {self._escape_md_cell(page_name)} | {total_visuals} | {breakdown['charts']} | {breakdown['tables']} | {breakdown['cards']} | {breakdown['slicers']} | {breakdown['text']} | {breakdown['buttons']} | {breakdown['other']} |"
            )

        lines.append("")
        return lines

    def _count_visuals_by_category(self, visuals: list[dict[str, Any]]) -> dict[str, int]:
        """Count visual categories on a page."""
        counts = {
            "charts": 0,
            "tables": 0,
            "cards": 0,
            "slicers": 0,
            "text": 0,
            "buttons": 0,
            "other": 0,
        }

        for visual in visuals:
            category = str(visual.get("category", "OTHER")).upper()
            if category == "CHART":
                counts["charts"] += 1
            elif category == "TABLE":
                counts["tables"] += 1
            elif category == "CARD":
                counts["cards"] += 1
            elif category == "SLICER":
                counts["slicers"] += 1
            elif category == "TEXT":
                counts["text"] += 1
            elif category == "BUTTON":
                counts["buttons"] += 1
            else:
                counts["other"] += 1

        return counts

    def _section_unused_measures(self) -> list[str]:
        """Potentially unused measures section with analysis scope."""
        lines = []

        summary = self._get_measures_summary()
        top_unused = self._get_unused_measures_by_complexity(limit=10)
        if not summary.get("unused_measures", 0) and not top_unused:
            return lines

        analysis = {}
        if isinstance(self.unused_measures_raw, dict):
            analysis = self.unused_measures_raw.get("analysis", {}) or {}
        coverage = analysis.get("analysis_coverage", {}) if isinstance(analysis, dict) else {}
        limitations = analysis.get("analysis_limitations", []) if isinstance(analysis, dict) else []

        lines.extend([
            "## U001 - Potentially Unused Measures",
            "",
            "The parser only marks measures as potentially unused when they have no detected references in the analyzed channels.",
            "",
            f"**Analyzed:** measure-to-measure dependencies = {'yes' if coverage.get('measure_dependencies') else 'no'}, visual fields = {'yes' if coverage.get('visual_fields') else 'no'}",
            f"**Not analyzed:** {', '.join(limitations) if limitations else 'No additional limitations recorded'}",
            "",
            f"**Potential candidates:** {summary.get('unused_measures', 0)} / {summary.get('total_measures', len(self.measures_data))}",
            f"**Potential unused percentage:** {summary.get('unused_percentage', 0.0):.1f}%",
            "",
        ])

        risk = {}
        if isinstance(self.unused_measures_raw, dict):
            analysis = self.unused_measures_raw.get("analysis", {})
            if isinstance(analysis, dict):
                risk = analysis.get("cleanup_by_risk", {}) or {}

        if risk:
            lines.extend([
                "### Cleanup Risk Distribution",
                "",
                "| Risk | Count |",
                "|------|-------|",
                f"| Safe Delete | {risk.get('safe_delete', 0)} |",
                f"| Review Suggested | {risk.get('review_suggested', 0)} |",
                f"| Investigate | {risk.get('investigate', 0)} |",
                f"| Do Not Delete | {risk.get('do_not_delete', 0)} |",
                "",
            ])

        if top_unused:
            lines.extend([
                "### Top Cleanup Candidates",
                "",
                "| Table | Measure | Complexity | Risk | Reason |",
                "|-------|---------|-----------|------|--------|",
            ])
            for measure in top_unused:
                lines.append(
                    f"| {self._escape_md_cell(measure.get('table', 'Unknown'))} | {self._escape_md_cell(measure.get('name', 'Unknown'))} | {measure.get('complexity', 0):.2f} | {self._escape_md_cell(measure.get('cleanup_risk', 'UNKNOWN'))} | {self._escape_md_cell(measure.get('reason', 'N/A'))} |"
                )
            lines.extend([
                "",
                "These candidates are sourced from unused_measures.json and should be verified manually when they appear in tooltips, RLS, conditional formatting, or dynamic DAX.",
                ""
            ])

        return lines

    def _section_table_usage(self) -> list[str]:
        """Table column usage section."""
        lines = []

        column_usage_summary = self._get_table_usage_summary()
        table_usage_rows = self._get_table_usage_rows()

        if table_usage_rows or column_usage_summary:
            lines.append("## Table Column Usage")
            lines.append("")

            lines.extend([
                "### Summary",
                "",
                f"- **Total Columns:** {column_usage_summary.get('total_columns', 0)}",
                f"- **Columns Used in Measures:** {column_usage_summary.get('columns_used_in_measures', 0)}",
                f"- **Columns Used in Pages:** {column_usage_summary.get('columns_used_in_pages', 0)}",
                f"- **Total Unique Columns Used:** {column_usage_summary.get('total_unique_columns_used', 0)}",
                f"- **Unused Columns:** {column_usage_summary.get('total_unused', 0)}",
                f"- **Average Table Usage:** {column_usage_summary.get('average_table_usage_percentage', 0)}%",
                f"- **Tables with Full Usage:** {column_usage_summary.get('tables_with_full_usage', 0)}",
                "",
            ])

            if table_usage_rows:
                lines.extend([
                    "### Table Column Usage",
                    "",
                    "| Table | Used | Total | Usage % | Calc Cols | Measures |",
                    "|-------|------|-------|---------|-----------|----------|",
                ])

                for row in sorted(table_usage_rows, key=lambda x: (x.get("usage_percentage", 0), -x.get("unused_columns", 0))):
                    lines.append(
                        f"| {self._escape_md_cell(row.get('table_name', 'Unknown'))} | {row.get('used_columns', 0)} | {row.get('total_columns', 0)} | {row.get('usage_percentage', 0)}% | {row.get('calculated_column_count', 0)} | {row.get('measure_count', 0)} |"
                    )
                lines.append("")

        return lines
