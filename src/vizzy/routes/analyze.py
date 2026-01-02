"""Analysis routes - duplicates, paths, comparisons, why chain, cache management"""

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from vizzy.models import WhyChainQuery, DependencyDirection, EssentialityAnalysis
from vizzy.services import analysis
from vizzy.services import graph as graph_service
from vizzy.services import why_chain as why_chain_service
from vizzy.services import attribution_cache
from vizzy.services import variant_matrix as variant_matrix_service
from vizzy.services.cache import cache

router = APIRouter(prefix="/analyze")

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/duplicates/{import_id}", response_class=HTMLResponse)
async def duplicates(request: Request, import_id: int):
    """Show packages with multiple derivations"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    duplicate_groups = analysis.find_duplicates(import_id)

    return templates.TemplateResponse(
        "analyze/duplicates.html",
        {
            "request": request,
            "import_info": import_info,
            "duplicates": duplicate_groups,
        },
    )


@router.get("/compare/{import_id}/{label}", response_class=HTMLResponse)
async def compare_duplicates(request: Request, import_id: int, label: str):
    """Compare different derivations of the same package"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    comparison = analysis.compare_duplicates(import_id, label)

    return templates.TemplateResponse(
        "analyze/compare.html",
        {
            "request": request,
            "import_info": import_info,
            "comparison": comparison,
        },
    )


@router.get("/path/{import_id}", response_class=HTMLResponse)
async def path_finder(request: Request, import_id: int, source: int | None = None, target: int | None = None):
    """Find path between two nodes"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    path_result = None
    if source and target:
        path_result = analysis.find_path(source, target)

    return templates.TemplateResponse(
        "analyze/path.html",
        {
            "request": request,
            "import_info": import_info,
            "source_id": source,
            "target_id": target,
            "path_result": path_result,
        },
    )


@router.get("/sankey/{import_id}/{label}", response_class=HTMLResponse)
async def sankey_view(
    request: Request,
    import_id: int,
    label: str,
    use_legacy: bool = False,
    filter_app: str | None = Query(default=None, description="Filter to show only paths from this top-level application"),
):
    """Sankey diagram showing flow from top-level apps to package variants.

    The CORRECT flow direction is:
    - Left side: Top-level applications (firefox, vscode, etc.)
    - Middle: Intermediate dependencies (curl, openssl, etc.)
    - Right side: Package variants (the target package with different hashes)

    This answers the question: "Why do these variants exist?"

    Args:
        import_id: The import to analyze
        label: Package name to show variants for (e.g., "openssl")
        use_legacy: If True, use the old (incorrect) flow direction
        filter_app: Optional application name to filter by (e.g., "firefox").
            When specified, only shows paths from this specific application to the variants.
    """
    import json

    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    # Use the new Why Chain-based Sankey by default (correct flow direction)
    if use_legacy:
        sankey_data = analysis.build_sankey_data(import_id, label)
    else:
        sankey_data = analysis.build_sankey_data_from_why_chain(
            import_id, label, filter_app=filter_app
        )

    # Get list of top-level apps that depend on this package (for filter dropdown)
    available_apps = analysis.get_top_level_apps_for_package(import_id, label)

    return templates.TemplateResponse(
        "analyze/sankey.html",
        {
            "request": request,
            "import_info": import_info,
            "label": label,
            "sankey_data": json.dumps(sankey_data),
            "variant_count": sankey_data.get("variant_count", 0),
            "top_level_count": sankey_data.get("top_level_count", 0),
            "intermediate_count": sankey_data.get("intermediate_count", 0),
            "flow_direction": sankey_data.get("flow_direction", "unknown"),
            "filter_app": filter_app,
            "is_filtered": sankey_data.get("is_filtered", False),
            "available_apps": available_apps,
        },
    )


@router.get("/loops/{import_id}", response_class=HTMLResponse)
async def loops_view(request: Request, import_id: int):
    """Show circular dependencies (strongly connected components) in the graph"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    loops = analysis.find_loops(import_id)

    return templates.TemplateResponse(
        "analyze/loops.html",
        {
            "request": request,
            "import_info": import_info,
            "loops": loops,
            "total_nodes": sum(loop.size for loop in loops),
        },
    )


