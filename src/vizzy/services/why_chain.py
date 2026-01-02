"""Why Chain service - Attribution path computation for dependency analysis.

This module implements the Why Chain feature (Phase 8E) which answers:
"Why is package X in my closure?" by finding all paths from top-level packages
to any target dependency.

Key features:
- Efficient reverse path computation using BFS with depth limiting
- Cycle detection to avoid infinite loops in circular dependencies
- Support for filtering by dependency type (build-time vs runtime)
- Caching for expensive computations
- Path aggregation for cleaner UX (implemented in 8E-003)

Performance considerations:
- Uses batch queries to minimize database round trips
- Respects max_depth and max_paths limits for large graphs
- Caches results using the analysis table
"""

import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Iterator

from vizzy.database import get_db
from vizzy.models import (
    AttributionCache,
    AttributionGroup,
    AttributionPath,
    DependencyDirection,
    EssentialityAnalysis,
    EssentialityStatus,
    Node,
    RemovalImpact,
    WhyChainQuery,
    WhyChainResult,
)
from vizzy.services.cache import cache, cache_key_for_import

logger = logging.getLogger("vizzy.why_chain")


def get_node_by_id(node_id: int) -> Node | None:
    """Fetch a single node by ID.

    Args:
        node_id: The node ID to fetch

    Returns:
        Node object or None if not found
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type,
                       depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE id = %s
                """,
                (node_id,)
            )
            row = cur.fetchone()
            return Node(**row) if row else None


def get_nodes_by_ids(node_ids: list[int]) -> dict[int, Node]:
    """Fetch multiple nodes by their IDs.

    Args:
        node_ids: List of node IDs to fetch

    Returns:
        Dictionary mapping node ID to Node object
    """
    if not node_ids:
        return {}

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, import_id, drv_hash, drv_name, label, package_type,
                       depth, closure_size, metadata, is_top_level, top_level_source
                FROM nodes
                WHERE id = ANY(%s)
                """,
                (node_ids,)
            )
            return {row['id']: Node(**row) for row in cur.fetchall()}


def get_reverse_edges(import_id: int, include_build_deps: bool = True) -> dict[int, list[tuple[int, str]]]:
    """Build reverse adjacency list: target_id -> [(source_id, dependency_type)].

    In our edge model, source depends on target (source -> target).
    For reverse path finding (target to top-level), we need:
    - Given a target node, find all nodes that depend on it (sources)
    - These sources are "dependents" of the target

    Args:
        import_id: The import to query
        include_build_deps: Whether to include build-time dependencies

    Returns:
        Dictionary mapping target_id to list of (source_id, dependency_type)
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            if include_build_deps:
                cur.execute(
                    """
                    SELECT source_id, target_id, COALESCE(dependency_type, 'unknown') as dep_type
                    FROM edges
                    WHERE import_id = %s
                    """,
                    (import_id,)
                )
            else:
                # Only include runtime dependencies
                cur.execute(
                    """
                    SELECT source_id, target_id, COALESCE(dependency_type, 'unknown') as dep_type
                    FROM edges
                    WHERE import_id = %s AND (dependency_type = 'runtime' OR dependency_type IS NULL)
                    """,
                    (import_id,)
                )

            # Build reverse adjacency: target -> list of (source, dep_type)
            reverse_adj: dict[int, list[tuple[int, str]]] = {}
            for row in cur.fetchall():
                source_id = row['source_id']
                target_id = row['target_id']
                dep_type = row['dep_type']

                if target_id not in reverse_adj:
                    reverse_adj[target_id] = []
                reverse_adj[target_id].append((source_id, dep_type))

            return reverse_adj


def get_top_level_node_ids(import_id: int) -> set[int]:
    """Get IDs of all top-level nodes for an import.

    Args:
        import_id: The import to query

    Returns:
        Set of node IDs marked as top-level
    """
    cache_key = cache_key_for_import("why_chain_top_level_ids", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            result = {row['id'] for row in cur.fetchall()}

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def compute_reverse_paths(
    node_id: int,
    query: WhyChainQuery,
) -> list[AttributionPath]:
    """Compute all paths from top-level packages to a target node.

    Uses BFS traversal going "up" the dependency graph (from target toward
    packages that depend on it) until reaching top-level packages.

    Algorithm:
    1. Start from target node
    2. BFS to find all nodes that depend on target (directly or transitively)
    3. When we reach a top-level node, record the path
    4. Avoid cycles by tracking visited nodes per path
    5. Respect max_depth and max_paths limits

    Args:
        node_id: The target node we want to explain (why is this here?)
        query: Query parameters including max_depth, max_paths, etc.

    Returns:
        List of AttributionPath objects, each representing a path from
        a top-level package down to the target
    """
    start_time = time.time()

    # Get target node
    target_node = get_node_by_id(node_id)
    if not target_node:
        logger.warning(f"Target node {node_id} not found")
        return []

    import_id = target_node.import_id

    # Build reverse adjacency list for efficient traversal
    reverse_adj = get_reverse_edges(import_id, query.include_build_deps)

    # Get set of top-level node IDs for quick lookup
    top_level_ids = get_top_level_node_ids(import_id)

    if not top_level_ids:
        logger.warning(f"No top-level nodes found for import {import_id}")
        return []

    # BFS state
    # Each queue item: (current_node_id, path_ids, dependency_types)
    # path_ids: list of node IDs from current toward target (reverse order)
    # dependency_types: types of edges traversed
    queue: deque[tuple[int, list[int], list[str]]] = deque()

    # Start with all nodes that directly depend on target
    for source_id, dep_type in reverse_adj.get(node_id, []):
        queue.append((source_id, [source_id, node_id], [dep_type]))

    # Also check if target itself is top-level (trivial path)
    if node_id in top_level_ids:
        # Target is itself a top-level package
        target_path = AttributionPath(
            path_nodes=[target_node],
            path_length=0,
            top_level_node_id=node_id,
            target_node_id=node_id,
            dependency_types=[],
            is_runtime_path=True,
        )
        return [target_path]

    # Collect paths
    paths: list[tuple[list[int], list[str]]] = []  # (path_ids, dep_types)

    while queue and len(paths) < query.max_paths:
        current_id, path_ids, dep_types = queue.popleft()

        # Check depth limit (path_ids includes current and target)
        if len(path_ids) > query.max_depth + 1:
            continue

        # Check if we've reached a top-level node
        if current_id in top_level_ids:
            # Found a complete path from top-level to target
            paths.append((path_ids, dep_types))
            continue

        # Continue BFS - find nodes that depend on current
        for source_id, dep_type in reverse_adj.get(current_id, []):
            # Avoid cycles - don't revisit nodes in current path
            if source_id not in path_ids:
                new_path = [source_id] + path_ids
                new_deps = [dep_type] + dep_types
                queue.append((source_id, new_path, new_deps))

    # Convert paths to AttributionPath objects
    # First, fetch all required nodes in one query
    all_node_ids = set()
    for path_ids, _ in paths:
        all_node_ids.update(path_ids)

    nodes_by_id = get_nodes_by_ids(list(all_node_ids))
    nodes_by_id[node_id] = target_node  # Ensure target is included

    attribution_paths: list[AttributionPath] = []
    for path_ids, dep_types in paths:
        # Build list of Node objects in order (top-level first, target last)
        path_nodes = [nodes_by_id[nid] for nid in path_ids if nid in nodes_by_id]

        if len(path_nodes) < 2:
            continue

        # Check if all dependencies are runtime
        is_runtime = all(dt in ('runtime', 'unknown') for dt in dep_types)

        attribution_paths.append(AttributionPath(
            path_nodes=path_nodes,
            path_length=len(path_nodes) - 1,
            top_level_node_id=path_ids[0],
            target_node_id=node_id,
            dependency_types=dep_types,
            is_runtime_path=is_runtime,
        ))

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        f"compute_reverse_paths: found {len(attribution_paths)} paths "
        f"for node {node_id} in {elapsed_ms:.1f}ms"
    )

    return attribution_paths


