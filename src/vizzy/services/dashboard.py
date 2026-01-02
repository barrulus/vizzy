"""Dashboard metrics service for System Health Dashboard.

This module provides the backend logic for computing dashboard metrics:
- Total derivations and edges
- Redundancy score (percentage of redundant edges)
- Runtime vs build-time dependency ratio
- Depth statistics
- Top contributors by closure size
- Package type distribution

These metrics answer the question: "How healthy is my system closure?"
"""

from dataclasses import dataclass
from datetime import datetime

from vizzy.database import get_db
from vizzy.models import Node
from vizzy.services.cache import cache, cache_key_for_import


@dataclass
class DepthStats:
    """Statistics about dependency depth in the graph."""
    max_depth: int
    avg_depth: float
    median_depth: float


@dataclass
class BaselineComparison:
    """Comparison against a baseline configuration."""
    baseline_name: str
    node_difference: int
    percentage: float


@dataclass
class DashboardSummary:
    """Complete dashboard summary metrics.

    Contains all key health indicators for a system closure.
    """
    import_id: int
    total_nodes: int
    total_edges: int
    redundancy_score: float  # Percentage of redundant edges (0.0 - 1.0)
    runtime_ratio: float  # Percentage of runtime dependencies (0.0 - 1.0)
    depth_stats: DepthStats
    baseline_comparison: BaselineComparison | None = None


@dataclass
class TopContributor:
    """A package that contributes significantly to closure size."""
    node_id: int
    label: str
    closure_size: int
    package_type: str | None
    unique_contribution: int | None


@dataclass
class TypeDistributionEntry:
    """Distribution of packages by type."""
    package_type: str
    count: int
    percentage: float
    total_closure_size: int


