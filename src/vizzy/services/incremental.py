"""Incremental recomputation service for closure contributions.

This module implements efficient incremental updates to closure contribution
calculations when the graph changes, rather than recomputing everything from scratch.

Key features:
- Change detection: Identifies what changed in the graph
- Affected node analysis: Determines which contributions need updating
- Selective recomputation: Only recomputes affected nodes
- Batch processing: Handles large updates efficiently
- Staleness tracking: Monitors computation freshness

Usage patterns:
1. After importing new nodes/edges, call `mark_contributions_stale()`
2. Periodically call `recompute_stale_contributions()` to update
3. For targeted updates, call `recompute_for_affected_nodes()`
4. Use `get_staleness_report()` to monitor data freshness

Performance characteristics:
- Full recomputation: O(n * m) where n=top-level packages, m=closure size
- Incremental update: O(k * m) where k=affected packages (typically k << n)
- Change detection: O(1) with proper indexing
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from vizzy.database import get_db
from vizzy.services.cache import cache, cache_key_for_import
from vizzy.services.contribution import compute_closure, compute_contributions

logger = logging.getLogger("vizzy.incremental")


class ChangeType(str, Enum):
    """Type of graph change that triggers recomputation."""
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_MODIFIED = "node_modified"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"
    TOP_LEVEL_CHANGED = "top_level_changed"
    FULL_REIMPORT = "full_reimport"


@dataclass
class GraphChange:
    """Represents a single change to the graph."""
    change_type: ChangeType
    import_id: int
    node_id: int | None = None
    edge_id: int | None = None
    source_id: int | None = None  # For edge changes
    target_id: int | None = None  # For edge changes
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StalenessReport:
    """Report on staleness of contribution data for an import."""
    import_id: int
    total_top_level: int
    stale_count: int
    never_computed_count: int
    oldest_computation: datetime | None
    newest_computation: datetime | None
    freshness_threshold: timedelta
    is_fresh: bool
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def stale_percentage(self) -> float:
        """Percentage of top-level nodes with stale contributions."""
        if self.total_top_level == 0:
            return 0.0
        return (self.stale_count / self.total_top_level) * 100

    @property
    def needs_recomputation(self) -> bool:
        """True if any contributions need recomputation."""
        return self.stale_count > 0 or self.never_computed_count > 0


@dataclass
class RecomputationResult:
    """Result of an incremental recomputation operation."""
    import_id: int
    nodes_updated: int
    nodes_skipped: int
    computation_time_ms: float
    strategy_used: str  # 'incremental', 'full', 'selective'
    affected_nodes: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if recomputation completed without errors."""
        return len(self.errors) == 0


# =============================================================================
# Staleness Detection and Tracking
# =============================================================================


def get_staleness_report(
    import_id: int,
    freshness_threshold: timedelta = timedelta(hours=24)
) -> StalenessReport:
    """Generate a staleness report for contribution data.

    Analyzes the contribution data freshness for an import and determines
    if recomputation is needed.

    Args:
        import_id: The import to analyze
        freshness_threshold: How old data can be before considered stale

    Returns:
        StalenessReport with detailed staleness information
    """
    threshold_time = datetime.now() - freshness_threshold

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get overall stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_top_level,
                    COUNT(*) FILTER (WHERE contribution_computed_at IS NULL) as never_computed,
                    COUNT(*) FILTER (
                        WHERE contribution_computed_at IS NOT NULL
                        AND contribution_computed_at < %s
                    ) as stale,
                    MIN(contribution_computed_at) as oldest,
                    MAX(contribution_computed_at) as newest
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (threshold_time, import_id)
            )
            stats = cur.fetchone()

            # Get breakdown by top_level_source
            cur.execute(
                """
                SELECT
                    COALESCE(top_level_source, 'unknown') as source,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE contribution_computed_at IS NULL) as never_computed,
                    COUNT(*) FILTER (
                        WHERE contribution_computed_at IS NOT NULL
                        AND contribution_computed_at < %s
                    ) as stale
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                GROUP BY top_level_source
                ORDER BY total DESC
                """,
                (threshold_time, import_id)
            )
            breakdown = {row['source']: {
                'total': row['total'],
                'never_computed': row['never_computed'],
                'stale': row['stale'],
            } for row in cur.fetchall()}

    total = stats['total_top_level'] or 0
    stale = stats['stale'] or 0
    never_computed = stats['never_computed'] or 0
    oldest = stats['oldest']
    newest = stats['newest']

    return StalenessReport(
        import_id=import_id,
        total_top_level=total,
        stale_count=stale,
        never_computed_count=never_computed,
        oldest_computation=oldest,
        newest_computation=newest,
        freshness_threshold=freshness_threshold,
        is_fresh=(stale == 0 and never_computed == 0),
        details={
            'by_source': breakdown,
            'threshold_time': threshold_time.isoformat(),
        }
    )


