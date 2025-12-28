"""Graph analysis service - duplicates, paths, loops, Sankey flows"""

import json
from dataclasses import dataclass
from vizzy.database import get_db
from vizzy.models import Node


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
                       n.package_type, n.depth, n.closure_size, n.metadata
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

            return [
                DuplicateGroup(label=label, nodes=nodes)
                for label, nodes in sorted(groups.items())
            ]


def find_path(source_id: int, target_id: int, max_depth: int = 20) -> PathResult | None:
    """Find shortest path between two nodes using BFS via recursive CTE.

    Returns the path from source to target following dependency edges.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get source and target nodes
            cur.execute(
                "SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata FROM nodes WHERE id = %s",
                (source_id,)
            )
            source_row = cur.fetchone()
            if not source_row:
                return None
            source = Node(**source_row)

            cur.execute(
                "SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata FROM nodes WHERE id = %s",
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
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
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
