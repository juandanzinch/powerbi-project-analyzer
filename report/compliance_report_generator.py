#!/usr/bin/env python3
"""
Compliance Report Generator for Power BI Models.

Purpose:
- Converts ScoringResult JSON into audit-ready Markdown
- Separates issues by severity (CRITICAL, WARNING, INFO)
- Provides actionable recommendations for stakeholders and developers
- Follows strict formatting for readability

Output:
- compliance_report.md in reports/{project-name}/reports/
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime


class ComplianceReportGenerator:
    """Generates compliance reports from scoring results."""
    
    # Visual status indicators per grade range
    STATUS_ICONS = {
        "A": "✅",  # Green - Excellent
        "B": "✅",  # Green - Good
        "C": "⚠️",  # Yellow - Needs work
        "D": "🔴",  # Red - Urgent
        "F": "⛔",  # Critical
    }
    
    def __init__(self, data_dir: str, output_dir: str, pbip_name: str, rules_path: str = None):
        """
        Initialize report generator.
        
        Args:
            data_dir: Path to data/ directory with scoring_result.json
            output_dir: Path to reports/{project-name}/ directory
            pbip_name: Name of the Power BI project
            rules_path: Optional path to rules.yaml (for dimension weights)
        """
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.pbip_name = pbip_name
        
        # Load scoring result
        self.scoring_result = self._load_scoring_result()
        self.unused_measures_data = self._load_unused_measures()
        
        # Load rules for dimension names and weights
        if rules_path is None:
            rules_path = Path.cwd() / "scoring" / "rules.yaml"
        self.rules = self._load_rules(str(rules_path))
        
        # Map dimension internal names to display names
        self.dimension_display_names = {
            "model_health": "Model Health",
            "dax_quality": "DAX Quality",
            "report_design": "Report Design",
            "governance": "Governance",
            # Also support uppercase variants for backward compatibility
            "MODEL": "Model Health",
            "DAX": "DAX Quality",
            "REPORT": "Report Design",
            "GOVERNANCE": "Governance"
        }

        self.issue_recommendations = {
            "D001": "Move measures to a dedicated _Measures table and keep business logic centralized.",
            "G001": "Deduplicate the repeated measures and keep only the canonical definition.",
            "R001": "Reduce the visual density of the page and split dense content into dedicated drill-through or summary pages.",
        }
    
    def _load_scoring_result(self) -> Dict[str, Any]:
        """Load scoring_result.json."""
        result_path = self.data_dir / "scoring_result.json"
        if not result_path.exists():
            raise FileNotFoundError(f"Scoring result not found: {result_path}")
        
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_unused_measures(self) -> Dict[str, Any]:
        """Load unused_measures.json if available."""
        path = self.data_dir / "unused_measures.json"
        if not path.exists():
            return {}

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _load_rules(self, rules_path: str) -> Dict[str, Any]:
        """Load rules.yaml for dimension weights."""
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            # Return defaults if rules not available
            return {
                "scoring": {
                    "weights": {
                        "model_health": 0.35,
                        "dax_quality": 0.25,
                        "report_design": 0.25,
                        "governance": 0.15
                    }
                }
            }
    
    def generate(self) -> str:
        """Generate compliance report markdown."""
        doc_lines = []
        
        # Header
        doc_lines.extend(self._generate_header())
        
        # Global score section
        doc_lines.extend(self._generate_global_score_section())
        
        # Dimension scores table
        doc_lines.extend(self._generate_dimensions_table())
        
        # Critical issues
        doc_lines.extend(self._generate_issues_section("CRITICAL", "Critical Issues (blocks deployment)"))
        
        # Warnings
        doc_lines.extend(self._generate_issues_section("WARNING", "Warnings (must be resolved before next sprint)"))
        
        # Info
        doc_lines.extend(self._generate_issues_section("INFO", "Information (recommended improvements)"))
        
        # Breakdown of penalties and bonuses
        doc_lines.extend(self._generate_breakdown_section())

        # Unused measures cleanup candidates
        doc_lines.extend(self._generate_unused_measures_section())
        
        # Recommendations
        doc_lines.extend(self._generate_recommendations_section())
        
        # Footer
        doc_lines.extend(self._generate_footer())
        
        return "\n".join(doc_lines)
    
    def _generate_header(self) -> List[str]:
        """Generate report header."""
        # Extract metadata
        metadata = self.scoring_result.get("metadata", {})
        schema_type = metadata.get("schema_type", "N/A")
        workspace = metadata.get("workspace", "N/A")
        
        lines = [
            "# Power BI Compliance Report",
            "",
            f"**Project:** {self.pbip_name}",
            f"**Workspace:** {workspace}",
            f"**Schema:** {schema_type}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "**Framework version:** 1.0.0",
            "",
            "---",
            ""
        ]
        return lines
    
    def _generate_global_score_section(self) -> List[str]:
        """Generate global score section."""
        score = self.scoring_result.get("global_score", 0)
        grade = self.scoring_result.get("grade", "F")
        icon = self.STATUS_ICONS.get(grade, "❓")
        
        lines = [
            f"## Global Score: {score}/100 — Grade {grade} {icon}",
            ""
        ]
        return lines
    
    def _generate_dimensions_table(self) -> List[str]:
        """Generate dimensions table with scores and status."""
        lines = [
            "| Dimension        | Score  | Weight | Weighted | Status |",
            "|------------------|--------|--------|----------|--------|" ,
        ]
        
        dimensions = self.scoring_result.get("dimensions", {})
        
        # Order of dimensions for consistency (lowercase keys)
        dim_order = ["model_health", "dax_quality", "report_design", "governance"]
        
        for dim_key in dim_order:
            if dim_key not in dimensions:
                continue
            
            dim_data = dimensions[dim_key]
            dim_name = self.dimension_display_names.get(dim_key, dim_key)
            
            score = dim_data.get("score", 0)
            weight_pct = f"{int(dim_data.get('weight', 0) * 100)}%"
            weighted = dim_data.get("weighted", 0)
            
            # Determine status icon based on score
            status_icon = self._get_status_for_score(score)
            
            line = f"| {dim_name:<16} | {score:>3}/100 | {weight_pct:>5} | {weighted:>7.2f} | {status_icon} |"
            lines.append(line)
        
        lines.append("")
        return lines
    
    def _get_status_for_score(self, score: int) -> str:
        """Get status icon for a given score."""
        if score >= 90:
            return "✅"
        elif score >= 75:
            return "✅"
        elif score >= 60:
            return "⚠️"
        elif score >= 40:
            return "🔴"
        else:
            return "⛔"
    
    def _generate_issues_section(self, severity: str, title: str) -> List[str]:
        """Generate section for issues of specific severity."""
        lines = [
            "---",
            "",
            f"## {title}",
            ""
        ]
        
        # Filter issues by severity
        all_issues = self.scoring_result.get("issues", [])
        issues = [i for i in all_issues if i.get("severity") == severity]
        
        if not issues:
            lines.append("*(None)*")
            lines.append("")
            return lines
        
        # Build reverse lookup for shared affected items across issue codes
        all_affected_map = self._build_affected_issue_map(issues)
        
        for issue in issues:
            code = issue.get("code", "???")
            message = issue.get("message", "")
            dimension = issue.get("dimension", "")
            affected = issue.get("affected", [])
            recommendation = self._get_hardcoded_recommendation(code, issue.get("recommendation", ""))

            affected = self._dedupe_sequence(affected)
            
            # Make R001 messages contextual based on visual types
            if code == "R001" and "Meaningful Visuals" in message:
                message = self._create_contextual_r001_message(message)

            related_codes = self._get_cross_references(code, affected, all_affected_map)
            
            # Format: ### [CODE] Issue message
            lines.append(f"### [{code}] {message}")
            lines.append("")
            
            # Metadata
            lines.append(f"**Dimension:** {self.dimension_display_names.get(dimension, dimension)}")
            lines.append("")
            
            if affected:
                lines.append(f"**Affects:** {', '.join(affected)}")
                lines.append("")

            if related_codes:
                lines.append(f"**Related issues:** {', '.join(related_codes)}")
                lines.append("")
            
            if recommendation:
                lines.append(f"**What to do:** {recommendation}")
                lines.append("")
        
        return lines
    
    def _generate_breakdown_section(self) -> List[str]:
        """Generate detailed breakdown of penalties and bonuses."""
        lines = [
            "---",
            "",
            "## Breakdown of Penalties and Bonuses",
            ""
        ]
        
        dimensions = self.scoring_result.get("dimensions", {})
        
        # Order of dimensions (lowercase keys)
        dim_order = ["model_health", "dax_quality", "report_design", "governance"]
        
        # Collect footnotes for special rules
        footnotes = []
        footnote_num = 1
        
        for dim_key in dim_order:
            if dim_key not in dimensions:
                continue
            
            dim_data = dimensions[dim_key]
            dim_name = self.dimension_display_names.get(dim_key, dim_key)
            dim_score = dim_data.get("score", 0)
            
            # Add dimension header
            lines.append(f"### {dim_name} ({dim_score}/100)")
            lines.append("")
            
            # Create breakdown table
            breakdown = dim_data.get("breakdown", {})
            
            if breakdown:
                lines.append("| Rule | Impact | Detail |")
                lines.append("|------|--------|--------|")
                
                for rule_name, impact_value in breakdown.items():
                    # Format rule name nicely
                    rule_display = rule_name.replace("_", " ").title()
                    
                    # Skip Schema Ceiling - will go to footnote
                    if "schema" in rule_name.lower() and "ceiling" in rule_name.lower():
                        footnotes.append(f"[{footnote_num}] {rule_display}: Measures architectural capacity based on star schema. Positive adjustments for clean schemas.")
                        impact_str = f"+{impact_value}[^{footnote_num}]" if impact_value > 0 else str(impact_value)
                        footnote_num += 1
                        lines.append(f"| {rule_display} | {impact_str} | Architecture |")
                        continue
                    
                    # Format impact (positive or negative)
                    if impact_value > 0:
                        impact_str = f"+{impact_value}"
                    else:
                        impact_str = str(impact_value)
                    
                    # Get detail from issues with affected items
                    detail = self._get_detail_for_rule(dim_key, rule_name)
                    
                    lines.append(f"| {rule_display} | {impact_str} | {detail} |")
                
                lines.append("")
        
        # Add footnotes if any
        if footnotes:
            lines.append("### Notes")
            lines.append("")
            for footnote in footnotes:
                lines.append(f"- {footnote}")
            lines.append("")
            
        return lines
    
    def _get_detail_for_rule(self, dimension: str, rule_name: str) -> str:
        """Get detail/count for a specific rule from issues."""
        all_issues = self.scoring_result.get("issues", [])
        normalized_dimension = dimension.upper()
        rule_label = self._get_rule_label(dimension, rule_name)
        
        # Find issues that relate to this rule
        matching_issues = []
        for issue in all_issues:
            issue_dimension = str(issue.get("dimension", "")).upper()
            issue_message = str(issue.get("message", ""))
            if issue_dimension != normalized_dimension:
                continue
            if rule_name == "schema_type_ceiling":
                if issue.get("code", "") == "M003" or "schema" in issue_message.lower():
                    matching_issues.append(issue)
            elif rule_label and issue_message == rule_label:
                matching_issues.append(issue)
            elif rule_name.replace("_", " ").title() == issue_message:
                matching_issues.append(issue)
        
        if matching_issues:
            # Collect all affected items, deduplicated
            affected_set = set()
            for issue in matching_issues:
                affected_items = issue.get("affected", [])
                if isinstance(affected_items, list):
                    affected_set.update(affected_items)
            
            if affected_set:
                items_list = sorted(list(affected_set))[:3]  # Show first 3
                detail = ", ".join(items_list)
                if len(affected_set) > 3:
                    detail += f", +{len(affected_set) - 3} more"
                return detail

            messages = self._dedupe_sequence([str(issue.get("message", "")) for issue in matching_issues if issue.get("message")])
            if messages:
                return messages[0]

            return f"{len(matching_issues)} issue(s)"
        
        return "No affected items"

    def _get_rule_label(self, dimension: str, rule_name: str) -> str:
        """Return the configured label for a rule when available."""
        dimension_key_map = {
            "MODEL_HEALTH": "model",
            "DAX_QUALITY": "dax",
            "REPORT_DESIGN": "report",
            "GOVERNANCE": "governance",
        }
        dimension_rules = self.rules.get(dimension_key_map.get(dimension.upper(), dimension.lower()), {})
        if not isinstance(dimension_rules, dict):
            return ""

        penalties = dimension_rules.get("penalties", {})
        bonuses = dimension_rules.get("bonuses", {})
        rule_data = penalties.get(rule_name) or bonuses.get(rule_name)
        if isinstance(rule_data, dict):
            return str(rule_data.get("label", ""))
        return ""

    def _dedupe_sequence(self, values: List[str]) -> List[str]:
        """Deduplicate a list while preserving order."""
        seen = set()
        deduped = []
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    def _build_affected_issue_map(self, issues: List[Dict[str, Any]]) -> Dict[str, set]:
        """Build reverse lookup of affected item to issue codes."""
        affected_map: Dict[str, set] = {}
        for issue in issues:
            code = issue.get("code", "")
            for affected in self._dedupe_sequence(issue.get("affected", []) or []):
                affected_map.setdefault(affected, set()).add(code)
        return affected_map

    def _get_cross_references(self, code: str, affected: List[str], affected_map: Dict[str, set]) -> List[str]:
        """Return issue codes that share the same affected items."""
        related = set()
        for item in affected:
            for other_code in affected_map.get(item, set()):
                if other_code and other_code != code:
                    related.add(other_code)
        return sorted(related)

    def _get_hardcoded_recommendation(self, code: str, fallback: str) -> str:
        """Return a code-specific recommendation when available."""
        recommendation = self.issue_recommendations.get(code)
        if recommendation:
            return recommendation
        return fallback or "Review this item for improvement."

    def _generate_unused_measures_section(self) -> List[str]:
        """Generate transparent potentially-unused measures section."""
        analysis = {}
        if isinstance(self.unused_measures_data, dict):
            analysis = self.unused_measures_data.get("analysis", {})

        candidates = analysis.get("cleanup_candidates", []) if isinstance(analysis, dict) else []
        if not isinstance(candidates, list) or not candidates:
            return []

        coverage = analysis.get("analysis_coverage", {}) if isinstance(analysis, dict) else {}
        limitations = analysis.get("analysis_limitations", []) if isinstance(analysis, dict) else []

        lines = [
            "---",
            "",
            "## U001 - Potentially Unused Measures",
            "",
            "These measures have no detected references in the channels the framework can analyze deterministically.",
            "",
            f"**Analyzed:** measure-to-measure dependencies = {'yes' if coverage.get('measure_dependencies') else 'no'}, visual fields = {'yes' if coverage.get('visual_fields') else 'no'}",
            f"**Not analyzed:** {', '.join(limitations) if limitations else 'No additional limitations recorded'}",
            "",
            f"**Potential candidates:** {analysis.get('unused_measures', len(candidates))}",
            f"**Cleanup profile:** {analysis.get('cleanup_by_risk', {}).get('review_suggested', 0)} review-suggested | {analysis.get('cleanup_by_risk', {}).get('investigate', 0)} investigate | {analysis.get('cleanup_by_risk', {}).get('do_not_delete', 0)} preserve",
            "",
            "| Table | Measure | Complexity | Risk | Reason |",
            "|-------|---------|-----------|------|--------|",
        ]

        for measure in candidates[:10]:
            lines.append(
                f"| {self._escape_table_cell(measure.get('table', 'Unknown'))} | "
                f"{self._escape_table_cell(measure.get('name', 'Unknown'))} | "
                f"{measure.get('complexity', 0):.2f} | "
                f"{self._escape_table_cell(measure.get('cleanup_risk', 'UNKNOWN'))} | "
                f"{self._escape_table_cell(measure.get('reason', 'N/A'))} |"
            )

        lines.extend([
            "",
            "This section is intentionally conservative: it only marks measures as potentially unused in the analyzed channels and does not claim safe deletion.",
            ""
        ])

        return lines

    def _escape_table_cell(self, value: Any) -> str:
        """Escape markdown table cell content for compliance tables."""
        text = "" if value is None else str(value)
        return text.replace("\n", " ").replace("|", "\\|").strip()
    
    def _generate_recommendations_section(self) -> List[str]:
        """Generate prioritized recommendations (simplified)."""
        lines = [
            "---",
            "",
            "## Next Steps",
            ""
        ]
        
        all_issues = self.scoring_result.get("issues", [])
        
        # Separate by severity
        critical = [i for i in all_issues if i.get("severity") == "CRITICAL"]
        warnings = [i for i in all_issues if i.get("severity") == "WARNING"]
        info = [i for i in all_issues if i.get("severity") == "INFO"]
        
        step_num = 1
        
        # Critical issues (Immediate)
        if critical:
            lines.append("**1. Immediate:**")
            for issue in critical[:3]:  # Top 3
                code = issue.get("code", "")
                lines.append(f"   - {code}")
            lines.append("")
            step_num = 2
        
        # Warnings (This sprint)
        if warnings:
            lines.append(f"**{step_num}. This sprint:**")
            for issue in warnings[:5]:  # Top 5
                code = issue.get("code", "")
                lines.append(f"   - {code}")
            lines.append("")
            step_num += 1
        
        # Info (Backlog)
        if info:
            lines.append(f"**{step_num}. Backlog:**")
            for issue in info[:5]:  # Top 5
                code = issue.get("code", "")
                lines.append(f"   - {code}")
            lines.append("")
        
        return lines
    
    def _create_contextual_r001_message(self, generic_message: str) -> str:
        """Create contextual R001 message based on dominant visual type."""
        if "Tables:" in generic_message:
            return "Too many tables on page - consider splitting the analysis into drill-through or summary pages"
        if "Cards:" in generic_message:
            return "Too many cards on page - reduce KPI count and group related metrics"
        if "Charts:" in generic_message:
            return "Too many charts on page - consolidate visuals or split the page by topic"
        if "Slicers:" in generic_message:
            return "Too many slicers on page - consolidate filters and move repeated filters to a dedicated panel"
        
        return "Page design density exceeds recommended limits"
    
    def _generate_footer(self) -> List[str]:
        """Generate report footer."""
        lines = [
            "---",
            "",
            "*Automatically generated by Power BI Analysis Framework v1.0.0*"
        ]
        return lines
    
    def save(self, filename: str = "compliance_report.md") -> Path:
        """
        Generate and save the report.
        
        Args:
            filename: Output filename
            
        Returns:
            Path to generated file
        """
        # Ensure output directory exists
        reports_dir = self.output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate content
        content = self.generate()
        
        # Save to file
        output_path = reports_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return output_path