def mark_contributions_stale(
    import_id: int,
    node_ids: list[int] | None = None
) -> int:
    """Mark contribution data as stale (needing recomputation).

    This is used to signal that contributions need to be recalculated
    without actually computing them immediately.

    Args:
        import_id: The import to mark
        node_ids: Specific node IDs to mark stale. If None, marks all top-level.

    Returns:
        Number of nodes marked as stale
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            if node_ids:
                # Mark specific nodes stale
                cur.execute(
                    """
                    UPDATE nodes
                    SET contribution_computed_at = NULL
                    WHERE import_id = %s AND id = ANY(%s) AND is_top_level = TRUE
                    """,
                    (import_id, node_ids)
                )
            else:
                # Mark all top-level nodes stale
                cur.execute(
                    """
                    UPDATE nodes
                    SET contribution_computed_at = NULL
                    WHERE import_id = %s AND is_top_level = TRUE
                    """,
                    (import_id,)
                )

            count = cur.rowcount
            conn.commit()

            logger.info(f"Marked {count} nodes as stale for import {import_id}")

            # Invalidate related caches
            cache.invalidate(f"import:{import_id}:contribution")

            return count


# =============================================================================
# Affected Node Analysis
# =============================================================================


def find_affected_nodes_by_edge_change(
    import_id: int,
    source_id: int,
    target_id: int,
    edge_removed: bool = False
) -> set[int]:
    """Find all top-level nodes affected by an edge change.

    When an edge is added or removed, we need to determine which top-level
    packages have changed closures. An edge change affects a top-level package
    if the target node was in its closure (for removal) or could be in its
    closure (for addition).

    Args:
        import_id: The import ID
        source_id: The source node of the changed edge
        target_id: The target node of the changed edge
        edge_removed: True if the edge was removed, False if added

    Returns:
        Set of top-level node IDs that need recomputation
    """
    affected = set()

    with get_db() as conn:
        with conn.cursor() as cur:
            # Find all top-level packages that can reach the source node
            # These are potentially affected by the edge change
            cur.execute(
                """
                WITH RECURSIVE reverse_closure AS (
                    -- Base: top-level packages
                    SELECT id, id as top_level_id
                    FROM nodes
                    WHERE import_id = %s AND is_top_level = TRUE

                    UNION

                    -- Follow edges backwards
                    SELECT e.source_id, rc.top_level_id
                    FROM reverse_closure rc
                    JOIN edges e ON e.target_id = rc.id AND e.import_id = %s
                )
                SELECT DISTINCT top_level_id
                FROM reverse_closure
                WHERE id = %s
                """,
                (import_id, import_id, target_id)
            )
            affected.update(row['top_level_id'] for row in cur.fetchall())

    logger.debug(f"Edge change ({source_id} -> {target_id}) affects {len(affected)} top-level nodes")
    return affected


def find_affected_nodes_by_node_change(
    import_id: int,
    changed_node_id: int
) -> set[int]:
    """Find all top-level nodes affected by a node change.

    When a node is added, removed, or modified, we need to determine which
    top-level packages have changed closures.

    Args:
        import_id: The import ID
        changed_node_id: The ID of the changed node

    Returns:
        Set of top-level node IDs that need recomputation
    """
    affected = set()

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if the changed node is top-level itself
            cur.execute(
                """
                SELECT is_top_level FROM nodes WHERE id = %s
                """,
                (changed_node_id,)
            )
            row = cur.fetchone()
            if row and row['is_top_level']:
                affected.add(changed_node_id)

            # Find all top-level packages that include this node in their closure
            cur.execute(
                """
                WITH RECURSIVE reverse_closure AS (
                    -- Start from the changed node
                    SELECT %s as id, ARRAY[%s] as path

                    UNION

                    -- Follow edges backwards (towards top-level)
                    SELECT e.target_id, rc.path || e.target_id
                    FROM reverse_closure rc
                    JOIN edges e ON e.source_id = rc.id AND e.import_id = %s
                    WHERE NOT (e.target_id = ANY(rc.path))
                )
                SELECT DISTINCT n.id
                FROM reverse_closure rc
                JOIN nodes n ON n.id = rc.id
                WHERE n.is_top_level = TRUE AND n.import_id = %s
                """,
                (changed_node_id, changed_node_id, import_id, import_id)
            )
            affected.update(row['id'] for row in cur.fetchall())

    logger.debug(f"Node change ({changed_node_id}) affects {len(affected)} top-level nodes")
    return affected


def find_affected_by_top_level_change(
    import_id: int,
    changed_node_id: int
) -> set[int]:
    """Find nodes affected when a node's top-level status changes.

    When a node becomes top-level or loses top-level status, it affects
    the unique/shared contribution calculations for all other top-level nodes.

    Args:
        import_id: The import ID
        changed_node_id: The node whose top-level status changed

    Returns:
        Set of all top-level node IDs (all need recomputation)
    """
    # A top-level change affects all other top-level packages' shared/unique
    # calculations, so we need to recompute everything
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            affected = {row['id'] for row in cur.fetchall()}

    logger.debug(f"Top-level change affects all {len(affected)} top-level nodes")
    return affected


# =============================================================================
# Incremental Recomputation Strategies
# =============================================================================


def recompute_stale_contributions(
    import_id: int,
    max_nodes: int | None = None,
    freshness_threshold: timedelta = timedelta(hours=24)
) -> RecomputationResult:
    """Recompute contributions for stale top-level nodes.

    This is the main entry point for incremental recomputation. It identifies
    nodes with stale or missing contribution data and recomputes them.

    Args:
        import_id: The import to recompute
        max_nodes: Maximum nodes to recompute in this run (for batching)
        freshness_threshold: How old data can be before considered stale

    Returns:
        RecomputationResult with details of the operation
    """
    start_time = time.time()
    threshold_time = datetime.now() - freshness_threshold

    with get_db() as conn:
        with conn.cursor() as cur:
            # Find stale nodes (never computed or older than threshold)
            query = """
                SELECT id FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND (contribution_computed_at IS NULL
                       OR contribution_computed_at < %s)
                ORDER BY
                    CASE WHEN contribution_computed_at IS NULL THEN 0 ELSE 1 END,
                    contribution_computed_at ASC
            """
            params: list[Any] = [import_id, threshold_time]

            if max_nodes:
                query += " LIMIT %s"
                params.append(max_nodes)

            cur.execute(query, params)
            stale_node_ids = [row['id'] for row in cur.fetchall()]

    if not stale_node_ids:
        logger.info(f"No stale contributions for import {import_id}")
        return RecomputationResult(
            import_id=import_id,
            nodes_updated=0,
            nodes_skipped=0,
            computation_time_ms=0,
            strategy_used='none_needed',
        )

    # Determine strategy based on number of stale nodes
    total_top_level = get_top_level_count_internal(import_id, conn)

    if len(stale_node_ids) > total_top_level * 0.5:
        # More than 50% stale - do full recomputation
        logger.info(f"High staleness ({len(stale_node_ids)}/{total_top_level}) - using full recomputation")
        updated = compute_contributions(import_id)
        elapsed = (time.time() - start_time) * 1000

        return RecomputationResult(
            import_id=import_id,
            nodes_updated=updated,
            nodes_skipped=0,
            computation_time_ms=elapsed,
            strategy_used='full',
            affected_nodes=stale_node_ids,
        )
    else:
        # Selective recomputation for stale nodes
        logger.info(f"Selective recomputation for {len(stale_node_ids)} nodes")
        return recompute_selective(import_id, stale_node_ids, start_time)


def recompute_selective(
    import_id: int,
    node_ids: list[int],
    start_time: float | None = None
) -> RecomputationResult:
    """Selectively recompute contributions for specific nodes.

    This implements the core incremental algorithm:
    1. Fetch all top-level closures (needed for shared computation)
    2. Recompute only the specified nodes' contributions
    3. Update the database with new values

    Args:
        import_id: The import to recompute
        node_ids: Specific node IDs to recompute
        start_time: Optional start time for timing (uses now if not provided)

    Returns:
        RecomputationResult with details of the operation
    """
    if start_time is None:
        start_time = time.time()

    errors: list[str] = []
    updated = 0
    skipped = 0

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all top-level node IDs
            cur.execute(
                """
                SELECT id FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            all_top_level_ids = [row['id'] for row in cur.fetchall()]

            if not all_top_level_ids:
                return RecomputationResult(
                    import_id=import_id,
                    nodes_updated=0,
                    nodes_skipped=0,
                    computation_time_ms=(time.time() - start_time) * 1000,
                    strategy_used='selective',
                    errors=['No top-level nodes found'],
                )

            # Compute closures for all top-level nodes
            # (needed for accurate shared/unique calculation)
            logger.debug(f"Computing closures for {len(all_top_level_ids)} top-level nodes")
            closures: dict[int, set[int]] = {}
            for tl_id in all_top_level_ids:
                try:
                    closures[tl_id] = compute_closure(tl_id, conn)
                except Exception as e:
                    errors.append(f"Failed to compute closure for node {tl_id}: {e}")
                    skipped += 1

            # Compute union of all other closures for each node to update
            now = datetime.now()
            for tl_id in node_ids:
                if tl_id not in closures:
                    skipped += 1
                    continue

                try:
                    deps = closures[tl_id]
                    # Get deps reachable via OTHER packages
                    other_deps = set()
                    for other_id, other_closure in closures.items():
                        if other_id != tl_id:
                            other_deps.update(other_closure)

                    unique = deps - other_deps
                    shared = deps & other_deps
                    total = len(deps)

                    cur.execute(
                        """
                        UPDATE nodes
                        SET unique_contribution = %s,
                            shared_contribution = %s,
                            total_contribution = %s,
                            contribution_computed_at = %s
                        WHERE id = %s
                        """,
                        (len(unique), len(shared), total, now, tl_id)
                    )
                    updated += 1

                except Exception as e:
                    errors.append(f"Failed to update node {tl_id}: {e}")
                    skipped += 1

            conn.commit()

    elapsed = (time.time() - start_time) * 1000

    # Invalidate cache
    cache.invalidate(f"import:{import_id}:contribution")

    logger.info(
        f"Selective recomputation complete: {updated} updated, {skipped} skipped "
        f"in {elapsed:.2f}ms"
    )

    return RecomputationResult(
        import_id=import_id,
        nodes_updated=updated,
        nodes_skipped=skipped,
        computation_time_ms=elapsed,
        strategy_used='selective',
        affected_nodes=node_ids,
        errors=errors,
    )


