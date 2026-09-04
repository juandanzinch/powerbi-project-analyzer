#!/usr/bin/env python3
"""
Datatype distribution visualization - Column datatypes distribution.
"""

import json
from pathlib import Path
from typing import Dict, Any
from collections import Counter
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore')


class DatatypeDistributionBuilder:
    def __init__(self, tables_json: str):
        self.tables_json = tables_json
        self.tables = []
        self._load_data()
    
    def _load_data(self):
        """Load tables data from JSON file"""
        with open(self.tables_json, 'r', encoding='utf-8') as f:
            self.tables = json.load(f)
    
    def _extract_datatype_distribution(self) -> Dict[str, int]:
        """Extract datatype distribution from all tables"""
        datatypes = Counter()
        
        for table in self.tables:
            for column in table.get('columns', []):
                col_name = column.get('name', '')
                col_type = column.get('dataType', 'Unknown')  # Fix: dataType with capital T
                
                # Classify column type
                column_type = self._classify_column_type(col_name, col_type)
                datatypes[column_type] += 1
        
        return dict(datatypes)
    
    def _classify_column_type(self, col_name: str, datatype: str) -> str:
        """Classify column type based on name and datatype"""
        col_lower = col_name.lower()
        
        # Detect calculated columns (contain "=")
        if ' = ' in col_name:
            return 'Calculated Column'
        
        # Classify by Power BI datatype
        if datatype == 'string':
            return 'Text'
        elif datatype in ['int64', 'int', 'integer']:
            return 'Whole Number'
        elif datatype in ['double', 'real', 'float', 'decimal']:
            return 'Decimal Number'
        elif datatype in ['dateTime', 'date']:
            if 'date' in col_lower or 'fecha' in col_lower or 'posting' in col_lower:
                return 'Date'
            return 'DateTime'
        elif datatype == 'boolean':
            return 'True/False'
        elif datatype == 'binary':
            return 'Binary'
        else:
            # For unknown types, try to infer from name
            if any(k in col_lower for k in ['amt', 'amount', 'qty', 'quantity', 'count', 'total']):
                return 'Whole Number'
            elif any(k in col_lower for k in ['price', 'rate', 'pct', 'percent']):
                return 'Decimal Number'
            elif any(k in col_lower for k in ['date', 'fecha', 'posting', 'month', 'day']):
                return 'Date'
            return f'Other ({datatype})'
    
    def create_visualization(self, output_file: str, figsize: tuple = (14, 8)):
        """Create bar chart visualization"""
        datatype_dist = self._extract_datatype_distribution()
        
        if not datatype_dist:
            print("No datatype data available")
            return None
        
        # Sort by frequency
        sorted_types = sorted(datatype_dist.items(), key=lambda x: x[1], reverse=True)
        types, counts = zip(*sorted_types)
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize, dpi=150)
        
        # Color palette with meaningful colors for data types
        color_map = {
            'Text': '#3498db',
            'Whole Number': '#2ecc71',
            'Decimal Number': '#f39c12',
            'Date': '#e74c3c',
            'DateTime': '#e67e22',
            'Calculated Column': '#9b59b6',
            'True/False': '#1abc9c',
            'Binary': '#34495e'
        }
        
        colors = [color_map.get(t, '#95a5a6') for t in types]
        
        # Create bar chart
        bars = ax.bar(types, counts, color=colors, alpha=0.85, edgecolor='black', linewidth=1.5)
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2.,
                height,
                f'{int(height)}',
                ha='center',
                va='bottom',
                fontsize=11,
                fontweight='bold'
            )
        
        # Styling
        ax.set_xlabel('Data Type', fontsize=13, fontweight='bold')
        ax.set_ylabel('Column Count', fontsize=13, fontweight='bold')
        ax.set_title(
            'Semantic Model Column Type Distribution\nAcross All Tables',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        
        plt.xticks(rotation=45, ha='right', fontsize=11)
        plt.yticks(fontsize=10)
        
        # Add grid for readability
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)
        
        # Add total at bottom
        total = sum(counts)
        ax.text(
            0.99, 0.02,
            f'Total Columns: {total}',
            transform=ax.transAxes,
            fontsize=11,
            verticalalignment='bottom',
            horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        )
        
        plt.tight_layout()
        
        # Save
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        
        return output_file
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get datatype distribution statistics"""
        datatype_dist = self._extract_datatype_distribution()
        
        total_columns = sum(datatype_dist.values())
        most_common = max(datatype_dist.items(), key=lambda x: x[1]) if datatype_dist else (None, 0)
        
        return {
            'total_columns': total_columns,
            'unique_datatypes': len(datatype_dist),
            'most_common_type': most_common[0],
            'most_common_count': most_common[1],
            'distribution': datatype_dist
        }


def create_datatype_distribution(
    tables_json: str,
    output_file: str
) -> Dict[str, Any]:
    """
    Create datatype distribution visualization.
    
    Args:
        tables_json: Path to tables.json
        output_file: Output PNG file path
    
    Returns:
        Dict with file path and statistics
    """
    builder = DatatypeDistributionBuilder(tables_json)
    
    png_file = builder.create_visualization(output_file)
    stats = builder.get_statistics()
    
    return {
        'png': png_file,
        'statistics': stats
    }
