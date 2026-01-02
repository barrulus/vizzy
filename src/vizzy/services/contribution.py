"""Closure contribution calculation service.

This module computes how much each package contributes to the overall closure size.
This enables answering questions like:
- "Why is my closure so big?"
- "What packages contribute most to closure size?"
- "Which packages can I remove to reduce closure size?"

The key metrics computed are:
- unique_contribution: Dependencies only reachable via this package
- shared_contribution: Dependencies also reachable via other top-level packages
- total_contribution: Sum of unique + shared
"""

import logging
import time
from datetime import datetime
from collections import defaultdict

from vizzy.database import get_db
from vizzy.models import ClosureContribution, ClosureContributionSummary
from vizzy.services.cache import cache, cache_key_for_import

logger = logging.getLogger("vizzy.contribution")


def compute_closure(node_id: int, conn) -> set[int]:
    """Compute the transitive closure (all reachable dependencies) for a node.

    Uses a recursive CTE to find all nodes reachable from the given node.

    Args:
        node_id: The node ID to compute closure for
        conn: Database connection

    Returns:
        Set of node IDs that are in this node's closure
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH RECURSIVE closure AS (
                -- Base case: direct dependencies
                SELECT source_id as dep_id
                FROM edges WHERE target_id = %s

                UNION

                -- Recursive case: transitive dependencies
                SELECT e.source_id
                FROM closure c
                JOIN edges e ON e.target_id = c.dep_id
            )
            SELECT DISTINCT dep_id FROM closure
            """,
            (node_id,)
        )
        return {row['dep_id'] for row in cur.fetchall()}