def recompute_for_graph_change(
    change: GraphChange
) -> RecomputationResult:
    """Recompute contributions in response to a graph change.

    This is the main handler for incremental updates triggered by graph changes.
    It analyzes the change type and determines the minimal set of nodes that
    need recomputation.

    Args:
        change: The graph change that occurred

    Returns:
        RecomputationResult with details of the operation
    """
    start_time = time.time()
    import_id = change.import_id
    affected: set[int] = set()

    # Determine affected nodes based on change type
    if change.change_type == ChangeType.FULL_REIMPORT:
        # Full reimport - recompute everything
        logger.info(f"Full reimport detected - computing all contributions")
        updated = compute_contributions(import_id)
        return RecomputationResult(
            import_id=import_id,
            nodes_updated=updated,
            nodes_skipped=0,
            computation_time_ms=(time.time() - start_time) * 1000,
            strategy_used='full',
        )

    elif change.change_type in (ChangeType.EDGE_ADDED, ChangeType.EDGE_REMOVED):
        if change.source_id and change.target_id:
            affected = find_affected_nodes_by_edge_change(
                import_id,
                change.source_id,
                change.target_id,
                edge_removed=(change.change_type == ChangeType.EDGE_REMOVED)
            )

    elif change.change_type in (ChangeType.NODE_ADDED, ChangeType.NODE_REMOVED, ChangeType.NODE_MODIFIED):
        if change.node_id:
            affected = find_affected_nodes_by_node_change(import_id, change.node_id)

    elif change.change_type == ChangeType.TOP_LEVEL_CHANGED:
        if change.node_id:
            affected = find_affected_by_top_level_change(import_id, change.node_id)

    if not affected:
        logger.info(f"No nodes affected by change {change.change_type}")
        return RecomputationResult(
            import_id=import_id,
            nodes_updated=0,
            nodes_skipped=0,
            computation_time_ms=(time.time() - start_time) * 1000,
            strategy_used='incremental',
        )

    # Recompute affected nodes
    return recompute_selective(import_id, list(affected), start_time)


