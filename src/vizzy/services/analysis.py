"""Graph analysis service - duplicates, paths, loops, Sankey flows"""

import json
from dataclasses import dataclass
from vizzy.database import get_db
from vizzy.models import Node, Edge, LoopGroup, RedundantLink
from vizzy.services.cache import cache, cache_key_for_import


@dataclass
class DuplicateGroup:
    """A group of nodes with the same label but different hashes"""
    label: str
    nodes: list[Node]

    @property
    def count(self) -> int:
        return len(self.nodes)


@dataclass
class PathResult:
    """Result of path finding between two nodes"""
    source: Node
    target: Node
    path: list[Node]
    found: bool

    @property
    def length(self) -> int:
        return len(self.path) - 1 if self.path else 0


def find_duplicates(import_id: int, min_count: int = 2) -> list[DuplicateGroup]:
    """Find packages with same name but different derivation hashes.

    This identifies packages that appear multiple times in the graph,
    often due to different build contexts (build-time vs runtime, cross-compilation, etc.)
    """
    # Check cache first - duplicates don't change often
    cache_key = cache_key_for_import("duplicates", import_id, min_count)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Find labels that have multiple different hashes
            cur.execute(
                """
                WITH duplicate_labels AS (
                    SELECT label
                    FROM nodes
                    WHERE import_id = %s
                    GROUP BY label
                    HAVING COUNT(DISTINCT drv_hash) >= %s
                )
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                JOIN duplicate_labels dl ON n.label = dl.label
                WHERE n.import_id = %s
                ORDER BY n.label, n.drv_hash
                """,
                (import_id, min_count, import_id)
            )

            # Group by label
            groups: dict[str, list[Node]] = {}
            for row in cur.fetchall():
                node = Node(**row)
                if node.label not in groups:
                    groups[node.label] = []
                groups[node.label].append(node)

            result = [
                DuplicateGroup(label=label, nodes=nodes)
                for label, nodes in sorted(groups.items())
            ]

    # Cache for 10 minutes
    cache.set(cache_key, result, ttl=600)
    return result


def find_path(source_id: int, target_id: int, max_depth: int = 20) -> PathResult | None:
    """Find shortest path between two nodes using BFS via recursive CTE.

    Returns the path from source to target following dependency edges.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get source and target nodes
            cur.execute(
                "SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source FROM nodes WHERE id = %s",
                (source_id,)
            )
            source_row = cur.fetchone()
            if not source_row:
                return None
            source = Node(**source_row)

            cur.execute(
                "SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source FROM nodes WHERE id = %s",
                (target_id,)
            )
            target_row = cur.fetchone()
            if not target_row:
                return None
            target = Node(**target_row)

            # Use recursive CTE to find shortest path
            # Edge direction: source depends on target (source -> target in edges means source needs target)
            cur.execute(
                """
                WITH RECURSIVE path_search AS (
                    -- Base case: start from source
                    SELECT
                        source_id as current_node,
                        ARRAY[%s] as path,
                        1 as depth
                    FROM edges
                    WHERE target_id = %s

                    UNION ALL

                    -- Recursive case: follow edges
                    SELECT
                        e.source_id,
                        ps.path || e.target_id,
                        ps.depth + 1
                    FROM path_search ps
                    JOIN edges e ON e.target_id = ps.current_node
                    WHERE ps.depth < %s
                      AND NOT (e.source_id = ANY(ps.path))  -- Avoid cycles
                )
                SELECT path || current_node as full_path
                FROM path_search
                WHERE current_node = %s
                ORDER BY depth
                LIMIT 1
                """,
                (source_id, source_id, max_depth, target_id)
            )

            result = cur.fetchone()
            if not result:
                return PathResult(source=source, target=target, path=[], found=False)

            path_ids = result['full_path']

            # Fetch all nodes in path
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE id = ANY(%s)
                """,
                (path_ids,)
            )
            nodes_by_id = {row['id']: Node(**row) for row in cur.fetchall()}
            path_nodes = [nodes_by_id[nid] for nid in path_ids if nid in nodes_by_id]

            return PathResult(source=source, target=target, path=path_nodes, found=True)


