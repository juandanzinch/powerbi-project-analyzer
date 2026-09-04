#!/usr/bin/env python3
"""
Relationship graph visualization - Tables as nodes, relationships as edges.
Creates both static (PNG) and interactive (HTML) versions.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import warnings

try:
    import pyvis.network as net
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False

warnings.filterwarnings('ignore')


class RelationshipGraphBuilder:
    def __init__(self, tables_json: str, relationships_json: str):
        self.tables_json = tables_json
        self.relationships_json = relationships_json
        self.tables = {}
        self.relationships = []
        self.graph = nx.DiGraph()
        self._load_data()
    
    def _load_data(self):
        """Load tables and relationships from JSON files"""
        with open(self.tables_json, 'r', encoding='utf-8') as f:
            tables_data = json.load(f)
            for table in tables_data:
                self.tables[table['name']] = {
                    'column_count': table['column_count'],
                    'measure_count': len(table['measures'])
                }
        
        with open(self.relationships_json, 'r', encoding='utf-8') as f:
            self.relationships = json.load(f)
    
    def _build_graph(self):
        """Build networkx directed graph from relationships"""
        # Add nodes for each table
        for table_name, info in self.tables.items():
            self.graph.add_node(
                table_name,
                size=info['column_count'] * 100,
                measures=info['measure_count']
            )
        
        # Add edges for relationships
        for rel in self.relationships:
            from_table = rel['from_table']
            to_table = rel['to_table']
            
            if from_table in self.tables and to_table in self.tables:
                self.graph.add_edge(
                    from_table,
                    to_table,
                    label=f"{rel['from_column']} → {rel['to_column']}",
                    cardinality=rel['cardinality']
                )
    
    def create_static_graph(self, output_file: str, figsize: Tuple[int, int] = (16, 12)):
        """Create static PNG visualization using matplotlib"""
        self._build_graph()
        
        fig, ax = plt.subplots(figsize=figsize, dpi=150)
        
        # Use spring layout for better spacing
        pos = nx.spring_layout(
            self.graph,
            k=2,
            iterations=50,
            seed=42,
            scale=2
        )
        
        # Draw nodes with size based on column count
        node_sizes = [self.graph.nodes[node].get('size', 1000) for node in self.graph.nodes()]
        
        # Color by table type (heuristic)
        node_colors = []
        for node in self.graph.nodes():
            if 'fact' in node.lower():
                node_colors.append('#FF6B6B')  # Red for fact tables
            elif 'dim' in node.lower() or 'calendar' in node.lower():
                node_colors.append('#4ECDC4')  # Teal for dimensions
            elif 'bridge' in node.lower():
                node_colors.append('#FFE66D')  # Yellow for bridge
            elif 'param' in node.lower():
                node_colors.append('#95E1D3')  # Light teal for parameters
            else:
                node_colors.append('#A8DADC')  # Default
        
        # Draw network
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
            edge_color='#999999',
            arrows=True,
            arrowsize=20,
            arrowstyle='->',
            connectionstyle='arc3,rad=0.1',
            width=1.5,
            alpha=0.6,
            ax=ax
        )
        
        # Draw labels
        nx.draw_networkx_labels(
            self.graph,
            pos,
            font_size=8,
            font_weight='bold',
            font_color='white',
            ax=ax
        )
        
        # Add legend
        fact_patch = mpatches.Patch(color='#FF6B6B', label='Fact Tables')
        dim_patch = mpatches.Patch(color='#4ECDC4', label='Dimension Tables')
        bridge_patch = mpatches.Patch(color='#FFE66D', label='Bridge Tables')
        param_patch = mpatches.Patch(color='#95E1D3', label='Parameter Tables')
        
        ax.legend(
            handles=[fact_patch, dim_patch, bridge_patch, param_patch],
            loc='upper left',
            fontsize=10,
            framealpha=0.95
        )
        
        ax.set_title(
            'Semantic Model Relationship Graph\nTables as Nodes, Relationships as Edges',
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
    
    def create_interactive_graph(self, output_file: str):
        """Create interactive HTML visualization using pyvis"""
        if not PYVIS_AVAILABLE:
            print("⚠️  pyvis not installed. Skipping interactive graph.")
            return None
        
        self._build_graph()
        
        # Create pyvis network
        g = net.Network(
            height='750px',
            width='100%',
            directed=True,
            notebook=False
        )
        
        # Add nodes
        for node in self.graph.nodes():
            size = self.graph.nodes[node].get('size', 1000) / 100
            measures = self.graph.nodes[node].get('measures', 0)
            
            # Color by type
            if 'fact' in node.lower():
                color = '#FF6B6B'
            elif 'dim' in node.lower() or 'calendar' in node.lower():
                color = '#4ECDC4'
            elif 'bridge' in node.lower():
                color = '#FFE66D'
            elif 'param' in node.lower():
                color = '#95E1D3'
            else:
                color = '#A8DADC'
            
            g.add_node(
                node,
                label=node,
                size=size,
                title=f"{node}\nMeasures: {measures}",
                color=color
            )
        
        # Add edges
        for edge in self.graph.edges(data=True):
            from_node, to_node, data = edge
            label = data.get('label', '')
            g.add_edge(from_node, to_node, title=label)
        
        # Configure physics
        g.show_buttons(filter_=['physics'])
        g.toggle_physics(True)
        
        # Save
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        g.show(output_file)
        
        return str(output_path)


def create_relationship_graph(
    tables_json: str,
    relationships_json: str,
    output_png: str,
    output_html: str = None
) -> Dict[str, str]:
    """
    Create relationship graph visualizations.
    
    Args:
        tables_json: Path to tables.json
        relationships_json: Path to relationships.json
        output_png: Output PNG file path
        output_html: Optional output HTML file path (pyvis)
    
    Returns:
        Dict with paths to generated files
    """
    builder = RelationshipGraphBuilder(tables_json, relationships_json)
    
    results = {
        'png': builder.create_static_graph(output_png)
    }
    
    # Skip HTML generation on Windows with pyvis (known issue)
    # Users can generate manually if needed
    if output_html and False:  # Disabled for stability
        try:
            results['html'] = builder.create_interactive_graph(output_html)
        except:
            pass
    
    return results
