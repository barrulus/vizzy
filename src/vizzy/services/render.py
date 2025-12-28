"""Graphviz rendering service"""

import subprocess
import tempfile
from pathlib import Path

from vizzy.models import GraphData, Node, ClusterInfo


# Color scheme for package types
TYPE_COLORS = {
    "kernel": "#ff6b6b",
    "firmware": "#ffa94d",
    "service": "#69db7c",
    "library": "#74c0fc",
    "development": "#b197fc",
    "bootstrap": "#f783ac",
    "configuration": "#ffd43b",
    "python-package": "#3b82f6",
    "perl-package": "#8b5cf6",
    "font": "#ec4899",
    "documentation": "#94a3b8",
    "application": "#22d3ee",
}

DEFAULT_COLOR = "#e2e8f0"


def get_type_color(package_type: str | None) -> str:
    """Get color for a package type"""
    if not package_type:
        return DEFAULT_COLOR
    return TYPE_COLORS.get(package_type, DEFAULT_COLOR)


def generate_dot(graph: GraphData, highlight_ids: set[int] | None = None) -> str:
    """Generate DOT source from graph data"""
    lines = [
        "digraph G {",
        '    rankdir=TB;',
        '    node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10];',
        '    edge [color="#64748b"];',
        "",
    ]

    # Add nodes
    for node in graph.nodes:
        color = get_type_color(node.package_type)
        border_color = "#1e293b" if highlight_ids and node.id in highlight_ids else color

        # Truncate long labels
        label = node.label[:40] + "..." if len(node.label) > 40 else node.label

        lines.append(
            f'    n{node.id} [label="{label}", fillcolor="{color}", '
            f'color="{border_color}", penwidth={3 if highlight_ids and node.id in highlight_ids else 1}, '
            f'href="/graph/node/{node.id}"];'
        )

    lines.append("")

    # Add edges
    for edge in graph.edges:
        style = "dashed" if edge.is_redundant else "solid"
        lines.append(f'    n{edge.source_id} -> n{edge.target_id} [style={style}];')

    lines.append("}")

    return "\n".join(lines)


def generate_cluster_dot(clusters: list[ClusterInfo], import_id: int) -> str:
    """Generate DOT source for cluster overview"""
    lines = [
        "digraph G {",
        '    rankdir=TB;',
        '    node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=12];',
        "",
    ]

    for cluster in clusters:
        color = get_type_color(cluster.package_type)
        label = f"{cluster.package_type}\\n({cluster.node_count} packages)"

        lines.append(
            f'    "{cluster.package_type}" [label="{label}", fillcolor="{color}", '
            f'href="/graph/cluster/{import_id}/{cluster.package_type}"];'
        )

    lines.append("}")

    return "\n".join(lines)


def generate_node_detail_dot(node: Node, dependencies: list[Node], dependents: list[Node]) -> str:
    """Generate DOT source for node detail view.

    Layout: Dependents (left) → Node (center) → Dependencies (right)
    Arrows mean "depends on" / "needs"
    """
    lines = [
        "digraph G {",
        '    rankdir=LR;',
        '    node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10];',
        '    edge [color="#64748b"];',
        "",
        "    // Dependents (left) - things that need this node",
        '    subgraph cluster_dependents {',
        '        label="Dependents";',
        '        style=dashed;',
        '        color="#94a3b8";',
    ]

    for dep in dependents[:20]:  # Limit to 20
        color = get_type_color(dep.package_type)
        label = dep.label[:30] + "..." if len(dep.label) > 30 else dep.label
        lines.append(
            f'        n{dep.id} [label="{label}", fillcolor="{color}", href="/graph/node/{dep.id}"];'
        )

    lines.append("    }")
    lines.append("")
    lines.append("    // Central node")

    color = get_type_color(node.package_type)
    lines.append(
        f'    n{node.id} [label="{node.label}", fillcolor="{color}", '
        f'penwidth=3, color="#1e293b"];'
    )

    lines.append("")
    lines.append("    // Dependencies (right) - things this node needs")
    lines.append('    subgraph cluster_dependencies {')
    lines.append('        label="Dependencies";')
    lines.append('        style=dashed;')
    lines.append('        color="#94a3b8";')

    for dep in dependencies[:20]:  # Limit to 20
        color = get_type_color(dep.package_type)
        label = dep.label[:30] + "..." if len(dep.label) > 30 else dep.label
        lines.append(
            f'        n{dep.id} [label="{label}", fillcolor="{color}", href="/graph/node/{dep.id}"];'
        )

    lines.append("    }")
    lines.append("")

    # Add edges from dependents to central node (dependents depend on node)
    for dep in dependents[:20]:
        lines.append(f'    n{dep.id} -> n{node.id};')

    # Add edges from central node to dependencies (node depends on dependencies)
    for dep in dependencies[:20]:
        lines.append(f'    n{node.id} -> n{dep.id};')

    lines.append("}")

    return "\n".join(lines)


def render_dot_to_svg(dot_source: str) -> str:
    """Render DOT source to SVG using Graphviz"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
        f.write(dot_source)
        dot_path = Path(f.name)

    try:
        result = subprocess.run(
            ["dot", "-Tsvg", str(dot_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Graphviz error: {result.stderr}")

        return result.stdout
    finally:
        dot_path.unlink()


def render_graph(graph: GraphData, highlight_ids: set[int] | None = None) -> str:
    """Render graph data to SVG"""
    dot = generate_dot(graph, highlight_ids)
    return render_dot_to_svg(dot)


def render_clusters(clusters: list[ClusterInfo], import_id: int) -> str:
    """Render cluster overview to SVG"""
    dot = generate_cluster_dot(clusters, import_id)
    return render_dot_to_svg(dot)


def render_node_detail(node: Node, dependencies: list[Node], dependents: list[Node]) -> str:
    """Render node detail view to SVG"""
    dot = generate_node_detail_dot(node, dependencies, dependents)
    return render_dot_to_svg(dot)
