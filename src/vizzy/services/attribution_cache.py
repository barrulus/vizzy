"""Attribution caching service for Why Chain queries (Phase 8E-008).

This module provides robust caching for attribution/Why Chain computations
to improve performance, especially for frequently queried packages like glibc.

Features:
- Two-tier caching: fast in-memory cache + persistent database cache
- Cache warming for commonly queried packages
- Automatic cache invalidation when imports are updated/deleted
- Statistics and monitoring for cache effectiveness
- Configurable TTLs for different cache tiers

Usage:
    from vizzy.services.attribution_cache import (
        get_cached_attribution,
        cache_attribution_result,
        warm_cache_for_import,
        invalidate_attribution_cache,
    )
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from vizzy.database import get_db
from vizzy.models import (
    WhyChainQuery,
    WhyChainResult,
    AttributionPath,
    DependencyDirection,
    EssentialityStatus,
    Node,
)
from vizzy.services.cache import cache, cache_key_for_import

logger = logging.getLogger("vizzy.attribution_cache")

# Cache TTL configurations (in seconds)
MEMORY_CACHE_TTL = 600  # 10 minutes for in-memory cache
DB_CACHE_TTL = 3600  # 1 hour for database cache
COMMON_PACKAGE_TTL = 7200  # 2 hours for commonly queried packages (glibc, gcc, etc.)

# Commonly queried packages that should have extended cache times
COMMON_PACKAGES = {
    "glibc", "gcc", "coreutils", "bash", "openssl", "curl", "python",
    "nodejs", "zlib", "glib", "systemd", "linux", "binutils", "perl",
    "gnugrep", "gnused", "gawk", "findutils", "diffutils", "patch",
    "ncurses", "readline", "sqlite", "libffi", "expat", "libxml2",
}


def _is_common_package(label: str) -> bool:
    """Check if a package label matches a commonly queried package."""
    label_lower = label.lower()
    for common in COMMON_PACKAGES:
        if common in label_lower:
            return True
    return False


def _build_attribution_cache_key(
    node_id: int,
    import_id: int,
    max_depth: int = 10,
    include_build_deps: bool = True,
) -> str:
    """Build a standardized cache key for attribution results."""
    return cache_key_for_import(
        "why_chain",
        import_id,
        node_id,
        max_depth,
        include_build_deps,
    )


def _build_db_analysis_type(
    node_id: int,
    max_depth: int = 10,
    include_build_deps: bool = True,
) -> str:
    """Build analysis type string for database storage."""
    return f"why_chain:{node_id}:{max_depth}:{include_build_deps}"


def get_cached_attribution(
    node_id: int,
    query: WhyChainQuery,
) -> WhyChainResult | None:
    """Retrieve cached attribution result from memory or database.

    Implements two-tier caching:
    1. First checks fast in-memory cache
    2. Falls back to database cache if memory cache misses
    3. Populates memory cache on database hit for future requests

    Args:
        node_id: The target node ID
        query: The Why Chain query parameters

    Returns:
        Cached WhyChainResult if found and valid, None otherwise
    """
    cache_key = _build_attribution_cache_key(
        node_id,
        query.import_id,
        query.max_depth,
        query.include_build_deps,
    )

    # Tier 1: Check in-memory cache
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Attribution cache hit (memory): node {node_id}")
        return cached

    # Tier 2: Check database cache
    analysis_type = _build_db_analysis_type(
        node_id,
        query.max_depth,
        query.include_build_deps,
    )

    try:
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
                    computed_at = row['computed_at']
                    # Check TTL
                    max_age = timedelta(seconds=DB_CACHE_TTL)
                    if datetime.now() - computed_at < max_age:
                        result_data = row['result']
                        result = _deserialize_attribution_result(
                            result_data, query, computed_at
                        )
                        if result:
                            # Populate memory cache for future requests
                            cache.set(cache_key, result, ttl=MEMORY_CACHE_TTL)
                            logger.debug(f"Attribution cache hit (database): node {node_id}")
                            return result
                    else:
                        logger.debug(f"Attribution cache expired (database): node {node_id}")
    except Exception as e:
        logger.warning(f"Error reading attribution cache: {e}")

    logger.debug(f"Attribution cache miss: node {node_id}")
    return None


def cache_attribution_result(
    node_id: int,
    query: WhyChainQuery,
    result: WhyChainResult,
    paths: list[AttributionPath],
    is_common_package: bool = False,
) -> None:
    """Cache an attribution result in both memory and database.

    Args:
        node_id: The target node ID
        query: The Why Chain query parameters
        result: The computed result to cache
        paths: The computed paths (serialized for database storage)
        is_common_package: If True, use extended TTL for this entry
    """
    cache_key = _build_attribution_cache_key(
        node_id,
        query.import_id,
        query.max_depth,
        query.include_build_deps,
    )

    # Determine TTL based on package commonality
    memory_ttl = COMMON_PACKAGE_TTL if is_common_package else MEMORY_CACHE_TTL

    # Tier 1: Memory cache
    cache.set(cache_key, result, ttl=memory_ttl)

    # Tier 2: Database cache
    analysis_type = _build_db_analysis_type(
        node_id,
        query.max_depth,
        query.include_build_deps,
    )

    result_data = _serialize_attribution_result(result, paths)

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Upsert: delete old entry if exists, then insert new
                cur.execute(
                    """
                    DELETE FROM analysis
                    WHERE import_id = %s AND analysis_type = %s
                    """,
                    (query.import_id, analysis_type)
                )

                cur.execute(
                    """
                    INSERT INTO analysis (import_id, analysis_type, result)
                    VALUES (%s, %s, %s)
                    """,
                    (query.import_id, analysis_type, json.dumps(result_data))
                )
                conn.commit()
                logger.debug(f"Attribution cached (both tiers): node {node_id}")
    except Exception as e:
        logger.warning(f"Error writing attribution cache to database: {e}")


def invalidate_attribution_cache(import_id: int) -> dict[str, int]:
    """Invalidate all attribution caches for an import.

    Call this when:
    - An import is deleted
    - An import's nodes or edges are modified
    - Refreshing import data

    Args:
        import_id: The import ID to invalidate

    Returns:
        Dictionary with counts of invalidated entries per tier
    """
    counts = {"memory": 0, "database": 0}

    # Tier 1: Memory cache - invalidate all why_chain entries for this import
    counts["memory"] = cache.invalidate(f"import:{import_id}:why_chain")

    # Also invalidate related caches
    cache.invalidate(f"import:{import_id}:why_chain_top_level_ids")
    cache.invalidate(f"import:{import_id}:why_chain_summary")

    # Tier 2: Database cache
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM analysis
                    WHERE import_id = %s AND analysis_type LIKE 'why_chain:%%'
                    """,
                    (import_id,)
                )
                counts["database"] = cur.rowcount
                conn.commit()
    except Exception as e:
        logger.warning(f"Error invalidating database attribution cache: {e}")

    logger.info(
        f"Attribution cache invalidated for import {import_id}: "
        f"{counts['memory']} memory, {counts['database']} database entries"
    )
    return counts