# =============================================================================
# Batch Processing and Scheduling
# =============================================================================


def recompute_all_imports_stale(
    freshness_threshold: timedelta = timedelta(hours=24),
    max_nodes_per_import: int = 100
) -> dict[int, RecomputationResult]:
    """Recompute stale contributions across all imports.

    Useful for batch processing or scheduled maintenance tasks.

    Args:
        freshness_threshold: How old data can be before considered stale
        max_nodes_per_import: Maximum nodes to recompute per import

    Returns:
        Dictionary mapping import_id to RecomputationResult
    """
    results: dict[int, RecomputationResult] = {}

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all imports with stale contribution data
            threshold_time = datetime.now() - freshness_threshold
            cur.execute(
                """
                SELECT DISTINCT n.import_id
                FROM nodes n
                WHERE n.is_top_level = TRUE
                  AND (n.contribution_computed_at IS NULL
                       OR n.contribution_computed_at < %s)
                """,
                (threshold_time,)
            )
            import_ids = [row['import_id'] for row in cur.fetchall()]

    logger.info(f"Found {len(import_ids)} imports with stale contributions")

    for import_id in import_ids:
        try:
            result = recompute_stale_contributions(
                import_id,
                max_nodes=max_nodes_per_import,
                freshness_threshold=freshness_threshold
            )
            results[import_id] = result
        except Exception as e:
            logger.error(f"Failed to recompute import {import_id}: {e}")
            results[import_id] = RecomputationResult(
                import_id=import_id,
                nodes_updated=0,
                nodes_skipped=0,
                computation_time_ms=0,
                strategy_used='error',
                errors=[str(e)],
            )

    return results


