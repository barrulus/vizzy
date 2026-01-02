"""Treemap data aggregation service for Closure Treemap visualization.

This module provides the backend logic for generating hierarchical data
suitable for D3.js treemap visualization. It answers the question:
"Which packages contribute most to my system's closure size?"

The service supports multiple hierarchy modes:
- application: Top-level apps as root, deps as children
- type: Package type as root, packages as children
- depth: Dependency depth as root
- flat: No hierarchy, all packages at same level

Performance considerations:
- Limits children per parent (default 20)
- Aggregates small nodes into "other" groups
- Caches results for 5 minutes
- Limits recursive depth in queries
"""

from dataclasses import dataclass, field
from typing import Any

from vizzy.database import get_db
from vizzy.services.cache import cache, cache_key_for_import


@dataclass
class TreemapNode:
    """A node in the treemap hierarchy.

    This structure is directly serializable to the JSON format
    expected by D3.js treemap layout.
    """
    name: str
    node_id: int | None = None
    value: int = 0  # Closure size or aggregated value
    package_type: str | None = None
    unique_contribution: int | None = None
    children: list["TreemapNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "node_id": self.node_id,
            "package_type": self.package_type,
        }

        if self.unique_contribution is not None:
            result["unique_contribution"] = self.unique_contribution

        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        else:
            # Leaf nodes need a value for D3 treemap
            result["value"] = self.value if self.value > 0 else 1

        return result


# Configuration constants
MAX_CHILDREN_PER_PARENT = 20
MIN_VALUE_PERCENTAGE = 1.0  # Minimum % of parent's value to show separately
MAX_TOTAL_NODES = 500
DEFAULT_MAX_DEPTH = 3


