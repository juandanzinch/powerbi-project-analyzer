"""
Report Design Dimension Scorer.

Consumes:
- pages.json: Report page structure, visuals, and configurations

Evaluates:
- Visual density per page
- Slicer binding (dimension vs fact columns)
- Hidden visuals
- Drillthrough patterns
"""

from typing import Dict, List, Any
from .base import BaseDimension, DimensionScore


class ReportDesignDimension(BaseDimension):
    """Scores report design based on usability and performance best practices."""
    
    def __init__(self, data: Dict[str, Any], rules: Dict[str, Any], weight: float = 0.25):
        """
        Initialize report design scorer.
        
        Args:
            data: Must contain:
                - "pages": list of report page configurations
            rules: Rules from scoring.report
            weight: Dimension weight (default 0.25)
        """
        super().__init__(data, rules, weight)
        self.pages = data.get("pages", [])
    
    def calculate(self) -> DimensionScore:
        """
        Calculate report design score.
        
        Returns:
            DimensionScore with breakdown and issues
        """
        if not self.pages:
            return self._make_dimension_score()
        
        # ====================================================================
        # Penalty: Excessive visuals per page
        # Only count MEANINGFUL visuals (charts, tables, cards)
        # Exclude: slicers, text boxes, buttons, other UI elements
        # ====================================================================
        pages_with_many_visuals = []
        
        for page in self.pages:
            # Get page name (from display_name field in pages.json)
            page_name = page.get("display_name", page.get("name", "Unknown"))
            
            # Get all visuals for this page
            all_visuals = page.get("visuals", [])
            
            # Categorize visuals and count only meaningful ones
            visual_breakdown = self._categorize_visuals(all_visuals)
            
            # Count only meaningful visuals (CHART, TABLE, CARD)
            meaningful_count = (
                visual_breakdown["chart_count"] + 
                visual_breakdown["table_count"] + 
                visual_breakdown["card_count"]
            )
            
            warning_threshold = self.rules["penalties"]["visuals_per_page"]["warning_threshold"]
            critical_threshold = self.rules["penalties"]["visuals_per_page"]["critical_threshold"]
            
            # Check if meaningful visuals exceed threshold
            if meaningful_count > warning_threshold:
                over_count = meaningful_count - warning_threshold
                penalty = over_count * self.rules["penalties"]["visuals_per_page"]["per_visual_over_warning"]
                
                # Create detailed description with visual breakdown
                breakdown_details = (
                    f"Charts: {visual_breakdown['chart_count']}, "
                    f"Tables: {visual_breakdown['table_count']}, "
                    f"Cards: {visual_breakdown['card_count']}, "
                    f"Slicers: {visual_breakdown['slicer_count']}, "
                    f"Text/Other: {visual_breakdown['other_count']}"
                )
                
                pages_with_many_visuals.append({
                    "page": page_name,
                    "meaningful_count": meaningful_count,
                    "breakdown": visual_breakdown,
                    "details": breakdown_details,
                    "penalty": penalty,
                    "severity": "CRITICAL" if meaningful_count > critical_threshold else "WARNING"
                })
        
        # Apply penalties with detailed descriptions
        for page_info in pages_with_many_visuals:
            penalty_value = min(
                self.rules["penalties"]["visuals_per_page"]["max"],
                page_info["penalty"]
            )
            
            # Create detailed description
            dominant_visual = self._get_dominant_visual_type(page_info["breakdown"])
            description = self._build_visual_density_message(page_info, dominant_visual)
            
            self._apply_penalty(
                "visuals_per_page",
                penalty_value,
                description,
                affected=[page_info["page"]],
                severity=page_info["severity"]
            )
        
        # ====================================================================
        # Penalty: Hidden visuals
        # ====================================================================
        hidden_visual_count = 0
        pages_with_hidden = []
        
        for page in self.pages:
            hidden = [v for v in page.get("visuals", []) if v.get("isHidden", False)]
            if hidden:
                hidden_visual_count += len(hidden)
                page_name = page.get("display_name", page.get("name", "Unknown"))
                pages_with_hidden.append(page_name)
        
        if hidden_visual_count > 0:
            penalty_value = min(
                self.rules["penalties"]["hidden_visuals"]["max"],
                hidden_visual_count * self.rules["penalties"]["hidden_visuals"]["per_visual"]
            )
            self._apply_penalty(
                "hidden_visuals",
                penalty_value,
                self.rules["penalties"]["hidden_visuals"]["label"],
                affected=pages_with_hidden,
                severity="INFO"
            )
        
        # ====================================================================
        # Bonuses
        # ====================================================================
        
        # Bonus: Slicers only from dimensions
        total_slicers = 0
        fact_slicers = 0
        
        for page in self.pages:
            for visual in page.get("visuals", []):
                if visual.get("type") == "Slicer":
                    total_slicers += 1
                    if visual.get("bound_table_type") == "FACT":
                        fact_slicers += 1
        
        if total_slicers > 0 and fact_slicers == 0:
            self._apply_bonus(
                "slicers_from_dimensions_only",
                self.rules["bonuses"]["slicers_from_dimensions_only"]["value"],
                self.rules["bonuses"]["slicers_from_dimensions_only"]["label"]
            )
        
        # ====================================================================
        # Final clamp
        # ====================================================================
        self._clamp_score()
        
        return self._make_dimension_score()
    
    def _make_dimension_score(self) -> DimensionScore:
        """Create DimensionScore object."""
        return DimensionScore(
            name="REPORT",
            score=max(0, min(100, self.score)),
            weight=self.weight,
            weighted=round(self.score * self.weight, 2),
            issues=self.issues,
            bonuses_applied=self.bonuses_applied,
            penalties_applied=self.penalties_applied,
            breakdown=self.breakdown
        )
    
    def _categorize_visuals(self, visuals: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Categorize visuals by type.
        
        Meaningful visuals (count towards threshold):
        - CHART: Actual visualization types (column, bar, line, pie, donut, etc.)
        - TABLE: Table and matrix visuals
        - CARD: KPI cards and multi-row cards
        
        Non-meaningful (don't count):
        - SLICER: Filter slicers
        - TEXT: Text boxes and shapes
        - BUTTON: Action buttons
        - OTHER: Page navigators and other UI elements
        """
        breakdown = {
            "chart_count": 0,
            "table_count": 0,
            "card_count": 0,
            "slicer_count": 0,
            "text_count": 0,
            "button_count": 0,
            "other_count": 0,
            "total_count": len(visuals)
        }
        
        for visual in visuals:
            # Get category from visual (set by parse_pages.py)
            category = visual.get("category", "OTHER")
            
            if category == "CHART":
                breakdown["chart_count"] += 1
            elif category == "TABLE":
                breakdown["table_count"] += 1
            elif category == "CARD":
                breakdown["card_count"] += 1
            elif category == "SLICER":
                breakdown["slicer_count"] += 1
            elif category == "TEXT":
                breakdown["text_count"] += 1
            elif category == "BUTTON":
                breakdown["button_count"] += 1
            else:
                breakdown["other_count"] += 1
        
        return breakdown

    def _get_dominant_visual_type(self, breakdown: Dict[str, int]) -> str:
        """Return the dominant meaningful visual type on the page."""
        candidates = {
            "CHART": breakdown.get("chart_count", 0),
            "TABLE": breakdown.get("table_count", 0),
            "CARD": breakdown.get("card_count", 0),
        }

        dominant_type, dominant_count = max(candidates.items(), key=lambda item: item[1])
        if dominant_count <= 0:
            return "visuals"
        return dominant_type.lower()

    def _build_visual_density_message(self, page_info: Dict[str, Any], dominant_visual: str) -> str:
        """Build a contextual message for pages that exceed the visual budget."""
        page_name = page_info.get("page", "Unknown")
        meaningful_count = page_info.get("meaningful_count", 0)
        details = page_info.get("details", "")

        if dominant_visual == "chart":
            context = "charts dominate the page"
        elif dominant_visual == "table":
            context = "tables dominate the page"
        elif dominant_visual == "card":
            context = "cards dominate the page"
        else:
            context = "too many visuals are competing for attention"

        return (
            f"{self.rules['penalties']['visuals_per_page']['label']} "
            f"(Page: {page_name}, Meaningful Visuals: {meaningful_count}, Context: {context} - {details})"
        )