def get_node_context(node_id: int) -> dict:
    """Get contextual information about a node - why it exists, what uses it.

    Returns dependency chain information useful for understanding the node's role.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get the node
            cur.execute(
                "SELECT id, import_id, drv_hash, drv_name, label, package_type FROM nodes WHERE id = %s",
                (node_id,)
            )
            node_row = cur.fetchone()
            if not node_row:
                return {}

            # Get what this node depends on (its inputs)
            cur.execute(
                """
                SELECT n.label, n.package_type, COUNT(*) as edge_count
                FROM edges e
                JOIN nodes n ON e.source_id = n.id
                WHERE e.target_id = %s
                GROUP BY n.label, n.package_type
                ORDER BY edge_count DESC
                LIMIT 10
                """,
                (node_id,)
            )
            dependencies = [dict(row) for row in cur.fetchall()]

            # Get what depends on this node (its consumers)
            cur.execute(
                """
                SELECT n.label, n.package_type, COUNT(*) as edge_count
                FROM edges e
                JOIN nodes n ON e.target_id = n.id
                WHERE e.source_id = %s
                GROUP BY n.label, n.package_type
                ORDER BY edge_count DESC
                LIMIT 10
                """,
                (node_id,)
            )
            dependents = [dict(row) for row in cur.fetchall()]

            # Determine likely role based on patterns
            role = "unknown"
            dep_types = {d['package_type'] for d in dependencies}

            if 'development' in dep_types or any('cargo' in d['label'] or 'rustc' in d['label'] for d in dependencies):
                role = "build-time (compiled with dev tools)"
            elif all(d['package_type'] in ('library', 'application', None) for d in dependencies):
                role = "runtime (uses runtime deps only)"

            return {
                "node": dict(node_row),
                "dependencies": dependencies,
                "dependents": dependents,
                "likely_role": role,
            }


def compare_duplicates(import_id: int, label: str) -> dict:
    """Compare two or more derivations of the same package.

    Returns detailed comparison of what's different between them.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all nodes with this label
            cur.execute(
                """
                SELECT id, drv_hash, label, package_type
                FROM nodes
                WHERE import_id = %s AND label = %s
                """,
                (import_id, label)
            )
            nodes = [dict(row) for row in cur.fetchall()]

            comparisons = []
            for node in nodes:
                node_id = node['id']

                # Get dependencies for this node
                cur.execute(
                    """
                    SELECT n.label, n.package_type
                    FROM edges e
                    JOIN nodes n ON e.source_id = n.id
                    WHERE e.target_id = %s
                    ORDER BY n.label
                    """,
                    (node_id,)
                )
                deps = [row['label'] for row in cur.fetchall()]

                # Get direct dependents (what uses this node directly)
                cur.execute(
                    """
                    SELECT n.label
                    FROM edges e
                    JOIN nodes n ON e.target_id = n.id
                    WHERE e.source_id = %s
                    ORDER BY n.label
                    LIMIT 5
                    """,
                    (node_id,)
                )
                used_by = [row['label'] for row in cur.fetchall()]

                # Trace root cause - what top-level packages ultimately require this?
                # Follow the dependency chain up to find "interesting" packages (apps, services)
                cur.execute(
                    """
                    WITH RECURSIVE dep_chain AS (
                        -- Start from direct dependents
                        SELECT
                            e.target_id as node_id,
                            n.label,
                            n.package_type,
                            1 as depth
                        FROM edges e
                        JOIN nodes n ON e.target_id = n.id
                        WHERE e.source_id = %s

                        UNION

                        -- Follow chain up
                        SELECT
                            e.target_id,
                            n.label,
                            n.package_type,
                            dc.depth + 1
                        FROM dep_chain dc
                        JOIN edges e ON e.source_id = dc.node_id
                        JOIN nodes n ON e.target_id = n.id
                        WHERE dc.depth < 5
                    )
                    SELECT DISTINCT label, package_type
                    FROM dep_chain
                    WHERE package_type IN ('application', 'service')
                      AND label NOT LIKE '%%-unwrapped'
                      AND label NOT LIKE '%%-wrapped'
                    ORDER BY label
                    LIMIT 10
                    """,
                    (node_id,)
                )
                root_causes = [row['label'] for row in cur.fetchall()]

                # Categorize dependencies
                build_deps = [d for d in deps if any(x in d for x in ['cargo', 'rustc', 'gcc', 'clang', 'hook', 'wrapper', 'stdenv'])]
                runtime_deps = [d for d in deps if d not in build_deps]

                comparisons.append({
                    "node_id": node_id,
                    "hash": node['drv_hash'][:12] + "...",
                    "build_deps": build_deps,
                    "runtime_deps": runtime_deps[:10],  # Limit for display
                    "used_by": used_by,
                    "root_causes": root_causes,
                    "is_build_time": len(build_deps) > len(runtime_deps) / 2,
                })

            return {
                "label": label,
                "count": len(nodes),
                "variants": comparisons,
            }