def get_direct_dependents(node_id: int, import_id: int) -> list[Node]:
    """Get nodes that directly depend on the given node.

    Args:
        node_id: The target node
        import_id: The import context

    Returns:
        List of nodes that have a direct edge to this node
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE e.target_id = %s AND n.import_id = %s
                ORDER BY n.label
                """,
                (node_id, import_id)
            )
            return [Node(**row) for row in cur.fetchall()]


def determine_essentiality(
    target: Node,
    paths: list[AttributionPath],
    import_id: int,
    include_build_deps: bool,
) -> EssentialityStatus:
    """Determine if a package is essential, removable, or build-only.

    Enhanced essentiality classification (Phase 8E-007):
    - ESSENTIAL: Required at runtime by multiple top-level packages
    - ESSENTIAL_SINGLE: Required at runtime by only one top-level package
    - ESSENTIAL_DEEP: Essential but deeply nested (avg path depth > 5)
    - REMOVABLE: Only needed by optional packages
    - BUILD_ONLY: Only required via build-time dependencies
    - ORPHAN: No top-level package depends on it at all

    Args:
        target: The target node being analyzed
        paths: Attribution paths found for this target
        import_id: The import context
        include_build_deps: Whether build deps were included in search

    Returns:
        EssentialityStatus classification
    """
    if not paths:
        return EssentialityStatus.ORPHAN

    # Separate runtime and build-only paths
    runtime_paths = [p for p in paths if p.is_runtime_path]
    build_only_paths = [p for p in paths if not p.is_runtime_path]

    # If no runtime paths, it's either build-only or orphan
    if not runtime_paths:
        if build_only_paths:
            return EssentialityStatus.BUILD_ONLY
        return EssentialityStatus.ORPHAN

    # Count unique top-level packages with runtime dependencies
    runtime_top_level_ids = {p.top_level_node_id for p in runtime_paths}
    runtime_top_level_count = len(runtime_top_level_ids)

    # Calculate average path depth for runtime paths
    if runtime_paths:
        avg_depth = sum(p.path_length for p in runtime_paths) / len(runtime_paths)
    else:
        avg_depth = 0

    # Determine granular classification
    if runtime_top_level_count == 1:
        # Only one top-level package needs this
        if avg_depth > 5:
            return EssentialityStatus.ESSENTIAL_DEEP
        return EssentialityStatus.ESSENTIAL_SINGLE
    elif runtime_top_level_count > 1:
        # Multiple top-level packages need this
        if avg_depth > 5:
            return EssentialityStatus.ESSENTIAL_DEEP
        return EssentialityStatus.ESSENTIAL
    else:
        # No runtime dependencies, only build
        return EssentialityStatus.BUILD_ONLY


def compute_removal_impact(
    target: Node,
    paths: list[AttributionPath],
    import_id: int,
) -> RemovalImpact:
    """Compute the impact of removing a package from the closure.

    Analyzes what would happen if the target package were removed:
    - Which top-level packages would break
    - How many unique dependencies would be removed
    - What the overall closure reduction would be

    Args:
        target: The target node being analyzed for removal
        paths: Attribution paths found for this target
        import_id: The import context

    Returns:
        RemovalImpact with detailed analysis
    """
    # Get all top-level packages that depend on this target
    affected_top_level_ids = {p.top_level_node_id for p in paths if p.is_runtime_path}
    affected_nodes = get_nodes_by_ids(list(affected_top_level_ids))
    affected_packages = list(affected_nodes.values())

    # Determine essentiality
    essentiality = determine_essentiality(
        target, paths, import_id, include_build_deps=True
    )

    # Calculate unique dependencies that would be removed
    # These are dependencies only reachable through this package
    unique_deps = get_unique_dependencies(target.id, import_id)

    # Calculate closure reduction
    closure_reduction = len(unique_deps) + 1  # +1 for the target itself

    # Determine if removal is safe
    removal_safe = essentiality in (
        EssentialityStatus.ORPHAN,
        EssentialityStatus.BUILD_ONLY,
        EssentialityStatus.REMOVABLE,
    )

    # Generate warning if needed
    removal_warning = None
    if not removal_safe:
        if len(affected_packages) == 1:
            removal_warning = f"Required by {affected_packages[0].label}"
        elif len(affected_packages) > 1:
            removal_warning = f"Required by {len(affected_packages)} packages"

    return RemovalImpact(
        target=target,
        essentiality=essentiality,
        affected_packages=affected_packages,
        unique_deps_removed=unique_deps,
        closure_reduction=closure_reduction,
        removal_safe=removal_safe,
        removal_warning=removal_warning,
    )