@router.get("/redundant/{import_id}", response_class=HTMLResponse)
async def redundant_view(request: Request, import_id: int):
    """Show redundant edges that can be removed without changing transitive closure"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    redundant_links = analysis.find_redundant_links(import_id)

    return templates.TemplateResponse(
        "analyze/redundant.html",
        {
            "request": request,
            "import_info": import_info,
            "redundant_links": redundant_links,
            "total_redundant": len(redundant_links),
        },
    )


# =============================================================================
# Variant Matrix Endpoints (Phase 8D-003)
# =============================================================================


@router.get("/matrix/{import_id}/{label}", response_class=HTMLResponse)
async def matrix_view(
    request: Request,
    import_id: int,
    label: str,
    sort_by: str = Query(default="dependent_count", pattern="^(dependent_count|closure_size|hash)$"),
    filter_type: str = Query(default="all", pattern="^(all|runtime|build)$"),
    show_top_level: bool = Query(default=True),
    direct_only: bool = Query(default=False),
):
    """Show variant matrix for a package with multiple derivations.

    Displays a matrix showing which applications use which variants of a package.
    This helps identify consolidation opportunities and understand why multiple
    variants of the same package exist in the closure.

    Args:
        import_id: The import to analyze
        label: Package name (e.g., "openssl")
        sort_by: How to sort variants (dependent_count, closure_size, hash)
        filter_type: Filter edges by type (all, runtime, build)
        show_top_level: Whether to highlight top-level packages
        direct_only: If True, only show top-level packages (explicitly installed)
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    matrix = variant_matrix_service.build_variant_matrix(
        import_id=import_id,
        label=label,
        sort_by=sort_by,
        filter_type=filter_type,
        direct_only=direct_only,
    )

    return templates.TemplateResponse(
        "analyze/matrix.html",
        {
            "request": request,
            "import_info": import_info,
            "matrix": matrix,
            "sort_by": sort_by,
            "filter_type": filter_type,
            "show_top_level": show_top_level,
            "direct_only": direct_only,
        },
    )


@router.get("/api/matrix/{import_id}/{label}")
async def matrix_api(
    import_id: int,
    label: str,
    sort_by: str = Query(default="dependent_count", pattern="^(dependent_count|closure_size|hash)$"),
    filter_type: str = Query(default="all", pattern="^(all|runtime|build)$"),
    direct_only: bool = Query(default=False),
):
    """JSON API endpoint for variant matrix data.

    Returns structured matrix data suitable for programmatic access or
    custom visualizations.

    Response structure:
    {
        "label": "package-name",
        "import_id": int,
        "total_variants": int,
        "total_dependents": int,
        "has_build_runtime_info": bool,
        "variants": [
            {
                "node_id": int,
                "drv_hash": str,
                "short_hash": str,
                "label": str,
                "package_type": str | null,
                "dependency_type": str | null,
                "dependent_count": int,
                "closure_size": int | null
            },
            ...
        ],
        "applications": [
            {
                "label": str,
                "node_id": int | null,
                "package_type": str | null,
                "is_top_level": bool,
                "cells": {
                    "variant_node_id": {
                        "has_dep": bool,
                        "dep_type": str | null
                    },
                    ...
                }
            },
            ...
        ]
    }
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    matrix = variant_matrix_service.build_variant_matrix(
        import_id=import_id,
        label=label,
        sort_by=sort_by,
        filter_type=filter_type,
        direct_only=direct_only,
    )

    return JSONResponse(matrix.to_dict())


@router.get("/api/matrix/{import_id}")
async def matrix_labels_api(
    import_id: int,
    min_count: int = Query(default=2, ge=2, le=100),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get list of packages with multiple variants.

    Returns a list of package labels that have multiple derivations,
    suitable for populating a package selector for the matrix view.

    Response structure:
    {
        "labels": [
            {
                "label": str,
                "variant_count": int,
                "total_dependents": int
            },
            ...
        ]
    }
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    labels = variant_matrix_service.get_variant_labels(
        import_id=import_id,
        min_count=min_count,
        limit=limit,
    )

    return JSONResponse({"labels": labels})


@router.get("/api/matrix/{import_id}/{label}/summary")
async def matrix_summary_api(
    import_id: int,
    label: str,
):
    """Get quick summary of a package's variants.

    Returns lightweight summary data suitable for previews or tooltips.

    Response structure:
    {
        "label": str,
        "import_id": int,
        "variant_count": int,
        "total_nodes": int,
        "total_closure": int,
        "unique_dependents": int
    }
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    summary = variant_matrix_service.get_variant_summary(
        import_id=import_id,
        label=label,
    )

    if summary is None:
        return JSONResponse(
            {"error": "No variants found", "label": label},
            status_code=404,
        )

    return JSONResponse(summary)


