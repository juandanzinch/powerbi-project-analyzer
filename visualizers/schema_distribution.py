#!/usr/bin/env python3
"""
Schema type distribution visualization - Donut chart of table types.
"""

import json
from pathlib import Path
from typing import Dict, Any
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore')


class SchemaDistributionBuilder:
    def __init__(self, classifications_json: str):
        self.classifications_json = classifications_json
        self.classifications = {}
        self._load_data()
    
    def _load_data(self):
        """Load classification data from JSON file"""
        with open(self.classifications_json, 'r', encoding='utf-8') as f:
            self.classifications = json.load(f)
    
    def create_visualization(self, output_file: str, figsize: tuple = (10, 8)):
        """Create donut chart visualization"""
        # Extract table type counts
        summary = self.classifications.get('summary', {})
        
        table_types = {
            'Fact Tables': summary.get('fact_tables', 0),
            'Dimension Tables': summary.get('dimension_tables', 0),
            'Bridge Tables': summary.get('bridge_tables', 0),
            'Calculation Tables': summary.get('calculation_tables', 0),
            'Parameter Tables': summary.get('parameter_tables', 0)
        }
        
        # Remove zero-count types
        table_types = {k: v for k, v in table_types.items() if v > 0}
        
        if not table_types:
            print("No table type data available")
            return None
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize, dpi=150)
        
        # Colors matching the schema classifier
        colors = {
            'Fact Tables': '#FF6B6B',
            'Dimension Tables': '#4ECDC4',
            'Bridge Tables': '#FFE66D',
            'Calculation Tables': '#95E1D3',
            'Parameter Tables': '#DDA0DD'
        }
        
        colors_list = [colors.get(k, '#A8DADC') for k in table_types.keys()]
        
        # Create donut chart
        wedges, texts, autotexts = ax.pie(
            table_types.values(),
            labels=table_types.keys(),
            autopct='%1.1f%%',
            colors=colors_list,
            startangle=90,
            textprops={'fontsize': 11, 'weight': 'bold'}
        )
        
        # Make percentage text white
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(10)
            autotext.set_weight('bold')
        
        # Create donut hole
        centre_circle = plt.Circle((0, 0), 0.70, fc='white')
        ax.add_artist(centre_circle)
        
        # Add title
        ax.set_title(
            'Semantic Model Schema Distribution\nTable Types',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        
        # Add center text with total
        total_tables = sum(table_types.values())
        ax.text(
            0, 0,
            f'{total_tables}\nTables',
            ha='center',
            va='center',
            fontsize=16,
            weight='bold'
        )
        
        plt.tight_layout()
        
        # Save
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        
        return output_file
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get schema distribution statistics"""
        summary = self.classifications.get('summary', {})
        
        return {
            'fact_tables': summary.get('fact_tables', 0),
            'dimension_tables': summary.get('dimension_tables', 0),
            'bridge_tables': summary.get('bridge_tables', 0),
            'calculation_tables': summary.get('calculation_tables', 0),
            'parameter_tables': summary.get('parameter_tables', 0),
            'total_tables': summary.get('total_tables', 0)
        }


def create_schema_distribution(
    classifications_json: str,
    output_file: str
) -> Dict[str, Any]:
    """
    Create schema type distribution visualization.
    
    Args:
        classifications_json: Path to classifications.json
        output_file: Output PNG file path
    
    Returns:
        Dict with file path and statistics
    """
    builder = SchemaDistributionBuilder(classifications_json)
    
    png_file = builder.create_visualization(output_file)
    stats = builder.get_statistics()
    
    return {
        'png': png_file,
        'statistics': stats
    }