def get_unique_dependencies(node_id: int, import_id: int, limit: int = 50) -> list[Node]:
    """Get dependencies that are only reachable through this node.

    Finds packages that would be orphaned if this node were removed.

    Args:
        node_id: The node to analyze
        import_id: The import context
        limit: Maximum number of unique deps to return

    Returns:
        List of Node objects that are uniquely dependent on this node
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find all transitive dependencies of this node
            cur.execute(
                """
                WITH RECURSIVE deps AS (
                    -- Direct dependencies of the target
                    SELECT target_id as node_id, 1 as depth
                    FROM edges
                    WHERE source_id = %s AND import_id = %s

                    UNION

                    -- Transitive dependencies
                    SELECT e.target_id, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.source_id = d.node_id
                    WHERE d.depth < 20 AND e.import_id = %s
                ),
                -- Get all top-level nodes except those that depend on target
                other_top_level AS (
                    SELECT id FROM nodes
                    WHERE import_id = %s
                      AND is_top_level = TRUE
                      AND id NOT IN (
                          SELECT source_id FROM edges
                          WHERE target_id = %s AND import_id = %s
                      )
                ),
                -- Find deps reachable from other top-level packages
                other_reachable AS (
                    SELECT DISTINCT target_id as node_id
                    FROM edges
                    WHERE source_id IN (SELECT id FROM other_top_level)
                      AND import_id = %s

                    UNION

                    SELECT DISTINCT e.target_id
                    FROM other_reachable r
                    JOIN edges e ON e.source_id = r.node_id
                    WHERE e.import_id = %s
                )
                -- Unique dependencies are in deps but not in other_reachable
                SELECT DISTINCT n.id, n.import_id, n.drv_hash, n.drv_name, n.label,
                       n.package_type, n.depth, n.closure_size, n.metadata,
                       n.is_top_level, n.top_level_source
                FROM deps d
                JOIN nodes n ON n.id = d.node_id
                WHERE d.node_id NOT IN (SELECT node_id FROM other_reachable)
                  AND n.import_id = %s
                ORDER BY n.label
                LIMIT %s
                """,
                (
                    node_id, import_id,  # deps CTE
                    import_id,  # deps recursive
                    import_id, node_id, import_id,  # other_top_level
                    import_id,  # other_reachable base
                    import_id,  # other_reachable recursive
                    import_id,  # final query
                    limit,
                )
            )
            return [Node(**row) for row in cur.fetchall()]


def build_essentiality_analysis(
    target: Node,
    paths: list[AttributionPath],
    import_id: int,
) -> EssentialityAnalysis:
    """Build a complete essentiality analysis for a package.

    Combines classification, removal impact, and path statistics
    into a comprehensive analysis.

    Args:
        target: The target node being analyzed
        paths: Attribution paths found for this target
        import_id: The import context

    Returns:
        EssentialityAnalysis with full details
    """
    # Determine status
    status = determine_essentiality(target, paths, import_id, include_build_deps=True)

    # Compute removal impact
    removal_impact = compute_removal_impact(target, paths, import_id)

    # Count runtime vs build dependents
    runtime_top_level_ids = {p.top_level_node_id for p in paths if p.is_runtime_path}
    build_top_level_ids = {p.top_level_node_id for p in paths if not p.is_runtime_path}

    runtime_dependents = len(runtime_top_level_ids)
    build_dependents = len(build_top_level_ids - runtime_top_level_ids)

    # Calculate path depth statistics
    if paths:
        path_depths = [p.path_length for p in paths]
        path_depth_avg = sum(path_depths) / len(path_depths)
        path_depth_max = max(path_depths)
    else:
        path_depth_avg = 0.0
        path_depth_max = 0

    # Check if any top-level package directly depends on target
    is_direct = any(p.path_length == 1 for p in paths)

    # Build top dependent summary
    if runtime_dependents == 0:
        top_dependent_summary = "No runtime dependents"
    elif runtime_dependents == 1:
        top_level_node = get_node_by_id(list(runtime_top_level_ids)[0])
        if top_level_node:
            top_dependent_summary = top_level_node.label
        else:
            top_dependent_summary = "1 package"
    else:
        top_dependent_summary = f"{runtime_dependents} packages"

    return EssentialityAnalysis(
        target=target,
        status=status,
        removal_impact=removal_impact,
        runtime_dependents=runtime_dependents,
        build_dependents=build_dependents,
        path_depth_avg=path_depth_avg,
        path_depth_max=path_depth_max,
        is_direct_dependency=is_direct,
        top_dependent_summary=top_dependent_summary,
    )


def build_why_chain_result(
    node_id: int,
    query: WhyChainQuery,
    use_cache: bool = True,
    max_groups: int = 10,
) -> WhyChainResult | None:
    """Build a complete WhyChainResult for a target node.

    This is the main entry point for Why Chain queries. It:
    1. Checks cache for existing result (enhanced caching in 8E-008)
    2. Computes reverse paths from top-level to target
    3. Aggregates paths into groups by intermediate node (8E-003)
    4. Gets direct dependents
    5. Determines essentiality status

    Args:
        node_id: The target node to explain
        query: Query parameters
        use_cache: Whether to use/update cache
        max_groups: Maximum number of attribution groups to return

    Returns:
        WhyChainResult or None if target not found
    """
    from vizzy.services.attribution_cache import (
        get_cached_attribution,
        cache_attribution_result,
        _is_common_package,
    )

    start_time = time.time()

    # Try enhanced attribution cache first (8E-008)
    if use_cache:
        cached_result = get_cached_attribution(node_id, query)
        if cached_result:
            logger.debug(f"Using cached why chain result for node {node_id}")
            # If we have a cached result but need fresh groups, recompute them
            if not cached_result.attribution_groups:
                paths = compute_reverse_paths(node_id, query)
                cached_result.attribution_groups = aggregate_paths(paths, max_groups=max_groups)
            return cached_result

    # Get target node
    target = get_node_by_id(node_id)
    if not target:
        logger.warning(f"Target node {node_id} not found")
        return None

    # Compute reverse paths
    paths = compute_reverse_paths(node_id, query)

    # Get direct dependents
    direct_dependents = get_direct_dependents(node_id, query.import_id)

    # Determine essentiality
    essentiality = determine_essentiality(
        target, paths, query.import_id, query.include_build_deps
    )

    # Count unique top-level packages
    top_level_ids = {p.top_level_node_id for p in paths}

    # Aggregate paths into groups (8E-003)
    attribution_groups = aggregate_paths(paths, max_groups=max_groups)

    elapsed_ms = (time.time() - start_time) * 1000

    result = WhyChainResult(
        target=target,
        query=query,
        direct_dependents=direct_dependents,
        attribution_groups=attribution_groups,
        total_top_level_dependents=len(top_level_ids),
        total_paths_found=len(paths),
        essentiality=essentiality,
        computation_time_ms=elapsed_ms,
        cached_at=None,
    )

    # Cache the result using enhanced attribution cache (8E-008)
    if use_cache and paths:
        cache_attribution_result(
            node_id=node_id,
            query=query,
            result=result,
            paths=paths,
            is_common_package=_is_common_package(target.label),
        )

    logger.info(
        f"build_why_chain_result: node {node_id}, "
        f"{len(paths)} paths, {len(top_level_ids)} top-level deps, "
        f"{len(attribution_groups)} groups, {elapsed_ms:.1f}ms"
    )

    return result


def get_cached_why_chain(node_id: int, query: WhyChainQuery) -> WhyChainResult | None:
    """Check cache for an existing Why Chain result.

    Args:
        node_id: The target node
        query: Query parameters (used for cache key)

    Returns:
        Cached WhyChainResult or None
    """
    # Build cache key from query parameters
    cache_key = _build_cache_key(node_id, query)

    # Check in-memory cache first
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Check database cache
    analysis_type = f"why_chain:{node_id}:{query.max_depth}:{query.include_build_deps}"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result, computed_at FROM analysis
                WHERE import_id = %s AND analysis_type = %s
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                (query.import_id, analysis_type)
            )
            row = cur.fetchone()

            if row:
                # Check if cache is still valid (1 hour TTL)
                computed_at = row['computed_at']
                if datetime.now() - computed_at < timedelta(hours=1):
                    result_data = row['result']
                    # Reconstruct WhyChainResult from cached data
                    try:
                        result = _deserialize_why_chain_result(result_data, query)
                        if result:
                            result.cached_at = computed_at
                            # Update in-memory cache
                            cache.set(cache_key, result, ttl=600)
                            return result
                    except Exception as e:
                        logger.warning(f"Failed to deserialize cached result: {e}")

    return None


def cache_why_chain_result(
    node_id: int,
    query: WhyChainQuery,
    result: WhyChainResult,
    paths: list[AttributionPath],
) -> None:
    """Cache a Why Chain result for future use.

    Stores both in-memory cache (fast) and database cache (persistent).

    Args:
        node_id: The target node
        query: Query parameters
        result: The computed result
        paths: The computed paths (for serialization)
    """
    # In-memory cache
    cache_key = _build_cache_key(node_id, query)
    cache.set(cache_key, result, ttl=600)  # 10 minutes

    # Database cache
    analysis_type = f"why_chain:{node_id}:{query.max_depth}:{query.include_build_deps}"

    # Serialize result for storage
    result_data = _serialize_why_chain_result(result, paths)

    with get_db() as conn:
        with conn.cursor() as cur:
            # Delete old cache entry if exists
            cur.execute(
                """
                DELETE FROM analysis
                WHERE import_id = %s AND analysis_type = %s
                """,
                (query.import_id, analysis_type)
            )

            # Insert new cache entry
            cur.execute(
                """
                INSERT INTO analysis (import_id, analysis_type, result)
                VALUES (%s, %s, %s)
                """,
                (query.import_id, analysis_type, json.dumps(result_data))
            )
            conn.commit()


def _build_cache_key(node_id: int, query: WhyChainQuery) -> str:
    """Build a cache key for a Why Chain query."""
    return cache_key_for_import(
        "why_chain",
        query.import_id,
        node_id,
        query.max_depth,
        query.include_build_deps,
    )


def _serialize_why_chain_result(
    result: WhyChainResult,
    paths: list[AttributionPath],
) -> dict:
    """Serialize a WhyChainResult for database storage."""
    return {
        "target_id": result.target.id,
        "total_top_level_dependents": result.total_top_level_dependents,
        "total_paths_found": result.total_paths_found,
        "essentiality": result.essentiality.value,
        "computation_time_ms": result.computation_time_ms,
        "paths": [
            {
                "path_node_ids": [n.id for n in p.path_nodes],
                "dependency_types": p.dependency_types,
                "is_runtime_path": p.is_runtime_path,
            }
            for p in paths
        ],
    }


def _deserialize_why_chain_result(
    data: dict,
    query: WhyChainQuery,
) -> WhyChainResult | None:
    """Deserialize a WhyChainResult from database storage."""
    try:
        target_id = data["target_id"]
        target = get_node_by_id(target_id)
        if not target:
            return None

        # Get direct dependents (not cached - cheap query)
        direct_dependents = get_direct_dependents(target_id, query.import_id)

        return WhyChainResult(
            target=target,
            query=query,
            direct_dependents=direct_dependents,
            attribution_groups=[],  # Will be populated by 8E-003
            total_top_level_dependents=data["total_top_level_dependents"],
            total_paths_found=data["total_paths_found"],
            essentiality=EssentialityStatus(data["essentiality"]),
            computation_time_ms=data.get("computation_time_ms"),
            cached_at=None,  # Will be set by caller
        )
    except Exception as e:
        logger.error(f"Error deserializing why chain result: {e}")
        return None


def invalidate_why_chain_cache(import_id: int) -> int:
    """Invalidate all Why Chain cache entries for an import.

    Call this when nodes or edges are modified.
    Uses the enhanced attribution cache (8E-008) for comprehensive invalidation.

    Args:
        import_id: The import to invalidate

    Returns:
        Number of cache entries invalidated
    """
    from vizzy.services.attribution_cache import invalidate_attribution_cache

    counts = invalidate_attribution_cache(import_id)
    return counts["memory"] + counts["database"]


def get_paths_for_result(
    node_id: int,
    query: WhyChainQuery,
) -> list[AttributionPath]:
    """Get the attribution paths for a Why Chain result.

    This is a convenience function that returns just the paths,
    useful for the path aggregation step (8E-003).

    Args:
        node_id: The target node
        query: Query parameters

    Returns:
        List of AttributionPath objects
    """
    return compute_reverse_paths(node_id, query)


def count_top_level_dependents(node_id: int, import_id: int) -> int:
    """Count how many top-level packages depend on a node.

    Quick check without computing full paths.

    Args:
        node_id: The target node
        import_id: The import context

    Returns:
        Count of top-level packages that depend on this node
    """
    # Use a simplified query that just checks reachability
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE reachable AS (
                    -- Start from nodes that directly depend on target
                    SELECT source_id as node_id, 1 as depth
                    FROM edges
                    WHERE target_id = %s AND import_id = %s

                    UNION

                    -- Follow edges upward (source depends on target)
                    SELECT e.source_id, r.depth + 1
                    FROM reachable r
                    JOIN edges e ON e.target_id = r.node_id
                    WHERE r.depth < 20  -- Reasonable depth limit
                      AND e.import_id = %s
                )
                SELECT COUNT(DISTINCT n.id)
                FROM reachable r
                JOIN nodes n ON n.id = r.node_id
                WHERE n.is_top_level = TRUE AND n.import_id = %s
                """,
                (node_id, import_id, import_id, import_id)
            )
            row = cur.fetchone()
            return row[0] if row else 0


