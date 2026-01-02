"""Semantic zoom service for level-of-detail graph rendering.

This service generates graphs at different levels of detail based on zoom level:
- Level 0 (zoomed out): Clusters only (package types)
- Level 1 (medium): Top packages by closure size per cluster, with aggregation
- Level 2 (zoomed in): Full detail with all visible nodes

The semantic zoom feature allows users to see aggregated views when zoomed out
and progressively more detail as they zoom in.

Task 8G-002 adds node aggregation which collapses similar nodes into aggregate
groups when zoomed out, expanding them when zoomed in.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from vizzy.database import get_db
from vizzy.models import Node, Edge, GraphData, ClusterInfo
from vizzy.services.cache import cache, cache_key_for_import


class ZoomLevel(IntEnum):
    """Semantic zoom levels for graph rendering."""
    CLUSTER = 0      # Show only package type clusters
    OVERVIEW = 1     # Show top packages per cluster
    DETAILED = 2     # Show full detail


class AggregationMode(IntEnum):
    """How to aggregate similar nodes."""
    NONE = 0         # No aggregation (show all individual nodes)
    BY_PREFIX = 1    # Aggregate by common label prefix (e.g., python3.11-*)
    BY_DEPTH = 2     # Aggregate nodes at similar depth levels
    BY_TYPE = 3      # Aggregate by package type (similar to clusters but as nodes)


@dataclass
class NodeAggregate:
    """An aggregate representing multiple similar nodes collapsed into one.

    When zoomed out, similar nodes (e.g., all python packages) are collapsed
    into a single aggregate node. When the user zooms in, these expand back
    to individual nodes.

    Attributes:
        id: Unique identifier for this aggregate (e.g., "agg_python3.11_library")
        label_prefix: Common prefix of aggregated nodes (e.g., "python3.11-")
        package_type: Common package type (if all same) or "mixed"
        node_count: Number of nodes in this aggregate
        total_closure_size: Sum of closure sizes of aggregated nodes
        contained_node_ids: IDs of the nodes collapsed into this aggregate
        representative_nodes: Top 3 nodes for preview/tooltip
        can_expand: True if this aggregate can be expanded at current zoom
        average_depth: Average depth of contained nodes
    """
    id: str
    label_prefix: str
    package_type: str
    node_count: int
    total_closure_size: int
    contained_node_ids: list[int]
    representative_nodes: list[Node]
    can_expand: bool = True
    average_depth: float = 0.0


@dataclass
class AggregateEdge:
    """An edge connecting aggregates or aggregate to regular node."""
    source_id: str  # Can be aggregate ID or "n{node_id}"
    target_id: str  # Can be aggregate ID or "n{node_id}"
    edge_count: int
    is_aggregate_edge: bool = True


@dataclass
class ClusterNode:
    """A cluster representing aggregated nodes of a package type."""
    id: str  # e.g., "cluster_library"
    package_type: str
    node_count: int
    total_closure_size: int
    representative_nodes: list[Node]  # Top nodes for tooltip/preview


@dataclass
class ClusterEdge:
    """An edge between clusters representing aggregated dependencies."""
    source_cluster: str
    target_cluster: str
    edge_count: int


@dataclass
class SemanticGraphData:
    """Graph data for a specific zoom level with optional aggregation.

    At different zoom levels, the graph can contain:
    - Cluster level (0): clusters and cluster_edges only
    - Overview level (1): clusters, nodes, edges, plus aggregates
    - Detailed level (2): nodes and edges (individual)

    Aggregates represent collapsed groups of similar nodes that expand
    when zoomed in.
    """
    zoom_level: ZoomLevel
    clusters: list[ClusterNode]
    cluster_edges: list[ClusterEdge]
    nodes: list[Node]
    edges: list[Edge]
    # Aggregation support (Task 8G-002)
    aggregates: list[NodeAggregate] = field(default_factory=list)
    aggregate_edges: list[AggregateEdge] = field(default_factory=list)
    aggregation_mode: AggregationMode = AggregationMode.NONE
    aggregation_threshold: int = 5  # Min nodes to aggregate


def get_semantic_graph(
    import_id: int,
    zoom_level: ZoomLevel,
    center_node_id: Optional[int] = None,
    package_type: Optional[str] = None,
    max_nodes: int = 100,
) -> SemanticGraphData:
    """Get graph data at the specified semantic zoom level.

    Args:
        import_id: The import to query
        zoom_level: The semantic zoom level (CLUSTER, OVERVIEW, or DETAILED)
        center_node_id: Optional node to center the view on
        package_type: Optional filter to a specific package type
        max_nodes: Maximum number of nodes to return at DETAILED level

    Returns:
        SemanticGraphData with appropriate level of detail
    """
    cache_key = cache_key_for_import(
        "semantic_graph",
        import_id,
        int(zoom_level),
        center_node_id or "none",
        package_type or "all",
        max_nodes,
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if zoom_level == ZoomLevel.CLUSTER:
        result = _get_cluster_level_graph(import_id, package_type)
    elif zoom_level == ZoomLevel.OVERVIEW:
        result = _get_overview_level_graph(import_id, package_type, max_nodes)
    else:  # DETAILED
        result = _get_detailed_level_graph(
            import_id, center_node_id, package_type, max_nodes
        )

    # Cache for 2 minutes
    cache.set(cache_key, result, ttl=120)
    return result


def _get_cluster_level_graph(
    import_id: int,
    package_type: Optional[str] = None,
) -> SemanticGraphData:
    """Get cluster-level graph showing only package type aggregations."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get cluster statistics
            if package_type:
                cur.execute(
                    """
                    SELECT
                        package_type,
                        COUNT(*) as node_count,
                        COALESCE(SUM(closure_size), 0) as total_closure_size
                    FROM nodes
                    WHERE import_id = %s AND package_type = %s
                    GROUP BY package_type
                    ORDER BY node_count DESC
                    """,
                    (import_id, package_type),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        package_type,
                        COUNT(*) as node_count,
                        COALESCE(SUM(closure_size), 0) as total_closure_size
                    FROM nodes
                    WHERE import_id = %s
                    GROUP BY package_type
                    ORDER BY node_count DESC
                    """,
                    (import_id,),
                )
            cluster_rows = cur.fetchall()

            clusters = []
            for row in cluster_rows:
                pkg_type = row['package_type'] or 'other'

                # Get top 3 representative nodes for this cluster
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND COALESCE(package_type, 'other') = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT 3
                    """,
                    (import_id, pkg_type),
                )
                rep_nodes = [Node(**r) for r in cur.fetchall()]

                clusters.append(ClusterNode(
                    id=f"cluster_{pkg_type}",
                    package_type=pkg_type,
                    node_count=row['node_count'],
                    total_closure_size=row['total_closure_size'] or 0,
                    representative_nodes=rep_nodes,
                ))

            # Get inter-cluster edge counts
            cur.execute(
                """
                SELECT
                    COALESCE(sn.package_type, 'other') as source_type,
                    COALESCE(tn.package_type, 'other') as target_type,
                    COUNT(*) as edge_count
                FROM edges e
                JOIN nodes sn ON e.source_id = sn.id
                JOIN nodes tn ON e.target_id = tn.id
                WHERE e.import_id = %s
                GROUP BY COALESCE(sn.package_type, 'other'), COALESCE(tn.package_type, 'other')
                HAVING COUNT(*) > 0
                """,
                (import_id,),
            )
            cluster_edges = [
                ClusterEdge(
                    source_cluster=f"cluster_{row['source_type']}",
                    target_cluster=f"cluster_{row['target_type']}",
                    edge_count=row['edge_count'],
                )
                for row in cur.fetchall()
                if row['source_type'] != row['target_type']  # Skip self-edges for clarity
            ]

    return SemanticGraphData(
        zoom_level=ZoomLevel.CLUSTER,
        clusters=clusters,
        cluster_edges=cluster_edges,
        nodes=[],
        edges=[],
    )


