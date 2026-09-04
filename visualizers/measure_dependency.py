#!/usr/bin/env python3
"""
Measure dependency DAG visualization - Shows dependencies between measures.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Any
import networkx as nx
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore')


class MeasureDependencyBuilder:
    def __init__(self, measures_json: str):
        self.measures_json = measures_json
        self.measures = []
        self.graph = nx.DiGraph()
        self._load_data()
    
    def _load_data(self):
        """Load measures from JSON file"""
        with open(self.measures_json, 'r', encoding='utf-8') as f:
            self.measures = json.load(f)
    
    def _extract_measure_references(self, expression: str) -> Set[str]:
        """Extract measure names from DAX expression"""
        if not expression or expression.startswith('[Expression'):
            return set()
        
        # Pattern to find [measure_name] references
        pattern = r'\[([^\]]+)\]'
        matches = re.findall(pattern, expression)
        
        # Filter to keep only valid measure references (typically lowercase with underscores)
        references = set()
        for match in matches:
            # Check if it looks like a measure name (not a table.column reference)
            if '.' not in match and not any(c.isupper() for c in match):
                references.add(match)
        
        return references
    
    def _build_graph(self):
        """Build DAG of measure dependencies"""
        measure_names = {m['name'] for m in self.measures}
        
        # Add nodes
        for measure in self.measures:
            complexity = measure.get('complexity_score', 1)
            self.graph.add_node(
                measure['name'],
                table=measure['table'],
                complexity=complexity,
                expression=measure.get('expression', '')[:100]  # Store first 100 chars
            )
        
        # Add edges for dependencies
        for measure in self.measures:
            references = self._extract_measure_references(
                measure.get('expression', '')
            )
            
            for ref in references:
                if ref in measure_names and ref != measure['name']:
                    self.graph.add_edge(
                        measure['name'],
                        ref,  # Points to the measure it depends on
                        label='depends_on'
                    )
    
    def create_visualization(self, output_file: str, figsize: tuple = (16, 12)):
        """Create DAG visualization"""
        self._build_graph()
        
        fig, ax = plt.subplots(figsize=figsize, dpi=150)
        
        # Use hierarchical layout for DAG
        try:
            # Try topological sort for better hierarchy
            pos = nx.spring_layout(
                self.graph,
                k=3,
                iterations=50,
                seed=42
            )
        except:
            pos = nx.spring_layout(self.graph, k=2, iterations=50, seed=42)
        
        # Color by complexity
        node_colors = []
        node_sizes = []
        
        for node in self.graph.nodes():
            complexity = self.graph.nodes[node].get('complexity', 1)
            
            # Color gradient based on complexity (1-10)
            if complexity <= 3:
                color = '#2ECC71'  # Green (simple)
            elif complexity <= 6:
                color = '#F39C12'  # Orange (medium)
            else:
                color = '#E74C3C'  # Red (complex)
            
            node_colors.append(color)
            node_sizes.append(complexity * 150)
        
        # Draw nodes
        nx.draw_networkx_nodes(
            self.graph,
            pos,
            node_color=node_colors,
            node_size=node_sizes,
            alpha=0.9,
            ax=ax
        )
        
        # Draw edges
        nx.draw_networkx_edges(
            self.graph,
            pos,
            edge_color='#555555',
            arrows=True,
            arrowsize=15,
            arrowstyle='->',
            connectionstyle='arc3,rad=0.1',
            width=1.5,
            alpha=0.5,
            ax=ax
        )
        
        # Draw labels
        nx.draw_networkx_labels(
            self.graph,
            pos,
            font_size=7,
            font_weight='bold',
            font_color='white',
            ax=ax
        )
        
        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#2ECC71', label='Simple (Complexity 1-3)'),
            Patch(facecolor='#F39C12', label='Medium (Complexity 4-6)'),
            Patch(facecolor='#E74C3C', label='Complex (Complexity 7-10)')
        ]
        
        ax.legend(
            handles=legend_elements,
            loc='upper left',
            fontsize=10,
            framealpha=0.95
        )
        
        ax.set_title(
            'Measure Dependency DAG\nNode Size = Complexity, Arrows = Dependencies',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        
        ax.axis('off')
        plt.tight_layout()
        
        # Save
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        
        return output_file
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get DAG statistics"""
        if not self.graph or len(self.graph.nodes()) == 0:
            return {
                'total_measures': len(self.measures),
                'measures_with_dependencies': 0,
                'max_depth': 0,
                'avg_complexity': 0
            }
        
        # Find measures with dependencies
        measures_with_deps = len([n for n in self.graph.nodes() if self.graph.in_degree(n) > 0])
        
        # Calculate average complexity
        complexities = [self.graph.nodes[n].get('complexity', 1) for n in self.graph.nodes()]
        avg_complexity = sum(complexities) / len(complexities) if complexities else 0
        
        return {
            'total_measures': len(self.measures),
            'measures_with_dependencies': measures_with_deps,
            'total_edges': self.graph.number_of_edges(),
            'avg_complexity': round(avg_complexity, 2)
        }


def create_measure_dependency_dag(
    measures_json: str,
    output_file: str
) -> Dict[str, Any]:
    """
    Create measure dependency DAG visualization.
    
    Args:
        measures_json: Path to measures.json
        output_file: Output PNG file path
    
    Returns:
        Dict with file path and statistics
    """
    builder = MeasureDependencyBuilder(measures_json)
    
    png_file = builder.create_visualization(output_file)
    stats = builder.get_statistics()
    
    return {
        'png': png_file,
        'statistics': stats
    }
