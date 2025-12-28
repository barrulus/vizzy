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


def get_imports() -> list[ImportInfo]:
    """Get all imports"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, config_path, drv_path, imported_at, node_count, edge_count
                FROM imports
                ORDER BY imported_at DESC
                """
            )
            return [ImportInfo(**row) for row in cur.fetchall()]


def get_import(import_id: int) -> ImportInfo | None:
    """Get a specific import"""
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
            return ImportInfo(**row) if row else None


def get_clusters(import_id: int) -> list[ClusterInfo]:
    """Get package type clusters for overview"""
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
            return [ClusterInfo(**row) for row in cur.fetchall()]


def get_nodes_by_type(import_id: int, package_type: str, limit: int = 100) -> list[Node]:
    """Get nodes of a specific package type"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
                FROM nodes
                WHERE import_id = %s AND package_type = %s
                ORDER BY COALESCE(closure_size, 0) DESC
                LIMIT %s
                """,
                (import_id, package_type, limit)
            )
            return [Node(**row) for row in cur.fetchall()]


def get_node(node_id: int) -> Node | None:
    """Get a specific node"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
                FROM nodes
                WHERE id = %s
                """,
                (node_id,)
            )
            row = cur.fetchone()
            return Node(**row) if row else None


def get_node_by_hash(import_id: int, drv_hash: str) -> Node | None:
    """Get a node by its derivation hash"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
                FROM nodes
                WHERE import_id = %s AND drv_hash = %s
                """,
                (import_id, drv_hash)
            )
            row = cur.fetchone()
            return Node(**row) if row else None


def get_node_with_neighbors(node_id: int) -> NodeWithNeighbors | None:
    """Get a node with its dependencies and dependents"""
    node = get_node(node_id)
    if not node:
        return None

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get dependencies (what this node depends on)
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata
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
                       n.package_type, n.depth, n.closure_size, n.metadata
                FROM nodes n
                JOIN edges e ON e.target_id = n.id
                WHERE e.source_id = %s
                ORDER BY n.label
                """,
                (node_id,)
            )
            dependents = [Node(**row) for row in cur.fetchall()]

    return NodeWithNeighbors(
        node=node,
        dependencies=dependencies,
        dependents=dependents,
    )


def get_subgraph(
    import_id: int,
    node_ids: list[int] | None = None,
    package_type: str | None = None,
    max_nodes: int = 200,
) -> GraphData:
    """Get a subgraph for rendering"""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Build node query
            if node_ids:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
                    FROM nodes
                    WHERE id = ANY(%s)
                    LIMIT %s
                    """,
                    (node_ids, max_nodes)
                )
            elif package_type:
                cur.execute(
                    """
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
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
                    SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata
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
                SELECT id, import_id, source_id, target_id, edge_color, is_redundant
                FROM edges
                WHERE source_id = ANY(%s) AND target_id = ANY(%s)
                """,
                (list(node_id_set), list(node_id_set))
            )
            edges = [Edge(**row) for row in cur.fetchall()]

    return GraphData(nodes=nodes, edges=edges)


def search_nodes(import_id: int, query: str, limit: int = 20) -> list[Node]:
    """Search for nodes by name"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type, depth, closure_size, metadata,
                       similarity(label, %s) as sim
                FROM nodes
                WHERE import_id = %s AND label %% %s
                ORDER BY sim DESC
                LIMIT %s
                """,
                (query, import_id, query, limit)
            )
            return [Node(**{k: v for k, v in row.items() if k != "sim"}) for row in cur.fetchall()]


def get_root_node(import_id: int) -> Node | None:
    """Get the root node (typically the system derivation)"""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Root has most incoming edges (most things depend on it being built)
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata
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
            return Node(**row) if row else None