# =============================================================================
# Why Chain API Endpoints (Phase 8E-005)
# =============================================================================


@router.get("/why/{import_id}/{node_id}", response_class=HTMLResponse)
async def why_chain_view(
    request: Request,
    import_id: int,
    node_id: int,
    max_depth: int = Query(default=10, ge=1, le=50, description="Maximum path depth to search"),
    max_groups: int = Query(default=10, ge=1, le=50, description="Maximum attribution groups to return"),
    include_build_deps: bool = Query(default=True, description="Whether to include build-time dependencies"),
):
    """Show why a package is in the closure - HTML view.

    Answers the question "Why is package X in my closure?" by showing
    attribution paths from top-level packages to the target node.

    This endpoint returns an HTML page suitable for direct browser navigation.
    For HTMX partial updates, use /analyze/why/{import_id}/{node_id}/partial.
    For JSON API, use /api/why/{import_id}/{node_id}.
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    # Build query
    query = WhyChainQuery(
        target_node_id=node_id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=max_depth,
        max_paths=100,
        include_build_deps=include_build_deps,
    )

    # Compute why chain result
    result = why_chain_service.build_why_chain_result(
        node_id=node_id,
        query=query,
        use_cache=True,
        max_groups=max_groups,
    )

    if not result:
        return HTMLResponse("Node not found", status_code=404)

    # Generate summary text
    summary = why_chain_service.summarize_attribution(
        groups=result.attribution_groups,
        target_label=result.target.label,
        total_paths=result.total_paths_found,
        total_top_level=result.total_top_level_dependents,
    )

    # Compute paths for essentiality analysis (8E-007)
    paths = why_chain_service.get_paths_for_result(node_id, query)
    essentiality_analysis = why_chain_service.build_essentiality_analysis(
        target=result.target,
        paths=paths,
        import_id=import_id,
    )

    # Build module attribution summary (8E-009)
    module_attribution = why_chain_service.get_module_breakdown_for_why_chain(
        attribution_groups=result.attribution_groups,
        import_id=import_id,
    )

    return templates.TemplateResponse(
        "analyze/why_chain.html",
        {
            "request": request,
            "import_info": import_info,
            "result": result,
            "summary": summary,
            "max_depth": max_depth,
            "max_groups": max_groups,
            "include_build_deps": include_build_deps,
            "essentiality_analysis": essentiality_analysis,
            "module_attribution": module_attribution,
        },
    )


@router.get("/why/{import_id}/{node_id}/partial", response_class=HTMLResponse)
async def why_chain_partial(
    request: Request,
    import_id: int,
    node_id: int,
    max_depth: int = Query(default=10, ge=1, le=50),
    max_groups: int = Query(default=10, ge=1, le=50),
    include_build_deps: bool = Query(default=True),
):
    """Return Why Chain result as an HTML partial for HTMX updates.

    This endpoint is designed for hx-get usage to dynamically update
    parts of a page without full page reload.
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse(
            '<div class="text-red-500">Import not found</div>',
            status_code=404,
        )

    query = WhyChainQuery(
        target_node_id=node_id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=max_depth,
        max_paths=100,
        include_build_deps=include_build_deps,
    )

    result = why_chain_service.build_why_chain_result(
        node_id=node_id,
        query=query,
        use_cache=True,
        max_groups=max_groups,
    )

    if not result:
        return HTMLResponse(
            '<div class="text-red-500">Node not found</div>',
            status_code=404,
        )

    summary = why_chain_service.summarize_attribution(
        groups=result.attribution_groups,
        target_label=result.target.label,
        total_paths=result.total_paths_found,
        total_top_level=result.total_top_level_dependents,
    )

    return templates.TemplateResponse(
        "analyze/why_chain_partial.html",
        {
            "request": request,
            "import_info": import_info,
            "result": result,
            "summary": summary,
        },
    )


