"""API routes for incremental recomputation, contribution data, and dashboard metrics.

This module provides REST API endpoints for:
- Dashboard metrics (summary, top contributors, type distribution)
- Triggering incremental recomputation
- Getting staleness reports
- Estimating recomputation costs
- Contribution data access
"""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from vizzy.services import graph as graph_service
from vizzy.services import contribution
from vizzy.services import incremental
from vizzy.services import dashboard as dashboard_service
from vizzy.services import semantic_zoom
from vizzy.services import render as render_service

router = APIRouter(prefix="/api", tags=["api"])


# =============================================================================
# Request/Response Models
# =============================================================================


class StalenessReportResponse(BaseModel):
    """Response model for staleness report."""
    import_id: int
    total_top_level: int
    stale_count: int
    never_computed_count: int
    oldest_computation: str | None
    newest_computation: str | None
    is_fresh: bool
    stale_percentage: float
    needs_recomputation: bool
    details: dict[str, Any]


class RecomputationResultResponse(BaseModel):
    """Response model for recomputation result."""
    import_id: int
    nodes_updated: int
    nodes_skipped: int
    computation_time_ms: float
    strategy_used: str
    affected_nodes_count: int
    success: bool
    errors: list[str]


class CostEstimateResponse(BaseModel):
    """Response model for cost estimate."""
    import_id: int
    total_nodes: int
    total_edges: int
    top_level_count: int
    avg_closure_size: float
    stale_count: int
    stale_percentage: float
    estimated_full_cost_ms: float
    estimated_incremental_cost_ms: float
    recommendation: str
    savings_percentage: float


class TriggerRecomputeRequest(BaseModel):
    """Request model for triggering recomputation."""
    node_ids: list[int] | None = None
    max_nodes: int | None = None
    freshness_hours: int = 24


class MarkStaleRequest(BaseModel):
    """Request model for marking contributions stale."""
    node_ids: list[int] | None = None


class ContributionResponse(BaseModel):
    """Response model for contribution data."""
    node_id: int
    label: str
    package_type: str | None
    unique_contribution: int
    shared_contribution: int
    total_contribution: int
    closure_size: int | None
    unique_percentage: float
    removal_impact: str


# =============================================================================
# Dashboard Response Models (Task 8B-002)
# =============================================================================


class DepthStatsResponse(BaseModel):
    """Depth statistics for the dashboard."""
    max: int
    avg: float
    median: float


class BaselineComparisonResponse(BaseModel):
    """Baseline comparison data."""
    baseline_name: str
    node_difference: int
    percentage: float


class DashboardSummaryResponse(BaseModel):
    """Complete dashboard summary response.

    Matches the schema defined in designs/dashboard-spec.md.
    """
    total_nodes: int
    total_edges: int
    redundancy_score: float
    build_runtime_ratio: float  # Ratio of runtime deps (named for API clarity)
    depth_stats: DepthStatsResponse
    baseline_comparison: BaselineComparisonResponse | None = None


class TopContributorResponse(BaseModel):
    """A package contributing to closure size."""
    node_id: int
    label: str
    closure_size: int
    package_type: str | None
    unique_contribution: int | None


class TypeDistributionEntryResponse(BaseModel):
    """Single entry in type distribution."""
    type: str
    count: int
    percentage: float


class TypeDistributionResponse(BaseModel):
    """Package type distribution response."""
    types: list[TypeDistributionEntryResponse]


# =============================================================================
# Staleness and Monitoring Endpoints
# =============================================================================