def _get_overview_level_graph(
    import_id: int,
    package_type: Optional[str] = None,
    max_nodes: int = 100,
) -> SemanticGraphData:
    """Get overview-level graph showing top packages per cluster."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get clusters first
            cluster_result = _get_cluster_level_graph(import_id, package_type)

            # Get top N nodes per package type
            nodes_per_type = max_nodes // max(len(cluster_result.clusters), 1)
            nodes_per_type = max(nodes_per_type, 5)  # At least 5 per type

            all_nodes = []
            for cluster in cluster_result.clusters:
                pkg_type = cluster.package_type
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND COALESCE(package_type, 'other') = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, pkg_type, nodes_per_type),
                )
                all_nodes.extend([Node(**r) for r in cur.fetchall()])

            # Get edges between these nodes
            node_ids = [n.id for n in all_nodes]
            if node_ids:
                cur.execute(
                    """
                    SELECT id, import_id, source_id, target_id, edge_color,
                           is_redundant, dependency_type
                    FROM edges
                    WHERE import_id = %s
                      AND source_id = ANY(%s)
                      AND target_id = ANY(%s)
                    """,
                    (import_id, node_ids, node_ids),
                )
                edges = [Edge(**r) for r in cur.fetchall()]
            else:
                edges = []

    return SemanticGraphData(
        zoom_level=ZoomLevel.OVERVIEW,
        clusters=cluster_result.clusters,
        cluster_edges=cluster_result.cluster_edges,
        nodes=all_nodes,
        edges=edges,
    )


def _get_detailed_level_graph(
    import_id: int,
    center_node_id: Optional[int] = None,
    package_type: Optional[str] = None,
    max_nodes: int = 100,
) -> SemanticGraphData:
    """Get detailed graph with all nodes (filtered by center or type)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if center_node_id:
                # Get nodes around the center node (BFS expansion)
                cur.execute(
                    """
                    WITH RECURSIVE neighbors AS (
                        -- Start with center node
                        SELECT id, 0 as distance
                        FROM nodes WHERE id = %s

                        UNION

                        -- Add neighbors within distance limit
                        SELECT
                            CASE
                                WHEN e.source_id = nb.id THEN e.target_id
                                ELSE e.source_id
                            END as id,
                            nb.distance + 1 as distance
                        FROM neighbors nb
                        JOIN edges e ON e.source_id = nb.id OR e.target_id = nb.id
                        WHERE nb.distance < 2
                    )
                    SELECT DISTINCT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                           n.package_type, n.depth, n.closure_size, n.metadata,
                           n.is_top_level, n.top_level_source
                    FROM neighbors nb
                    JOIN nodes n ON n.id = nb.id
                    ORDER BY n.closure_size DESC NULLS LAST
                    LIMIT %s
                    """,
                    (center_node_id, max_nodes),
                )
            elif package_type:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND COALESCE(package_type, 'other') = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, package_type, max_nodes),
                )
            else:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, max_nodes),
                )

            nodes = [Node(**r) for r in cur.fetchall()]
            node_ids = [n.id for n in nodes]

            if node_ids:
                cur.execute(
                    """
                    SELECT id, import_id, source_id, target_id, edge_color,
                           is_redundant, dependency_type
                    FROM edges
                    WHERE import_id = %s
                      AND source_id = ANY(%s)
                      AND target_id = ANY(%s)
                    """,
                    (import_id, node_ids, node_ids),
                )
                edges = [Edge(**r) for r in cur.fetchall()]
            else:
                edges = []

    # Get cluster info for context
    cluster_result = _get_cluster_level_graph(import_id, package_type)

    return SemanticGraphData(
        zoom_level=ZoomLevel.DETAILED,
        clusters=cluster_result.clusters,
        cluster_edges=[],  # Don't show cluster edges at detail level
        nodes=nodes,
        edges=edges,
    )


