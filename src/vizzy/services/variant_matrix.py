"""Variant Matrix data service for enhanced duplicate visualization.

This module provides the backend logic for generating matrix data showing
which applications use which package variants. It answers the question:
"Which of my packages are causing duplicate derivations?"

The Variant Matrix extends the basic duplicates view by showing a clear
matrix layout of variants (columns) vs dependents (rows), making it easy
to identify:
- Which apps share variants (consolidation opportunities)
- Which apps use unique variants (potential build issues)
- Dependency type patterns (runtime vs build-time)

Example matrix for openssl variants:
                | openssl-3.0   | openssl-3.0   | openssl-1.1
                | (runtime)     | (static)      | (legacy)
    ------------+---------------+---------------+-------------
    firefox     |      *        |               |
    curl        |      *        |               |
    rustc       |               |      *        |
    python-ssl  |               |               |      *
    ------------+---------------+---------------+-------------
    Dependents  |      12       |       5       |       3

Performance considerations:
- Limits variants per package (default 20)
- Limits dependents per variant (default 50)
- Caches results for 10 minutes
- Includes dependency type information where available
"""

from dataclasses import dataclass, field
from typing import Any

from vizzy.database import get_db
from vizzy.models import Node
from vizzy.services.cache import cache, cache_key_for_import


# Configuration constants
MAX_VARIANTS = 20
MAX_DEPENDENTS_PER_VARIANT = 50
MAX_APPLICATIONS = 100


@dataclass
class VariantInfo:
    """Information about a single package variant.

    A variant is one of multiple derivations of the same package name,
    distinguished by different hashes (due to different build inputs).
    """
    node_id: int
    drv_hash: str
    short_hash: str  # First 12 chars for display
    label: str
    package_type: str | None
    dependency_type: str | None  # 'build', 'runtime', 'mixed', or None
    dependent_count: int
    closure_size: int | None


@dataclass
class ApplicationRow:
    """A row in the variant matrix showing which variants an app uses.

    Each cell indicates whether this application depends on that variant,
    and optionally includes the dependency type.
    """
    label: str
    node_id: int | None
    package_type: str | None
    is_top_level: bool
    cells: dict[int, dict[str, Any]]  # variant_node_id -> {has_dep, dep_type}


@dataclass
class VariantMatrix:
    """Complete matrix data for variant visualization.

    Contains all the information needed to render the variant matrix UI.
    """
    label: str  # Package name (e.g., "openssl")
    import_id: int
    variants: list[VariantInfo]
    applications: list[ApplicationRow]
    total_variants: int
    total_dependents: int
    has_build_runtime_info: bool  # True if edge classification is available

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "label": self.label,
            "import_id": self.import_id,
            "variants": [
                {
                    "node_id": v.node_id,
                    "drv_hash": v.drv_hash,
                    "short_hash": v.short_hash,
                    "label": v.label,
                    "package_type": v.package_type,
                    "dependency_type": v.dependency_type,
                    "dependent_count": v.dependent_count,
                    "closure_size": v.closure_size,
                }
                for v in self.variants
            ],
            "applications": [
                {
                    "label": app.label,
                    "node_id": app.node_id,
                    "package_type": app.package_type,
                    "is_top_level": app.is_top_level,
                    "cells": app.cells,
                }
                for app in self.applications
            ],
            "total_variants": self.total_variants,
            "total_dependents": self.total_dependents,
            "has_build_runtime_info": self.has_build_runtime_info,
        }