@router.get("/incremental/{import_id}/staleness", response_model=StalenessReportResponse)
async def get_staleness_report(
    import_id: int,
    freshness_hours: int = Query(default=24, ge=1, le=720)
) -> StalenessReportResponse:
    """Get a staleness report for contribution data.

    Returns information about how fresh the contribution data is and
    whether recomputation is needed.

    Args:
        import_id: The import to analyze
        freshness_hours: Hours before data is considered stale (default 24)

    Returns:
        StalenessReportResponse with detailed staleness information
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    report = incremental.get_staleness_report(
        import_id,
        freshness_threshold=timedelta(hours=freshness_hours)
    )

    return StalenessReportResponse(
        import_id=report.import_id,
        total_top_level=report.total_top_level,
        stale_count=report.stale_count,
        never_computed_count=report.never_computed_count,
        oldest_computation=(
            report.oldest_computation.isoformat()
            if report.oldest_computation else None
        ),
        newest_computation=(
            report.newest_computation.isoformat()
            if report.newest_computation else None
        ),
        is_fresh=report.is_fresh,
        stale_percentage=report.stale_percentage,
        needs_recomputation=report.needs_recomputation,
        details=report.details,
    )


@router.get("/incremental/{import_id}/cost", response_model=CostEstimateResponse)
async def estimate_recomputation_cost(import_id: int) -> CostEstimateResponse:
    """Estimate the cost of recomputing contributions.

    Returns estimates useful for deciding whether to run incremental
    or full recomputation.

    Args:
        import_id: The import to analyze

    Returns:
        CostEstimateResponse with cost estimates and recommendation
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    estimate = incremental.estimate_recomputation_cost(import_id)

    return CostEstimateResponse(**estimate)


# =============================================================================
# Recomputation Trigger Endpoints
# =============================================================================


@router.post("/incremental/{import_id}/recompute", response_model=RecomputationResultResponse)
async def trigger_recomputation(
    import_id: int,
    request: TriggerRecomputeRequest | None = None
) -> RecomputationResultResponse:
    """Trigger incremental recomputation of contributions.

    This endpoint allows triggering recomputation with various options:
    - No body: Recompute all stale nodes
    - node_ids: Recompute specific nodes only
    - max_nodes: Limit number of nodes to recompute

    Args:
        import_id: The import to recompute
        request: Optional configuration for the recomputation

    Returns:
        RecomputationResultResponse with details of the operation
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    if request is None:
        request = TriggerRecomputeRequest()

    if request.node_ids:
        # Selective recomputation for specific nodes
        result = incremental.recompute_selective(import_id, request.node_ids)
    else:
        # Recompute stale contributions
        result = incremental.recompute_stale_contributions(
            import_id,
            max_nodes=request.max_nodes,
            freshness_threshold=timedelta(hours=request.freshness_hours)
        )

    return RecomputationResultResponse(
        import_id=result.import_id,
        nodes_updated=result.nodes_updated,
        nodes_skipped=result.nodes_skipped,
        computation_time_ms=result.computation_time_ms,
        strategy_used=result.strategy_used,
        affected_nodes_count=len(result.affected_nodes),
        success=result.success,
        errors=result.errors,
    )


@router.post("/incremental/{import_id}/recompute/full", response_model=RecomputationResultResponse)
async def trigger_full_recomputation(import_id: int) -> RecomputationResultResponse:
    """Trigger full recomputation of all contributions.

    This forces a complete recalculation of all contribution data,
    ignoring staleness. Use this when you suspect data corruption
    or after major graph changes.

    Args:
        import_id: The import to recompute

    Returns:
        RecomputationResultResponse with details of the operation
    """
    import time

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    start_time = time.time()
    updated = contribution.compute_contributions(import_id)
    elapsed = (time.time() - start_time) * 1000

    return RecomputationResultResponse(
        import_id=import_id,
        nodes_updated=updated,
        nodes_skipped=0,
        computation_time_ms=elapsed,
        strategy_used='full',
        affected_nodes_count=updated,
        success=True,
        errors=[],
    )


@router.post("/incremental/{import_id}/mark-stale")
async def mark_contributions_stale(
    import_id: int,
    request: MarkStaleRequest | None = None
) -> dict[str, Any]:
    """Mark contribution data as stale (needing recomputation).

    This is useful for signaling that contributions need to be recalculated
    without actually computing them immediately.

    Args:
        import_id: The import to mark
        request: Optional specification of which nodes to mark stale

    Returns:
        Dictionary with count of nodes marked stale
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    node_ids = request.node_ids if request else None
    count = incremental.mark_contributions_stale(import_id, node_ids)

    return {
        "import_id": import_id,
        "nodes_marked_stale": count,
    }


# =============================================================================
# Contribution Data Endpoints
# =============================================================================


