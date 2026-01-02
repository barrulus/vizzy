"""Baseline closure reference system for comparative context.

This module provides functionality for creating and comparing against baseline
configurations. Baselines are lightweight snapshots of import metrics that
can be used to:
- Compare current system closure against known reference points
- Track closure growth over time
- Compare against previous system states
- Share standardized baselines across teams

Related tasks:
- 8A-004: Create baseline closure reference system
- 8F-004: Add baseline comparison presets (uses this)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import json
import logging

from vizzy.database import get_db
from vizzy.services.cache import cache, cache_key_for_import

logger = logging.getLogger("vizzy.baseline")


@dataclass
class Baseline:
    """A baseline reference configuration for comparison.

    Contains snapshot metrics from an import that persist even if
    the source import is deleted.
    """
    id: int
    name: str
    description: str | None
    source_import_id: int | None
    node_count: int
    edge_count: int
    closure_by_type: dict[str, int]
    top_level_count: int | None
    runtime_edge_count: int | None
    build_edge_count: int | None
    max_depth: int | None
    avg_depth: float | None
    top_contributors: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    is_system_baseline: bool
    tags: list[str]


@dataclass
class BaselineComparison:
    """Result of comparing an import against a baseline.

    Contains summary metrics and detailed differences for display
    in the dashboard and comparison views.
    """
    import_id: int
    baseline_id: int
    baseline_name: str

    # Summary differences
    node_difference: int           # import.nodes - baseline.nodes
    edge_difference: int           # import.edges - baseline.edges
    percentage_difference: float   # ((import - baseline) / baseline) * 100

    # Detailed differences by package type
    differences_by_type: dict[str, int]

    # Interpretation helpers
    is_larger: bool               # True if import has more nodes
    growth_category: str          # "minimal", "moderate", "significant", "excessive"

    computed_at: datetime


@dataclass
class BaselineCreateResult:
    """Result of creating a baseline."""
    baseline_id: int
    name: str
    node_count: int
    edge_count: int
    success: bool
    message: str


def create_baseline_from_import(
    import_id: int,
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
    is_system_baseline: bool = False,
) -> BaselineCreateResult:
    """Create a baseline snapshot from an existing import.

    This captures the current state of an import as a baseline for
    future comparisons. The baseline persists even if the source
    import is later deleted.

    Args:
        import_id: The import to create a baseline from
        name: User-friendly name for the baseline
        description: Optional description of what this baseline represents
        tags: Optional list of tags for categorization
        is_system_baseline: True for built-in reference baselines

    Returns:
        BaselineCreateResult with the created baseline info

    Raises:
        ValueError: If the import doesn't exist
    """
    tags = tags or []

    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify import exists and get basic counts
            cur.execute(
                """
                SELECT node_count, edge_count, name
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            import_row = cur.fetchone()
            if not import_row:
                return BaselineCreateResult(
                    baseline_id=0,
                    name=name,
                    node_count=0,
                    edge_count=0,
                    success=False,
                    message=f"Import {import_id} not found"
                )

            node_count = import_row['node_count'] or 0
            edge_count = import_row['edge_count'] or 0

            # Get actual counts if not stored
            if node_count == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE import_id = %s",
                    (import_id,)
                )
                node_count = cur.fetchone()['cnt']

            if edge_count == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM edges WHERE import_id = %s",
                    (import_id,)
                )
                edge_count = cur.fetchone()['cnt']

            # Get closure breakdown by package type
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                """,
                (import_id,)
            )
            closure_by_type = {row['package_type']: row['count'] for row in cur.fetchall()}

            # Get top-level count
            cur.execute(
                """
                SELECT COUNT(*) as cnt
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                """,
                (import_id,)
            )
            top_level_count = cur.fetchone()['cnt']

            # Get edge type counts
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE dependency_type = 'runtime') as runtime_count,
                    COUNT(*) FILTER (WHERE dependency_type = 'build') as build_count
                FROM edges
                WHERE import_id = %s
                """,
                (import_id,)
            )
            edge_types = cur.fetchone()
            runtime_edge_count = edge_types['runtime_count'] or 0
            build_edge_count = edge_types['build_count'] or 0

            # Get depth statistics
            cur.execute(
                """
                SELECT
                    COALESCE(MAX(depth), 0) as max_depth,
                    COALESCE(AVG(depth), 0) as avg_depth
                FROM nodes
                WHERE import_id = %s AND depth IS NOT NULL
                """,
                (import_id,)
            )
            depth_row = cur.fetchone()
            max_depth = int(depth_row['max_depth'] or 0)
            avg_depth = float(depth_row['avg_depth'] or 0)

            # Get top contributors
            cur.execute(
                """
                SELECT label, closure_size
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                ORDER BY COALESCE(closure_size, 0) DESC
                LIMIT 10
                """,
                (import_id,)
            )
            top_contributors = [
                {"label": row['label'], "closure_size": row['closure_size'] or 0}
                for row in cur.fetchall()
            ]

            # Insert the baseline
            cur.execute(
                """
                INSERT INTO baselines (
                    name, description, source_import_id,
                    node_count, edge_count, closure_by_type,
                    top_level_count, runtime_edge_count, build_edge_count,
                    max_depth, avg_depth, top_contributors,
                    is_system_baseline, tags
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    name, description, import_id,
                    node_count, edge_count, json.dumps(closure_by_type),
                    top_level_count, runtime_edge_count, build_edge_count,
                    max_depth, avg_depth, json.dumps(top_contributors),
                    is_system_baseline, tags
                )
            )
            baseline_id = cur.fetchone()['id']
            conn.commit()

            logger.info(
                f"Created baseline '{name}' (id={baseline_id}) "
                f"from import {import_id}: {node_count} nodes, {edge_count} edges"
            )

            return BaselineCreateResult(
                baseline_id=baseline_id,
                name=name,
                node_count=node_count,
                edge_count=edge_count,
                success=True,
                message=f"Created baseline '{name}' with {node_count} nodes"
            )


def get_baseline(baseline_id: int) -> Baseline | None:
    """Get a baseline by ID.

    Args:
        baseline_id: The baseline ID

    Returns:
        Baseline object or None if not found
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM baselines
                WHERE id = %s
                """,
                (baseline_id,)
            )
            row = cur.fetchone()
            if not row:
                return None

            return _row_to_baseline(row)


def list_baselines(
    include_system: bool = True,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[Baseline]:
    """List all available baselines.

    Args:
        include_system: Whether to include system baselines
        tags: Optional filter by tags (any match)
        limit: Maximum number of baselines to return

    Returns:
        List of Baseline objects
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            query = "SELECT * FROM baselines WHERE 1=1"
            params: list[Any] = []

            if not include_system:
                query += " AND is_system_baseline = FALSE"

            if tags:
                query += " AND tags && %s"
                params.append(tags)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            return [_row_to_baseline(row) for row in cur.fetchall()]


def compare_to_baseline(import_id: int, baseline_id: int) -> BaselineComparison | None:
    """Compare an import against a baseline.

    This computes differences between the current import and a stored
    baseline, providing metrics useful for understanding closure growth.

    Args:
        import_id: The import to compare
        baseline_id: The baseline to compare against

    Returns:
        BaselineComparison with detailed differences, or None if not found

    Note:
        Results are cached in the baseline_comparisons table for performance.
        Use invalidate_comparison() to force recomputation.
    """
    # Check cache first
    cache_key = f"baseline_comparison:{import_id}:{baseline_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if we have a cached comparison in the database
            cur.execute(
                """
                SELECT bc.*, b.name as baseline_name
                FROM baseline_comparisons bc
                JOIN baselines b ON b.id = bc.baseline_id
                WHERE bc.import_id = %s AND bc.baseline_id = %s
                """,
                (import_id, baseline_id)
            )
            cached_row = cur.fetchone()

            if cached_row:
                comparison = _row_to_comparison(cached_row)
                cache.set(cache_key, comparison, ttl=300)
                return comparison

            # No cache, compute the comparison
            # Get import data
            cur.execute(
                """
                SELECT node_count, edge_count
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            import_row = cur.fetchone()
            if not import_row:
                return None

            import_nodes = import_row['node_count'] or 0
            import_edges = import_row['edge_count'] or 0

            # Get actual counts if needed
            if import_nodes == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE import_id = %s",
                    (import_id,)
                )
                import_nodes = cur.fetchone()['cnt']

            if import_edges == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM edges WHERE import_id = %s",
                    (import_id,)
                )
                import_edges = cur.fetchone()['cnt']

            # Get import breakdown by type
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                """,
                (import_id,)
            )
            import_by_type = {row['package_type']: row['count'] for row in cur.fetchall()}

            # Get baseline data
            cur.execute(
                """
                SELECT name, node_count, edge_count, closure_by_type
                FROM baselines
                WHERE id = %s
                """,
                (baseline_id,)
            )
            baseline_row = cur.fetchone()
            if not baseline_row:
                return None

            baseline_name = baseline_row['name']
            baseline_nodes = baseline_row['node_count']
            baseline_edges = baseline_row['edge_count']
            baseline_by_type = baseline_row['closure_by_type'] or {}

            # Ensure baseline_by_type is a dict (might be JSON string)
            if isinstance(baseline_by_type, str):
                baseline_by_type = json.loads(baseline_by_type)

            # Compute differences
            node_diff = import_nodes - baseline_nodes
            edge_diff = import_edges - baseline_edges
            pct_diff = ((import_nodes - baseline_nodes) / baseline_nodes * 100) if baseline_nodes > 0 else 0

            # Compute differences by type
            all_types = set(import_by_type.keys()) | set(baseline_by_type.keys())
            differences_by_type = {}
            for pkg_type in all_types:
                import_count = import_by_type.get(pkg_type, 0)
                baseline_count = baseline_by_type.get(pkg_type, 0)
                differences_by_type[pkg_type] = import_count - baseline_count

            # Categorize growth
            if pct_diff < 5:
                growth_category = "minimal"
            elif pct_diff < 15:
                growth_category = "moderate"
            elif pct_diff < 30:
                growth_category = "significant"
            else:
                growth_category = "excessive"

            now = datetime.now()

            # Cache in database
            cur.execute(
                """
                INSERT INTO baseline_comparisons (
                    import_id, baseline_id,
                    node_difference, edge_difference, percentage_difference,
                    differences_by_type, computed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (import_id, baseline_id) DO UPDATE SET
                    node_difference = EXCLUDED.node_difference,
                    edge_difference = EXCLUDED.edge_difference,
                    percentage_difference = EXCLUDED.percentage_difference,
                    differences_by_type = EXCLUDED.differences_by_type,
                    computed_at = EXCLUDED.computed_at
                """,
                (
                    import_id, baseline_id,
                    node_diff, edge_diff, pct_diff,
                    json.dumps(differences_by_type), now
                )
            )
            conn.commit()

            comparison = BaselineComparison(
                import_id=import_id,
                baseline_id=baseline_id,
                baseline_name=baseline_name,
                node_difference=node_diff,
                edge_difference=edge_diff,
                percentage_difference=round(pct_diff, 2),
                differences_by_type=differences_by_type,
                is_larger=node_diff > 0,
                growth_category=growth_category,
                computed_at=now,
            )

            cache.set(cache_key, comparison, ttl=300)
            return comparison


def delete_baseline(baseline_id: int) -> bool:
    """Delete a baseline.

    Note: System baselines cannot be deleted.

    Args:
        baseline_id: The baseline to delete

    Returns:
        True if deleted, False if not found or system baseline
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM baselines
                WHERE id = %s AND is_system_baseline = FALSE
                RETURNING id
                """,
                (baseline_id,)
            )
            result = cur.fetchone()
            conn.commit()
            return result is not None