def estimate_recomputation_cost(import_id: int) -> dict[str, Any]:
    """Estimate the cost of recomputing contributions for an import.

    Returns estimates useful for deciding whether to run incremental
    or full recomputation.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary with cost estimates and recommendations
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get graph size metrics
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM nodes WHERE import_id = %s) as total_nodes,
                    (SELECT COUNT(*) FROM edges WHERE import_id = %s) as total_edges,
                    (SELECT COUNT(*) FROM nodes WHERE import_id = %s AND is_top_level = TRUE) as top_level_count,
                    (SELECT AVG(closure_size) FROM nodes WHERE import_id = %s AND is_top_level = TRUE) as avg_closure,
                    (SELECT COUNT(*) FROM nodes
                     WHERE import_id = %s AND is_top_level = TRUE
                       AND contribution_computed_at IS NULL) as stale_count
                """,
                (import_id, import_id, import_id, import_id, import_id)
            )
            metrics = cur.fetchone()

    total_nodes = metrics['total_nodes'] or 0
    total_edges = metrics['total_edges'] or 0
    top_level = metrics['top_level_count'] or 0
    avg_closure = float(metrics['avg_closure'] or 0)
    stale = metrics['stale_count'] or 0

    # Estimate computation time (rough heuristics)
    # Full recomputation: ~10ms per top-level package * closure traversal
    full_cost_ms = top_level * 10 * (1 + avg_closure / 1000)
    # Incremental: same cost but for stale nodes only
    incremental_cost_ms = stale * 10 * (1 + avg_closure / 1000)

    # Recommendation
    if stale == 0:
        recommendation = "no_recomputation_needed"
    elif stale > top_level * 0.5:
        recommendation = "full_recomputation"
    else:
        recommendation = "incremental_recomputation"

    return {
        "import_id": import_id,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "top_level_count": top_level,
        "avg_closure_size": avg_closure,
        "stale_count": stale,
        "stale_percentage": (stale / top_level * 100) if top_level > 0 else 0,
        "estimated_full_cost_ms": full_cost_ms,
        "estimated_incremental_cost_ms": incremental_cost_ms,
        "recommendation": recommendation,
        "savings_percentage": (
            ((full_cost_ms - incremental_cost_ms) / full_cost_ms * 100)
            if full_cost_ms > 0 else 0
        ),
    }