# =============================================================================
# Path Aggregation (8E-003)
# =============================================================================
#
# When a package like glibc has thousands of paths leading to it, we need to
# intelligently group and summarize them for cleaner presentation.
#
# Aggregation strategy:
# 1. Group paths by their "via" node (the node immediately before target)
# 2. For each group, track all top-level packages that reach target through that via node
# 3. Sort groups by importance (number of top-level packages)
# 4. Limit displayed paths per group with "and N more" indicator
#
# Example output for "why is glibc here?":
#   Via curl (15 packages): firefox, wget, git, ...
#   Via python (12 packages): ansible, youtube-dl, ...
#   Via openssl (8 packages): nginx, nodejs, ...
#


def aggregate_paths(
    paths: list[AttributionPath],
    max_groups: int = 10,
    max_packages_per_group: int = 5,
) -> list[AttributionGroup]:
    """Aggregate multiple attribution paths into groups by intermediate node.

    Groups paths by their "via" node - the node immediately before the target.
    This provides a cleaner summary when many paths exist.

    Algorithm:
    1. For each path, identify the "via" node (second-to-last in path)
    2. Group paths by via node ID
    3. For each group, collect unique top-level packages
    4. Sort groups by number of top-level packages (descending)
    5. Build AttributionGroup objects with representative data

    Args:
        paths: List of AttributionPath objects to aggregate
        max_groups: Maximum number of groups to return
        max_packages_per_group: Maximum packages to show per group (rest summarized as "+N more")

    Returns:
        List of AttributionGroup objects, sorted by importance (most dependents first)
    """
    if not paths:
        return []

    # Special case: handle direct top-level to target connections (path length 1)
    direct_paths = [p for p in paths if p.path_length == 1]
    multi_hop_paths = [p for p in paths if p.path_length > 1]

    # Group multi-hop paths by via node
    # via_node_id -> {top_level_node_id -> path}
    via_groups: dict[int, dict[int, AttributionPath]] = {}

    for path in multi_hop_paths:
        via_node = path.get_via_node()
        if via_node is None:
            continue

        via_id = via_node.id
        top_level_id = path.top_level_node_id

        if via_id not in via_groups:
            via_groups[via_id] = {}

        # Keep the shortest path for each top-level package
        existing = via_groups[via_id].get(top_level_id)
        if existing is None or path.path_length < existing.path_length:
            via_groups[via_id][top_level_id] = path

    # Build AttributionGroup objects
    groups: list[AttributionGroup] = []

    # First, handle direct connections as a special group
    if direct_paths:
        # Get unique top-level packages for direct connections
        direct_top_levels: dict[int, Node] = {}
        shortest_direct: AttributionPath | None = None

        for path in direct_paths:
            if path.path_nodes and len(path.path_nodes) > 0:
                top_level_node = path.path_nodes[0]
                direct_top_levels[top_level_node.id] = top_level_node
                if shortest_direct is None or path.path_length < shortest_direct.path_length:
                    shortest_direct = path

        if direct_top_levels and shortest_direct and len(shortest_direct.path_nodes) >= 2:
            # For direct paths, the "via" node is actually the top-level itself
            # But we represent it as the target being directly used by top-level packages
            # We use the target as via_node to indicate "direct dependency"
            target_node = shortest_direct.path_nodes[-1]

            groups.append(AttributionGroup(
                via_node=target_node,  # Use target itself for direct connections
                top_level_packages=list(direct_top_levels.values())[:max_packages_per_group * 2],  # Keep more for sorting
                shortest_path=shortest_direct.path_nodes,
                total_dependents=len(direct_top_levels),
                common_path_suffix=[target_node],
            ))

    # Then build groups for multi-hop paths
    for via_id, paths_by_top_level in via_groups.items():
        if not paths_by_top_level:
            continue

        # Get all paths for this via node
        all_paths = list(paths_by_top_level.values())

        # Find shortest path
        shortest = min(all_paths, key=lambda p: p.path_length)

        # Get via node
        via_node = shortest.get_via_node()
        if via_node is None:
            continue

        # Get unique top-level packages
        top_level_nodes = [p.path_nodes[0] for p in all_paths if p.path_nodes]

        # Build common path suffix (from via_node to target)
        # This is typically just [via_node, target] but could be longer
        common_suffix = []
        if len(shortest.path_nodes) >= 2:
            # Find where via_node appears in the path
            for i, node in enumerate(shortest.path_nodes):
                if node.id == via_node.id:
                    common_suffix = shortest.path_nodes[i:]
                    break

        groups.append(AttributionGroup(
            via_node=via_node,
            top_level_packages=top_level_nodes,
            shortest_path=shortest.path_nodes,
            total_dependents=len(top_level_nodes),
            common_path_suffix=common_suffix,
        ))

    # Sort groups by number of dependents (most first)
    groups.sort(key=lambda g: g.total_dependents, reverse=True)

    # Limit to max_groups
    groups = groups[:max_groups]

    # Trim top_level_packages in each group and sort by label
    for group in groups:
        # Sort by label for consistent display
        group.top_level_packages.sort(key=lambda n: n.label.lower())

    return groups