def update_baseline(
    baseline_id: int,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Baseline | None:
    """Update baseline metadata.

    Note: Cannot update metrics - those are captured at creation time.

    Args:
        baseline_id: The baseline to update
        name: New name (optional)
        description: New description (optional)
        tags: New tags (optional)

    Returns:
        Updated Baseline or None if not found
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            updates = []
            params: list[Any] = []

            if name is not None:
                updates.append("name = %s")
                params.append(name)

            if description is not None:
                updates.append("description = %s")
                params.append(description)

            if tags is not None:
                updates.append("tags = %s")
                params.append(tags)

            if not updates:
                return get_baseline(baseline_id)

            updates.append("updated_at = NOW()")
            params.append(baseline_id)

            query = f"""
                UPDATE baselines
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """

            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()

            if not row:
                return None

            return _row_to_baseline(row)


def invalidate_comparison(import_id: int, baseline_id: int | None = None) -> int:
    """Invalidate cached comparisons.

    Call this when import data changes and comparisons need recomputation.

    Args:
        import_id: The import whose comparisons to invalidate
        baseline_id: Optional specific baseline to invalidate (all if None)

    Returns:
        Number of comparisons invalidated
    """
    # Clear in-memory cache
    cache.invalidate(f"baseline_comparison:{import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            if baseline_id:
                cur.execute(
                    """
                    DELETE FROM baseline_comparisons
                    WHERE import_id = %s AND baseline_id = %s
                    """,
                    (import_id, baseline_id)
                )
            else:
                cur.execute(
                    """
                    DELETE FROM baseline_comparisons
                    WHERE import_id = %s
                    """,
                    (import_id,)
                )
            count = cur.rowcount
            conn.commit()
            return count


def get_comparison_for_dashboard(import_id: int) -> BaselineComparison | None:
    """Get the best baseline comparison for dashboard display.

    This selects the most appropriate baseline for comparison:
    1. First system baseline (if any)
    2. Most recent user baseline

    Args:
        import_id: The import to find a comparison for

    Returns:
        BaselineComparison or None if no baselines exist
    """
    cache_key = cache_key_for_import("dashboard_baseline", import_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Try system baseline first
            cur.execute(
                """
                SELECT id FROM baselines
                WHERE is_system_baseline = TRUE
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()

            if not row:
                # Fall back to most recent user baseline
                cur.execute(
                    """
                    SELECT id FROM baselines
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()

            if not row:
                return None

            baseline_id = row['id']
            comparison = compare_to_baseline(import_id, baseline_id)

            if comparison:
                cache.set(cache_key, comparison, ttl=300)

            return comparison


def _row_to_baseline(row: dict) -> Baseline:
    """Convert a database row to a Baseline object."""
    closure_by_type = row['closure_by_type']
    if isinstance(closure_by_type, str):
        closure_by_type = json.loads(closure_by_type)

    top_contributors = row['top_contributors']
    if isinstance(top_contributors, str):
        top_contributors = json.loads(top_contributors)

    tags = row['tags']
    if tags is None:
        tags = []

    return Baseline(
        id=row['id'],
        name=row['name'],
        description=row['description'],
        source_import_id=row['source_import_id'],
        node_count=row['node_count'],
        edge_count=row['edge_count'],
        closure_by_type=closure_by_type or {},
        top_level_count=row['top_level_count'],
        runtime_edge_count=row['runtime_edge_count'],
        build_edge_count=row['build_edge_count'],
        max_depth=row['max_depth'],
        avg_depth=row['avg_depth'],
        top_contributors=top_contributors or [],
        created_at=row['created_at'],
        updated_at=row['updated_at'],
        is_system_baseline=row['is_system_baseline'],
        tags=tags,
    )


def _row_to_comparison(row: dict) -> BaselineComparison:
    """Convert a database row to a BaselineComparison object."""
    differences_by_type = row['differences_by_type']
    if isinstance(differences_by_type, str):
        differences_by_type = json.loads(differences_by_type)

    pct_diff = row['percentage_difference']
    if pct_diff < 5:
        growth_category = "minimal"
    elif pct_diff < 15:
        growth_category = "moderate"
    elif pct_diff < 30:
        growth_category = "significant"
    else:
        growth_category = "excessive"

    return BaselineComparison(
        import_id=row['import_id'],
        baseline_id=row['baseline_id'],
        baseline_name=row['baseline_name'],
        node_difference=row['node_difference'],
        edge_difference=row['edge_difference'],
        percentage_difference=round(pct_diff, 2),
        differences_by_type=differences_by_type or {},
        is_larger=row['node_difference'] > 0,
        growth_category=growth_category,
        computed_at=row['computed_at'],
    )


# =============================================================================
# Baseline Comparison Presets (Phase 8F-004)
# =============================================================================


@dataclass
class BaselinePreset:
    """A preset option for baseline comparison.

    Presets provide quick access to common comparison targets:
    - Previous import of the same host
    - System baselines (minimal NixOS, etc.)
    - User-saved baselines
    """
    id: str  # Unique identifier (e.g., "previous", "baseline:123")
    name: str  # Display name
    description: str | None
    preset_type: str  # "previous_import", "baseline", "system_baseline"
    target_id: int | None  # Import ID or baseline ID
    node_count: int | None
    edge_count: int | None
    created_at: datetime | None


def get_previous_import(import_id: int) -> dict | None:
    """Get the previous import for the same host.

    Finds the most recent import with the same name as the given import
    that was imported before it.

    Args:
        import_id: The current import ID

    Returns:
        Import info dict or None if no previous import exists
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get the current import's name and timestamp
            cur.execute(
                """
                SELECT name, imported_at
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            current = cur.fetchone()
            if not current:
                return None

            # Find the most recent import with the same name, imported before this one
            cur.execute(
                """
                SELECT id, name, config_path, drv_path, imported_at, node_count, edge_count
                FROM imports
                WHERE name = %s
                  AND imported_at < %s
                ORDER BY imported_at DESC
                LIMIT 1
                """,
                (current['name'], current['imported_at'])
            )
            previous = cur.fetchone()
            if not previous:
                return None

            return dict(previous)


def get_available_presets(import_id: int) -> list[BaselinePreset]:
    """Get all available comparison presets for an import.

    Returns a list of presets including:
    1. Previous import (if available)
    2. System baselines (minimal NixOS, etc.)
    3. User-saved baselines

    The presets are ordered by relevance and usefulness.

    Args:
        import_id: The import to get presets for

    Returns:
        List of BaselinePreset objects
    """
    presets: list[BaselinePreset] = []

    # 1. Check for previous import
    previous = get_previous_import(import_id)
    if previous:
        presets.append(BaselinePreset(
            id=f"import:{previous['id']}",
            name="Previous Import",
            description=f"Compare with previous import of {previous['name']} from {previous['imported_at'].strftime('%Y-%m-%d %H:%M')}",
            preset_type="previous_import",
            target_id=previous['id'],
            node_count=previous['node_count'],
            edge_count=previous['edge_count'],
            created_at=previous['imported_at'],
        ))

    # 2. Get all baselines (system first, then user)
    baselines = list_baselines(include_system=True, limit=50)

    # Add system baselines first
    for baseline in baselines:
        if baseline.is_system_baseline:
            presets.append(BaselinePreset(
                id=f"baseline:{baseline.id}",
                name=baseline.name,
                description=baseline.description or f"System baseline with {baseline.node_count:,} packages",
                preset_type="system_baseline",
                target_id=baseline.id,
                node_count=baseline.node_count,
                edge_count=baseline.edge_count,
                created_at=baseline.created_at,
            ))

    # Add user baselines
    for baseline in baselines:
        if not baseline.is_system_baseline:
            presets.append(BaselinePreset(
                id=f"baseline:{baseline.id}",
                name=baseline.name,
                description=baseline.description or f"User baseline with {baseline.node_count:,} packages",
                preset_type="baseline",
                target_id=baseline.id,
                node_count=baseline.node_count,
                edge_count=baseline.edge_count,
                created_at=baseline.created_at,
            ))

    return presets


def get_imports_for_host(host_name: str, limit: int = 20) -> list[dict]:
    """Get all imports for a specific host.

    Useful for comparing different versions of the same host over time.

    Args:
        host_name: The host name to find imports for
        limit: Maximum number of imports to return

    Returns:
        List of import info dicts, newest first
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, config_path, drv_path, imported_at, node_count, edge_count
                FROM imports
                WHERE name = %s
                ORDER BY imported_at DESC
                LIMIT %s
                """,
                (host_name, limit)
            )
            return [dict(row) for row in cur.fetchall()]


def create_baseline_with_auto_name(import_id: int, suffix: str | None = None) -> BaselineCreateResult:
    """Create a baseline with an automatically generated name.

    The name is based on the import name and timestamp.

    Args:
        import_id: The import to create a baseline from
        suffix: Optional suffix to add to the name

    Returns:
        BaselineCreateResult with the created baseline info
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, imported_at
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            import_info = cur.fetchone()
            if not import_info:
                return BaselineCreateResult(
                    baseline_id=0,
                    name="",
                    node_count=0,
                    edge_count=0,
                    success=False,
                    message=f"Import {import_id} not found"
                )

            # Generate name
            base_name = f"{import_info['name']} - {import_info['imported_at'].strftime('%Y-%m-%d')}"
            if suffix:
                base_name = f"{base_name} ({suffix})"

            return create_baseline_from_import(
                import_id=import_id,
                name=base_name,
                description=f"Baseline created from {import_info['name']} import",
                tags=["auto-created"],
            )


def get_baseline_by_source_import(source_import_id: int) -> Baseline | None:
    """Get a baseline that was created from a specific import.

    Args:
        source_import_id: The source import ID

    Returns:
        Baseline or None if not found
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM baselines
                WHERE source_import_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (source_import_id,)
            )
            row = cur.fetchone()
            if not row:
                return None

            return _row_to_baseline(row)


def compare_to_previous_import(import_id: int) -> BaselineComparison | None:
    """Compare an import to its previous version.

    This is a convenience function that finds the previous import
    of the same host and computes a comparison.

    Args:
        import_id: The current import ID

    Returns:
        BaselineComparison or None if no previous import exists
    """
    previous = get_previous_import(import_id)
    if not previous:
        return None

    # For import-to-import comparison, we need to create a temporary
    # comparison result. We'll compute it directly.
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get current import counts
            cur.execute(
                """
                SELECT name, node_count, edge_count
                FROM imports
                WHERE id = %s
                """,
                (import_id,)
            )
            current = cur.fetchone()
            if not current:
                return None

            current_nodes = current['node_count'] or 0
            current_edges = current['edge_count'] or 0
            previous_nodes = previous['node_count'] or 0
            previous_edges = previous['edge_count'] or 0

            if current_nodes == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE import_id = %s",
                    (import_id,)
                )
                current_nodes = cur.fetchone()['cnt']

            if current_edges == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM edges WHERE import_id = %s",
                    (import_id,)
                )
                current_edges = cur.fetchone()['cnt']

            if previous_nodes == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE import_id = %s",
                    (previous['id'],)
                )
                previous_nodes = cur.fetchone()['cnt']

            if previous_edges == 0:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM edges WHERE import_id = %s",
                    (previous['id'],)
                )
                previous_edges = cur.fetchone()['cnt']

            # Get current breakdown by type
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                """,
                (import_id,)
            )
            current_by_type = {row['package_type']: row['count'] for row in cur.fetchall()}

            # Get previous breakdown by type
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                """,
                (previous['id'],)
            )
            previous_by_type = {row['package_type']: row['count'] for row in cur.fetchall()}

            # Compute differences
            node_diff = current_nodes - previous_nodes
            edge_diff = current_edges - previous_edges
            pct_diff = ((current_nodes - previous_nodes) / previous_nodes * 100) if previous_nodes > 0 else 0

            all_types = set(current_by_type.keys()) | set(previous_by_type.keys())
            differences_by_type = {}
            for pkg_type in all_types:
                current_count = current_by_type.get(pkg_type, 0)
                previous_count = previous_by_type.get(pkg_type, 0)
                differences_by_type[pkg_type] = current_count - previous_count

            # Categorize growth
            if pct_diff < 5:
                growth_category = "minimal"
            elif pct_diff < 15:
                growth_category = "moderate"
            elif pct_diff < 30:
                growth_category = "significant"
            else:
                growth_category = "excessive"

            return BaselineComparison(
                import_id=import_id,
                baseline_id=previous['id'],  # Use previous import ID as "baseline" ID
                baseline_name=f"Previous: {previous['name']} ({previous['imported_at'].strftime('%Y-%m-%d')})",
                node_difference=node_diff,
                edge_difference=edge_diff,
                percentage_difference=round(pct_diff, 2),
                differences_by_type=differences_by_type,
                is_larger=node_diff > 0,
                growth_category=growth_category,
                computed_at=datetime.now(),
            )
