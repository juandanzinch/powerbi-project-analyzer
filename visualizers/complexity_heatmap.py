#!/usr/bin/env python3
"""
Complexity heatmap visualization - Tables x Complexity Metrics.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

warnings.filterwarnings('ignore')


class ComplexityHeatmapBuilder:
    def __init__(self, tables_json: str, measures_json: str, classifications_json: str):
        self.tables_json = tables_json
        self.measures_json = measures_json
        self.classifications_json = classifications_json
        self.tables = []
        self.measures = []
        self.classifications = {}
        self._load_data()
    
    def _load_data(self):
        """Load data from JSON files"""
        with open(self.tables_json, 'r', encoding='utf-8') as f:
            self.tables = json.load(f)
        
        with open(self.measures_json, 'r', encoding='utf-8') as f:
            self.measures = json.load(f)
        
        with open(self.classifications_json, 'r', encoding='utf-8') as f:
            self.classifications = json.load(f)
    
    def _build_complexity_matrix(self) -> tuple:
        """Build complexity metrics matrix"""
        # Build relationships count by table from classifications data
        relationships = self.classifications.get('relationship_analysis', {}).get('relationships', [])
        rel_by_table = {}
        for rel in relationships:
            for table_name in [rel.get('from_table'), rel.get('to_table')]:
                if table_name:
                    rel_by_table[table_name] = rel_by_table.get(table_name, 0) + 1
        
        # Get unique tables
        table_names = [t.get('name', t.get('table_name', '')) for t in self.tables]
        
        # Metrics: columns, measures, relationships, avg_measure_complexity
        metrics = ['Columns', 'Measures', 'Relationships', 'Avg Measure Complexity']
        
        # Initialize matrix
        matrix_data = []
        
        for table in self.tables:
            table_name = table.get('name', table.get('table_name', ''))
            col_count = table.get('column_count', len(table.get('columns', [])))
            measure_count = len(table.get('measures', []))
            rel_count = rel_by_table.get(table_name, 0)
            
            # Calculate average measure complexity for this table
            table_measures = [m for m in self.measures if m.get('table') == table_name]
            avg_complexity = (
                sum(m.get('complexity_score', 1) for m in table_measures) / len(table_measures)
                if table_measures else 0
            )
            
            # Normalize values to 1-10 scale for heatmap
            col_norm = min(col_count / 5, 10)
            measure_norm = min(measure_count * 2, 10)
            rel_norm = min(rel_count * 2, 10)
            
            matrix_data.append([col_norm, measure_norm, rel_norm, avg_complexity])
        
        return table_names, metrics, matrix_data
    
    def create_visualization(self, output_file: str, figsize: tuple = (14, 10)):
        """Create heatmap visualization"""
        table_names, metrics, matrix_data = self._build_complexity_matrix()
        
        # Limit to top 15 tables to avoid cluttering
        if len(table_names) > 15:
            # Sort by total complexity
            complexity_scores = [sum(row) for row in matrix_data]
            top_indices = sorted(range(len(complexity_scores)), key=lambda i: complexity_scores[i], reverse=True)[:15]
            table_names = [table_names[i] for i in top_indices]
            matrix_data = [matrix_data[i] for i in top_indices]
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize, dpi=150)
        
        # Create heatmap
        sns.heatmap(
            matrix_data,
            xticklabels=metrics,
            yticklabels=table_names,
            cmap='RdYlGn_r',  # Red=high complexity, Green=low
            annot=True,
            fmt='.1f',
            cbar_kws={'label': 'Complexity Score (0-10)'},
            linewidths=0.5,
            linecolor='white',
            ax=ax,
            vmin=0,
            vmax=10
        )
        
        ax.set_title(
            'Semantic Model Complexity Heatmap\nTables × Complexity Metrics',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        
        ax.set_xlabel('Complexity Metrics', fontsize=12, fontweight='bold')
        ax.set_ylabel('Tables', fontsize=12, fontweight='bold')
        
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0, fontsize=9)
        
        plt.tight_layout()
        
        # Save
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        
        return output_file


def create_complexity_heatmap(
    tables_json: str,
    measures_json: str,
    classifications_json: str,
    output_file: str
) -> str:
    """
    Create complexity heatmap visualization.
    
    Args:
        tables_json: Path to tables.json
        measures_json: Path to measures.json
        classifications_json: Path to classifications.json
        output_file: Output PNG file path
    
    Returns:
        Path to generated PNG
    """
    builder = ComplexityHeatmapBuilder(tables_json, measures_json, classifications_json)
    return builder.create_visualization(output_file)
