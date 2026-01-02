"""API routes for baseline closure reference system.

This module provides REST API endpoints for:
- Creating baselines from imports
- Listing and retrieving baselines
- Comparing imports against baselines
- Managing baseline metadata

Related tasks:
- 8A-004: Create baseline closure reference system
- 8F-004: Add baseline comparison presets (uses these endpoints)
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from vizzy.services import graph as graph_service
from vizzy.services import baseline as baseline_service

router = APIRouter(prefix="/api/baselines", tags=["baselines"])


# =============================================================================
# Request/Response Models
# =============================================================================


class BaselineResponse(BaseModel):
    """Response model for a baseline."""
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


class BaselineListResponse(BaseModel):
    """Response model for baseline list."""
    baselines: list[BaselineResponse]
    total: int


class BaselineCreateRequest(BaseModel):
    """Request model for creating a baseline."""
    name: str
    description: str | None = None
    tags: list[str] = []
    is_system_baseline: bool = False


class BaselineCreateResponse(BaseModel):
    """Response model for baseline creation."""
    baseline_id: int
    name: str
    node_count: int
    edge_count: int
    success: bool
    message: str


class BaselineUpdateRequest(BaseModel):
    """Request model for updating a baseline."""
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class BaselineComparisonResponse(BaseModel):
    """Response model for baseline comparison."""
    import_id: int
    baseline_id: int
    baseline_name: str
    node_difference: int
    edge_difference: int
    percentage_difference: float
    differences_by_type: dict[str, int]
    is_larger: bool
    growth_category: str
    computed_at: datetime


# =============================================================================
# Baseline CRUD Endpoints
# =============================================================================


@router.get("", response_model=BaselineListResponse)
async def list_baselines(
    include_system: bool = Query(default=True, description="Include system baselines"),
    tags: list[str] | None = Query(default=None, description="Filter by tags"),
    limit: int = Query(default=50, ge=1, le=100),
) -> BaselineListResponse:
    """List all available baselines.

    Returns baselines sorted by creation date (newest first).

    Args:
        include_system: Whether to include system baselines (default True)
        tags: Optional filter by tags (any match)
        limit: Maximum number of baselines to return (1-100)

    Returns:
        BaselineListResponse with list of baselines
    """
    baselines = baseline_service.list_baselines(
        include_system=include_system,
        tags=tags,
        limit=limit,
    )

    return BaselineListResponse(
        baselines=[_baseline_to_response(b) for b in baselines],
        total=len(baselines),
    )


@router.get("/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(baseline_id: int) -> BaselineResponse:
    """Get a specific baseline by ID.

    Args:
        baseline_id: The baseline ID

    Returns:
        BaselineResponse with baseline details

    Raises:
        HTTPException 404: Baseline not found
    """
    baseline = baseline_service.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")

    return _baseline_to_response(baseline)


@router.post("/from-import/{import_id}", response_model=BaselineCreateResponse)
async def create_baseline_from_import(
    import_id: int,
    request: BaselineCreateRequest,
) -> BaselineCreateResponse:
    """Create a baseline from an existing import.

    Captures the current state of an import as a baseline for future comparisons.
    The baseline persists even if the source import is later deleted.

    Args:
        import_id: The import to create a baseline from
        request: Baseline creation parameters

    Returns:
        BaselineCreateResponse with created baseline info

    Raises:
        HTTPException 404: Import not found
        HTTPException 400: Creation failed
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    result = baseline_service.create_baseline_from_import(
        import_id=import_id,
        name=request.name,
        description=request.description,
        tags=request.tags,
        is_system_baseline=request.is_system_baseline,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return BaselineCreateResponse(
        baseline_id=result.baseline_id,
        name=result.name,
        node_count=result.node_count,
        edge_count=result.edge_count,
        success=result.success,
        message=result.message,
    )


@router.patch("/{baseline_id}", response_model=BaselineResponse)
async def update_baseline(
    baseline_id: int,
    request: BaselineUpdateRequest,
) -> BaselineResponse:
    """Update baseline metadata.

    Note: Metrics cannot be updated after creation - only name, description, and tags.

    Args:
        baseline_id: The baseline to update
        request: Update parameters

    Returns:
        Updated BaselineResponse

    Raises:
        HTTPException 404: Baseline not found
    """
    baseline = baseline_service.update_baseline(
        baseline_id=baseline_id,
        name=request.name,
        description=request.description,
        tags=request.tags,
    )

    if not baseline:
        raise HTTPException(status_code=404, detail="Baseline not found")

    return _baseline_to_response(baseline)


@router.delete("/{baseline_id}")
async def delete_baseline(baseline_id: int) -> dict[str, Any]:
    """Delete a baseline.

    Note: System baselines cannot be deleted.

    Args:
        baseline_id: The baseline to delete

    Returns:
        Success message

    Raises:
        HTTPException 404: Baseline not found or is system baseline
    """
    success = baseline_service.delete_baseline(baseline_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Baseline not found or is a system baseline (cannot delete)"
        )

    return {"success": True, "message": f"Baseline {baseline_id} deleted"}


# =============================================================================
# Comparison Endpoints
# =============================================================================


@router.get("/compare/{import_id}/{baseline_id}", response_model=BaselineComparisonResponse)
async def compare_import_to_baseline(
    import_id: int,
    baseline_id: int,
) -> BaselineComparisonResponse:
    """Compare an import against a baseline.

    Computes differences between the current import and a stored baseline,
    providing metrics useful for understanding closure growth.

    Args:
        import_id: The import to compare
        baseline_id: The baseline to compare against

    Returns:
        BaselineComparisonResponse with detailed differences

    Raises:
        HTTPException 404: Import or baseline not found
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    comparison = baseline_service.compare_to_baseline(import_id, baseline_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="Baseline not found")

    return BaselineComparisonResponse(
        import_id=comparison.import_id,
        baseline_id=comparison.baseline_id,
        baseline_name=comparison.baseline_name,
        node_difference=comparison.node_difference,
        edge_difference=comparison.edge_difference,
        percentage_difference=comparison.percentage_difference,
        differences_by_type=comparison.differences_by_type,
        is_larger=comparison.is_larger,
        growth_category=comparison.growth_category,
        computed_at=comparison.computed_at,
    )


@router.get("/compare/{import_id}", response_model=BaselineComparisonResponse | None)
async def get_dashboard_comparison(import_id: int) -> BaselineComparisonResponse | None:
    """Get the best baseline comparison for dashboard display.

    Selects the most appropriate baseline for comparison:
    1. First system baseline (if any)
    2. Most recent user baseline

    Args:
        import_id: The import to find a comparison for

    Returns:
        BaselineComparisonResponse or None if no baselines exist
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    comparison = baseline_service.get_comparison_for_dashboard(import_id)
    if not comparison:
        return None

    return BaselineComparisonResponse(
        import_id=comparison.import_id,
        baseline_id=comparison.baseline_id,
        baseline_name=comparison.baseline_name,
        node_difference=comparison.node_difference,
        edge_difference=comparison.edge_difference,
        percentage_difference=comparison.percentage_difference,
        differences_by_type=comparison.differences_by_type,
        is_larger=comparison.is_larger,
        growth_category=comparison.growth_category,
        computed_at=comparison.computed_at,
    )


@router.post("/compare/{import_id}/{baseline_id}/invalidate")
async def invalidate_comparison(
    import_id: int,
    baseline_id: int,
) -> dict[str, Any]:
    """Invalidate a cached baseline comparison.

    Call this when import data changes and the comparison needs recomputation.

    Args:
        import_id: The import whose comparison to invalidate
        baseline_id: The baseline to invalidate comparison for

    Returns:
        Count of comparisons invalidated
    """
    count = baseline_service.invalidate_comparison(import_id, baseline_id)
    return {"invalidated": count}


@router.post("/compare/{import_id}/invalidate-all")
async def invalidate_all_comparisons(import_id: int) -> dict[str, Any]:
    """Invalidate all baseline comparisons for an import.

    Call this when import data changes significantly.

    Args:
        import_id: The import whose comparisons to invalidate

    Returns:
        Count of comparisons invalidated
    """
    count = baseline_service.invalidate_comparison(import_id)
    return {"invalidated": count}


# =============================================================================
# Helper Functions
# =============================================================================


def _baseline_to_response(baseline: baseline_service.Baseline) -> BaselineResponse:
    """Convert a Baseline service object to API response."""
    return BaselineResponse(
        id=baseline.id,
        name=baseline.name,
        description=baseline.description,
        source_import_id=baseline.source_import_id,
        node_count=baseline.node_count,
        edge_count=baseline.edge_count,
        closure_by_type=baseline.closure_by_type,
        top_level_count=baseline.top_level_count,
        runtime_edge_count=baseline.runtime_edge_count,
        build_edge_count=baseline.build_edge_count,
        max_depth=baseline.max_depth,
        avg_depth=baseline.avg_depth,
        top_contributors=baseline.top_contributors,
        created_at=baseline.created_at,
        updated_at=baseline.updated_at,
        is_system_baseline=baseline.is_system_baseline,
        tags=baseline.tags,
    )


# =============================================================================
# Preset Endpoints (Phase 8F-004)
# =============================================================================


class BaselinePresetResponse(BaseModel):
    """Response model for a baseline preset."""
    id: str
    name: str
    description: str | None
    preset_type: str
    target_id: int | None
    node_count: int | None
    edge_count: int | None
    created_at: datetime | None


class PresetListResponse(BaseModel):
    """Response model for preset list."""
    presets: list[BaselinePresetResponse]
    total: int


class PreviousImportComparisonResponse(BaseModel):
    """Response model for previous import comparison."""
    import_id: int
    previous_import_id: int
    previous_import_name: str
    previous_imported_at: datetime
    node_difference: int
    edge_difference: int
    percentage_difference: float
    differences_by_type: dict[str, int]
    is_larger: bool
    growth_category: str
    computed_at: datetime


@router.get("/presets/{import_id}", response_model=PresetListResponse)
async def get_presets(import_id: int) -> PresetListResponse:
    """Get available comparison presets for an import.

    Returns a list of presets including:
    - Previous import (if available)
    - System baselines (minimal NixOS, etc.)
    - User-saved baselines

    Presets are ordered by relevance.

    Args:
        import_id: The import to get presets for

    Returns:
        PresetListResponse with list of available presets
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    presets = baseline_service.get_available_presets(import_id)

    return PresetListResponse(
        presets=[
            BaselinePresetResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                preset_type=p.preset_type,
                target_id=p.target_id,
                node_count=p.node_count,
                edge_count=p.edge_count,
                created_at=p.created_at,
            )
            for p in presets
        ],
        total=len(presets),
    )


@router.get("/previous-import/{import_id}")
async def get_previous_import(import_id: int) -> dict[str, Any] | None:
    """Get the previous import for the same host.

    Finds the most recent import with the same name that was
    imported before the given import.

    Args:
        import_id: The current import ID

    Returns:
        Previous import info or None if no previous import exists
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    previous = baseline_service.get_previous_import(import_id)
    return previous


@router.get("/compare-previous/{import_id}", response_model=PreviousImportComparisonResponse | None)
async def compare_to_previous_import(import_id: int) -> PreviousImportComparisonResponse | None:
    """Compare an import to its previous version.

    Finds the previous import of the same host and computes
    a comparison showing what changed.

    Args:
        import_id: The current import ID

    Returns:
        PreviousImportComparisonResponse or None if no previous import exists
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    comparison = baseline_service.compare_to_previous_import(import_id)
    if not comparison:
        return None

    # Get previous import info for the response
    previous = baseline_service.get_previous_import(import_id)
    if not previous:
        return None

    return PreviousImportComparisonResponse(
        import_id=comparison.import_id,
        previous_import_id=previous['id'],
        previous_import_name=previous['name'],
        previous_imported_at=previous['imported_at'],
        node_difference=comparison.node_difference,
        edge_difference=comparison.edge_difference,
        percentage_difference=comparison.percentage_difference,
        differences_by_type=comparison.differences_by_type,
        is_larger=comparison.is_larger,
        growth_category=comparison.growth_category,
        computed_at=comparison.computed_at,
    )


@router.get("/host-imports/{host_name}")
async def get_host_imports(
    host_name: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Get all imports for a specific host.

    Useful for comparing different versions of the same host over time.

    Args:
        host_name: The host name to find imports for
        limit: Maximum number of imports to return

    Returns:
        List of import info dicts, newest first
    """
    return baseline_service.get_imports_for_host(host_name, limit)


@router.post("/quick-save/{import_id}", response_model=BaselineCreateResponse)
async def quick_save_baseline(
    import_id: int,
    suffix: str | None = Query(default=None, description="Optional suffix for the baseline name"),
) -> BaselineCreateResponse:
    """Quickly save an import as a baseline.

    Creates a baseline with an automatically generated name based on
    the import name and timestamp.

    Args:
        import_id: The import to create a baseline from
        suffix: Optional suffix to add to the name

    Returns:
        BaselineCreateResponse with created baseline info
    """
    # Verify import exists
    import_info = graph_service.get_import(import_id)
    if not import_info:
        raise HTTPException(status_code=404, detail="Import not found")

    result = baseline_service.create_baseline_with_auto_name(import_id, suffix)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return BaselineCreateResponse(
        baseline_id=result.baseline_id,
        name=result.name,
        node_count=result.node_count,
        edge_count=result.edge_count,
        success=result.success,
        message=result.message,
    )