@router.get("/api/why/{import_id}/{node_id}")
async def why_chain_api(
    import_id: int,
    node_id: int,
    max_depth: int = Query(default=10, ge=1, le=50),
    max_groups: int = Query(default=10, ge=1, le=50),
    include_build_deps: bool = Query(default=True),
):
    """JSON API endpoint for Why Chain queries.

    Returns a structured JSON response suitable for programmatic access.

    Response structure:
    {
        "target": { node object },
        "summary": "human-readable summary",
        "total_top_level_dependents": int,
        "total_paths_found": int,
        "essentiality": "essential|removable|build_only|orphan",
        "computation_time_ms": float,
        "cached": bool,
        "attribution_groups": [
            {
                "via_label": "package-name",
                "via_node_id": int,
                "total_dependents": int,
                "top_level_packages": [{"id": int, "label": str}, ...],
                "shortest_path": [{"id": int, "label": str}, ...]
            },
            ...
        ],
        "direct_dependents": [{"id": int, "label": str}, ...]
    }
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    query = WhyChainQuery(
        target_node_id=node_id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=max_depth,
        max_paths=100,
        include_build_deps=include_build_deps,
    )

    result = why_chain_service.build_why_chain_result(
        node_id=node_id,
        query=query,
        use_cache=True,
        max_groups=max_groups,
    )

    if not result:
        return JSONResponse(
            {"error": "Node not found", "node_id": node_id},
            status_code=404,
        )

    summary = why_chain_service.summarize_attribution(
        groups=result.attribution_groups,
        target_label=result.target.label,
        total_paths=result.total_paths_found,
        total_top_level=result.total_top_level_dependents,
    )

    # Compute paths for essentiality analysis (8E-007)
    paths = why_chain_service.get_paths_for_result(node_id, query)
    essentiality_analysis = why_chain_service.build_essentiality_analysis(
        target=result.target,
        paths=paths,
        import_id=import_id,
    )

    # Build JSON-serializable response
    response = {
        "target": {
            "id": result.target.id,
            "label": result.target.label,
            "package_type": result.target.package_type,
            "is_top_level": result.target.is_top_level,
            "closure_size": result.target.closure_size,
        },
        "summary": summary,
        "total_top_level_dependents": result.total_top_level_dependents,
        "total_paths_found": result.total_paths_found,
        "essentiality": result.essentiality.value,
        "computation_time_ms": result.computation_time_ms,
        "cached": result.cached_at is not None,
        "attribution_groups": [
            {
                "via_label": group.via_label,
                "via_node_id": group.via_node.id,
                "total_dependents": group.total_dependents,
                "top_level_packages": [
                    {"id": pkg.id, "label": pkg.label}
                    for pkg in group.top_level_packages[:10]  # Limit for API response size
                ],
                "shortest_path": [
                    {"id": node.id, "label": node.label}
                    for node in group.shortest_path
                ],
            }
            for group in result.attribution_groups
        ],
        "direct_dependents": [
            {"id": dep.id, "label": dep.label}
            for dep in result.direct_dependents[:20]  # Limit for API response size
        ],
        # Enhanced essentiality analysis (8E-007)
        "essentiality_analysis": {
            "status": essentiality_analysis.status.value,
            "status_display": essentiality_analysis.status.display_name,
            "status_description": essentiality_analysis.status.description,
            "is_removable": essentiality_analysis.status.is_removable_category,
            "runtime_dependents": essentiality_analysis.runtime_dependents,
            "build_dependents": essentiality_analysis.build_dependents,
            "path_depth_avg": round(essentiality_analysis.path_depth_avg, 1),
            "path_depth_max": essentiality_analysis.path_depth_max,
            "is_direct_dependency": essentiality_analysis.is_direct_dependency,
            "action_guidance": essentiality_analysis.action_guidance,
            "removal_impact": {
                "closure_reduction": essentiality_analysis.removal_impact.closure_reduction,
                "affected_packages": [
                    {"id": pkg.id, "label": pkg.label}
                    for pkg in essentiality_analysis.removal_impact.affected_packages[:10]
                ],
                "unique_deps_count": essentiality_analysis.removal_impact.unique_deps_count,
                "removal_safe": essentiality_analysis.removal_impact.removal_safe,
                "impact_level": essentiality_analysis.removal_impact.impact_level,
                "summary": essentiality_analysis.removal_impact.summary,
            },
        },
        # Module-level attribution (8E-009)
        "module_attribution": why_chain_service.get_module_breakdown_for_why_chain(
            attribution_groups=result.attribution_groups,
            import_id=import_id,
        ),
    }

    return JSONResponse(response)


# =============================================================================
# Cache Management API Endpoints (Phase 8E-008)
# =============================================================================


@router.get("/api/cache/stats")
async def cache_stats(import_id: int | None = Query(default=None)):
    """Get comprehensive cache statistics.

    Returns statistics about the in-memory and database caches,
    including hit/miss rates, entry counts, and per-prefix breakdowns.

    Query Parameters:
        import_id: Optional import ID to filter database cache stats

    Response structure:
    {
        "memory_cache": {
            "total_entries": int,
            "max_entries": int,
            "active_entries": int,
            "expired_entries": int,
            "global": {
                "hits": int,
                "misses": int,
                "hit_rate": float,
                ...
            },
            "by_prefix": {
                "why_chain": { hit/miss stats... },
                ...
            }
        },
        "why_chain_stats": { ... },
        "database_cache": {
            "total_entries": int,
            "by_import": { import_id: { count, oldest, newest } }
        }
    }
    """
    stats = attribution_cache.get_attribution_cache_stats(import_id)
    return JSONResponse(stats)


@router.post("/api/cache/warm/{import_id}")
async def warm_cache(
    import_id: int,
    max_packages: int = Query(default=50, ge=1, le=200),
    include_common: bool = Query(default=True),
    force: bool = Query(default=False),
):
    """Pre-warm the attribution cache for an import.

    This pre-computes Why Chain results for commonly queried packages
    (glibc, gcc, python, etc.) and packages with large closure sizes.

    This is useful after importing a new configuration to improve
    first-query response times.

    Args:
        import_id: The import to warm cache for
        max_packages: Maximum packages to warm (default 50)
        include_common: Whether to prioritize common packages (default True)
        force: If True, recompute even if cache exists (default False)

    Returns:
        Dictionary with warming statistics
    """
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    result = attribution_cache.warm_cache_for_import(
        import_id=import_id,
        max_packages=max_packages,
        include_common=include_common,
        force=force,
    )
    return JSONResponse(result)


@router.delete("/api/cache/invalidate/{import_id}")
async def invalidate_cache(import_id: int):
    """Invalidate all caches for an import.

    Removes both in-memory and database cache entries for the
    specified import. Use this when you know the graph data has
    changed and cached results are stale.

    Args:
        import_id: The import to invalidate caches for

    Returns:
        Dictionary with counts of invalidated entries
    """
    counts = attribution_cache.invalidate_attribution_cache(import_id)
    # Also invalidate general cache entries for this import
    general_count = cache.invalidate_import(import_id)
    counts["general"] = general_count
    return JSONResponse(counts)


@router.delete("/api/cache/clear")
async def clear_all_cache():
    """Clear all in-memory cache entries.

    WARNING: This clears the entire in-memory cache across all imports.
    Use with caution. Database cache entries are NOT cleared by this endpoint.

    Returns:
        Dictionary with count of cleared entries
    """
    count = cache.invalidate()
    return JSONResponse({
        "cleared": count,
        "note": "Only in-memory cache was cleared. Database cache remains."
    })


@router.post("/api/cache/cleanup")
async def cleanup_cache(
    max_age_hours: int = Query(default=24, ge=1, le=168),
    import_id: int | None = Query(default=None),
):
    """Clean up expired cache entries.

    Removes expired entries from both in-memory and database caches.

    Args:
        max_age_hours: Maximum age for database entries (default 24)
        import_id: Optional import ID to limit cleanup scope

    Returns:
        Dictionary with counts of removed entries
    """
    # Clean up in-memory cache
    memory_cleaned = cache.cleanup_expired()

    # Clean up database cache
    db_cleaned = attribution_cache.cleanup_expired_db_cache(
        max_age_hours=max_age_hours,
        import_id=import_id,
    )

    return JSONResponse({
        "memory_cleaned": memory_cleaned,
        "database_cleaned": db_cleaned,
    })


@router.get("/api/cache/entries")
async def cache_entries(
    prefix: str = Query(default="why_chain"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get information about cached entries for debugging.

    Lists cache entries matching the specified prefix with their
    expiration times and value types.

    Args:
        prefix: Cache key prefix to filter (default "why_chain")
        limit: Maximum entries to return (default 50)

    Returns:
        List of entry information dictionaries
    """
    entries = cache.get_entries_info(limit=limit)
    # Filter by prefix if specified
    if prefix:
        entries = [e for e in entries if prefix in e["key"]]
    return JSONResponse({"entries": entries, "total": len(entries)})