def get_zoom_level_for_scale(scale: float) -> ZoomLevel:
    """Determine the appropriate zoom level based on the current scale.

    Args:
        scale: The current zoom scale (1.0 = default, <1 = zoomed out, >1 = zoomed in)

    Returns:
        The appropriate ZoomLevel for rendering
    """
    if scale < 0.3:
        return ZoomLevel.CLUSTER
    elif scale < 0.7:
        return ZoomLevel.OVERVIEW
    else:
        return ZoomLevel.DETAILED


# =============================================================================
# Node Aggregation Functions (Task 8G-002)
# =============================================================================


def _extract_label_prefix(label: str) -> str:
    """Extract a prefix from a package label for aggregation.

    For NixOS derivation names, we extract prefixes like:
    - "python3.11-" from "python3.11-requests-2.28.0"
    - "perl5.36-" from "perl5.36-HTTP-Message-1.2"
    - Base package name from "openssl-3.0.12" -> "openssl"

    Args:
        label: The package label

    Returns:
        The extracted prefix for grouping
    """
    import re

    # Common prefix patterns for NixOS packages
    patterns = [
        # Python packages: python3.11-*
        (r'^(python\d+\.\d+-)', lambda m: m.group(1)),
        # Perl packages: perl5.36-*
        (r'^(perl\d+\.\d+-)', lambda m: m.group(1)),
        # Haskell packages: ghc9.4.4-*
        (r'^(ghc\d+\.\d+\.\d+-)', lambda m: m.group(1)),
        # Ruby gems: ruby3.1-*
        (r'^(ruby\d+\.\d+-)', lambda m: m.group(1)),
        # Node packages: nodejs-18.*
        (r'^(nodejs-\d+\.)', lambda m: m.group(1)),
        # Go packages: go_1_20-*
        (r'^(go_\d+_\d+-)', lambda m: m.group(1)),
        # Rust crates: rust_1_70-*
        (r'^(rust_\d+_\d+-)', lambda m: m.group(1)),
        # Generic pattern: name-version -> name
        (r'^([a-zA-Z][a-zA-Z0-9_-]*?)-\d', lambda m: m.group(1)),
    ]

    for pattern, extractor in patterns:
        match = re.match(pattern, label)
        if match:
            return extractor(match)

    # Fallback: use the label up to first digit if any
    for i, char in enumerate(label):
        if char.isdigit() and i > 2:
            return label[:i].rstrip('-_')

    # If no pattern matches, return first 15 chars or full label
    return label[:15] if len(label) > 15 else label


