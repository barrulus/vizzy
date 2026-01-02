"""Graph query service"""

from vizzy.database import get_db
from vizzy.models import (
    Node,
    Edge,
    GraphData,
    NodeWithNeighbors,
    ClusterInfo,
    ImportInfo,
)
from vizzy.services.cache import cache, cache_key_for_import


def get_imports() -> list[ImportInfo]:
    """Get all imports"""
    cache_key = "imports:all"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, config_path, drv_path, imported_at, node_count, edge_count
                FROM imports
                ORDER BY imported_at DESC
                """
            )
            result = [ImportInfo(**row) for row in cur.fetchall()]

    # Cache for 60 seconds - imports list doesn't change often
    cache.set(cache_key, result, ttl=60)
    return result


def get_import(import_id: int) -> ImportInfo | None:
    """Get a specific import"""
    cache_key = cache_key_for_import("info", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, config_path, drv_path, imported_at, node_count, edge_count
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            row = cur.fetchone()
            result = ImportInfo(**row) if row else None

    if result:
        # Cache for 5 minutes
        cache.set(cache_key, result, ttl=300)
    return result


def get_clusters(import_id: int) -> list[ClusterInfo]:
    """Get package type clusters for overview"""
    # Check cache first
    cache_key = cache_key_for_import("clusters", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
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
                (import_id,)
            )
            result = [ClusterInfo(**row) for row in cur.fetchall()]

    # Cache for 5 minutes (cluster data doesn't change often)
    cache.set(cache_key, result, ttl=300)
    return result


def get_nodes_by_type(import_id: int, package_type: str, limit: int = 100) -> list[Node]:
    """Get nodes of a specific package type"""
    # Check cache first
    cache_key = cache_key_for_import("nodes_by_type", import_id, package_type, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE import_id = %s AND package_type = %s
                ORDER BY COALESCE(closure_size, 0) DESC
                LIMIT %s
                """,
                (import_id, package_type, limit)
            )
            result = [Node(**row) for row in cur.fetchall()]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_node(node_id: int) -> Node | None:
    """Get a specific node"""
    cache_key = f"node:{node_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE id = %s
                """,
                (node_id,)
            )
            row = cur.fetchone()
            result = Node(**row) if row else None

    if result:
        # Cache for 5 minutes
        cache.set(cache_key, result, ttl=300)
    return result


def get_node_by_hash(import_id: int, drv_hash: str) -> Node | None:
    """Get a node by its derivation hash"""
    cache_key = cache_key_for_import("node_hash", import_id, drv_hash)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE import_id = %s AND drv_hash = %s
                """,
                (import_id, drv_hash)
            )
            row = cur.fetchone()
            result = Node(**row) if row else None

    if result:
        cache.set(cache_key, result, ttl=300)
    return result


def get_node_with_neighbors(node_id: int) -> NodeWithNeighbors | None:
    """Get a node with its dependencies and dependents"""
    cache_key = f"node_neighbors:{node_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    node = get_node(node_id)
    if not node:
        return None

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get dependencies (what this node depends on)
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE e.target_id = %s
                ORDER BY n.label
                """,
                (node_id,)
            )
            dependencies = [Node(**row) for row in cur.fetchall()]

            # Get dependents (what depends on this node)
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                JOIN edges e ON e.target_id = n.id
                WHERE e.source_id = %s
                ORDER BY n.label
                """,
                (node_id,)
            )
            dependents = [Node(**row) for row in cur.fetchall()]

    result = NodeWithNeighbors(
        node=node,
        dependencies=dependencies,
        dependents=dependents,
    )

    # Cache for 3 minutes
    cache.set(cache_key, result, ttl=180)
    return result


def get_subgraph(
    import_id: int,
    node_ids: list[int] | None = None,
    package_type: str | None = None,
    max_nodes: int = 200,
) -> GraphData:
    """Get a subgraph for rendering"""
    # Build cache key based on parameters
    if node_ids:
        sorted_ids = sorted(node_ids)[:10]  # Use first 10 IDs for key
        ids_key = "_".join(str(i) for i in sorted_ids)
        cache_key = cache_key_for_import("subgraph", import_id, f"ids_{ids_key}", max_nodes)
    elif package_type:
        cache_key = cache_key_for_import("subgraph", import_id, f"type_{package_type}", max_nodes)
    else:
        cache_key = cache_key_for_import("subgraph", import_id, "top", max_nodes)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Build node query
            if node_ids:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE id = ANY(%s)
                    LIMIT %s
                    """,
                    (node_ids, max_nodes)
                )
            elif package_type:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND package_type = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, package_type, max_nodes)
                )
            else:
                # Get top nodes by closure size
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, max_nodes)
                )

            nodes = [Node(**row) for row in cur.fetchall()]
            node_id_set = {n.id for n in nodes}

            # Get edges between these nodes
            cur.execute(
                """
                SELECT id, import_id, source_id, target_id, edge_color, is_redundant, dependency_type
                FROM edges
                WHERE source_id = ANY(%s) AND target_id = ANY(%s)
                """,
                (list(node_id_set), list(node_id_set))
            )
            edges = [Edge(**row) for row in cur.fetchall()]

    result = GraphData(nodes=nodes, edges=edges)

    # Cache for 2 minutes
    cache.set(cache_key, result, ttl=120)
    return result


def search_nodes(import_id: int, query: str, limit: int = 20) -> list[Node]:
    """Search for nodes by name"""
    # Cache search results for a short time (1 minute) to handle rapid searches
    cache_key = cache_key_for_import("search", import_id, query, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata,
                       is_top_level, top_level_source, similarity(label, %s) as sim
                FROM nodes
                WHERE import_id = %s AND label %% %s
                ORDER BY sim DESC
                LIMIT %s
                """,
                (query, import_id, query, limit)
            )
            result = [Node(**{k: v for k, v in row.items() if k != "sim"}) for row in cur.fetchall()]

    # Cache for 1 minute (search results may need fresher data)
    cache.set(cache_key, result, ttl=60)
    return result