@router.post("/api/cache/reset-stats")
async def reset_cache_stats():
    """Reset cache statistics.

    Clears all hit/miss counters while preserving cached entries.
    Useful for measuring cache effectiveness over a specific period.

    Returns:
        Confirmation message
    """
    cache.reset_stats()
    return JSONResponse({"message": "Cache statistics reset successfully"})


# =============================================================================
# Attribution Export Endpoints (Phase 8E-010)
# =============================================================================
#
# These endpoints export attribution/why-chain data in multiple formats.
# Similar to the comparison export functionality (8F-003), this allows
# users to download attribution reports for documentation or sharing.


from fastapi.responses import Response
import json


@router.get("/why/{import_id}/{node_id}/export")
async def export_attribution(
    import_id: int,
    node_id: int,
    format: str = "json",
    max_depth: int = Query(default=10, ge=1, le=50),
    max_groups: int = Query(default=10, ge=1, le=50),
    include_build_deps: bool = Query(default=True),
    include_paths: bool = Query(default=False, description="Include detailed paths in JSON export"),
):
    """Export attribution/why-chain data in various formats.

    Generates downloadable reports explaining why a package is in the closure.
    Supports JSON, CSV, and Markdown formats with attribution paths,
    essentiality analysis, and module attribution.

    Args:
        import_id: ID of the import to analyze
        node_id: ID of the target node to explain
        format: Export format - one of 'json', 'csv', 'md' (markdown)
        max_depth: Maximum path depth to search
        max_groups: Maximum attribution groups to include
        include_build_deps: Whether to include build-time dependencies
        include_paths: Whether to include detailed paths in JSON (larger file)

    Returns:
        A downloadable file response with appropriate Content-Type and
        Content-Disposition headers for the requested format.

    Raises:
        HTTPException: If import or node not found, or invalid format
    """
    # Validate import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse(f"Import {import_id} not found", status_code=404)

    # Build query
    query = WhyChainQuery(
        target_node_id=node_id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=max_depth,
        max_paths=100,
        include_build_deps=include_build_deps,
    )

    # Compute why chain result
    result = why_chain_service.build_why_chain_result(
        node_id=node_id,
        query=query,
        use_cache=True,
        max_groups=max_groups,
    )

    if not result:
        return HTMLResponse("Node not found", status_code=404)

    # Compute essentiality analysis
    paths = why_chain_service.get_paths_for_result(node_id, query)
    essentiality_analysis = why_chain_service.build_essentiality_analysis(
        target=result.target,
        paths=paths,
        import_id=import_id,
    )

    # Build module attribution summary
    module_attribution = why_chain_service.get_module_breakdown_for_why_chain(
        attribution_groups=result.attribution_groups,
        import_id=import_id,
    )

    # Generate export based on format
    export_format = format.lower()

    if export_format == "json":
        # Include paths if requested (makes file larger but more complete)
        export_paths = paths if include_paths else None
        content = json.dumps(
            why_chain_service.attribution_to_json(
                result=result,
                essentiality=essentiality_analysis,
                module_attribution=module_attribution,
                paths=export_paths,
            ),
            indent=2,
            ensure_ascii=False,
        )
        media_type = "application/json"
        extension = "json"

    elif export_format == "csv":
        content = why_chain_service.attribution_to_csv(
            result=result,
            essentiality=essentiality_analysis,
        )
        media_type = "text/csv"
        extension = "csv"

    elif export_format in ("md", "markdown"):
        content = why_chain_service.attribution_to_markdown(
            result=result,
            essentiality=essentiality_analysis,
            module_attribution=module_attribution,
            import_name=import_info.name,
        )
        media_type = "text/markdown"
        extension = "md"

    else:
        return HTMLResponse(
            f"Invalid format: {format}. Supported formats: json, csv, md",
            status_code=400,
        )

    # Generate filename
    filename = why_chain_service.get_attribution_export_filename(
        target_label=result.target.label,
        import_name=import_info.name,
        format=extension,
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/api/why/{import_id}/{node_id}/export/preview")
async def export_attribution_preview(
    import_id: int,
    node_id: int,
    format: str = "json",
    lines: int = Query(default=50, ge=10, le=200),
    max_depth: int = Query(default=10, ge=1, le=50),
    max_groups: int = Query(default=10, ge=1, le=50),
    include_build_deps: bool = Query(default=True),
):
    """Preview attribution export content without downloading.

    Returns the first N lines of the export for preview purposes
    in the UI before committing to a full download.

    Args:
        import_id: ID of the import
        node_id: ID of the target node
        format: Export format - json, csv, or md
        lines: Number of lines to preview (default 50)
        max_depth: Maximum path depth to search
        max_groups: Maximum attribution groups

    Returns:
        JSON object with preview content and metadata
    """
    # Validate import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return JSONResponse(
            {"error": "Import not found", "import_id": import_id},
            status_code=404,
        )

    # Build query
    query = WhyChainQuery(
        target_node_id=node_id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=max_depth,
        max_paths=100,
        include_build_deps=include_build_deps,
    )

    # Compute why chain result
    result = why_chain_service.build_why_chain_result(
        node_id=node_id,
        query=query,
        use_cache=True,
        max_groups=max_groups,
    )

    if not result:
        return JSONResponse(
            {"error": "Node not found", "node_id": node_id},
            status_code=404,
        )

    # Compute essentiality analysis
    paths = why_chain_service.get_paths_for_result(node_id, query)
    essentiality_analysis = why_chain_service.build_essentiality_analysis(
        target=result.target,
        paths=paths,
        import_id=import_id,
    )

    # Build module attribution summary
    module_attribution = why_chain_service.get_module_breakdown_for_why_chain(
        attribution_groups=result.attribution_groups,
        import_id=import_id,
    )

    export_format = format.lower()

    if export_format == "json":
        full_content = json.dumps(
            why_chain_service.attribution_to_json(
                result=result,
                essentiality=essentiality_analysis,
                module_attribution=module_attribution,
            ),
            indent=2,
        )
    elif export_format == "csv":
        full_content = why_chain_service.attribution_to_csv(
            result=result,
            essentiality=essentiality_analysis,
        )
    elif export_format in ("md", "markdown"):
        full_content = why_chain_service.attribution_to_markdown(
            result=result,
            essentiality=essentiality_analysis,
            module_attribution=module_attribution,
            import_name=import_info.name,
        )
    else:
        return JSONResponse(
            {"error": f"Invalid format: {format}"},
            status_code=400,
        )

    # Get preview lines
    all_lines = full_content.split('\n')
    preview_lines = all_lines[:lines]
    is_truncated = len(all_lines) > lines

    return JSONResponse({
        "format": export_format,
        "target_label": result.target.label,
        "total_lines": len(all_lines),
        "preview_lines": lines,
        "is_truncated": is_truncated,
        "preview": '\n'.join(preview_lines),
        "filename": why_chain_service.get_attribution_export_filename(
            target_label=result.target.label,
            import_name=import_info.name,
            format="md" if export_format == "markdown" else export_format,
        ),
    })