def _compute_aggregates_by_prefix(
    nodes: list[Node],
    edges: list[Edge],
    threshold: int = 5,
) -> tuple[list[NodeAggregate], list[Node], list[AggregateEdge], list[Edge]]:
    """Aggregate nodes by common label prefix.

    Groups nodes with similar prefixes (e.g., all python3.11-* packages)
    into aggregates when there are enough nodes to aggregate.

    Args:
        nodes: List of nodes to potentially aggregate
        edges: List of edges between nodes
        threshold: Minimum nodes needed to form an aggregate

    Returns:
        Tuple of (aggregates, remaining_nodes, aggregate_edges, remaining_edges)
    """
    from collections import defaultdict

    # Group nodes by prefix
    prefix_groups: dict[str, list[Node]] = defaultdict(list)
    for node in nodes:
        prefix = _extract_label_prefix(node.label)
        prefix_groups[prefix].append(node)

    # Determine which groups become aggregates
    aggregates: list[NodeAggregate] = []
    remaining_nodes: list[Node] = []
    aggregated_node_ids: set[int] = set()

    for prefix, group_nodes in prefix_groups.items():
        if len(group_nodes) >= threshold:
            # Create aggregate
            pkg_types = set(n.package_type or 'other' for n in group_nodes)
            common_type = pkg_types.pop() if len(pkg_types) == 1 else 'mixed'

            total_closure = sum(n.closure_size or 0 for n in group_nodes)
            avg_depth = (
                sum(n.depth or 0 for n in group_nodes) / len(group_nodes)
                if group_nodes else 0
            )

            # Sort by closure size for representative nodes
            sorted_nodes = sorted(
                group_nodes,
                key=lambda n: n.closure_size or 0,
                reverse=True
            )

            aggregate = NodeAggregate(
                id=f"agg_{prefix.replace('.', '_').replace('-', '_')}_{common_type}",
                label_prefix=prefix,
                package_type=common_type,
                node_count=len(group_nodes),
                total_closure_size=total_closure,
                contained_node_ids=[n.id for n in group_nodes],
                representative_nodes=sorted_nodes[:3],
                can_expand=True,
                average_depth=avg_depth,
            )
            aggregates.append(aggregate)
            aggregated_node_ids.update(n.id for n in group_nodes)
        else:
            # Keep nodes as-is
            remaining_nodes.extend(group_nodes)

    # Build mapping of node_id to aggregate_id for edge processing
    node_to_aggregate: dict[int, str] = {}
    for agg in aggregates:
        for node_id in agg.contained_node_ids:
            node_to_aggregate[node_id] = agg.id

    # Process edges: aggregate edges between aggregates, keep others
    aggregate_edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    remaining_edges: list[Edge] = []

    for edge in edges:
        source_agg = node_to_aggregate.get(edge.source_id)
        target_agg = node_to_aggregate.get(edge.target_id)

        if source_agg and target_agg:
            # Both in aggregates - count as aggregate edge
            if source_agg != target_agg:  # Skip internal edges
                aggregate_edge_counts[(source_agg, target_agg)] += 1
        elif source_agg:
            # Source in aggregate, target is regular node
            aggregate_edge_counts[(source_agg, f"n{edge.target_id}")] += 1
        elif target_agg:
            # Target in aggregate, source is regular node
            aggregate_edge_counts[(f"n{edge.source_id}", target_agg)] += 1
        else:
            # Neither in aggregate - keep as regular edge
            remaining_edges.append(edge)

    # Convert aggregate edge counts to AggregateEdge objects
    aggregate_edges = [
        AggregateEdge(
            source_id=src,
            target_id=tgt,
            edge_count=count,
            is_aggregate_edge=True,
        )
        for (src, tgt), count in aggregate_edge_counts.items()
    ]

    return aggregates, remaining_nodes, aggregate_edges, remaining_edges