def aggregate_paths_by_first_hop(
    paths: list[AttributionPath],
    max_groups: int = 10,
) -> list[AttributionGroup]:
    """Alternative aggregation: group by first hop from top-level.

    This groups paths by what the top-level package directly depends on,
    rather than what directly depends on the target.

    Useful for answering "through which direct dependencies does X get pulled in?"

    Args:
        paths: List of AttributionPath objects to aggregate
        max_groups: Maximum number of groups to return

    Returns:
        List of AttributionGroup objects
    """
    if not paths:
        return []

    # Group paths by first hop (node at index 1 in path)
    # first_hop_id -> {top_level_node_id -> path}
    hop_groups: dict[int, dict[int, AttributionPath]] = {}

    for path in paths:
        # Need at least 2 nodes for first hop
        if len(path.path_nodes) < 2:
            continue

        first_hop = path.path_nodes[1]
        first_hop_id = first_hop.id
        top_level_id = path.top_level_node_id

        if first_hop_id not in hop_groups:
            hop_groups[first_hop_id] = {}

        existing = hop_groups[first_hop_id].get(top_level_id)
        if existing is None or path.path_length < existing.path_length:
            hop_groups[first_hop_id][top_level_id] = path

    # Build groups
    groups: list[AttributionGroup] = []

    for first_hop_id, paths_by_top_level in hop_groups.items():
        if not paths_by_top_level:
            continue

        all_paths = list(paths_by_top_level.values())
        shortest = min(all_paths, key=lambda p: p.path_length)

        # First hop node
        first_hop = shortest.path_nodes[1] if len(shortest.path_nodes) > 1 else None
        if first_hop is None:
            continue

        top_level_nodes = [p.path_nodes[0] for p in all_paths if p.path_nodes]

        groups.append(AttributionGroup(
            via_node=first_hop,
            top_level_packages=top_level_nodes,
            shortest_path=shortest.path_nodes,
            total_dependents=len(top_level_nodes),
            common_path_suffix=shortest.path_nodes[1:] if len(shortest.path_nodes) > 1 else [],
        ))

    # Sort by dependents
    groups.sort(key=lambda g: g.total_dependents, reverse=True)

    return groups[:max_groups]


def summarize_attribution(
    groups: list[AttributionGroup],
    target_label: str,
    total_paths: int,
    total_top_level: int,
) -> str:
    """Generate a human-readable summary of attribution groups.

    Creates a concise text summary suitable for display in the UI header
    or for logging purposes.

    Args:
        groups: Aggregated attribution groups
        target_label: Label of the target package
        total_paths: Total number of paths found
        total_top_level: Total number of unique top-level dependents

    Returns:
        Human-readable summary string
    """
    if not groups:
        return f"{target_label} is not required by any top-level package"

    if total_top_level == 1:
        # Single dependent
        if groups[0].top_level_packages:
            dependent = groups[0].top_level_packages[0].label
            return f"{target_label} is needed by {dependent}"
        return f"{target_label} is needed by 1 top-level package"

    # Multiple dependents - summarize by top groups
    summary_parts = []

    # Check for direct dependencies (via_node is the target itself)
    direct_group = None
    other_groups = []
    for g in groups:
        # Direct dependencies have via_node equal to target (or path length 1)
        if len(g.shortest_path) == 2:
            direct_group = g
        else:
            other_groups.append(g)

    if direct_group and direct_group.total_dependents > 0:
        count = direct_group.total_dependents
        if count == 1:
            summary_parts.append(f"directly by {direct_group.top_level_packages[0].label}")
        else:
            summary_parts.append(f"directly by {count} packages")

    # Add top 3 via-groups
    for group in other_groups[:3]:
        via_label = group.via_label
        count = group.total_dependents
        if count == 1:
            summary_parts.append(f"via {via_label}")
        else:
            summary_parts.append(f"via {via_label} ({count})")

    # Count remaining groups
    remaining = len(other_groups) - 3
    if remaining > 0:
        summary_parts.append(f"and {remaining} more paths")

    summary = ", ".join(summary_parts)
    return f"{target_label} is needed by {total_top_level} top-level packages: {summary}"


def get_attribution_text_for_group(group: AttributionGroup, max_show: int = 3) -> str:
    """Generate display text for a single attribution group.

    Args:
        group: The attribution group
        max_show: Maximum number of package names to show

    Returns:
        Formatted string like "firefox, wget, git (+12 more)"
    """
    labels = [n.label for n in group.top_level_packages[:max_show]]
    text = ", ".join(labels)

    remaining = group.total_dependents - max_show
    if remaining > 0:
        text += f" (+{remaining} more)"

    return text