# =============================================================================
# Helper Functions
# =============================================================================


def get_top_level_count_internal(import_id: int, conn) -> int:
    """Get count of top-level nodes (internal helper, uses existing connection)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as count FROM nodes WHERE import_id = %s AND is_top_level = TRUE",
            (import_id,)
        )
        row = cur.fetchone()
        return row['count'] if row else 0


def get_last_computation_time(import_id: int) -> datetime | None:
    """Get the timestamp of the most recent contribution computation."""
    cache_key = cache_key_for_import("last_computation", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(contribution_computed_at) as last_computed
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            row = cur.fetchone()
            result = row['last_computed'] if row else None

    if result:
        cache.set(cache_key, result, ttl=60)
    return result


def should_trigger_recomputation(
    import_id: int,
    threshold: timedelta = timedelta(hours=1)
) -> bool:
    """Check if recomputation should be triggered based on data age.

    Args:
        import_id: The import to check
        threshold: Maximum age before recomputation is needed

    Returns:
        True if recomputation should be triggered
    """
    report = get_staleness_report(import_id, threshold)
    return report.needs_recomputation


# =============================================================================
# API Integration Helpers
# =============================================================================


def handle_import_completed(import_id: int, is_reimport: bool = False) -> RecomputationResult:
    """Handle completion of an import operation.

    Called after a new import or reimport to compute/update contributions.

    Args:
        import_id: The import ID
        is_reimport: True if this is replacing an existing import

    Returns:
        RecomputationResult from the triggered computation
    """
    if is_reimport:
        # Mark all as stale and let the scheduler handle it
        mark_contributions_stale(import_id)
        return recompute_stale_contributions(import_id)
    else:
        # New import - do full computation
        change = GraphChange(
            change_type=ChangeType.FULL_REIMPORT,
            import_id=import_id,
        )
        return recompute_for_graph_change(change)


def handle_node_change(
    import_id: int,
    node_id: int,
    change_type: ChangeType
) -> RecomputationResult:
    """Handle a node being added, removed, or modified.

    Args:
        import_id: The import ID
        node_id: The changed node ID
        change_type: Type of change

    Returns:
        RecomputationResult from the triggered computation
    """
    change = GraphChange(
        change_type=change_type,
        import_id=import_id,
        node_id=node_id,
    )
    return recompute_for_graph_change(change)


def handle_edge_change(
    import_id: int,
    source_id: int,
    target_id: int,
    added: bool = True
) -> RecomputationResult:
    """Handle an edge being added or removed.

    Args:
        import_id: The import ID
        source_id: Source node of the edge
        target_id: Target node of the edge
        added: True if edge was added, False if removed

    Returns:
        RecomputationResult from the triggered computation
    """
    change = GraphChange(
        change_type=ChangeType.EDGE_ADDED if added else ChangeType.EDGE_REMOVED,
        import_id=import_id,
        source_id=source_id,
        target_id=target_id,
    )
    return recompute_for_graph_change(change)


def handle_top_level_change(import_id: int, node_id: int) -> RecomputationResult:
    """Handle a node's top-level status changing.

    Args:
        import_id: The import ID
        node_id: The node whose top-level status changed

    Returns:
        RecomputationResult from the triggered computation
    """
    change = GraphChange(
        change_type=ChangeType.TOP_LEVEL_CHANGED,
        import_id=import_id,
        node_id=node_id,
    )
    return recompute_for_graph_change(change)