def build_sankey_data(import_id: int, label: str, max_deps_per_variant: int = 10) -> dict:
    """Build Sankey diagram data showing DIRECT dependents → variants.

    Shows only direct relationships to avoid misleading aggregated paths.

    Returns Plotly-compatible Sankey data structure.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants of this package
            cur.execute(
                """
                SELECT id, drv_hash, label
                FROM nodes
                WHERE import_id = %s AND label = %s
                """,
                (import_id, label)
            )
            variants = [dict(row) for row in cur.fetchall()]

            if not variants:
                return {"nodes": [], "links": []}

            all_nodes = {}  # label -> {name, layer}
            all_links = []  # {source, target, value}
            variant_hashes = {v['drv_hash'] for v in variants}

            # Add variant nodes (right side)
            for v in variants:
                short_hash = v['drv_hash'][:8]
                node_label = f"{label} ({short_hash})"
                all_nodes[node_label] = {
                    "name": node_label,
                    "layer": "variant",
                    "node_id": v['id'],
                    "drv_hash": v['drv_hash'],
                }

            for v in variants:
                variant_id = v['id']
                short_hash = v['drv_hash'][:8]
                variant_label = f"{label} ({short_hash})"

                # Get DIRECT dependents only (what directly uses this variant)
                cur.execute(
                    """
                    SELECT n.label, n.drv_hash, COUNT(*) as link_count
                    FROM edges e
                    JOIN nodes n ON e.target_id = n.id
                    WHERE e.source_id = %s
                    GROUP BY n.label, n.drv_hash
                    ORDER BY link_count DESC
                    LIMIT %s
                    """,
                    (variant_id, max_deps_per_variant)
                )

                direct_deps = cur.fetchall()

                for row in direct_deps:
                    dep_label = row['label']
                    dep_hash = row['drv_hash']
                    link_count = row['link_count']

                    # Check if this dependent is another variant of the same package
                    if dep_hash in variant_hashes:
                        # It's another variant - use the variant label format
                        dep_display = f"{label} ({dep_hash[:8]})"
                    else:
                        dep_display = dep_label

                    if dep_display not in all_nodes:
                        all_nodes[dep_display] = {
                            "name": dep_display,
                            "layer": "dependent",
                        }

                    all_links.append({
                        "source": variant_label,
                        "target": dep_display,
                        "value": link_count,
                    })

            # Convert to Plotly format
            node_list = list(all_nodes.keys())
            node_indices = {name: i for i, name in enumerate(node_list)}

            # Assign colors by layer
            colors = []
            for name in node_list:
                layer = all_nodes[name].get("layer", "")
                if layer == "variant":
                    colors.append("#10b981")  # green - variants (left side)
                else:
                    colors.append("#3b82f6")  # blue - dependents (right side)

            # Deduplicate and aggregate links
            link_map = {}
            for link in all_links:
                key = (link["source"], link["target"])
                if key not in link_map:
                    link_map[key] = 0
                link_map[key] += link["value"]

            links_source = []
            links_target = []
            links_value = []
            for (src, tgt), val in link_map.items():
                if src in node_indices and tgt in node_indices:
                    links_source.append(node_indices[src])
                    links_target.append(node_indices[tgt])
                    links_value.append(val)

            return {
                "nodes": {
                    "label": node_list,
                    "color": colors,
                },
                "links": {
                    "source": links_source,
                    "target": links_target,
                    "value": links_value,
                },
                "variant_count": len(variants),
                "package_label": label,
            }


def find_loops(import_id: int) -> list[LoopGroup]:
    """Find all strongly connected components (cycles) in the dependency graph.

    Uses Tarjan's algorithm implemented in Python since PostgreSQL lacks native SCC support.
    A cycle indicates circular dependencies, which are unusual in Nix but possible with overrides.

    Returns list of LoopGroup objects, each containing the nodes involved in a cycle.
    """
    # Check cache first - loop detection is expensive and results don't change
    cache_key = cache_key_for_import("loops", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Fetch all nodes and edges for this import
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes WHERE import_id = %s
                """,
                (import_id,)
            )
            nodes_by_id = {row['id']: Node(**row) for row in cur.fetchall()}

            cur.execute(
                """
                SELECT source_id, target_id FROM edges WHERE import_id = %s
                """,
                (import_id,)
            )
            edges = [(row['source_id'], row['target_id']) for row in cur.fetchall()]

            # Build adjacency list (source depends on target, so source -> target)
            adjacency: dict[int, list[int]] = {node_id: [] for node_id in nodes_by_id}
            for source_id, target_id in edges:
                if source_id in adjacency and target_id in nodes_by_id:
                    adjacency[source_id].append(target_id)

            # Tarjan's SCC algorithm
            index_counter = [0]
            stack: list[int] = []
            lowlinks: dict[int, int] = {}
            index: dict[int, int] = {}
            on_stack: dict[int, bool] = {}
            sccs: list[list[int]] = []

            def strongconnect(node: int):
                index[node] = index_counter[0]
                lowlinks[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack[node] = True

                for successor in adjacency.get(node, []):
                    if successor not in index:
                        strongconnect(successor)
                        lowlinks[node] = min(lowlinks[node], lowlinks[successor])
                    elif on_stack.get(successor, False):
                        lowlinks[node] = min(lowlinks[node], index[successor])

                # If node is a root node, pop the stack and generate an SCC
                if lowlinks[node] == index[node]:
                    scc = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        scc.append(w)
                        if w == node:
                            break
                    # Only keep SCCs with more than one node (actual cycles)
                    if len(scc) > 1:
                        sccs.append(scc)

            # Run Tarjan's from each unvisited node
            for node_id in nodes_by_id:
                if node_id not in index:
                    strongconnect(node_id)

            # Build LoopGroup objects
            loop_groups = []
            for scc in sccs:
                scc_nodes = [nodes_by_id[nid] for nid in scc if nid in nodes_by_id]
                if scc_nodes:
                    # Find a simple cycle path within this SCC
                    cycle_path = _find_cycle_in_scc(scc, adjacency)
                    loop_groups.append(LoopGroup(nodes=scc_nodes, cycle_path=cycle_path))

    # Cache for 30 minutes - loop detection is expensive and data doesn't change
    cache.set(cache_key, loop_groups, ttl=1800)
    return loop_groups


def _find_cycle_in_scc(scc_nodes: list[int], adjacency: dict[int, list[int]]) -> list[int]:
    """Find a simple cycle path within an SCC using DFS."""
    scc_set = set(scc_nodes)
    if not scc_nodes:
        return []

    # Start from first node and find a path back to it
    start = scc_nodes[0]
    visited: set[int] = set()
    path: list[int] = []

    def dfs(node: int, target: int) -> bool:
        if node == target and path:
            return True
        if node in visited:
            return False

        visited.add(node)
        path.append(node)

        for neighbor in adjacency.get(node, []):
            if neighbor in scc_set:
                if neighbor == target and len(path) > 1:
                    path.append(neighbor)
                    return True
                if neighbor not in visited:
                    if dfs(neighbor, target):
                        return True

        path.pop()
        return False

    # Try to find cycle starting and ending at start
    for neighbor in adjacency.get(start, []):
        if neighbor in scc_set:
            visited = {start}
            path = [start]
            if dfs(neighbor, start):
                return path

    return scc_nodes  # Fallback to just returning the SCC nodes


def find_redundant_links(import_id: int, max_check: int = 1000) -> list[RedundantLink]:
    """Find edges that are redundant due to transitive dependencies.

    An edge A -> C is redundant if there exists a path A -> B -> ... -> C
    (i.e., the edge can be removed without changing the transitive closure).

    This implements transitive reduction detection for dependency graphs.

    Args:
        import_id: The import to analyze
        max_check: Maximum number of edges to check (for performance)

    Returns:
        List of RedundantLink objects with bypass path information
    """
    # Check cache first - redundant link detection is expensive
    cache_key = cache_key_for_import("redundant_links", import_id, max_check)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all edges for this import (limited for performance)
            cur.execute(
                """
                SELECT e.id, e.import_id, e.source_id, e.target_id, e.edge_color, e.is_redundant, e.dependency_type
                FROM edges e
                WHERE e.import_id = %s
                LIMIT %s
                """,
                (import_id, max_check)
            )
            edges = [Edge(**row) for row in cur.fetchall()]

            redundant_links = []

            for edge in edges:
                # Check if there's an alternative path from source to target
                # that doesn't use this direct edge (length >= 2)
                cur.execute(
                    """
                    WITH RECURSIVE alternative_path AS (
                        -- Start from source's other targets (not the direct edge target)
                        SELECT
                            e.target_id as current_node,
                            ARRAY[%s, e.target_id] as path,
                            1 as depth
                        FROM edges e
                        WHERE e.source_id = %s
                          AND e.target_id != %s

                        UNION ALL

                        -- Follow edges
                        SELECT
                            e.target_id,
                            ap.path || e.target_id,
                            ap.depth + 1
                        FROM alternative_path ap
                        JOIN edges e ON e.source_id = ap.current_node
                        WHERE ap.depth < 5
                          AND NOT (e.target_id = ANY(ap.path))
                    )
                    SELECT path
                    FROM alternative_path
                    WHERE current_node = %s
                    ORDER BY depth
                    LIMIT 1
                    """,
                    (edge.source_id, edge.source_id, edge.target_id, edge.target_id)
                )

                result = cur.fetchone()
                if result:
                    bypass_path_ids = result['path']

                    # Fetch the nodes for the bypass path
                    cur.execute(
                        """
                        SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                        FROM nodes WHERE id = ANY(%s)
                        """,
                        (bypass_path_ids,)
                    )
                    nodes_by_id = {row['id']: Node(**row) for row in cur.fetchall()}
                    bypass_nodes = [nodes_by_id[nid] for nid in bypass_path_ids if nid in nodes_by_id]

                    # Get source and target nodes
                    source_node = nodes_by_id.get(edge.source_id)
                    target_node = nodes_by_id.get(edge.target_id)

                    if source_node and target_node and bypass_nodes:
                        redundant_links.append(RedundantLink(
                            edge=edge,
                            source_node=source_node,
                            target_node=target_node,
                            bypass_path=bypass_nodes
                        ))

    # Cache for 10 minutes - this prevents N+1 queries on repeated calls
    cache.set(cache_key, redundant_links, ttl=600)
    return redundant_links


def mark_redundant_edges(import_id: int) -> int:
    """Mark all redundant edges in the database.

    This updates the is_redundant flag on edges table.

    Returns the count of edges marked as redundant.
    """
    redundant = find_redundant_links(import_id, max_check=10000)

    if not redundant:
        return 0

    with get_db() as conn:
        with conn.cursor() as cur:
            edge_ids = [r.edge.id for r in redundant]
            cur.execute(
                """
                UPDATE edges SET is_redundant = TRUE
                WHERE id = ANY(%s)
                """,
                (edge_ids,)
            )
            conn.commit()

    return len(redundant)


def build_sankey_data_from_why_chain(
    import_id: int,
    label: str,
    max_depth: int = 10,
    max_top_level: int = 20,
    max_intermediate: int = 10,
    filter_app: str | None = None,
) -> dict:
    """Build Sankey diagram data showing flow FROM top-level apps TO package variants.

    This is the CORRECT flow direction for answering "why do these variants exist?"
    The flow shows: Top-level apps (left) -> Intermediate deps -> Target variants (right)

    Uses the Why Chain path aggregation (8E-003) to group paths by intermediate nodes.

    Args:
        import_id: The import to analyze
        label: The package label to show variants for (e.g., "openssl")
        max_depth: Maximum path depth to search
        max_top_level: Maximum top-level packages to show per variant
        max_intermediate: Maximum intermediate nodes to show
        filter_app: Optional top-level application label to filter by (e.g., "firefox").
            When specified, only shows paths from this specific application to the variants.

    Returns:
        Plotly-compatible Sankey data structure with correct flow direction.
        When filter_app is set, includes additional metadata about the filtered view.
    """
    from vizzy.models import WhyChainQuery, DependencyDirection
    from vizzy.services import why_chain as why_chain_service

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants of this package
            cur.execute(
                """
                SELECT id, drv_hash, label, package_type, closure_size
                FROM nodes
                WHERE import_id = %s AND label = %s
                ORDER BY closure_size DESC NULLS LAST
                """,
                (import_id, label)
            )
            variants = [dict(row) for row in cur.fetchall()]

            if not variants:
                return {"nodes": {"label": [], "color": []}, "links": {"source": [], "target": [], "value": []}}

    # Collect all nodes and links for the Sankey
    all_nodes = {}  # label -> {name, layer, node_id?, drv_hash?}
    all_links = []  # {source_label, target_label, value}

    # For each variant, compute why-chain and extract flow data
    for variant in variants:
        variant_id = variant['id']
        short_hash = variant['drv_hash'][:8]
        variant_label = f"{label} ({short_hash})"

        # Add variant as a node (right side)
        all_nodes[variant_label] = {
            "name": variant_label,
            "layer": "variant",
            "node_id": variant_id,
            "drv_hash": variant['drv_hash'],
        }

        # Build WhyChain query for this variant
        query = WhyChainQuery(
            target_node_id=variant_id,
            import_id=import_id,
            direction=DependencyDirection.REVERSE,
            max_depth=max_depth,
            max_paths=100,
            include_build_deps=True,
        )

        # Compute reverse paths
        paths = why_chain_service.compute_reverse_paths(variant_id, query)

        if not paths:
            continue

        # Aggregate paths by "via" node (intermediate node closest to variant)
        groups = why_chain_service.aggregate_paths(paths, max_groups=max_intermediate)

        for group in groups:
            via_node = group.via_node
            via_label = via_node.label

            # Check if via_node is actually the target itself (direct dependency)
            is_direct = len(group.shortest_path) == 2

            # Filter top-level packages if filter_app is specified
            top_level_packages = group.top_level_packages[:max_top_level]
            if filter_app:
                top_level_packages = [
                    pkg for pkg in top_level_packages
                    if pkg.label == filter_app
                ]
                # Skip this group if no matching top-level packages
                if not top_level_packages:
                    continue

            if is_direct:
                # Direct dependencies: top-level packages connect directly to variant
                for top_level_node in top_level_packages:
                    tl_label = top_level_node.label

                    # Add top-level as node (left side)
                    if tl_label not in all_nodes:
                        all_nodes[tl_label] = {
                            "name": tl_label,
                            "layer": "top_level",
                            "node_id": top_level_node.id,
                        }

                    # Direct link: top-level -> variant
                    all_links.append({
                        "source_label": tl_label,
                        "target_label": variant_label,
                        "value": 1,
                    })
            else:
                # Indirect dependencies through via_node
                # Add via node as intermediate (middle layer)
                if via_label not in all_nodes:
                    all_nodes[via_label] = {
                        "name": via_label,
                        "layer": "intermediate",
                        "node_id": via_node.id,
                    }

                # Link: via -> variant (value is filtered count if filtering)
                filtered_count = len(top_level_packages) if filter_app else group.total_dependents
                all_links.append({
                    "source_label": via_label,
                    "target_label": variant_label,
                    "value": filtered_count,
                })

                # Add top-level packages that go through this via node
                for top_level_node in top_level_packages:
                    tl_label = top_level_node.label

                    # Add top-level as node (left side)
                    if tl_label not in all_nodes:
                        all_nodes[tl_label] = {
                            "name": tl_label,
                            "layer": "top_level",
                            "node_id": top_level_node.id,
                        }

                    # Link: top-level -> via
                    all_links.append({
                        "source_label": tl_label,
                        "target_label": via_label,
                        "value": 1,
                    })

    # Convert to Plotly format
    # Sort nodes by layer: top_level first, intermediate next, variants last
    layer_order = {"top_level": 0, "intermediate": 1, "variant": 2}
    sorted_nodes = sorted(
        all_nodes.items(),
        key=lambda x: (layer_order.get(x[1].get("layer", ""), 3), x[0])
    )

    node_list = [name for name, _ in sorted_nodes]
    node_indices = {name: i for i, name in enumerate(node_list)}

    # Assign colors by layer
    colors = []
    for name, info in sorted_nodes:
        layer = info.get("layer", "")
        if layer == "top_level":
            colors.append("#3b82f6")  # blue - top-level apps (left)
        elif layer == "intermediate":
            colors.append("#f59e0b")  # amber - intermediate deps (middle)
        else:  # variant
            colors.append("#10b981")  # green - package variants (right)

    # Deduplicate and aggregate links
    link_map = {}
    for link in all_links:
        key = (link["source_label"], link["target_label"])
        if key not in link_map:
            link_map[key] = 0
        link_map[key] += link["value"]

    links_source = []
    links_target = []
    links_value = []
    for (src_label, tgt_label), val in link_map.items():
        if src_label in node_indices and tgt_label in node_indices:
            links_source.append(node_indices[src_label])
            links_target.append(node_indices[tgt_label])
            links_value.append(val)

    # Count summary stats
    top_level_count = sum(1 for _, info in sorted_nodes if info.get("layer") == "top_level")
    intermediate_count = sum(1 for _, info in sorted_nodes if info.get("layer") == "intermediate")

    result = {
        "nodes": {
            "label": node_list,
            "color": colors,
        },
        "links": {
            "source": links_source,
            "target": links_target,
            "value": links_value,
        },
        "variant_count": len(variants),
        "package_label": label,
        "top_level_count": top_level_count,
        "intermediate_count": intermediate_count,
        "flow_direction": "top_level_to_variant",  # Indicates correct flow direction
        "filter_app": filter_app,  # The application filter applied (None if unfiltered)
        "is_filtered": filter_app is not None,
    }

    return result


def get_top_level_apps_for_package(import_id: int, label: str, max_apps: int = 50) -> list[dict]:
    """Get list of top-level applications that depend on a specific package.

    This is used to populate the application filter dropdown in the Sankey view.
    It queries the Why Chain paths to find which top-level packages ultimately
    depend on any variant of the specified package.

    Args:
        import_id: The import to analyze
        label: The package label to find dependents for (e.g., "openssl")
        max_apps: Maximum number of applications to return

    Returns:
        List of dicts with 'label', 'node_id', and 'closure_size' for each top-level app
    """
    # Check cache first
    cache_key = cache_key_for_import("top_level_apps_for_package", import_id, label, max_apps)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from vizzy.models import WhyChainQuery, DependencyDirection
    from vizzy.services import why_chain as why_chain_service

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants of this package
            cur.execute(
                """
                SELECT id, drv_hash, label
                FROM nodes
                WHERE import_id = %s AND label = %s
                """,
                (import_id, label)
            )
            variants = [dict(row) for row in cur.fetchall()]

            if not variants:
                return []

    # Collect all unique top-level apps across all variants
    top_level_apps = {}  # label -> {node_id, closure_size}

    for variant in variants:
        variant_id = variant['id']

        # Build WhyChain query for this variant
        query = WhyChainQuery(
            target_node_id=variant_id,
            import_id=import_id,
            direction=DependencyDirection.REVERSE,
            max_depth=10,
            max_paths=100,
            include_build_deps=True,
        )

        # Compute reverse paths
        paths = why_chain_service.compute_reverse_paths(variant_id, query)
        if not paths:
            continue

        # Aggregate paths to get top-level packages
        groups = why_chain_service.aggregate_paths(paths, max_groups=20)

        for group in groups:
            for top_level_node in group.top_level_packages:
                if top_level_node.label not in top_level_apps:
                    top_level_apps[top_level_node.label] = {
                        "label": top_level_node.label,
                        "node_id": top_level_node.id,
                        "closure_size": top_level_node.closure_size or 0,
                    }

    # Sort by closure size (largest first) and limit
    result = sorted(
        top_level_apps.values(),
        key=lambda x: x["closure_size"],
        reverse=True
    )[:max_apps]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_cached_analysis(import_id: int, analysis_type: str) -> dict | None:
    """Get cached analysis result if available."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result FROM analysis
                WHERE import_id = %s AND analysis_type = %s
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                (import_id, analysis_type)
            )
            row = cur.fetchone()
            return row['result'] if row else None


def cache_analysis(import_id: int, analysis_type: str, result: dict) -> None:
    """Cache an analysis result."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis (import_id, analysis_type, result)
                VALUES (%s, %s, %s)
                """,
                (import_id, analysis_type, json.dumps(result))
            )
            conn.commit()