def get_path_description(path: AttributionPath) -> str:
    """Generate a description of a single attribution path.

    Args:
        path: The attribution path

    Returns:
        Formatted string like "firefox -> nss -> nspr -> glibc"
    """
    labels = [n.label for n in path.path_nodes]
    return " -> ".join(labels)


def get_attribution_summary(import_id: int) -> dict:
    """Get summary statistics about attribution in an import.

    Useful for dashboard display.

    Args:
        import_id: The import to summarize

    Returns:
        Dictionary with summary statistics
    """
    cache_key = cache_key_for_import("why_chain_summary", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Count total nodes
            cur.execute(
                "SELECT COUNT(*) FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()[0]

            # Count top-level nodes
            cur.execute(
                "SELECT COUNT(*) FROM nodes WHERE import_id = %s AND is_top_level = TRUE",
                (import_id,)
            )
            top_level_count = cur.fetchone()[0]

            # Count edges by type
            cur.execute(
                """
                SELECT
                    COALESCE(dependency_type, 'unknown') as dep_type,
                    COUNT(*) as count
                FROM edges
                WHERE import_id = %s
                GROUP BY dependency_type
                """,
                (import_id,)
            )
            edge_counts = {row['dep_type']: row['count'] for row in cur.fetchall()}

    result = {
        "import_id": import_id,
        "total_nodes": total_nodes,
        "top_level_count": top_level_count,
        "edge_counts": edge_counts,
        "runtime_edges": edge_counts.get("runtime", 0),
        "build_edges": edge_counts.get("build", 0),
    }

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


# =============================================================================
# Module-Level Attribution (8E-009)
# =============================================================================
#
# These functions provide module-level attribution display, showing users
# WHERE packages are defined in their NixOS configuration, not just WHY
# they are in the closure.
#
# Module types:
# - systemPackages: environment.systemPackages list
# - programs: programs.*.enable options
# - services: services.*.enable options
# - other: Other configuration sources
#


def classify_module_type(source: str | None) -> str:
    """Classify a top_level_source into a module type.

    Args:
        source: The top_level_source value (e.g., 'systemPackages', 'programs.git.enable')

    Returns:
        Module type string: 'systemPackages', 'programs', 'services', or 'other'
    """
    if not source:
        return "other"

    if source == "systemPackages" or source == "environment.systemPackages":
        return "systemPackages"
    elif source.startswith("programs."):
        return "programs"
    elif source.startswith("services."):
        return "services"
    else:
        return "other"


def format_source_for_display(source: str | None) -> str:
    """Format a top_level_source value for human-readable display.

    Args:
        source: The raw source value

    Returns:
        Formatted display string
    """
    if not source:
        return "Unknown source"

    if source == "systemPackages":
        return "environment.systemPackages"

    # Already formatted sources like 'programs.git.enable'
    return source


def get_module_attribution_for_nodes(
    node_ids: list[int],
) -> dict[int, tuple[str, str]]:
    """Get module attribution for a list of nodes.

    Queries the database for top_level_source and module_type for the given nodes.

    Args:
        node_ids: List of node IDs to query

    Returns:
        Dictionary mapping node_id to (module_type, source)
    """
    if not node_ids:
        return {}

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, top_level_source, module_type
                FROM nodes
                WHERE id = ANY(%s)
                """,
                (node_ids,)
            )

            result = {}
            for row in cur.fetchall():
                source = row['top_level_source']
                module_type = row['module_type'] or classify_module_type(source)
                result[row['id']] = (module_type, source)

            return result


def build_module_attribution_summary(
    top_level_nodes: list[Node],
    target_node_id: int,
) -> dict:
    """Build a module attribution summary for Why Chain display.

    Groups top-level packages by their module type and provides
    breakdown statistics for the UI.

    Args:
        top_level_nodes: List of top-level Node objects that depend on target
        target_node_id: The target node we're explaining

    Returns:
        Dictionary with grouped attribution data suitable for template rendering
    """
    from collections import defaultdict
    from vizzy.models import ModuleType

    # Get attribution data for all top-level nodes
    node_ids = [n.id for n in top_level_nodes]
    attributions = get_module_attribution_for_nodes(node_ids)

    # Group by module type
    by_type: dict[str, list[dict]] = defaultdict(list)
    by_source: dict[str, int] = defaultdict(int)

    for node in top_level_nodes:
        module_type, source = attributions.get(node.id, ("other", None))

        # Use node's top_level_source if available and attribution lookup failed
        if not source and node.top_level_source:
            source = node.top_level_source
            module_type = node.module_type or classify_module_type(source)

        display_source = format_source_for_display(source)

        attribution_info = {
            "node_id": node.id,
            "label": node.label,
            "package_type": node.package_type,
            "module_type": module_type,
            "source": source or "unknown",
            "display_source": display_source,
            "closure_size": node.closure_size,
        }

        by_type[module_type].append(attribution_info)
        by_source[source or "unknown"] += 1

    # Build ordered groups
    # Priority order: systemPackages, programs, services, other
    type_order = ["systemPackages", "programs", "services", "other"]
    groups = []

    for module_type in type_order:
        packages = by_type.get(module_type, [])
        if packages:
            # Sort packages by label
            packages.sort(key=lambda p: p["label"].lower())

            # Get display info for this module type
            try:
                mt_enum = ModuleType(module_type)
                display_name = mt_enum.display_name
                description = mt_enum.description
                css_class = mt_enum.css_class
            except ValueError:
                display_name = module_type.replace("_", " ").title()
                description = ""
                css_class = "module-type-other"

            groups.append({
                "module_type": module_type,
                "display_name": display_name,
                "description": description,
                "css_class": css_class,
                "packages": packages,
                "count": len(packages),
            })

    return {
        "target_node_id": target_node_id,
        "groups": groups,
        "total_packages": len(top_level_nodes),
        "by_source": dict(by_source),
        "has_attribution": any(g["module_type"] != "other" for g in groups),
    }


def get_module_breakdown_for_why_chain(
    attribution_groups: list,
    import_id: int,
) -> dict:
    """Get module breakdown from Why Chain attribution groups.

    Extracts all top-level packages from attribution groups and
    builds a module-level summary.

    Args:
        attribution_groups: List of AttributionGroup objects from Why Chain
        import_id: The import context

    Returns:
        Module attribution summary dictionary
    """
    # Collect all unique top-level nodes from all groups
    seen_node_ids: set[int] = set()
    top_level_nodes: list[Node] = []

    for group in attribution_groups:
        for node in group.top_level_packages:
            if node.id not in seen_node_ids:
                seen_node_ids.add(node.id)
                top_level_nodes.append(node)

    if not top_level_nodes:
        return {
            "target_node_id": 0,
            "groups": [],
            "total_packages": 0,
            "by_source": {},
            "has_attribution": False,
        }

    # Get the target node ID from the first group's shortest path
    target_node_id = 0
    if attribution_groups and attribution_groups[0].shortest_path:
        target_node_id = attribution_groups[0].shortest_path[-1].id

    return build_module_attribution_summary(top_level_nodes, target_node_id)


def enrich_attribution_groups_with_module_info(
    attribution_groups: list,
) -> list:
    """Add module attribution information to each top-level package in groups.

    Mutates the attribution groups to add module_type and source information
    to each top-level package for display in the UI.

    Args:
        attribution_groups: List of AttributionGroup objects

    Returns:
        The same list with enriched package data
    """
    # Collect all node IDs
    node_ids = []
    for group in attribution_groups:
        for node in group.top_level_packages:
            node_ids.append(node.id)

    if not node_ids:
        return attribution_groups

    # Get attribution data
    attributions = get_module_attribution_for_nodes(node_ids)

    # The AttributionGroup model uses Node objects which already have
    # top_level_source and module_type fields. We just need to ensure
    # they're populated. Since we can't mutate the Node objects directly
    # (they're Pydantic models), we return the groups as-is and let the
    # template access the node's existing fields.

    return attribution_groups


def get_source_icon(module_type: str) -> str:
    """Get an icon/emoji representation for a module type.

    Args:
        module_type: The module type string

    Returns:
        Icon string for display
    """
    icons = {
        "systemPackages": "cube",
        "programs": "terminal",
        "services": "server",
        "other": "question",
    }
    return icons.get(module_type, "question")


def get_source_color_class(module_type: str) -> str:
    """Get a CSS color class for a module type.

    Args:
        module_type: The module type string

    Returns:
        CSS class name for coloring
    """
    colors = {
        "systemPackages": "module-source-system",
        "programs": "module-source-programs",
        "services": "module-source-services",
        "other": "module-source-other",
    }
    return colors.get(module_type, "module-source-other")


# =============================================================================
# Attribution Export Functions (8E-010)
# =============================================================================
#
# These functions export attribution/why-chain data in multiple formats:
# - JSON: Machine-readable format for programmatic consumption
# - CSV: Spreadsheet-compatible format for analysis
# - Markdown: Human-readable report format
#
# This mirrors the comparison export functionality (8F-003).


def attribution_to_json(
    result: WhyChainResult,
    essentiality: EssentialityAnalysis,
    module_attribution: dict | None = None,
    paths: list[AttributionPath] | None = None,
) -> dict:
    """Export attribution data as a structured JSON dictionary.

    Creates a complete JSON representation of why a package is in the closure,
    suitable for programmatic consumption and further analysis.

    Args:
        result: The WhyChainResult to export
        essentiality: The EssentialityAnalysis for removal impact info
        module_attribution: Optional module attribution data
        paths: Optional list of attribution paths (for detailed export)

    Returns:
        A dictionary containing all attribution data in JSON-serializable format
    """
    from datetime import datetime

    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "report_version": "1.0",
            "generator": "vizzy",
            "export_type": "attribution",
        },
        "target": {
            "id": result.target.id,
            "label": result.target.label,
            "drv_hash": result.target.drv_hash,
            "package_type": result.target.package_type,
            "depth": result.target.depth,
            "closure_size": result.target.closure_size,
            "is_top_level": result.target.is_top_level,
            "top_level_source": result.target.top_level_source,
        },
        "summary": {
            "total_top_level_dependents": result.total_top_level_dependents,
            "total_paths_found": result.total_paths_found,
            "essentiality": result.essentiality.value,
            "essentiality_display": result.essentiality.display_name,
            "computation_time_ms": result.computation_time_ms,
            "cached": result.cached_at is not None,
        },
        "essentiality_analysis": {
            "status": essentiality.status.value,
            "status_display": essentiality.status.display_name,
            "status_description": essentiality.status.description,
            "is_removable": essentiality.status.is_removable_category,
            "runtime_dependents": essentiality.runtime_dependents,
            "build_dependents": essentiality.build_dependents,
            "path_depth_avg": round(essentiality.path_depth_avg, 2),
            "path_depth_max": essentiality.path_depth_max,
            "is_direct_dependency": essentiality.is_direct_dependency,
            "action_guidance": essentiality.action_guidance,
            "removal_impact": {
                "closure_reduction": essentiality.removal_impact.closure_reduction,
                "affected_count": essentiality.removal_impact.affected_count,
                "unique_deps_count": essentiality.removal_impact.unique_deps_count,
                "removal_safe": essentiality.removal_impact.removal_safe,
                "impact_level": essentiality.removal_impact.impact_level,
                "summary": essentiality.removal_impact.summary,
                "affected_packages": [
                    {"id": pkg.id, "label": pkg.label}
                    for pkg in essentiality.removal_impact.affected_packages
                ],
                "unique_deps_removed": [
                    {"id": dep.id, "label": dep.label}
                    for dep in essentiality.removal_impact.unique_deps_removed[:20]
                ],
            },
        },
        "attribution_groups": [
            {
                "via_label": group.via_label,
                "via_node_id": group.via_node.id,
                "total_dependents": group.total_dependents,
                "top_level_packages": [
                    {
                        "id": pkg.id,
                        "label": pkg.label,
                        "package_type": pkg.package_type,
                    }
                    for pkg in group.top_level_packages
                ],
                "shortest_path": [
                    {"id": node.id, "label": node.label}
                    for node in group.shortest_path
                ],
            }
            for group in result.attribution_groups
        ],
        "direct_dependents": [
            {
                "id": dep.id,
                "label": dep.label,
                "package_type": dep.package_type,
            }
            for dep in result.direct_dependents
        ],
    }

    # Add module attribution if available
    if module_attribution:
        output["module_attribution"] = module_attribution

    # Add detailed paths if provided
    if paths:
        output["paths"] = [
            {
                "path_length": path.path_length,
                "top_level_label": path.top_level_label,
                "target_label": path.target_label,
                "is_runtime_path": path.is_runtime_path,
                "dependency_types": path.dependency_types,
                "nodes": [
                    {"id": node.id, "label": node.label}
                    for node in path.path_nodes
                ],
            }
            for path in paths[:100]  # Limit to 100 paths for reasonable size
        ]

    return output


def attribution_to_csv(
    result: WhyChainResult,
    essentiality: EssentialityAnalysis,
) -> str:
    """Export attribution data as CSV format.

    Creates a flat CSV representation with one row per attribution group,
    suitable for spreadsheet analysis.

    Args:
        result: The WhyChainResult to export
        essentiality: The EssentialityAnalysis for additional data

    Returns:
        A CSV-formatted string with headers and all attribution data
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "target_package",
        "target_hash",
        "essentiality_status",
        "total_top_level_dependents",
        "via_package",
        "via_node_id",
        "group_dependent_count",
        "top_level_packages",
        "shortest_path",
        "shortest_path_length",
        "is_runtime_path",
    ])

    # If no attribution groups, write a summary row
    if not result.attribution_groups:
        writer.writerow([
            result.target.label,
            result.target.drv_hash[:12] if result.target.drv_hash else "",
            result.essentiality.value,
            result.total_top_level_dependents,
            "(no attribution paths)",
            "",
            0,
            "",
            "",
            0,
            "",
        ])
    else:
        # Data rows - one row per attribution group
        for group in result.attribution_groups:
            # Format top-level packages as comma-separated list
            top_level_list = ", ".join(pkg.label for pkg in group.top_level_packages[:10])
            if len(group.top_level_packages) > 10:
                top_level_list += f" (+{len(group.top_level_packages) - 10} more)"

            # Format shortest path
            path_str = " -> ".join(node.label for node in group.shortest_path)

            writer.writerow([
                result.target.label,
                result.target.drv_hash[:12] if result.target.drv_hash else "",
                result.essentiality.value,
                result.total_top_level_dependents,
                group.via_label,
                group.via_node.id,
                group.total_dependents,
                top_level_list,
                path_str,
                len(group.shortest_path) - 1,
                "yes" if all(node.package_type != "build" for node in group.shortest_path) else "no",
            ])

    return output.getvalue()