@router.get("/contributions/{import_id}")
async def get_contributions(
    import_id: int,
    sort_by: str = Query(default="unique", pattern="^(unique|total|label)$"),
    limit: int = Query(default=20, ge=1, le=100)
) -> list[ContributionResponse]:
    """Get contribution data for top-level packages.

    Returns contribution data sorted by the specified field.

    Args:
        import_id: The import to get contributions for
        sort_by: Field to sort by ('unique', 'total', or 'label')
        limit: Maximum number of results (1-100)

    Returns:
        List of ContributionResponse objects
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    contributions = contribution.get_contribution_data(
        import_id,
        sort_by=sort_by,
        limit=limit
    )

    return [
        ContributionResponse(
            node_id=c.node_id,
            label=c.label,
            package_type=c.package_type,
            unique_contribution=c.unique_contribution,
            shared_contribution=c.shared_contribution,
            total_contribution=c.total_contribution,
            closure_size=c.closure_size,
            unique_percentage=c.unique_percentage,
            removal_impact=c.removal_impact,
        )
        for c in contributions
    ]


@router.get("/contributions/{import_id}/summary")
async def get_contribution_summary(import_id: int) -> dict[str, Any]:
    """Get a summary of contribution data for an import.

    Returns aggregate metrics and top contributors.

    Args:
        import_id: The import to get summary for

    Returns:
        Dictionary with contribution summary
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    summary = contribution.get_contribution_summary(import_id)

    if not summary:
        return {
            "import_id": import_id,
            "computed": False,
            "message": "Contributions not yet computed. Trigger /api/incremental/{import_id}/recompute",
        }

    return {
        "import_id": summary.import_id,
        "computed": True,
        "total_top_level_packages": summary.total_top_level_packages,
        "total_unique_contributions": summary.total_unique_contributions,
        "total_shared_contributions": summary.total_shared_contributions,
        "average_unique_contribution": summary.average_unique_contribution,
        "sharing_ratio": summary.sharing_ratio,
        "computed_at": (
            summary.computed_at.isoformat() if summary.computed_at else None
        ),
        "top_unique_contributors": [
            {
                "node_id": c.node_id,
                "label": c.label,
                "unique_contribution": c.unique_contribution,
            }
            for c in summary.top_unique_contributors[:5]
        ],
        "top_total_contributors": [
            {
                "node_id": c.node_id,
                "label": c.label,
                "total_contribution": c.total_contribution,
            }
            for c in summary.top_total_contributors[:5]
        ],
    }


@router.get("/contributions/{import_id}/by-type")
async def get_contributions_by_type(import_id: int) -> dict[str, dict]:
    """Get contribution data aggregated by package type.

    Useful for understanding which categories of packages contribute
    most to the closure.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary mapping package_type to aggregate metrics
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    return contribution.get_contribution_by_type(import_id)


@router.get("/contributions/{import_id}/removal-candidates")
async def get_removal_candidates(
    import_id: int,
    max_unique: int = Query(default=0, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=100)
) -> list[ContributionResponse]:
    """Find packages that can be removed with minimal closure impact.

    Returns top-level packages with low unique contributions,
    meaning they share most dependencies with other packages.

    Args:
        import_id: The import to analyze
        max_unique: Maximum unique contribution to be considered removable
        limit: Maximum number of candidates to return

    Returns:
        List of ContributionResponse objects for removal candidates
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    candidates = contribution.identify_removal_candidates(
        import_id,
        max_unique_threshold=max_unique,
        limit=limit
    )

    return [
        ContributionResponse(
            node_id=c.node_id,
            label=c.label,
            package_type=c.package_type,
            unique_contribution=c.unique_contribution,
            shared_contribution=c.shared_contribution,
            total_contribution=c.total_contribution,
            closure_size=c.closure_size,
            unique_percentage=c.unique_percentage,
            removal_impact=c.removal_impact,
        )
        for c in candidates
    ]


@router.get("/contributions/node/{node_id}")
async def get_node_contribution(node_id: int) -> ContributionResponse | dict:
    """Get contribution data for a specific node.

    Args:
        node_id: The node ID to get contribution for

    Returns:
        ContributionResponse for the node, or error if not found
    """
    node = graph_service.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    contrib = contribution.get_contribution_for_node(node_id)

    if not contrib:
        return {
            "node_id": node_id,
            "label": node.label,
            "computed": False,
            "message": "Contribution not yet computed for this node",
        }

    return ContributionResponse(
        node_id=contrib.node_id,
        label=contrib.label,
        package_type=contrib.package_type,
        unique_contribution=contrib.unique_contribution,
        shared_contribution=contrib.shared_contribution,
        total_contribution=contrib.total_contribution,
        closure_size=contrib.closure_size,
        unique_percentage=contrib.unique_percentage,
        removal_impact=contrib.removal_impact,
    )