def get_root_node(import_id: int) -> Node | None:
    """Get the root node (typically the system derivation)"""
    cache_key = cache_key_for_import("root", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Root has most incoming edges (most things depend on it being built)
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id
                WHERE n.import_id = %s
                GROUP BY n.id
                ORDER BY COUNT(e.id) DESC
                LIMIT 1
                """,
                (import_id,)
            )
            row = cur.fetchone()
            result = Node(**row) if row else None

    if result:
        # Cache for 5 minutes
        cache.set(cache_key, result, ttl=300)
    return result


def invalidate_import_cache(import_id: int) -> int:
    """Invalidate all cached data for a specific import.

    Call this when an import is deleted or modified.
    """
    return cache.invalidate_import(import_id)


def get_top_level_nodes(
    import_id: int,
    source: str | None = None,
    limit: int = 100,
) -> list[Node]:
    """Get all top-level (user-facing) nodes for an import.

    Top-level nodes are packages explicitly requested by the user
    (e.g., in environment.systemPackages, programs.*.enable, etc.)
    rather than transitive dependencies.

    Args:
        import_id: The import to query
        source: Optional filter by top_level_source (e.g., 'systemPackages')
        limit: Maximum nodes to return

    Returns:
        List of Node objects marked as top-level
    """
    if source:
        cache_key = cache_key_for_import("top_level", import_id, source, limit)
    else:
        cache_key = cache_key_for_import("top_level", import_id, "all", limit)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            if source:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND is_top_level = TRUE AND top_level_source = %s
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, source, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type,
                           depth, closure_size, metadata, is_top_level, top_level_source
                    FROM nodes
                    WHERE import_id = %s AND is_top_level = TRUE
                    ORDER BY COALESCE(closure_size, 0) DESC
                    LIMIT %s
                    """,
                    (import_id, limit)
                )
            result = [Node(**row) for row in cur.fetchall()]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_top_level_sources(import_id: int) -> list[dict]:
    """Get summary of top-level sources for an import.

    Returns a list of sources (e.g., 'systemPackages') with counts
    of how many packages came from each source.

    Args:
        import_id: The import to query

    Returns:
        List of dicts with 'source' and 'count' keys
    """
    cache_key = cache_key_for_import("top_level_sources", import_id)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT top_level_source as source, COUNT(*) as count
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                GROUP BY top_level_source
                ORDER BY count DESC
                """,
                (import_id,)
            )
            result = [dict(row) for row in cur.fetchall()]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_top_level_count(import_id: int) -> int:
    """Get the count of top-level packages for an import.

    Args:
        import_id: The import to query

    Returns:
        Number of top-level packages
    """
    cache_key = cache_key_for_import("top_level_count", import_id)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            row = cur.fetchone()
            result = row['count'] if row else 0

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_graph_roots(import_id: int, limit: int = 50) -> list[Node]:
    """Get nodes with no incoming edges (roots of the dependency graph).

    These are packages that nothing depends on - they are entry points
    to the dependency graph. In a NixOS system, the main root is typically
    the system derivation, but there may be multiple roots.

    Note: This is different from top-level packages. Graph roots are
    topological roots (no incoming edges), while top-level packages
    are user-facing packages that may have incoming edges from
    the system derivation.

    Args:
        import_id: The import to query
        limit: Maximum nodes to return

    Returns:
        List of Node objects that have no incoming edges
    """
    cache_key = cache_key_for_import("graph_roots", import_id, limit)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id AND e.import_id = n.import_id
                WHERE n.import_id = %s
                GROUP BY n.id
                HAVING COUNT(e.id) = 0
                ORDER BY COALESCE(n.closure_size, 0) DESC
                LIMIT %s
                """,
                (import_id, limit)
            )
            result = [Node(**row) for row in cur.fetchall()]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result