def build_variant_matrix(
    import_id: int,
    label: str,
    max_variants: int = MAX_VARIANTS,
    max_dependents: int = MAX_DEPENDENTS_PER_VARIANT,
    sort_by: str = "dependent_count",  # "dependent_count", "hash", or "closure_size"
    filter_type: str = "all",  # "all", "runtime", "build"
    direct_only: bool = False,  # If True, only show direct dependents (no transitive)
) -> VariantMatrix:
    """Build matrix data showing which apps use which package variants.

    This is the main entry point for the variant matrix feature. It returns
    a structured matrix showing the relationship between package variants
    and their dependents.

    Args:
        import_id: The import to analyze
        label: Package name to find variants for (e.g., "openssl")
        max_variants: Maximum number of variants to include
        max_dependents: Maximum dependents per variant
        sort_by: How to sort variants ("dependent_count", "hash", "closure_size")
        filter_type: Filter edges by type ("all", "runtime", "build")
        direct_only: If True, only include direct dependents (immediate edges only)

    Returns:
        VariantMatrix with all data needed for visualization

    Example:
        >>> matrix = build_variant_matrix(1, "openssl")
        >>> print(f"Found {matrix.total_variants} variants")
        Found 3 variants
    """
    # Build cache key
    cache_key = cache_key_for_import(
        "variant_matrix", import_id, label, max_variants,
        max_dependents, sort_by, filter_type, direct_only
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants of this package
            order_clause = _get_sort_order(sort_by)
            cur.execute(
                f"""
                SELECT id, drv_hash, label, package_type, closure_size
                FROM nodes
                WHERE import_id = %s AND label = %s
                ORDER BY {order_clause}
                LIMIT %s
                """,
                (import_id, label, max_variants)
            )
            variant_rows = cur.fetchall()

            if not variant_rows:
                # No variants found - return empty matrix
                return VariantMatrix(
                    label=label,
                    import_id=import_id,
                    variants=[],
                    applications=[],
                    total_variants=0,
                    total_dependents=0,
                    has_build_runtime_info=False,
                )

            # Check if we have edge classification data
            cur.execute(
                """
                SELECT COUNT(*) as classified
                FROM edges
                WHERE import_id = %s AND dependency_type IS NOT NULL
                LIMIT 1
                """,
                (import_id,)
            )
            has_edge_classification = cur.fetchone()['classified'] > 0

            # Build variant info list and collect all dependents
            variants: list[VariantInfo] = []
            all_dependent_ids: set[int] = set()
            variant_dependents: dict[int, set[int]] = {}  # variant_id -> set of dependent node_ids
            variant_dep_types: dict[int, dict[int, str]] = {}  # variant_id -> {dep_id: dep_type}

            for row in variant_rows:
                variant_id = row['id']

                # Build filter clause for edge types
                filter_clause = _get_dependency_type_filter(filter_type)

                # Get dependents for this variant (nodes that depend on it)
                cur.execute(
                    f"""
                    SELECT e.target_id as dep_id, n.label, n.package_type, n.is_top_level,
                           e.dependency_type
                    FROM edges e
                    JOIN nodes n ON e.target_id = n.id
                    WHERE e.source_id = %s
                    {filter_clause}
                    ORDER BY n.is_top_level DESC, n.label
                    LIMIT %s
                    """,
                    (variant_id, max_dependents)
                )
                deps = cur.fetchall()

                # Count total dependents (may exceed limit)
                cur.execute(
                    f"""
                    SELECT COUNT(*) as total
                    FROM edges e
                    WHERE e.source_id = %s
                    {filter_clause}
                    """,
                    (variant_id,)
                )
                total_deps = cur.fetchone()['total']

                # Track dependents for matrix
                dep_ids = set()
                dep_types = {}
                for dep in deps:
                    dep_id = dep['dep_id']
                    dep_ids.add(dep_id)
                    all_dependent_ids.add(dep_id)
                    if dep['dependency_type']:
                        dep_types[dep_id] = dep['dependency_type']

                variant_dependents[variant_id] = dep_ids
                variant_dep_types[variant_id] = dep_types

                # Determine overall dependency type for this variant
                overall_dep_type = _determine_variant_dep_type(dep_types.values())

                variants.append(VariantInfo(
                    node_id=variant_id,
                    drv_hash=row['drv_hash'],
                    short_hash=row['drv_hash'][:12],
                    label=row['label'],
                    package_type=row['package_type'],
                    dependency_type=overall_dep_type,
                    dependent_count=total_deps,
                    closure_size=row['closure_size'],
                ))

            # Build application rows
            applications: list[ApplicationRow] = []

            if all_dependent_ids:
                # Fetch all dependent node info in one query
                # If direct_only is True, filter to only top-level packages
                if direct_only:
                    cur.execute(
                        """
                        SELECT id, label, package_type, is_top_level
                        FROM nodes
                        WHERE id = ANY(%s) AND is_top_level = TRUE
                        ORDER BY label
                        LIMIT %s
                        """,
                        (list(all_dependent_ids), MAX_APPLICATIONS)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, label, package_type, is_top_level
                        FROM nodes
                        WHERE id = ANY(%s)
                        ORDER BY is_top_level DESC, label
                        LIMIT %s
                        """,
                        (list(all_dependent_ids), MAX_APPLICATIONS)
                    )
                dep_nodes = cur.fetchall()

                for dep_node in dep_nodes:
                    dep_id = dep_node['id']

                    # Build cells for each variant
                    cells: dict[int, dict[str, Any]] = {}
                    for variant in variants:
                        variant_id = variant.node_id
                        has_dep = dep_id in variant_dependents.get(variant_id, set())
                        dep_type = variant_dep_types.get(variant_id, {}).get(dep_id)

                        cells[variant_id] = {
                            "has_dep": has_dep,
                            "dep_type": dep_type,
                        }

                    applications.append(ApplicationRow(
                        label=dep_node['label'],
                        node_id=dep_node['id'],
                        package_type=dep_node['package_type'],
                        is_top_level=dep_node['is_top_level'],
                        cells=cells,
                    ))

            # Get total variant count (may be more than max_variants)
            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM nodes
                WHERE import_id = %s AND label = %s
                """,
                (import_id, label)
            )
            total_variants = cur.fetchone()['total']

    matrix = VariantMatrix(
        label=label,
        import_id=import_id,
        variants=variants,
        applications=applications,
        total_variants=total_variants,
        total_dependents=len(all_dependent_ids),
        has_build_runtime_info=has_edge_classification,
    )

    # Cache for 10 minutes
    cache.set(cache_key, matrix, ttl=600)
    return matrix


def _get_sort_order(sort_by: str) -> str:
    """Get SQL ORDER BY clause for variant sorting.

    Args:
        sort_by: Sort mode - "dependent_count", "hash", or "closure_size"

    Returns:
        SQL ORDER BY expression
    """
    if sort_by == "hash":
        return "drv_hash"
    elif sort_by == "closure_size":
        return "COALESCE(closure_size, 0) DESC"
    else:  # dependent_count is default
        # We'll re-order after counting dependents, so use hash as stable sort
        return "drv_hash"


def _get_dependency_type_filter(filter_type: str) -> str:
    """Get SQL WHERE clause fragment for dependency type filtering.

    Args:
        filter_type: Filter mode - "all", "runtime", or "build"

    Returns:
        SQL WHERE clause fragment (including AND prefix if needed)
    """
    if filter_type == "runtime":
        return "AND e.dependency_type = 'runtime'"
    elif filter_type == "build":
        return "AND e.dependency_type = 'build'"
    return ""


def _determine_variant_dep_type(dep_types: list[str] | Any) -> str | None:
    """Determine overall dependency type for a variant based on its edges.

    Args:
        dep_types: Collection of dependency types from edges

    Returns:
        "runtime", "build", "mixed", or None if no type info
    """
    types = set(dep_types) if dep_types else set()
    types.discard(None)

    if not types:
        return None
    elif len(types) == 1:
        return list(types)[0]
    else:
        return "mixed"


def get_variant_labels(import_id: int, min_count: int = 2, limit: int = 50) -> list[dict[str, Any]]:
    """Get list of package labels that have multiple variants.

    This is useful for the UI to show a list of packages that can be
    analyzed with the variant matrix.

    Args:
        import_id: The import to analyze
        min_count: Minimum number of variants to include a package
        limit: Maximum number of packages to return

    Returns:
        List of dicts with label, variant_count, and total_dependents
    """
    cache_key = cache_key_for_import("variant_labels", import_id, min_count, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH variant_counts AS (
                    SELECT label, COUNT(DISTINCT drv_hash) as variant_count
                    FROM nodes
                    WHERE import_id = %s
                    GROUP BY label
                    HAVING COUNT(DISTINCT drv_hash) >= %s
                )
                SELECT
                    vc.label,
                    vc.variant_count,
                    COUNT(DISTINCT e.target_id) as total_dependents
                FROM variant_counts vc
                JOIN nodes n ON vc.label = n.label AND n.import_id = %s
                LEFT JOIN edges e ON e.source_id = n.id
                GROUP BY vc.label, vc.variant_count
                ORDER BY vc.variant_count DESC, total_dependents DESC
                LIMIT %s
                """,
                (import_id, min_count, import_id, limit)
            )

            result = [dict(row) for row in cur.fetchall()]

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def get_variant_summary(import_id: int, label: str) -> dict[str, Any] | None:
    """Get quick summary information about a package's variants.

    This is a lighter-weight alternative to build_variant_matrix for
    preview/tooltip use cases.

    Args:
        import_id: The import to analyze
        label: Package name to summarize

    Returns:
        Summary dict or None if no variants found
    """
    cache_key = cache_key_for_import("variant_summary", import_id, label)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get variant count and basic stats
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT drv_hash) as variant_count,
                    COUNT(*) as total_nodes,
                    COALESCE(SUM(closure_size), 0) as total_closure
                FROM nodes
                WHERE import_id = %s AND label = %s
                """,
                (import_id, label)
            )
            stats = cur.fetchone()

            if not stats or stats['variant_count'] == 0:
                return None

            # Get unique dependent count across all variants
            cur.execute(
                """
                SELECT COUNT(DISTINCT e.target_id) as unique_dependents
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE n.import_id = %s AND n.label = %s
                """,
                (import_id, label)
            )
            deps = cur.fetchone()

            result = {
                "label": label,
                "import_id": import_id,
                "variant_count": stats['variant_count'],
                "total_nodes": stats['total_nodes'],
                "total_closure": stats['total_closure'],
                "unique_dependents": deps['unique_dependents'] if deps else 0,
            }

    # Cache for 5 minutes
    cache.set(cache_key, result, ttl=300)
    return result


def invalidate_variant_matrix_cache(import_id: int) -> int:
    """Invalidate all variant matrix cache entries for an import.

    Call this when data changes that affects variant matrix display.

    Args:
        import_id: The import to invalidate cache for

    Returns:
        Number of cache entries invalidated
    """
    count = 0
    count += cache.invalidate(f"import:{import_id}:variant_matrix")
    count += cache.invalidate(f"import:{import_id}:variant_labels")
    count += cache.invalidate(f"import:{import_id}:variant_summary")
    return count