def get_dashboard_summary(import_id: int) -> DashboardSummary | None:
    """Get complete dashboard summary metrics for an import.

    Args:
        import_id: The import to get metrics for

    Returns:
        DashboardSummary with all key metrics, or None if import not found
    """
    cache_key = cache_key_for_import("dashboard_summary", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check import exists and get basic counts
            cur.execute(
                """
                SELECT node_count, edge_count
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            row = cur.fetchone()
            if not row:
                return None

            total_nodes = row['node_count'] or 0
            total_edges = row['edge_count'] or 0

            # If counts are missing, compute them
            if total_nodes == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE import_id = %s",
                    (import_id,)
                )
                total_nodes = cur.fetchone()['cnt']

            if total_edges == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM edges WHERE import_id = %s",
                    (import_id,)
                )
                total_edges = cur.fetchone()['cnt']

            # Get redundancy score (percentage of redundant edges)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_redundant = TRUE) as redundant_count,
                    COUNT(*) as total_count
                FROM edges
                WHERE import_id = %s
                """,
                (import_id,)
            )
            edge_row = cur.fetchone()
            redundant_count = edge_row['redundant_count'] or 0
            edge_total = edge_row['total_count'] or 1  # Avoid division by zero
            redundancy_score = redundant_count / edge_total if edge_total > 0 else 0.0

            # Get runtime vs build-time ratio
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE dependency_type = 'runtime') as runtime_count,
                    COUNT(*) FILTER (WHERE dependency_type = 'build') as build_count,
                    COUNT(*) FILTER (WHERE dependency_type IS NOT NULL) as classified_count
                FROM edges
                WHERE import_id = %s
                """,
                (import_id,)
            )
            dep_row = cur.fetchone()
            runtime_count = dep_row['runtime_count'] or 0
            classified_count = dep_row['classified_count'] or 1
            runtime_ratio = runtime_count / classified_count if classified_count > 0 else 0.0

            # Get depth statistics
            cur.execute(
                """
                SELECT
                    COALESCE(MAX(depth), 0) as max_depth,
                    COALESCE(AVG(depth), 0) as avg_depth,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY depth), 0) as median_depth
                FROM nodes
                WHERE import_id = %s AND depth IS NOT NULL
                """,
                (import_id,)
            )
            depth_row = cur.fetchone()
            depth_stats = DepthStats(
                max_depth=int(depth_row['max_depth'] or 0),
                avg_depth=float(depth_row['avg_depth'] or 0),
                median_depth=float(depth_row['median_depth'] or 0),
            )

    # Get baseline comparison if available
    baseline_comparison = None
    try:
        from vizzy.services import baseline as baseline_service
        comparison = baseline_service.get_comparison_for_dashboard(import_id)
        if comparison:
            baseline_comparison = BaselineComparison(
                baseline_name=comparison.baseline_name,
                node_difference=comparison.node_difference,
                percentage=comparison.percentage_difference,
            )
    except Exception:
        # Baseline service not available or no baselines exist
        pass

    summary = DashboardSummary(
        import_id=import_id,
        total_nodes=total_nodes,
        total_edges=total_edges,
        redundancy_score=redundancy_score,
        runtime_ratio=runtime_ratio,
        depth_stats=depth_stats,
        baseline_comparison=baseline_comparison,
    )

    # Cache for 5 minutes
    cache.set(cache_key, summary, ttl=300)
    return summary


def get_top_contributors(
    import_id: int,
    limit: int = 10,
    top_level_only: bool = True,
) -> list[TopContributor]:
    """Get packages that contribute most to closure size.

    Returns top-level packages ordered by their closure size contribution.

    Args:
        import_id: The import to analyze
        limit: Maximum number of contributors to return
        top_level_only: If True, only return top-level packages

    Returns:
        List of TopContributor objects ordered by closure_size descending
    """
    cache_key = cache_key_for_import("top_contributors", import_id, limit, top_level_only)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            if top_level_only:
                cur.execute(
                    """
                    SELECT id, label, closure_size, package_type, unique_contribution
                    FROM nodes
                    WHERE import_id = %s AND is_top_level = TRUE
                    ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (import_id, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT id, label, closure_size, package_type, unique_contribution
                    FROM nodes
                    WHERE import_id = %s
                    ORDER BY COALESCE(closure_size, 0) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (import_id, limit)
                )

            result = [
                TopContributor(
                    node_id=row['id'],
                    label=row['label'],
                    closure_size=row['closure_size'] or 0,
                    package_type=row['package_type'],
                    unique_contribution=row['unique_contribution'],
                )
                for row in cur.fetchall()
            ]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_type_distribution(import_id: int) -> list[TypeDistributionEntry]:
    """Get distribution of packages by type.

    Returns counts and percentages for each package type.

    Args:
        import_id: The import to analyze

    Returns:
        List of TypeDistributionEntry objects ordered by count descending
    """
    cache_key = cache_key_for_import("type_distribution", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get total node count for percentage calculation
            cur.execute(
                "SELECT COUNT(*) as total FROM nodes WHERE import_id = %s",
                (import_id,)
            )
            total_nodes = cur.fetchone()['total'] or 1

            # Get distribution by package type
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count,
                    COALESCE(SUM(closure_size), 0) as total_closure_size
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                ORDER BY count DESC
                """,
                (import_id,)
            )

            result = [
                TypeDistributionEntry(
                    package_type=row['package_type'] or 'unknown',
                    count=row['count'],
                    percentage=round((row['count'] / total_nodes) * 100, 1),
                    total_closure_size=row['total_closure_size'] or 0,
                )
                for row in cur.fetchall()
            ]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_health_indicators(import_id: int) -> dict:
    """Get health indicators with status assessments.

    Returns health indicators with status (good, warning, critical)
    based on threshold values.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary with health indicators and their status
    """
    summary = get_dashboard_summary(import_id)
    if not summary:
        return {}

    # Assess redundancy health
    if summary.redundancy_score < 0.05:
        redundancy_status = "good"
    elif summary.redundancy_score < 0.10:
        redundancy_status = "warning"
    else:
        redundancy_status = "critical"

    # Assess depth health (deeper graphs may indicate complexity issues)
    if summary.depth_stats.avg_depth < 5:
        depth_status = "good"
    elif summary.depth_stats.avg_depth < 8:
        depth_status = "warning"
    else:
        depth_status = "critical"

    return {
        "redundancy": {
            "value": summary.redundancy_score,
            "percentage": round(summary.redundancy_score * 100, 1),
            "status": redundancy_status,
            "label": "redundancy",
            "description": "Percentage of edges that are redundant (can be removed)",
        },
        "runtime_ratio": {
            "value": summary.runtime_ratio,
            "percentage": round(summary.runtime_ratio * 100, 1),
            "status": "info",  # No good/bad for this metric
            "label": "runtime dependencies",
            "description": "Percentage of dependencies that are runtime (vs build-time)",
        },
        "depth": {
            "avg": round(summary.depth_stats.avg_depth, 1),
            "max": summary.depth_stats.max_depth,
            "median": round(summary.depth_stats.median_depth, 1),
            "status": depth_status,
            "label": "avg depth",
            "description": "Average dependency chain depth",
        },
        "total_nodes": {
            "value": summary.total_nodes,
            "formatted": f"{summary.total_nodes:,}",
            "label": "derivations",
        },
        "total_edges": {
            "value": summary.total_edges,
            "formatted": f"{summary.total_edges:,}",
            "label": "dependencies",
        },
    }


def invalidate_dashboard_cache(import_id: int) -> int:
    """Invalidate all dashboard cache entries for an import.

    Call this when data changes that affects dashboard metrics.

    Args:
        import_id: The import to invalidate cache for

    Returns:
        Number of cache entries invalidated
    """
    count = 0
    for key_suffix in ["dashboard_summary", "top_contributors", "type_distribution"]:
        cache_key = cache_key_for_import(key_suffix, import_id)
        if cache.delete(cache_key):
            count += 1
    return count