# =============================================================================
# Dashboard Metrics Endpoints (Task 8B-002)
# =============================================================================


@router.get("/dashboard/{import_id}/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(import_id: int) -> DashboardSummaryResponse:
    """Get complete dashboard summary metrics for an import.

    Returns key health indicators including:
    - Total derivations and edges
    - Redundancy score (percentage of redundant edges)
    - Runtime dependency ratio
    - Depth statistics (max, avg, median)
    - Baseline comparison (if available)

    This endpoint powers the metric cards at the top of the System Health Dashboard.

    Args:
        import_id: The import to get metrics for

    Returns:
        DashboardSummaryResponse with all key metrics
    """
    summary = dashboard_service.get_dashboard_summary(import_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Import not found")

    return DashboardSummaryResponse(
        total_nodes=summary.total_nodes,
        total_edges=summary.total_edges,
        redundancy_score=round(summary.redundancy_score, 4),
        build_runtime_ratio=round(summary.runtime_ratio, 4),
        depth_stats=DepthStatsResponse(
            max=summary.depth_stats.max_depth,
            avg=round(summary.depth_stats.avg_depth, 2),
            median=round(summary.depth_stats.median_depth, 2),
        ),
        baseline_comparison=(
            BaselineComparisonResponse(
                baseline_name=summary.baseline_comparison.baseline_name,
                node_difference=summary.baseline_comparison.node_difference,
                percentage=summary.baseline_comparison.percentage,
            )
            if summary.baseline_comparison else None
        ),
    )


@router.get("/dashboard/{import_id}/top-contributors")
async def get_dashboard_top_contributors(
    import_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    top_level_only: bool = Query(default=True),
) -> list[TopContributorResponse]:
    """Get packages that contribute most to closure size.

    Returns top-level packages ordered by their closure size contribution.
    This powers the "Largest Contributors" panel on the dashboard.

    Args:
        import_id: The import to analyze
        limit: Maximum number of contributors (default 10, max 50)
        top_level_only: Only include top-level packages (default True)

    Returns:
        List of TopContributorResponse objects ordered by closure_size
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    contributors = dashboard_service.get_top_contributors(
        import_id,
        limit=limit,
        top_level_only=top_level_only,
    )

    return [
        TopContributorResponse(
            node_id=c.node_id,
            label=c.label,
            closure_size=c.closure_size,
            package_type=c.package_type,
            unique_contribution=c.unique_contribution,
        )
        for c in contributors
    ]


@router.get("/dashboard/{import_id}/type-distribution", response_model=TypeDistributionResponse)
async def get_dashboard_type_distribution(import_id: int) -> TypeDistributionResponse:
    """Get distribution of packages by type.

    Returns counts and percentages for each package type.
    This powers the "By Package Type" chart on the dashboard.

    Args:
        import_id: The import to analyze

    Returns:
        TypeDistributionResponse with type breakdown
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    distribution = dashboard_service.get_type_distribution(import_id)

    return TypeDistributionResponse(
        types=[
            TypeDistributionEntryResponse(
                type=entry.package_type,
                count=entry.count,
                percentage=entry.percentage,
            )
            for entry in distribution
        ]
    )


@router.get("/dashboard/{import_id}/health")
async def get_dashboard_health_indicators(import_id: int) -> dict[str, Any]:
    """Get health indicators with status assessments.

    Returns health indicators with status labels (good, warning, critical)
    based on threshold values. Useful for UI coloring and alerts.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary with health indicators and their status assessments
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    indicators = dashboard_service.get_health_indicators(import_id)
    if not indicators:
        raise HTTPException(
            status_code=404,
            detail="Could not compute health indicators"
        )

    return indicators


# =============================================================================
# Semantic Zoom Endpoints (Task 8G-001)
# =============================================================================


class SemanticZoomRequest(BaseModel):
    """Request model for semantic zoom graph."""
    zoom_level: int = 2  # 0=cluster, 1=overview, 2=detailed
    center_node_id: int | None = None
    package_type: str | None = None
    max_nodes: int = 100


class SemanticGraphResponse(BaseModel):
    """Response model for semantic zoom graph."""
    zoom_level: int
    svg: str
    cluster_count: int
    node_count: int
    edge_count: int
    available_levels: list[dict]
    # Aggregation info (Task 8G-002)
    aggregate_count: int = 0
    aggregation_mode: str = "none"


class AggregateInfoResponse(BaseModel):
    """Information about an aggregate node (Task 8G-002)."""
    id: str
    label_prefix: str
    package_type: str
    node_count: int
    total_closure_size: int
    representative_labels: list[str]
    can_expand: bool


@router.get("/semantic-zoom/{import_id}")
async def get_semantic_zoom_graph(
    import_id: int,
    zoom_level: int = Query(default=2, ge=0, le=2),
    scale: float = Query(default=1.0, ge=0.1, le=5.0),
    center_node_id: int | None = None,
    package_type: str | None = None,
    max_nodes: int = Query(default=100, ge=10, le=500),
    # Task 8G-002: Aggregation parameters
    aggregation_mode: str = Query(default="none", pattern="^(none|prefix|depth)$"),
    aggregation_threshold: int = Query(default=5, ge=2, le=50),
    expand_aggregate: str | None = None,
) -> SemanticGraphResponse:
    """Get graph at the appropriate semantic zoom level with optional aggregation.

    This endpoint returns a graph rendered at different levels of detail
    based on the zoom level or scale:

    - Level 0 (scale < 0.3): Cluster view showing only package type aggregations
    - Level 1 (scale 0.3-0.7): Overview showing top packages per cluster
    - Level 2 (scale > 0.7): Detailed view with all visible nodes

    The scale parameter can be used to automatically determine the zoom level,
    or zoom_level can be explicitly specified.

    Task 8G-002 adds node aggregation support:
    - aggregation_mode: How to aggregate similar nodes (none, prefix, depth)
    - aggregation_threshold: Minimum nodes needed to form an aggregate
    - expand_aggregate: ID of an aggregate to expand (show its contents)

    Args:
        import_id: The import to visualize
        zoom_level: Explicit zoom level (0-2), overrides scale-based detection
        scale: Current display scale for automatic level selection
        center_node_id: Optional node to center the view on (for detailed level)
        package_type: Optional filter to a specific package type
        max_nodes: Maximum nodes to return at detailed level
        aggregation_mode: How to aggregate similar nodes (none, prefix, depth)
        aggregation_threshold: Minimum nodes to form an aggregate (2-50)
        expand_aggregate: ID of an aggregate to expand into individual nodes

    Returns:
        SemanticGraphResponse with rendered SVG, metadata, and aggregation info
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    # Determine effective zoom level
    effective_level = semantic_zoom.ZoomLevel(zoom_level)

    # Map aggregation mode string to enum
    agg_mode_map = {
        "none": semantic_zoom.AggregationMode.NONE,
        "prefix": semantic_zoom.AggregationMode.BY_PREFIX,
        "depth": semantic_zoom.AggregationMode.BY_DEPTH,
    }
    agg_mode = agg_mode_map.get(aggregation_mode, semantic_zoom.AggregationMode.NONE)

    # Get semantic graph data with aggregation (Task 8G-002)
    graph_data = semantic_zoom.get_semantic_graph_with_aggregation(
        import_id=import_id,
        zoom_level=effective_level,
        aggregation_mode=agg_mode,
        aggregation_threshold=aggregation_threshold,
        center_node_id=center_node_id,
        package_type=package_type,
        max_nodes=max_nodes,
        expand_aggregate=expand_aggregate,
    )

    # Generate DOT and render to SVG
    dot_source = semantic_zoom.generate_semantic_dot(graph_data, import_id)
    svg = render_service.render_dot_to_svg(dot_source)

    # Build available levels info
    available_levels = [
        {"level": 0, "name": "Clusters", "description": "Package type clusters only"},
        {"level": 1, "name": "Overview", "description": "Top packages per cluster"},
        {"level": 2, "name": "Detailed", "description": "All visible nodes"},
    ]

    # Get aggregation mode name for response
    agg_mode_names = {
        semantic_zoom.AggregationMode.NONE: "none",
        semantic_zoom.AggregationMode.BY_PREFIX: "prefix",
        semantic_zoom.AggregationMode.BY_DEPTH: "depth",
    }

    return SemanticGraphResponse(
        zoom_level=int(effective_level),
        svg=svg,
        cluster_count=len(graph_data.clusters),
        node_count=len(graph_data.nodes),
        edge_count=len(graph_data.edges),
        available_levels=available_levels,
        aggregate_count=len(graph_data.aggregates),
        aggregation_mode=agg_mode_names.get(graph_data.aggregation_mode, "none"),
    )


@router.get("/semantic-zoom/{import_id}/info")
async def get_semantic_zoom_info(import_id: int) -> dict[str, Any]:
    """Get information about available semantic zoom levels for an import.

    Returns details about what will be shown at each zoom level,
    useful for populating zoom level selector UI.

    Args:
        import_id: The import to analyze

    Returns:
        Dictionary with zoom level information
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    # Get cluster info for previews
    cluster_data = semantic_zoom.get_semantic_graph(
        import_id=import_id,
        zoom_level=semantic_zoom.ZoomLevel.CLUSTER,
    )

    return {
        "import_id": import_id,
        "total_nodes": import_info.node_count,
        "total_edges": import_info.edge_count,
        "levels": [
            {
                "level": 0,
                "name": "Clusters",
                "description": "Package type aggregations",
                "item_count": len(cluster_data.clusters),
                "preview": [
                    {
                        "type": c.package_type,
                        "count": c.node_count,
                    }
                    for c in cluster_data.clusters[:5]
                ],
            },
            {
                "level": 1,
                "name": "Overview",
                "description": "Top packages per cluster",
                "item_count": "~50-100 nodes",
                "preview": None,
            },
            {
                "level": 2,
                "name": "Detailed",
                "description": "Full detail view",
                "item_count": f"up to {import_info.node_count} nodes",
                "preview": None,
            },
        ],
        "recommended_thresholds": {
            "cluster_to_overview": 0.3,
            "overview_to_detailed": 0.7,
        },
        # Task 8G-002: Aggregation support
        "aggregation_modes": [
            {"mode": "none", "description": "No aggregation - show all nodes individually"},
            {"mode": "prefix", "description": "Aggregate by label prefix (e.g., python3.11-*)"},
            {"mode": "depth", "description": "Aggregate by dependency depth level"},
        ],
        "recommended_aggregation_threshold": 5,
    }


@router.get("/semantic-zoom/{import_id}/aggregates")
async def get_semantic_zoom_aggregates(
    import_id: int,
    zoom_level: int = Query(default=1, ge=0, le=2),
    aggregation_mode: str = Query(default="prefix", pattern="^(none|prefix|depth)$"),
    aggregation_threshold: int = Query(default=5, ge=2, le=50),
    package_type: str | None = None,
    max_nodes: int = Query(default=100, ge=10, le=500),
) -> list[AggregateInfoResponse]:
    """Get list of aggregates that would be created at a given zoom level.

    This endpoint returns information about the aggregates without the full
    SVG rendering, useful for UI previews and aggregate selection.

    Task 8G-002: Node aggregation support.

    Args:
        import_id: The import to analyze
        zoom_level: The zoom level to compute aggregates for (1 or 2)
        aggregation_mode: How to aggregate (prefix or depth)
        aggregation_threshold: Minimum nodes to form an aggregate
        package_type: Optional filter to a specific package type
        max_nodes: Maximum nodes to consider

    Returns:
        List of AggregateInfoResponse with aggregate details
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    # Map aggregation mode string to enum
    agg_mode_map = {
        "none": semantic_zoom.AggregationMode.NONE,
        "prefix": semantic_zoom.AggregationMode.BY_PREFIX,
        "depth": semantic_zoom.AggregationMode.BY_DEPTH,
    }
    agg_mode = agg_mode_map.get(aggregation_mode, semantic_zoom.AggregationMode.BY_PREFIX)

    if agg_mode == semantic_zoom.AggregationMode.NONE:
        return []

    # Get graph data with aggregation
    graph_data = semantic_zoom.get_semantic_graph_with_aggregation(
        import_id=import_id,
        zoom_level=semantic_zoom.ZoomLevel(zoom_level),
        aggregation_mode=agg_mode,
        aggregation_threshold=aggregation_threshold,
        package_type=package_type,
        max_nodes=max_nodes,
    )

    # Convert aggregates to response format
    return [
        AggregateInfoResponse(
            id=agg.id,
            label_prefix=agg.label_prefix,
            package_type=agg.package_type,
            node_count=agg.node_count,
            total_closure_size=agg.total_closure_size,
            representative_labels=[n.label for n in agg.representative_nodes[:5]],
            can_expand=agg.can_expand,
        )
        for agg in graph_data.aggregates
    ]


# =============================================================================
# Treemap Endpoints (Task 8C-002)
# =============================================================================


class TreemapNodeResponse(BaseModel):
    """A node in the treemap hierarchy."""
    name: str
    node_id: int | None = None
    value: int | None = None
    package_type: str | None = None
    unique_contribution: int | None = None
    children: list["TreemapNodeResponse"] | None = None


class TreemapDataRequest(BaseModel):
    """Request model for treemap data with optional parameters."""
    mode: str = "application"
    filter_type: str = "all"
    root_node_id: int | None = None
    max_depth: int = 3
    limit: int = 20


@router.get("/treemap/{import_id}")
async def get_treemap_data(
    import_id: int,
    mode: str = Query(default="application", pattern="^(application|type|depth|flat)$"),
    filter_type: str = Query(default="all"),
    root_node_id: int | None = None,
    max_depth: int = Query(default=3, ge=1, le=10),
    limit: int = Query(default=20, ge=5, le=50),
) -> dict[str, Any]:
    """Get hierarchical treemap data for D3.js visualization.

    Returns nested data structure suitable for D3.js treemap layout.
    The response includes nested children with value (closure_size) for leaf nodes.

    Modes:
    - application: Top-level apps as root, dependencies as children
    - type: Package types as root, packages as children
    - depth: Dependency depth levels as root
    - flat: All packages at same level

    Filter types:
    - all: Include all packages
    - runtime: Only runtime dependencies
    - build: Only build-time dependencies
    - type:X: Only packages of type X (e.g., type:library)

    Args:
        import_id: The import to visualize
        mode: Hierarchy organization mode
        filter_type: Filter for dependency or package types
        root_node_id: If set, build treemap rooted at this node (for zoom)
        max_depth: Maximum hierarchy depth to return (1-10)
        limit: Maximum children per parent node (5-50)

    Returns:
        Nested dictionary with treemap data structure
    """
    from vizzy.services import treemap as treemap_service

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    data = treemap_service.build_treemap_data(
        import_id=import_id,
        mode=mode,
        filter_type=filter_type,
        root_node_id=root_node_id,
        max_depth=max_depth,
        limit=limit,
    )

    return data


@router.get("/treemap/{import_id}/node/{node_id}")
async def get_treemap_node_info(import_id: int, node_id: int) -> dict[str, Any]:
    """Get detailed information about a treemap node for tooltip display.

    Returns detailed node information including closure size, contribution,
    dependency counts, and top-level status.

    Args:
        import_id: The import context (for validation)
        node_id: The node to get info for

    Returns:
        Dictionary with detailed node information
    """
    from vizzy.services import treemap as treemap_service

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    info = treemap_service.get_treemap_node_info(node_id)
    if not info:
        raise HTTPException(status_code=404, detail="Node not found")

    # Verify node belongs to this import
    node = graph_service.get_node(node_id)
    if not node or node.import_id != import_id:
        raise HTTPException(status_code=404, detail="Node not found in this import")

    return info


@router.get("/treemap/{import_id}/package-types")
async def get_treemap_package_types(import_id: int) -> list[dict[str, Any]]:
    """Get available package types for filter dropdown.

    Returns list of package types with counts, useful for populating
    the filter dropdown in the treemap UI.

    Args:
        import_id: The import to analyze

    Returns:
        List of dictionaries with package_type and count
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    from vizzy.database import get_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(package_type, 'unknown') as package_type,
                    COUNT(*) as count
                FROM nodes
                WHERE import_id = %s
                GROUP BY package_type
                ORDER BY count DESC
                """,
                (import_id,)
            )
            return [dict(row) for row in cur.fetchall()]


# =============================================================================
# Variant Matrix Endpoints (Task 8D-002)
# =============================================================================


class VariantInfoResponse(BaseModel):
    """Information about a single package variant."""
    node_id: int
    drv_hash: str
    short_hash: str
    label: str
    package_type: str | None
    dependency_type: str | None
    dependent_count: int
    closure_size: int | None


class ApplicationRowResponse(BaseModel):
    """A row in the variant matrix showing which variants an app uses."""
    label: str
    node_id: int | None
    package_type: str | None
    is_top_level: bool
    cells: dict[int, dict[str, Any]]


class VariantMatrixResponse(BaseModel):
    """Complete matrix data for variant visualization."""
    label: str
    import_id: int
    variants: list[VariantInfoResponse]
    applications: list[ApplicationRowResponse]
    total_variants: int
    total_dependents: int
    has_build_runtime_info: bool


class VariantLabelResponse(BaseModel):
    """A package with multiple variants."""
    label: str
    variant_count: int
    total_dependents: int


class VariantSummaryResponse(BaseModel):
    """Summary of a package's variants."""
    label: str
    import_id: int
    variant_count: int
    total_nodes: int
    total_closure: int
    unique_dependents: int


@router.get("/variant-matrix/{import_id}/{label}")
async def get_variant_matrix(
    import_id: int,
    label: str,
    max_variants: int = Query(default=20, ge=1, le=50),
    max_dependents: int = Query(default=50, ge=10, le=200),
    sort_by: str = Query(default="dependent_count", pattern="^(dependent_count|hash|closure_size)$"),
    filter_type: str = Query(default="all", pattern="^(all|runtime|build)$"),
    direct_only: bool = Query(default=False),
) -> dict[str, Any]:
    """Get variant matrix data showing which apps use which package variants.

    Returns a matrix structure showing:
    - Columns: Different variants (hashes) of the package
    - Rows: Applications/packages that depend on these variants
    - Cells: Whether a dependent uses each variant (and dependency type)

    This visualization helps answer:
    - "Which of my packages are causing duplicate derivations?"
    - "Which apps share variants (consolidation opportunities)?"
    - "Which apps use unique variants (potential build issues)?"

    Args:
        import_id: The import to analyze
        label: Package name to find variants for (e.g., "openssl")
        max_variants: Maximum number of variants to include (1-50)
        max_dependents: Maximum dependents per variant (10-200)
        sort_by: How to sort variants (dependent_count, hash, closure_size)
        filter_type: Filter by dependency type (all, runtime, build)
        direct_only: If True, only show top-level packages (explicitly installed)

    Returns:
        VariantMatrix as dictionary with variants, applications, and cells
    """
    from vizzy.services import variant_matrix as vm_service

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    matrix = vm_service.build_variant_matrix(
        import_id=import_id,
        label=label,
        max_variants=max_variants,
        max_dependents=max_dependents,
        sort_by=sort_by,
        filter_type=filter_type,
        direct_only=direct_only,
    )

    return matrix.to_dict()


@router.get("/variant-matrix/{import_id}/labels")
async def get_variant_labels(
    import_id: int,
    min_count: int = Query(default=2, ge=2, le=10),
    limit: int = Query(default=50, ge=10, le=200),
) -> list[VariantLabelResponse]:
    """Get list of package labels that have multiple variants.

    Returns packages sorted by variant count and total dependents,
    useful for populating a package selector in the variant matrix UI.

    Args:
        import_id: The import to analyze
        min_count: Minimum number of variants to include (default 2)
        limit: Maximum packages to return (10-200)

    Returns:
        List of packages with variant counts and dependent counts
    """
    from vizzy.services import variant_matrix as vm_service

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    labels = vm_service.get_variant_labels(
        import_id=import_id,
        min_count=min_count,
        limit=limit,
    )

    return [
        VariantLabelResponse(
            label=item['label'],
            variant_count=item['variant_count'],
            total_dependents=item['total_dependents'],
        )
        for item in labels
    ]


@router.get("/variant-matrix/{import_id}/summary/{label}")
async def get_variant_summary(
    import_id: int,
    label: str,
) -> VariantSummaryResponse | dict[str, Any]:
    """Get quick summary information about a package's variants.

    Returns lightweight summary data suitable for tooltips or previews
    without computing the full matrix.

    Args:
        import_id: The import to analyze
        label: Package name to summarize

    Returns:
        VariantSummaryResponse with summary metrics
    """
    from vizzy.services import variant_matrix as vm_service

    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    summary = vm_service.get_variant_summary(import_id, label)

    if not summary:
        return {
            "label": label,
            "import_id": import_id,
            "error": "No variants found for this package",
        }

    return VariantSummaryResponse(
        label=summary['label'],
        import_id=summary['import_id'],
        variant_count=summary['variant_count'],
        total_nodes=summary['total_nodes'],
        total_closure=summary['total_closure'],
        unique_dependents=summary['unique_dependents'],
    )