def warm_cache_for_import(
    import_id: int,
    max_packages: int = 50,
    include_common: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Pre-warm attribution cache for commonly queried packages.

    This function identifies packages that are likely to be queried often
    and pre-computes their Why Chain results, storing them in cache.

    Packages selected for warming:
    1. Known common packages (glibc, gcc, python, etc.) if present
    2. Packages with the highest closure sizes
    3. Packages with the most dependencies

    Args:
        import_id: The import to warm cache for
        max_packages: Maximum number of packages to warm
        include_common: Whether to prioritize common packages
        force: If True, recompute even if cache exists

    Returns:
        Dictionary with warming statistics
    """
    from vizzy.services import why_chain as why_chain_service

    start_time = time.time()
    stats = {
        "import_id": import_id,
        "packages_warmed": 0,
        "packages_skipped": 0,
        "packages_failed": 0,
        "total_time_ms": 0,
        "warmed_packages": [],
    }

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Find packages to warm
                packages_to_warm = []

                if include_common:
                    # First, find common packages present in this import
                    common_pattern = "|".join(COMMON_PACKAGES)
                    cur.execute(
                        f"""
                        SELECT id, label, closure_size
                        FROM nodes
                        WHERE import_id = %s
                          AND label ~* %s
                        ORDER BY closure_size DESC NULLS LAST
                        LIMIT %s
                        """,
                        (import_id, common_pattern, max_packages // 2)
                    )
                    for row in cur.fetchall():
                        packages_to_warm.append({
                            "id": row["id"],
                            "label": row["label"],
                            "is_common": True,
                        })

                # Add packages with largest closure sizes
                remaining = max_packages - len(packages_to_warm)
                if remaining > 0:
                    existing_ids = {p["id"] for p in packages_to_warm}
                    cur.execute(
                        """
                        SELECT id, label, closure_size
                        FROM nodes
                        WHERE import_id = %s
                          AND closure_size IS NOT NULL
                        ORDER BY closure_size DESC
                        LIMIT %s
                        """,
                        (import_id, remaining * 2)  # Get extra to filter duplicates
                    )
                    for row in cur.fetchall():
                        if row["id"] not in existing_ids:
                            packages_to_warm.append({
                                "id": row["id"],
                                "label": row["label"],
                                "is_common": False,
                            })
                            existing_ids.add(row["id"])
                            if len(packages_to_warm) >= max_packages:
                                break

                # Warm cache for each package
                for pkg in packages_to_warm:
                    node_id = pkg["id"]
                    label = pkg["label"]
                    is_common = pkg["is_common"]

                    # Check if already cached (unless forced)
                    query = WhyChainQuery(
                        target_node_id=node_id,
                        import_id=import_id,
                        direction=DependencyDirection.REVERSE,
                        max_depth=10,
                        max_paths=100,
                        include_build_deps=True,
                    )

                    if not force:
                        existing = get_cached_attribution(node_id, query)
                        if existing:
                            stats["packages_skipped"] += 1
                            continue

                    try:
                        # Compute and cache the result
                        result = why_chain_service.build_why_chain_result(
                            node_id=node_id,
                            query=query,
                            use_cache=False,  # Force fresh computation
                            max_groups=10,
                        )

                        if result:
                            # Get paths for caching
                            paths = why_chain_service.get_paths_for_result(node_id, query)

                            # Cache with appropriate TTL
                            cache_attribution_result(
                                node_id=node_id,
                                query=query,
                                result=result,
                                paths=paths,
                                is_common_package=is_common or _is_common_package(label),
                            )

                            stats["packages_warmed"] += 1
                            stats["warmed_packages"].append({
                                "id": node_id,
                                "label": label,
                                "paths_found": result.total_paths_found,
                            })
                            logger.debug(f"Cache warmed for {label} (node {node_id})")
                        else:
                            stats["packages_failed"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to warm cache for {label}: {e}")
                        stats["packages_failed"] += 1

    except Exception as e:
        logger.error(f"Error during cache warming: {e}")
        stats["error"] = str(e)

    stats["total_time_ms"] = (time.time() - start_time) * 1000
    logger.info(
        f"Cache warming complete for import {import_id}: "
        f"{stats['packages_warmed']} warmed, "
        f"{stats['packages_skipped']} skipped, "
        f"{stats['packages_failed']} failed, "
        f"{stats['total_time_ms']:.1f}ms"
    )
    return stats


def get_attribution_cache_stats(import_id: int | None = None) -> dict[str, Any]:
    """Get comprehensive cache statistics for attribution caching.

    Args:
        import_id: If provided, filter stats to specific import

    Returns:
        Dictionary with cache statistics
    """
    stats = {
        "memory_cache": cache.stats(),
        "why_chain_stats": {},
        "database_cache": {"total_entries": 0, "by_import": {}},
    }

    # Get Why Chain specific stats from memory cache
    why_chain_stats = cache.get_prefix_stats("why_chain")
    if why_chain_stats:
        stats["why_chain_stats"] = why_chain_stats.to_dict()

    # Get database cache stats
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if import_id:
                    cur.execute(
                        """
                        SELECT COUNT(*) as count,
                               MIN(computed_at) as oldest,
                               MAX(computed_at) as newest
                        FROM analysis
                        WHERE import_id = %s AND analysis_type LIKE 'why_chain:%%'
                        """,
                        (import_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        stats["database_cache"]["by_import"][import_id] = {
                            "count": row["count"],
                            "oldest": row["oldest"].isoformat() if row["oldest"] else None,
                            "newest": row["newest"].isoformat() if row["newest"] else None,
                        }
                else:
                    cur.execute(
                        """
                        SELECT import_id, COUNT(*) as count,
                               MIN(computed_at) as oldest,
                               MAX(computed_at) as newest
                        FROM analysis
                        WHERE analysis_type LIKE 'why_chain:%%'
                        GROUP BY import_id
                        """
                    )
                    for row in cur.fetchall():
                        stats["database_cache"]["by_import"][row["import_id"]] = {
                            "count": row["count"],
                            "oldest": row["oldest"].isoformat() if row["oldest"] else None,
                            "newest": row["newest"].isoformat() if row["newest"] else None,
                        }
                        stats["database_cache"]["total_entries"] += row["count"]
    except Exception as e:
        logger.warning(f"Error getting database cache stats: {e}")
        stats["database_cache"]["error"] = str(e)

    return stats


def cleanup_expired_db_cache(
    max_age_hours: int = 24,
    import_id: int | None = None,
) -> int:
    """Remove expired entries from the database cache.

    Args:
        max_age_hours: Maximum age of entries to keep
        import_id: If provided, only clean up for specific import

    Returns:
        Number of entries removed
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cutoff = datetime.now() - timedelta(hours=max_age_hours)

                if import_id:
                    cur.execute(
                        """
                        DELETE FROM analysis
                        WHERE analysis_type LIKE 'why_chain:%%'
                          AND computed_at < %s
                          AND import_id = %s
                        """,
                        (cutoff, import_id)
                    )
                else:
                    cur.execute(
                        """
                        DELETE FROM analysis
                        WHERE analysis_type LIKE 'why_chain:%%'
                          AND computed_at < %s
                        """,
                        (cutoff,)
                    )

                count = cur.rowcount
                conn.commit()

                if count > 0:
                    logger.info(f"Cleaned up {count} expired attribution cache entries")
                return count
    except Exception as e:
        logger.warning(f"Error cleaning up expired cache: {e}")
        return 0


def _serialize_attribution_result(
    result: WhyChainResult,
    paths: list[AttributionPath],
) -> dict[str, Any]:
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
            for p in paths[:100]  # Limit stored paths to prevent huge entries
        ],
    }


def _deserialize_attribution_result(
    data: dict[str, Any],
    query: WhyChainQuery,
    cached_at: datetime,
) -> WhyChainResult | None:
    """Deserialize a WhyChainResult from database storage."""
    try:
        # Import here to avoid circular dependency
        from vizzy.services.why_chain import (
            get_node_by_id,
            get_direct_dependents,
        )

        target_id = data["target_id"]
        target = get_node_by_id(target_id)
        if not target:
            return None

        # Get direct dependents (cheap query, not cached)
        direct_dependents = get_direct_dependents(target_id, query.import_id)

        return WhyChainResult(
            target=target,
            query=query,
            direct_dependents=direct_dependents,
            attribution_groups=[],  # Groups are recomputed from paths when needed
            total_top_level_dependents=data["total_top_level_dependents"],
            total_paths_found=data["total_paths_found"],
            essentiality=EssentialityStatus(data["essentiality"]),
            computation_time_ms=data.get("computation_time_ms"),
            cached_at=cached_at,
        )
    except Exception as e:
        logger.warning(f"Error deserializing attribution result: {e}")
        return None