def compute_contributions(import_id: int, batch_size: int = 50) -> int:
    """Compute unique vs shared contribution for all top-level packages.

    For each top-level package, computes:
    - unique_contribution: deps only reachable via this package
    - shared_contribution: deps also reachable via other top-level packages
    - total_contribution: all deps in the package's closure

    This is an expensive operation for large graphs - results are persisted
    in the database for later retrieval.

    Args:
        import_id: The import to compute contributions for
        batch_size: Number of closures to compute before committing

    Returns:
        Number of nodes updated with contribution data
    """
    start_time = time.time()
    logger.info(f"Starting contribution calculation for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all top-level nodes
            cur.execute(
                """
                SELECT id, label FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            top_level_nodes = cur.fetchall()

            if not top_level_nodes:
                logger.warning(f"No top-level nodes found for import {import_id}")
                return 0

            top_level_ids = [row['id'] for row in top_level_nodes]
            logger.info(f"Computing closures for {len(top_level_ids)} top-level packages")

            # Phase 1: Compute closure for each top-level package
            closures: dict[int, set[int]] = {}
            for i, tl_id in enumerate(top_level_ids):
                closures[tl_id] = compute_closure(tl_id, conn)
                if (i + 1) % 10 == 0:
                    logger.debug(f"Computed {i + 1}/{len(top_level_ids)} closures")

            # Phase 2: Compute union of all closures for shared computation
            all_deps = set().union(*closures.values()) if closures else set()
            logger.info(f"Total unique dependencies across all top-level: {len(all_deps)}")

            # Phase 3: Compute unique vs shared for each top-level
            updates = []
            for tl_id, deps in closures.items():
                # Get deps reachable via OTHER packages (not this one)
                other_deps = set().union(*(
                    c for tid, c in closures.items() if tid != tl_id
                )) if len(closures) > 1 else set()

                # Unique = deps NOT reachable via other packages
                unique = deps - other_deps
                # Shared = deps ALSO reachable via other packages
                shared = deps & other_deps
                # Total = all deps
                total = len(deps)

                updates.append({
                    'id': tl_id,
                    'unique': len(unique),
                    'shared': len(shared),
                    'total': total,
                })

            # Phase 4: Batch update the database
            now = datetime.now()
            for update in updates:
                cur.execute(
                    """
                    UPDATE nodes
                    SET unique_contribution = %s,
                        shared_contribution = %s,
                        total_contribution = %s,
                        contribution_computed_at = %s
                    WHERE id = %s
                    """,
                    (
                        update['unique'],
                        update['shared'],
                        update['total'],
                        now,
                        update['id'],
                    )
                )

            conn.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"Contribution calculation complete for import {import_id}: "
                f"{len(updates)} nodes updated in {elapsed:.2f}s"
            )

            # Invalidate cache
            cache.invalidate(f"import:{import_id}:contribution")

            return len(updates)


def compute_contributions_incremental(
    import_id: int,
    node_ids: list[int] | None = None
) -> int:
    """Incrementally recompute contributions for specific nodes.

    Use this when only a subset of nodes have changed, to avoid
    recomputing the entire graph.

    Args:
        import_id: The import to update
        node_ids: Specific node IDs to recompute. If None, recomputes
                 all top-level nodes with stale/missing contribution data.

    Returns:
        Number of nodes updated
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            if node_ids is None:
                # Find nodes needing recomputation
                cur.execute(
                    """
                    SELECT id FROM nodes
                    WHERE import_id = %s
                      AND is_top_level = TRUE
                      AND contribution_computed_at IS NULL
                    """,
                    (import_id,)
                )
                node_ids = [row['id'] for row in cur.fetchall()]

            if not node_ids:
                return 0

            # Get all top-level nodes for shared computation
            cur.execute(
                """
                SELECT id FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            all_top_level = [row['id'] for row in cur.fetchall()]

            # Compute all closures (needed for accurate shared computation)
            closures = {
                tl_id: compute_closure(tl_id, conn)
                for tl_id in all_top_level
            }

            # Update only the requested nodes
            now = datetime.now()
            updated = 0
            for tl_id in node_ids:
                if tl_id not in closures:
                    continue

                deps = closures[tl_id]
                other_deps = set().union(*(
                    c for tid, c in closures.items() if tid != tl_id
                )) if len(closures) > 1 else set()

                unique = deps - other_deps
                shared = deps & other_deps

                cur.execute(
                    """
                    UPDATE nodes
                    SET unique_contribution = %s,
                        shared_contribution = %s,
                        total_contribution = %s,
                        contribution_computed_at = %s
                    WHERE id = %s
                    """,
                    (len(unique), len(shared), len(deps), now, tl_id)
                )
                updated += 1

            conn.commit()
            cache.invalidate(f"import:{import_id}:contribution")
            return updated


def get_contribution_data(
    import_id: int,
    sort_by: str = "unique",
    limit: int = 20,
) -> list[ClosureContribution]:
    """Get closure contribution data for top-level packages.

    Args:
        import_id: The import to get contribution data for
        sort_by: How to sort results - 'unique', 'total', or 'label'
        limit: Maximum number of results to return

    Returns:
        List of ClosureContribution objects
    """
    cache_key = cache_key_for_import("contribution", import_id, sort_by, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    order_column = {
        'unique': 'unique_contribution DESC NULLS LAST',
        'total': 'total_contribution DESC NULLS LAST',
        'label': 'label ASC',
    }.get(sort_by, 'unique_contribution DESC NULLS LAST')

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, label, package_type, unique_contribution,
                       shared_contribution, total_contribution, closure_size
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                ORDER BY {order_column}
                LIMIT %s
                """,
                (import_id, limit)
            )

            result = [
                ClosureContribution(
                    node_id=row['id'],
                    label=row['label'],
                    package_type=row['package_type'],
                    unique_contribution=row['unique_contribution'] or 0,
                    shared_contribution=row['shared_contribution'] or 0,
                    total_contribution=row['total_contribution'] or 0,
                    closure_size=row['closure_size'],
                )
                for row in cur.fetchall()
            ]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_contribution_summary(import_id: int) -> ClosureContributionSummary | None:
    """Get a summary of closure contributions for an import.

    Args:
        import_id: The import to get summary for

    Returns:
        ClosureContributionSummary with aggregate metrics and top contributors,
        or None if no contribution data has been computed yet.
    """
    cache_key = cache_key_for_import("contribution_summary", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get aggregate metrics
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_top_level,
                    COALESCE(SUM(unique_contribution), 0) as total_unique,
                    COALESCE(SUM(shared_contribution), 0) as total_shared,
                    MAX(contribution_computed_at) as computed_at
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            metrics = cur.fetchone()

            if metrics['total_top_level'] == 0:
                return None

            # Check if contributions have been computed
            cur.execute(
                """
                SELECT COUNT(*) as computed_count
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                """,
                (import_id,)
            )
            computed = cur.fetchone()

            if computed['computed_count'] == 0:
                # Contributions not yet computed
                return None

    # Get top contributors
    top_unique = get_contribution_data(import_id, sort_by='unique', limit=10)
    top_total = get_contribution_data(import_id, sort_by='total', limit=10)

    result = ClosureContributionSummary(
        import_id=import_id,
        total_top_level_packages=metrics['total_top_level'],
        total_unique_contributions=metrics['total_unique'],
        total_shared_contributions=metrics['total_shared'],
        computed_at=metrics['computed_at'],
        top_unique_contributors=top_unique,
        top_total_contributors=top_total,
    )

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_contribution_for_node(node_id: int) -> ClosureContribution | None:
    """Get contribution data for a specific node.

    Args:
        node_id: The node ID to get contribution for

    Returns:
        ClosureContribution for the node, or None if not found/computed
    """
    cache_key = f"contribution:node:{node_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, label, package_type, unique_contribution,
                       shared_contribution, total_contribution, closure_size
                FROM nodes
                WHERE id = %s AND unique_contribution IS NOT NULL
                """,
                (node_id,)
            )
            row = cur.fetchone()

            if not row:
                return None

            result = ClosureContribution(
                node_id=row['id'],
                label=row['label'],
                package_type=row['package_type'],
                unique_contribution=row['unique_contribution'] or 0,
                shared_contribution=row['shared_contribution'] or 0,
                total_contribution=row['total_contribution'] or 0,
                closure_size=row['closure_size'],
            )

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def identify_removal_candidates(
    import_id: int,
    max_unique_threshold: int = 0,
    limit: int = 20,
) -> list[ClosureContribution]:
    """Find packages that can be removed with minimal closure impact.

    Identifies top-level packages with low unique contributions,
    meaning they share most of their dependencies with other packages.

    Args:
        import_id: The import to analyze
        max_unique_threshold: Maximum unique contribution to be considered removable
        limit: Maximum number of candidates to return

    Returns:
        List of ClosureContribution objects for removal candidates
    """
    cache_key = cache_key_for_import(
        "removal_candidates", import_id, max_unique_threshold, limit
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, label, package_type, unique_contribution,
                       shared_contribution, total_contribution, closure_size
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                  AND unique_contribution <= %s
                ORDER BY unique_contribution ASC, shared_contribution DESC
                LIMIT %s
                """,
                (import_id, max_unique_threshold, limit)
            )

            result = [
                ClosureContribution(
                    node_id=row['id'],
                    label=row['label'],
                    package_type=row['package_type'],
                    unique_contribution=row['unique_contribution'] or 0,
                    shared_contribution=row['shared_contribution'] or 0,
                    total_contribution=row['total_contribution'] or 0,
                    closure_size=row['closure_size'],
                )
                for row in cur.fetchall()
            ]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_contribution_by_type(import_id: int) -> dict[str, dict]:
    """Get contribution aggregated by package type.

    Useful for understanding which categories of packages contribute
    most to the closure.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary mapping package_type to aggregate metrics
    """
    cache_key = cache_key_for_import("contribution_by_type", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as package_count,
                    COALESCE(SUM(unique_contribution), 0) as total_unique,
                    COALESCE(SUM(shared_contribution), 0) as total_shared,
                    COALESCE(SUM(total_contribution), 0) as total_overall
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                GROUP BY package_type
                ORDER BY total_overall DESC
                """,
                (import_id,)
            )

            result = {
                row['package_type']: {
                    'package_count': row['package_count'],
                    'total_unique': row['total_unique'],
                    'total_shared': row['total_shared'],
                    'total_overall': row['total_overall'],
                }
                for row in cur.fetchall()
            }

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result