def _compute_aggregates_by_depth(
    nodes: list[Node],
    edges: list[Edge],
    depth_bucket_size: int = 2,
    threshold: int = 10,
) -> tuple[list[NodeAggregate], list[Node], list[AggregateEdge], list[Edge]]:
    """Aggregate nodes by dependency depth levels.

    Groups nodes at similar depths to show structural layers.

    Args:
        nodes: List of nodes to potentially aggregate
        edges: List of edges between nodes
        depth_bucket_size: Group nodes within this many depth levels
        threshold: Minimum nodes needed to form an aggregate

    Returns:
        Tuple of (aggregates, remaining_nodes, aggregate_edges, remaining_edges)
    """
    from collections import defaultdict

    # Group nodes by depth bucket
    depth_groups: dict[int, list[Node]] = defaultdict(list)
    for node in nodes:
        depth = node.depth or 0
        bucket = (depth // depth_bucket_size) * depth_bucket_size
        depth_groups[bucket].append(node)

    aggregates: list[NodeAggregate] = []
    remaining_nodes: list[Node] = []
    aggregated_node_ids: set[int] = set()

    for bucket, group_nodes in sorted(depth_groups.items()):
        if len(group_nodes) >= threshold:
            pkg_types = set(n.package_type or 'other' for n in group_nodes)
            common_type = pkg_types.pop() if len(pkg_types) == 1 else 'mixed'

            total_closure = sum(n.closure_size or 0 for n in group_nodes)

            sorted_nodes = sorted(
                group_nodes,
                key=lambda n: n.closure_size or 0,
                reverse=True
            )

            depth_range = f"{bucket}-{bucket + depth_bucket_size - 1}"
            aggregate = NodeAggregate(
                id=f"agg_depth_{bucket}_{common_type}",
                label_prefix=f"Depth {depth_range}",
                package_type=common_type,
                node_count=len(group_nodes),
                total_closure_size=total_closure,
                contained_node_ids=[n.id for n in group_nodes],
                representative_nodes=sorted_nodes[:3],
                can_expand=True,
                average_depth=float(bucket),
            )
            aggregates.append(aggregate)
            aggregated_node_ids.update(n.id for n in group_nodes)
        else:
            remaining_nodes.extend(group_nodes)

    # Process edges (same logic as prefix aggregation)
    node_to_aggregate: dict[int, str] = {}
    for agg in aggregates:
        for node_id in agg.contained_node_ids:
            node_to_aggregate[node_id] = agg.id

    aggregate_edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    remaining_edges: list[Edge] = []

    for edge in edges:
        source_agg = node_to_aggregate.get(edge.source_id)
        target_agg = node_to_aggregate.get(edge.target_id)

        if source_agg and target_agg:
            if source_agg != target_agg:
                aggregate_edge_counts[(source_agg, target_agg)] += 1
        elif source_agg:
            aggregate_edge_counts[(source_agg, f"n{edge.target_id}")] += 1
        elif target_agg:
            aggregate_edge_counts[(f"n{edge.source_id}", target_agg)] += 1
        else:
            remaining_edges.append(edge)

    aggregate_edges = [
        AggregateEdge(
            source_id=src,
            target_id=tgt,
            edge_count=count,
            is_aggregate_edge=True,
        )
        for (src, tgt), count in aggregate_edge_counts.items()
    ]

    return aggregates, remaining_nodes, aggregate_edges, remaining_edges


def apply_aggregation(
    graph_data: SemanticGraphData,
    mode: AggregationMode = AggregationMode.BY_PREFIX,
    threshold: int = 5,
) -> SemanticGraphData:
    """Apply aggregation to a semantic graph.

    Args:
        graph_data: The graph data to aggregate
        mode: The aggregation mode to use
        threshold: Minimum nodes to form an aggregate

    Returns:
        Updated SemanticGraphData with aggregates applied
    """
    if mode == AggregationMode.NONE or not graph_data.nodes:
        return graph_data

    if mode == AggregationMode.BY_PREFIX:
        aggregates, nodes, agg_edges, edges = _compute_aggregates_by_prefix(
            graph_data.nodes,
            graph_data.edges,
            threshold=threshold,
        )
    elif mode == AggregationMode.BY_DEPTH:
        aggregates, nodes, agg_edges, edges = _compute_aggregates_by_depth(
            graph_data.nodes,
            graph_data.edges,
            threshold=threshold,
        )
    else:
        # Other modes not yet implemented
        return graph_data

    return SemanticGraphData(
        zoom_level=graph_data.zoom_level,
        clusters=graph_data.clusters,
        cluster_edges=graph_data.cluster_edges,
        nodes=nodes,
        edges=edges,
        aggregates=aggregates,
        aggregate_edges=agg_edges,
        aggregation_mode=mode,
        aggregation_threshold=threshold,
    )


def generate_semantic_dot(graph_data: SemanticGraphData, import_id: int) -> str:
    """Generate DOT source for a semantic zoom graph.

    Supports both regular nodes and aggregated nodes (Task 8G-002).

    Args:
        graph_data: The semantic graph data to render
        import_id: The import ID (for href links)

    Returns:
        DOT language source string
    """
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
        "mixed": "#a1a1aa",
        "other": "#e2e8f0",
    }

    def get_color(pkg_type: str) -> str:
        return TYPE_COLORS.get(pkg_type, TYPE_COLORS["other"])

    def escape_dot_string(s: str) -> str:
        """Escape special characters for DOT labels."""
        return s.replace('"', '\\"').replace('\\', '\\\\')

    lines = [
        "digraph G {",
        '    rankdir=TB;',
        '    node [shape=box, style="rounded,filled", fontname="sans-serif"];',
        '    edge [color="#64748b"];',
        "",
    ]

    if graph_data.zoom_level == ZoomLevel.CLUSTER:
        # Render cluster-level view
        lines.append("    // Cluster nodes")
        for cluster in graph_data.clusters:
            color = get_color(cluster.package_type)
            label = f"{cluster.package_type}\\n({cluster.node_count} packages)"
            tooltip = "\\n".join([
                escape_dot_string(n.label) for n in cluster.representative_nodes[:3]
            ]) if cluster.representative_nodes else ""

            lines.append(
                f'    "{cluster.id}" [label="{label}", fillcolor="{color}", '
                f'fontsize=14, tooltip="{tooltip}", '
                f'href="/graph/cluster/{import_id}/{cluster.package_type}"];'
            )

        lines.append("")
        lines.append("    // Cluster edges")
        for edge in graph_data.cluster_edges:
            # Scale edge weight based on count
            penwidth = min(1 + edge.edge_count / 100, 5)
            lines.append(
                f'    "{edge.source_cluster}" -> "{edge.target_cluster}" '
                f'[penwidth={penwidth:.1f}, tooltip="{edge.edge_count} edges"];'
            )

    elif graph_data.zoom_level == ZoomLevel.OVERVIEW:
        # Render overview with clusters as subgraphs, including aggregates
        clusters_by_type: dict[str, list[Node]] = {}
        aggregates_by_type: dict[str, list[NodeAggregate]] = {}

        for node in graph_data.nodes:
            pkg_type = node.package_type or "other"
            if pkg_type not in clusters_by_type:
                clusters_by_type[pkg_type] = []
            clusters_by_type[pkg_type].append(node)

        for agg in graph_data.aggregates:
            pkg_type = agg.package_type if agg.package_type != "mixed" else "other"
            if pkg_type not in aggregates_by_type:
                aggregates_by_type[pkg_type] = []
            aggregates_by_type[pkg_type].append(agg)

        for cluster in graph_data.clusters:
            pkg_type = cluster.package_type
            color = get_color(pkg_type)
            nodes_in_cluster = clusters_by_type.get(pkg_type, [])
            aggs_in_cluster = aggregates_by_type.get(pkg_type, [])

            if nodes_in_cluster or aggs_in_cluster:
                lines.append(f'    subgraph cluster_{pkg_type.replace("-", "_")} {{')
                lines.append(f'        label="{pkg_type} ({cluster.node_count})";')
                lines.append(f'        style=dashed;')
                lines.append(f'        color="{color}";')
                lines.append(f'        bgcolor="{color}22";')

                # Render regular nodes
                for node in nodes_in_cluster:
                    label = escape_dot_string(
                        node.label[:30] + "..." if len(node.label) > 30 else node.label
                    )
                    lines.append(
                        f'        n{node.id} [label="{label}", fillcolor="{color}", '
                        f'fontsize=10, href="/graph/node/{node.id}"];'
                    )

                # Render aggregate nodes (Task 8G-002)
                for agg in aggs_in_cluster:
                    agg_label = escape_dot_string(f"{agg.label_prefix}*\\n({agg.node_count} packages)")
                    agg_color = get_color(agg.package_type)
                    tooltip_nodes = "\\n".join([
                        escape_dot_string(n.label) for n in agg.representative_nodes[:3]
                    ])
                    # Use hexagon shape for aggregates to distinguish from regular nodes
                    lines.append(
                        f'        "{agg.id}" [label="{agg_label}", fillcolor="{agg_color}", '
                        f'fontsize=10, shape=hexagon, penwidth=2, '
                        f'tooltip="{tooltip_nodes}", '
                        f'href="/api/semantic-zoom/{import_id}?expand_aggregate={agg.id}"];'
                    )

                lines.append("    }")
                lines.append("")

        # Render edges for regular nodes
        lines.append("    // Regular edges")
        for edge in graph_data.edges:
            style = "dashed" if edge.is_redundant else "solid"
            lines.append(f'    n{edge.source_id} -> n{edge.target_id} [style={style}];')

        # Render aggregate edges (Task 8G-002)
        if graph_data.aggregate_edges:
            lines.append("")
            lines.append("    // Aggregate edges")
            for agg_edge in graph_data.aggregate_edges:
                penwidth = min(1 + agg_edge.edge_count / 10, 4)
                lines.append(
                    f'    "{agg_edge.source_id}" -> "{agg_edge.target_id}" '
                    f'[penwidth={penwidth:.1f}, style=bold, '
                    f'tooltip="{agg_edge.edge_count} edges"];'
                )

    else:  # DETAILED
        # Render full detail view with optional aggregates
        lines.append("    // Nodes")
        for node in graph_data.nodes:
            color = get_color(node.package_type or "other")
            label = escape_dot_string(
                node.label[:40] + "..." if len(node.label) > 40 else node.label
            )
            lines.append(
                f'    n{node.id} [label="{label}", fillcolor="{color}", '
                f'fontsize=10, href="/graph/node/{node.id}"];'
            )

        # Render aggregates if any (for partial aggregation at detail level)
        if graph_data.aggregates:
            lines.append("")
            lines.append("    // Aggregate nodes")
            for agg in graph_data.aggregates:
                agg_label = escape_dot_string(f"{agg.label_prefix}*\\n({agg.node_count})")
                color = get_color(agg.package_type)
                tooltip_nodes = "\\n".join([
                    escape_dot_string(n.label) for n in agg.representative_nodes[:3]
                ])
                lines.append(
                    f'    "{agg.id}" [label="{agg_label}", fillcolor="{color}", '
                    f'fontsize=10, shape=hexagon, penwidth=2, '
                    f'tooltip="{tooltip_nodes}", '
                    f'href="/api/semantic-zoom/{import_id}?expand_aggregate={agg.id}"];'
                )

        lines.append("")
        lines.append("    // Edges")
        for edge in graph_data.edges:
            style = "dashed" if edge.is_redundant else "solid"
            lines.append(f'    n{edge.source_id} -> n{edge.target_id} [style={style}];')

        # Render aggregate edges
        if graph_data.aggregate_edges:
            lines.append("")
            lines.append("    // Aggregate edges")
            for agg_edge in graph_data.aggregate_edges:
                penwidth = min(1 + agg_edge.edge_count / 10, 4)
                lines.append(
                    f'    "{agg_edge.source_id}" -> "{agg_edge.target_id}" '
                    f'[penwidth={penwidth:.1f}, style=bold, '
                    f'tooltip="{agg_edge.edge_count} edges"];'
                )

    lines.append("}")
    return "\n".join(lines)