def build_treemap_data(
    import_id: int,
    mode: str = "application",
    filter_type: str = "all",
    root_node_id: int | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    limit: int = MAX_CHILDREN_PER_PARENT,
) -> dict[str, Any]:
    """Build hierarchical data for D3.js treemap.

    Args:
        import_id: The import to visualize
        mode: Hierarchy mode - "application", "type", "depth", or "flat"
        filter_type: Filter by dependency type - "all", "runtime", "build", or "type:X"
        root_node_id: If set, build treemap rooted at this node (for zoom)
        max_depth: Maximum hierarchy depth to return
        limit: Maximum children per parent node

    Returns:
        Dictionary in D3.js treemap-compatible format with nested children
    """
    # Build cache key
    cache_key = cache_key_for_import(
        "treemap", import_id, mode, filter_type,
        root_node_id or "root", max_depth, limit
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Build treemap based on mode
    if root_node_id:
        result = _build_from_node(import_id, root_node_id, max_depth, limit, filter_type)
    elif mode == "application":
        result = _build_by_application(import_id, max_depth, limit, filter_type)
    elif mode == "type":
        result = _build_by_type(import_id, limit, filter_type)
    elif mode == "depth":
        result = _build_by_depth(import_id, max_depth, limit, filter_type)
    else:  # flat
        result = _build_flat(import_id, limit, filter_type)

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def _get_dependency_type_filter(filter_type: str) -> str | None:
    """Convert filter_type to SQL WHERE clause fragment.

    Args:
        filter_type: Filter string like "all", "runtime", "build", or "type:library"

    Returns:
        SQL fragment for WHERE clause, or None if no filter
    """
    if filter_type == "runtime":
        return "e.dependency_type = 'runtime'"
    elif filter_type == "build":
        return "e.dependency_type = 'build'"
    elif filter_type.startswith("type:"):
        # Package type filter - applied to nodes, not edges
        return None
    return None


def _get_package_type_filter(filter_type: str) -> str | None:
    """Get package type filter if applicable.

    Args:
        filter_type: Filter string

    Returns:
        Package type to filter on, or None
    """
    if filter_type.startswith("type:"):
        return filter_type[5:]  # Remove "type:" prefix
    return None


def _build_by_application(
    import_id: int,
    max_depth: int,
    limit: int,
    filter_type: str,
) -> dict[str, Any]:
    """Build treemap with top-level applications as root nodes.

    Hierarchy: System > Applications > Direct Deps > Transitive Deps
    """
    pkg_type_filter = _get_package_type_filter(filter_type)

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get total closure size for the system
            cur.execute(
                "SELECT COUNT(*) as total FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()['total'] or 0

            # Get top-level packages (user-facing applications)
            pkg_filter_sql = ""
            if pkg_type_filter:
                pkg_filter_sql = f"AND package_type = '{pkg_type_filter}'"

            cur.execute(
                f"""
                SELECT id, label, package_type, closure_size, unique_contribution
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                {pkg_filter_sql}
                ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                LIMIT %s
                """,
                (import_id, limit)
            )
            top_level = cur.fetchall()

            # Build children for each top-level package
            children = []
            for tl in top_level:
                node = TreemapNode(
                    name=tl['label'],
                    node_id=tl['id'],
                    value=tl['closure_size'] or 1,
                    package_type=tl['package_type'],
                    unique_contribution=tl['unique_contribution'],
                )

                # Get direct dependencies if max_depth > 1
                if max_depth > 1:
                    node.children = _get_node_children(
                        cur, tl['id'], max_depth - 1, limit, filter_type
                    )

                children.append(node)

            # Aggregate remaining into "other" if we hit the limit
            if len(top_level) >= limit:
                cur.execute(
                    f"""
                    SELECT COUNT(*) as remaining_count,
                           COALESCE(SUM(closure_size), 0) as remaining_size
                    FROM nodes
                    WHERE import_id = %s
                      AND is_top_level = TRUE
                      AND id NOT IN (SELECT id FROM nodes
                                     WHERE import_id = %s AND is_top_level = TRUE
                                     {pkg_filter_sql}
                                     ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                                     LIMIT %s)
                    """,
                    (import_id, import_id, limit)
                )
                remaining = cur.fetchone()
                if remaining and remaining['remaining_count'] > 0:
                    children.append(TreemapNode(
                        name=f"{remaining['remaining_count']} others",
                        node_id=None,
                        value=remaining['remaining_size'] or 1,
                        package_type="aggregated",
                    ))

    root = TreemapNode(
        name="System",
        node_id=None,
        value=total_nodes,
        children=children,
    )

    return root.to_dict()


def _get_node_children(
    cur,
    node_id: int,
    remaining_depth: int,
    limit: int,
    filter_type: str,
) -> list[TreemapNode]:
    """Recursively get children for a node.

    Args:
        cur: Database cursor
        node_id: Parent node ID
        remaining_depth: How many more levels to traverse
        limit: Maximum children per level
        filter_type: Dependency filter type

    Returns:
        List of TreemapNode children
    """
    if remaining_depth <= 0:
        return []

    dep_filter = _get_dependency_type_filter(filter_type)
    pkg_type_filter = _get_package_type_filter(filter_type)

    filter_clauses = []
    if dep_filter:
        filter_clauses.append(dep_filter)
    if pkg_type_filter:
        filter_clauses.append(f"n.package_type = '{pkg_type_filter}'")

    where_clause = f"AND {' AND '.join(filter_clauses)}" if filter_clauses else ""

    cur.execute(
        f"""
        SELECT n.id, n.label, n.package_type, n.closure_size, n.unique_contribution
        FROM edges e
        JOIN nodes n ON e.source_id = n.id
        WHERE e.target_id = %s
        {where_clause}
        ORDER BY COALESCE(n.closure_size, 0) DESC NULLS LAST
        LIMIT %s
        """,
        (node_id, limit)
    )
    deps = cur.fetchall()

    children = []
    for dep in deps:
        child = TreemapNode(
            name=dep['label'],
            node_id=dep['id'],
            value=dep['closure_size'] or 1,
            package_type=dep['package_type'],
            unique_contribution=dep['unique_contribution'],
        )

        # Recursively get grandchildren
        if remaining_depth > 1:
            child.children = _get_node_children(
                cur, dep['id'], remaining_depth - 1, limit // 2, filter_type
            )

        children.append(child)

    return children


def _build_by_type(
    import_id: int,
    limit: int,
    filter_type: str,
) -> dict[str, Any]:
    """Build treemap with package types as root nodes.

    Hierarchy: System > Package Type > Packages
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get total count
            cur.execute(
                "SELECT COUNT(*) as total FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()['total'] or 0

            # Get package types with counts
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count,
                    COALESCE(SUM(closure_size), COUNT(*)) as total_size
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                ORDER BY count DESC
                """,
                (import_id,)
            )
            types = cur.fetchall()

            children = []
            for type_row in types:
                pkg_type = type_row['package_type']

                # Get top packages for this type
                cur.execute(
                    """
                    SELECT id, label, closure_size, unique_contribution
                    FROM nodes
                    WHERE import_id = %s AND COALESCE(package_type, 'unknown') = %s
                    ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (import_id, pkg_type, limit)
                )
                packages = cur.fetchall()

                pkg_children = [
                    TreemapNode(
                        name=pkg['label'],
                        node_id=pkg['id'],
                        value=pkg['closure_size'] or 1,
                        package_type=pkg_type,
                        unique_contribution=pkg['unique_contribution'],
                    )
                    for pkg in packages
                ]

                # Add "other" aggregation if needed
                if type_row['count'] > limit:
                    remaining_count = type_row['count'] - limit
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(closure_size), COUNT(*)) as remaining_size
                        FROM nodes
                        WHERE import_id = %s
                          AND COALESCE(package_type, 'unknown') = %s
                          AND id NOT IN (
                              SELECT id FROM nodes
                              WHERE import_id = %s AND COALESCE(package_type, 'unknown') = %s
                              ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                              LIMIT %s
                          )
                        """,
                        (import_id, pkg_type, import_id, pkg_type, limit)
                    )
                    remaining = cur.fetchone()
                    if remaining:
                        pkg_children.append(TreemapNode(
                            name=f"{remaining_count} others",
                            node_id=None,
                            value=remaining['remaining_size'] or 1,
                            package_type="aggregated",
                        ))

                children.append(TreemapNode(
                    name=pkg_type,
                    node_id=None,
                    value=type_row['total_size'] or type_row['count'],
                    package_type=pkg_type,
                    children=pkg_children,
                ))

    root = TreemapNode(
        name="System",
        node_id=None,
        value=total_nodes,
        children=children,
    )

    return root.to_dict()


def _build_by_depth(
    import_id: int,
    max_depth: int,
    limit: int,
    filter_type: str,
) -> dict[str, Any]:
    """Build treemap with dependency depth as root nodes.

    Hierarchy: System > Depth Level > Packages
    """
    pkg_type_filter = _get_package_type_filter(filter_type)
    pkg_filter_sql = f"AND package_type = '{pkg_type_filter}'" if pkg_type_filter else ""

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get total count
            cur.execute(
                "SELECT COUNT(*) as total FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()['total'] or 0

            # Get depth distribution
            cur.execute(
                f"""
                SELECT
                    COALESCE(depth, 0) as depth_level,
                    COUNT(*) as count,
                    COALESCE(SUM(closure_size), COUNT(*)) as total_size
                FROM nodes
                WHERE import_id = %s
                {pkg_filter_sql}
                GROUP BY depth
                ORDER BY depth NULLS FIRST
                LIMIT %s
                """,
                (import_id, max_depth)
            )
            depths = cur.fetchall()

            children = []
            for depth_row in depths:
                depth_level = depth_row['depth_level'] or 0

                # Get top packages at this depth
                cur.execute(
                    f"""
                    SELECT id, label, package_type, closure_size, unique_contribution
                    FROM nodes
                    WHERE import_id = %s AND COALESCE(depth, 0) = %s
                    {pkg_filter_sql}
                    ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (import_id, depth_level, limit)
                )
                packages = cur.fetchall()

                pkg_children = [
                    TreemapNode(
                        name=pkg['label'],
                        node_id=pkg['id'],
                        value=pkg['closure_size'] or 1,
                        package_type=pkg['package_type'],
                        unique_contribution=pkg['unique_contribution'],
                    )
                    for pkg in packages
                ]

                children.append(TreemapNode(
                    name=f"Depth {depth_level}",
                    node_id=None,
                    value=depth_row['total_size'] or depth_row['count'],
                    package_type=None,
                    children=pkg_children,
                ))

    root = TreemapNode(
        name="System",
        node_id=None,
        value=total_nodes,
        children=children,
    )

    return root.to_dict()


def _build_flat(
    import_id: int,
    limit: int,
    filter_type: str,
) -> dict[str, Any]:
    """Build flat treemap with no hierarchy.

    All packages at the same level, sized by closure_size.
    """
    pkg_type_filter = _get_package_type_filter(filter_type)
    pkg_filter_sql = f"AND package_type = '{pkg_type_filter}'" if pkg_type_filter else ""

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get total count
            cur.execute(
                "SELECT COUNT(*) as total FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()['total'] or 0

            # Get top packages by closure size
            cur.execute(
                f"""
                SELECT id, label, package_type, closure_size, unique_contribution
                FROM nodes
                WHERE import_id = %s
                {pkg_filter_sql}
                ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                LIMIT %s
                """,
                (import_id, limit)
            )
            packages = cur.fetchall()

            children = [
                TreemapNode(
                    name=pkg['label'],
                    node_id=pkg['id'],
                    value=pkg['closure_size'] or 1,
                    package_type=pkg['package_type'],
                    unique_contribution=pkg['unique_contribution'],
                )
                for pkg in packages
            ]

            # Add aggregated "other" for remaining
            if len(packages) >= limit:
                cur.execute(
                    f"""
                    SELECT COUNT(*) as remaining_count,
                           COALESCE(SUM(closure_size), COUNT(*)) as remaining_size
                    FROM nodes
                    WHERE import_id = %s
                    {pkg_filter_sql}
                    AND id NOT IN (
                        SELECT id FROM nodes
                        WHERE import_id = %s
                        {pkg_filter_sql}
                        ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                        LIMIT %s
                    )
                    """,
                    (import_id, import_id, limit)
                )
                remaining = cur.fetchone()
                if remaining and remaining['remaining_count'] > 0:
                    children.append(TreemapNode(
                        name=f"{remaining['remaining_count']} others",
                        node_id=None,
                        value=remaining['remaining_size'] or 1,
                        package_type="aggregated",
                    ))

    root = TreemapNode(
        name="System",
        node_id=None,
        value=total_nodes,
        children=children,
    )

    return root.to_dict()


def _build_from_node(
    import_id: int,
    root_node_id: int,
    max_depth: int,
    limit: int,
    filter_type: str,
) -> dict[str, Any]:
    """Build treemap rooted at a specific node (for zoom navigation).

    Args:
        import_id: The import to visualize
        root_node_id: The node to use as root
        max_depth: Maximum depth below this node
        limit: Maximum children per level
        filter_type: Dependency filter

    Returns:
        Treemap data rooted at the specified node
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get the root node info
            cur.execute(
                """
                SELECT id, label, package_type, closure_size, unique_contribution
                FROM nodes
                WHERE id = %s
                """,
                (root_node_id,)
            )
            root_info = cur.fetchone()

            if not root_info:
                return {
                    "name": "Not Found",
                    "node_id": None,
                    "value": 0,
                    "children": [],
                }

            # Get children
            children = _get_node_children(
                cur, root_node_id, max_depth, limit, filter_type
            )

            root = TreemapNode(
                name=root_info['label'],
                node_id=root_info['id'],
                value=root_info['closure_size'] or 1,
                package_type=root_info['package_type'],
                unique_contribution=root_info['unique_contribution'],
                children=children,
            )

            return root.to_dict()


def get_treemap_node_info(node_id: int) -> dict[str, Any] | None:
    """Get detailed information about a node for tooltip display.

    Args:
        node_id: The node to get info for

    Returns:
        Dictionary with node details, or None if not found
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.id,
                    n.label,
                    n.package_type,
                    n.closure_size,
                    n.unique_contribution,
                    n.shared_contribution,
                    n.is_top_level,
                    n.top_level_source,
                    (SELECT COUNT(*) FROM edges WHERE target_id = n.id) as direct_deps,
                    (SELECT COUNT(*) FROM edges WHERE source_id = n.id) as dependents
                FROM nodes n
                WHERE n.id = %s
                """,
                (node_id,)
            )
            row = cur.fetchone()

            if not row:
                return None

            return {
                "id": row['id'],
                "label": row['label'],
                "package_type": row['package_type'],
                "closure_size": row['closure_size'] or 0,
                "unique_contribution": row['unique_contribution'],
                "shared_contribution": row['shared_contribution'],
                "is_top_level": row['is_top_level'],
                "top_level_source": row['top_level_source'],
                "direct_deps": row['direct_deps'],
                "dependents": row['dependents'],
            }


def invalidate_treemap_cache(import_id: int) -> int:
    """Invalidate all treemap cache entries for an import.

    Call this when data changes that affects treemap display.

    Args:
        import_id: The import to invalidate cache for

    Returns:
        Number of cache entries invalidated
    """
    return cache.invalidate(f"import:{import_id}:treemap")