def attribution_to_markdown(
    result: WhyChainResult,
    essentiality: EssentialityAnalysis,
    module_attribution: dict | None = None,
    import_name: str = "Configuration",
) -> str:
    """Generate a Markdown report from attribution data.

    Creates a detailed, human-readable Markdown document explaining
    why a package is in the closure and its removal impact.

    Args:
        result: The WhyChainResult to export
        essentiality: The EssentialityAnalysis for removal impact
        module_attribution: Optional module attribution data
        import_name: Name of the import for the header

    Returns:
        A Markdown-formatted string with the complete attribution report
    """
    from datetime import datetime

    lines = []

    # Header
    lines.append(f"# Attribution Report: {result.target.label}")
    lines.append("")
    lines.append(f"**Configuration:** {import_name}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append(f"**Why is `{result.target.label}` in this closure?**")
    lines.append("")

    if result.total_top_level_dependents == 0:
        lines.append("This package is not required by any top-level package (orphan).")
    elif result.total_top_level_dependents == 1:
        lines.append(f"This package is needed by 1 top-level package.")
    else:
        lines.append(f"This package is needed by {result.total_top_level_dependents} top-level packages.")
    lines.append("")

    # Quick Stats
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Total Top-Level Dependents** | {result.total_top_level_dependents} |")
    lines.append(f"| **Total Paths Found** | {result.total_paths_found} |")
    lines.append(f"| **Essentiality Status** | {essentiality.status.display_name} |")
    lines.append(f"| **Package Type** | {result.target.package_type or 'unknown'} |")
    lines.append(f"| **Closure Size** | {result.target.closure_size or 'N/A'} |")
    lines.append("")

    # Essentiality Analysis
    lines.append("## Essentiality Analysis")
    lines.append("")
    lines.append(f"**Status:** {essentiality.status.display_name}")
    lines.append("")
    lines.append(f"> {essentiality.status.description}")
    lines.append("")
    lines.append(f"**Guidance:** {essentiality.action_guidance}")
    lines.append("")

    # Removal Impact
    lines.append("### Removal Impact")
    lines.append("")
    impact = essentiality.removal_impact
    lines.append(f"- **Impact Level:** {impact.impact_level.upper()}")
    lines.append(f"- **Removal Safe:** {'Yes' if impact.removal_safe else 'No'}")
    lines.append(f"- **Closure Reduction:** {impact.closure_reduction} packages")
    lines.append(f"- **Affected Packages:** {impact.affected_count}")
    lines.append(f"- **Unique Dependencies:** {impact.unique_deps_count}")
    lines.append("")

    if impact.affected_packages:
        lines.append("**Packages that would be affected:**")
        lines.append("")
        for pkg in impact.affected_packages[:10]:
            lines.append(f"- `{pkg.label}`")
        if len(impact.affected_packages) > 10:
            lines.append(f"- ... and {len(impact.affected_packages) - 10} more")
        lines.append("")

    # Dependency Path Statistics
    lines.append("### Dependency Statistics")
    lines.append("")
    lines.append(f"- **Runtime Dependents:** {essentiality.runtime_dependents}")
    lines.append(f"- **Build Dependents:** {essentiality.build_dependents}")
    lines.append(f"- **Average Path Depth:** {essentiality.path_depth_avg:.1f}")
    lines.append(f"- **Maximum Path Depth:** {essentiality.path_depth_max}")
    lines.append(f"- **Is Direct Dependency:** {'Yes' if essentiality.is_direct_dependency else 'No'}")
    lines.append("")

    # Attribution Groups
    lines.append("## Attribution Paths")
    lines.append("")

    if not result.attribution_groups:
        lines.append("*No attribution paths found.*")
        lines.append("")
    else:
        lines.append(f"Found {len(result.attribution_groups)} attribution groups.")
        lines.append("")

        for i, group in enumerate(result.attribution_groups, 1):
            lines.append(f"### {i}. Via `{group.via_label}`")
            lines.append("")
            lines.append(f"**Dependents:** {group.total_dependents} top-level package(s)")
            lines.append("")

            # List top-level packages
            lines.append("**Top-level packages:**")
            for pkg in group.top_level_packages[:8]:
                lines.append(f"- `{pkg.label}` ({pkg.package_type or 'unknown'})")
            if len(group.top_level_packages) > 8:
                lines.append(f"- ... and {len(group.top_level_packages) - 8} more")
            lines.append("")

            # Show shortest path
            lines.append("**Shortest path:**")
            path_str = " -> ".join(f"`{node.label}`" for node in group.shortest_path)
            lines.append(f"  {path_str}")
            lines.append("")

    # Direct Dependents
    if result.direct_dependents:
        lines.append("## Direct Dependents")
        lines.append("")
        lines.append(f"These {len(result.direct_dependents)} packages directly depend on `{result.target.label}`:")
        lines.append("")

        for dep in result.direct_dependents[:20]:
            lines.append(f"- `{dep.label}` ({dep.package_type or 'unknown'})")
        if len(result.direct_dependents) > 20:
            lines.append(f"- ... and {len(result.direct_dependents) - 20} more")
        lines.append("")

    # Module Attribution
    if module_attribution and module_attribution.get("groups"):
        lines.append("## Module Attribution")
        lines.append("")
        lines.append("Where do the top-level packages come from in your NixOS configuration?")
        lines.append("")

        for group in module_attribution["groups"]:
            lines.append(f"### {group['display_name']} ({group['count']} packages)")
            lines.append("")
            if group.get('description'):
                lines.append(f"*{group['description']}*")
                lines.append("")

            for pkg in group.get("packages", [])[:10]:
                source = pkg.get("display_source", pkg.get("source", "unknown"))
                lines.append(f"- `{pkg['label']}` - {source}")
            if group.get("count", 0) > 10:
                lines.append(f"- ... and {group['count'] - 10} more")
            lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by Vizzy - NixOS Derivation Graph Visualizer*")

    return "\n".join(lines)


def get_attribution_export_filename(
    target_label: str,
    import_name: str,
    format: str,
) -> str:
    """Generate a descriptive filename for an attribution export.

    Args:
        target_label: Label of the target package
        import_name: Name of the import/configuration
        format: The export format (json, csv, md)

    Returns:
        A sanitized filename string
    """
    import re
    from datetime import datetime

    # Sanitize names for use in filename
    safe_target = re.sub(r'[^\w\-]', '_', target_label)[:30]
    safe_import = re.sub(r'[^\w\-]', '_', import_name)[:20]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    return f"attribution_{safe_target}_{safe_import}_{timestamp}.{format}"