def get_semantic_graph_with_aggregation(
    import_id: int,
    zoom_level: ZoomLevel,
    aggregation_mode: AggregationMode = AggregationMode.NONE,
    aggregation_threshold: int = 5,
    center_node_id: Optional[int] = None,
    package_type: Optional[str] = None,
    max_nodes: int = 100,
    expand_aggregate: Optional[str] = None,
) -> SemanticGraphData:
    """Get semantic graph with level-of-detail aggregation.

    This is the main entry point for Task 8G-002, combining semantic zoom
    with node aggregation.

    Args:
        import_id: The import to query
        zoom_level: The semantic zoom level
        aggregation_mode: How to aggregate nodes (NONE, BY_PREFIX, BY_DEPTH)
        aggregation_threshold: Minimum nodes to form an aggregate
        center_node_id: Optional node to center on
        package_type: Optional package type filter
        max_nodes: Maximum nodes to return
        expand_aggregate: ID of an aggregate to expand (shows its contained nodes)

    Returns:
        SemanticGraphData with appropriate level of detail and aggregation
    """
    # Build cache key including aggregation parameters
    cache_key = cache_key_for_import(
        "semantic_graph_agg",
        import_id,
        int(zoom_level),
        int(aggregation_mode),
        aggregation_threshold,
        center_node_id or "none",
        package_type or "all",
        max_nodes,
        expand_aggregate or "none",
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Get base graph
    if expand_aggregate:
        # Expanding an aggregate - get detailed view of its nodes
        result = _get_expanded_aggregate_graph(
            import_id, expand_aggregate, max_nodes
        )
    else:
        result = get_semantic_graph(
            import_id, zoom_level, center_node_id, package_type, max_nodes
        )

    # Apply aggregation based on zoom level
    if aggregation_mode != AggregationMode.NONE and zoom_level != ZoomLevel.CLUSTER:
        # At cluster level, clusters already serve as aggregation
        # At overview and detailed levels, apply node aggregation
        result = apply_aggregation(result, aggregation_mode, aggregation_threshold)

    # Cache for 2 minutes
    cache.set(cache_key, result, ttl=120)
    return result


def _get_expanded_aggregate_graph(
    import_id: int,
    aggregate_id: str,
    max_nodes: int = 100,
) -> SemanticGraphData:
    """Get a graph showing the expanded contents of an aggregate.

    When a user clicks on an aggregate node, this function fetches
    the individual nodes that were collapsed into it.

    Args:
        import_id: The import to query
        aggregate_id: The aggregate ID to expand (e.g., "agg_python3_11_library")
        max_nodes: Maximum nodes to return

    Returns:
        SemanticGraphData with the expanded nodes
    """
    # Parse aggregate ID to extract prefix and type
    # Format: agg_{prefix}_{type}
    parts = aggregate_id.split('_')
    if len(parts) < 3 or parts[0] != 'agg':
        # Invalid aggregate ID, return empty graph
        return SemanticGraphData(
            zoom_level=ZoomLevel.DETAILED,
            clusters=[],
            cluster_edges=[],
            nodes=[],
            edges=[],
        )

    # Extract prefix (might contain underscores that were replaced from dots/dashes)
    # Last part is the type, everything in between is the prefix
    pkg_type = parts[-1]
    prefix = '_'.join(parts[1:-1])

    # Reconstruct possible original prefix patterns
    # We need to search for nodes matching this prefix
    with get_db() as conn:
        with conn.cursor() as cur:
            # Search for nodes that would match this aggregate
            # Convert underscores back to possible original characters
            search_prefix = prefix.replace('_', '%')

            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type,
                       depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE import_id = %s
                  AND (label LIKE %s OR label LIKE %s OR label LIKE %s)
                ORDER BY COALESCE(closure_size, 0) DESC
                LIMIT %s
                """,
                (
                    import_id,
                    f"{prefix.replace('_', '.')}%",  # e.g., python3.11-*
                    f"{prefix.replace('_', '-')}%",  # e.g., python3-11-*
                    f"{prefix}%",  # e.g., python3_11-*
                    max_nodes,
                ),
            )
            nodes = [Node(**r) for r in cur.fetchall()]
            node_ids = [n.id for n in nodes]

            if node_ids:
                cur.execute(
                    """
                    SELECT id, import_id, source_id, target_id, edge_color,
                           is_redundant, dependency_type
                    FROM edges
                    WHERE import_id = %s
                      AND source_id = ANY(%s)
                      AND target_id = ANY(%s)
                    """,
                    (import_id, node_ids, node_ids),
                )
                edges = [Edge(**r) for r in cur.fetchall()]
            else:
                edges = []

    return SemanticGraphData(
        zoom_level=ZoomLevel.DETAILED,
        clusters=[],
        cluster_edges=[],
        nodes=nodes,
        edges=edges,
    )
