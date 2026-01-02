"""Host/Import comparison routes"""

from pathlib import Path
from enum import Enum
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from vizzy.models import DiffType
from vizzy.services import comparison as comparison_service
from vizzy.services import graph as graph_service
from vizzy.services import baseline as baseline_service
from vizzy.database import get_db

router = APIRouter(prefix="/compare")

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


class DiffCategory(str, Enum):
    """High-level diff categories for UI grouping."""

    DESKTOP_ENV = "Desktop Environment"
    SYSTEM_SERVICES = "System Services"
    DEVELOPMENT = "Development Tools"
    NETWORKING = "Networking"
    MULTIMEDIA = "Multimedia"
    LIBRARIES = "Core Libraries"
    FONTS = "Fonts"
    DOCUMENTATION = "Documentation"
    OTHER = "Other"


# Pattern matching for categorization
CATEGORY_PATTERNS = {
    DiffCategory.DESKTOP_ENV: [
        r"^gnome-",
        r"^kde-",
        r"^plasma-",
        r"^gtk[234]",
        r"^wayland",
        r"^xorg-",
        r"^mutter",
        r"^kwin",
        r"^xfce",
        r"^lxqt",
        r"^qt[56]-",
    ],
    DiffCategory.SYSTEM_SERVICES: [
        r"^systemd-",
        r"-service$",
        r"^dbus",
        r"^polkit",
        r"^udev",
        r"^acpid",
        r"^cron",
    ],
    DiffCategory.DEVELOPMENT: [
        r"^gcc-",
        r"^clang-",
        r"^rustc",
        r"^cargo",
        r"^python\d",
        r"^nodejs",
        r"^go-",
        r"-dev$",
        r"^cmake",
        r"^make",
        r"^binutils",
    ],
    DiffCategory.NETWORKING: [
        r"^networkmanager",
        r"^wpa_supplicant",
        r"^iwd",
        r"^curl",
        r"^wget",
        r"^openssh",
        r"^openssl",
        r"^iptables",
        r"^nftables",
    ],
    DiffCategory.MULTIMEDIA: [
        r"^pulseaudio",
        r"^pipewire",
        r"^alsa-",
        r"^ffmpeg",
        r"^gstreamer",
        r"^vlc",
        r"^mpv",
        r"^libav",
    ],
    DiffCategory.LIBRARIES: [
        r"^glibc",
        r"^zlib",
        r"^libffi",
        r"^ncurses",
        r"^readline",
        r"^libiconv",
        r"^libunistring",
        r"^libxcrypt",
    ],
    DiffCategory.FONTS: [
        r"^font-",
        r"-font$",
        r"^noto-",
        r"^dejavu",
        r"^liberation-",
        r"^freefont",
    ],
    DiffCategory.DOCUMENTATION: [
        r"-man$",
        r"-doc$",
        r"^man-pages",
        r"-info$",
    ],
}


def categorize_diff(label: str) -> DiffCategory:
    """Categorize a package diff by its label."""
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, label, re.IGNORECASE):
                return category
    return DiffCategory.OTHER


def categorize_diffs(diffs):
    """Group diffs by semantic category.

    Alias for group_diffs_by_category for API consistency.
    """
    return group_diffs_by_category(diffs)


def group_diffs_by_category(diffs):
    """Group diffs by semantic category."""
    categorized = {cat: [] for cat in DiffCategory}

    for diff in diffs:
        category = categorize_diff(diff.label)
        categorized[category].append(diff)

    # Remove empty categories and sort by count
    return {k: v for k, v in sorted(categorized.items(), key=lambda x: -len(x[1])) if v}


def score_diff_importance(diff) -> float:
    """Score how 'important' a diff is to the user.

    High importance:
    - Top-level packages (is_top_level)
    - Large closure impact
    - User-facing applications

    Low importance:
    - Libraries
    - Build-time only
    - Small closure

    Args:
        diff: A NodeDiff object

    Returns:
        A float score indicating importance (higher = more important)
    """
    score = 0.0

    # Check if top-level (requires is_top_level field from Phase 6)
    node = diff.left_node or diff.right_node
    if node and getattr(node, 'is_top_level', False):
        score += 10

    # Package type scoring
    if diff.package_type == 'application':
        score += 5
    elif diff.package_type == 'service':
        score += 4
    elif diff.package_type == 'development':
        score += 3
    elif diff.package_type == 'library':
        score -= 2
    elif diff.package_type == 'documentation':
        score -= 3
    elif diff.package_type == 'font':
        score -= 1

    # Closure impact (larger impact = more important)
    left_closure = diff.left_node.closure_size if diff.left_node else 0
    right_closure = diff.right_node.closure_size if diff.right_node else 0
    closure_impact = abs((left_closure or 0) - (right_closure or 0))
    score += min(closure_impact / 100, 5)  # Cap at 5 points

    # Category scoring
    category = categorize_diff(diff.label)
    if category == DiffCategory.DESKTOP_ENV:
        score += 3
    elif category == DiffCategory.SYSTEM_SERVICES:
        score += 2
    elif category == DiffCategory.DEVELOPMENT:
        score += 2
    elif category == DiffCategory.LIBRARIES:
        score -= 1
    elif category == DiffCategory.DOCUMENTATION:
        score -= 2
    elif category == DiffCategory.FONTS:
        score -= 1

    return score


def sort_diffs_by_importance(diffs) -> list:
    """Sort diffs with most important first.

    Args:
        diffs: List of NodeDiff objects

    Returns:
        Sorted list with most important diffs first
    """
    return sorted(diffs, key=score_diff_importance, reverse=True)


@router.get("", response_class=HTMLResponse)
async def compare_select(
    request: Request,
    left: int | None = None,
    right: int | None = None,
):
    """Comparison page - shows selector or results."""
    imports = graph_service.get_imports()

    # If we have both imports selected, show comparison
    if left is not None and right is not None and left != right:
        left_import = graph_service.get_import(left)
        right_import = graph_service.get_import(right)

        if not left_import:
            return HTMLResponse(f"Left import {left} not found", status_code=404)
        if not right_import:
            return HTMLResponse(f"Right import {right} not found", status_code=404)

        # Get the comparison data
        comparison = comparison_service.compare_imports(left, right)
        # Use enhanced summary with semantic category breakdown
        summary = comparison_service.generate_enhanced_diff_summary(comparison)

        # Group diffs by side and category
        left_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_LEFT]
        right_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_RIGHT]
        different_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.DIFFERENT_HASH]

        left_by_category = group_diffs_by_category(left_diffs)
        right_by_category = group_diffs_by_category(right_diffs)

        return templates.TemplateResponse(
            "compare/compare.html",
            {
                "request": request,
                "left": left_import,
                "right": right_import,
                "summary": summary,
                "left_only_count": comparison.left_only_count,
                "right_only_count": comparison.right_only_count,
                "same_count": comparison.same_count,
                "different_count": comparison.different_count,
                "left_by_category": left_by_category,
                "right_by_category": right_by_category,
                "different_diffs": different_diffs[:50],  # Limit for initial load
                "total_different": len(different_diffs),
            },
        )

    # Show selector with presets
    # Determine which import to get presets for (first selected, or most recent)
    selected_import_id = left or (imports[0].id if imports else None)
    presets = []
    if selected_import_id:
        presets = baseline_service.get_available_presets(selected_import_id)

    return templates.TemplateResponse(
        "compare/select.html",
        {
            "request": request,
            "imports": imports,
            "selected_left": left,
            "selected_right": right,
            "selected_import_id": selected_import_id,
            "presets": presets,
        },
    )


@router.get("/partials/category/{left_id}/{right_id}/{category}", response_class=HTMLResponse)
async def compare_category_partial(
    request: Request,
    left_id: int,
    right_id: int,
    category: str,
    side: str = "both",
):
    """Return category HTML for HTMX swap."""
    comparison = comparison_service.compare_imports(left_id, right_id)

    # Find the matching category
    target_category = None
    for cat in DiffCategory:
        if cat.value == category:
            target_category = cat
            break

    if target_category is None:
        return HTMLResponse("Category not found", status_code=404)

    # Filter diffs by side
    if side == "left":
        diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_LEFT]
    elif side == "right":
        diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_RIGHT]
    else:
        diffs = comparison.all_diffs

    # Filter by category
    category_diffs = [d for d in diffs if categorize_diff(d.label) == target_category]

    return templates.TemplateResponse(
        "compare/partials/category.html",
        {
            "request": request,
            "diffs": category_diffs,
            "category": target_category,
            "side": side,
            "left_id": left_id,
            "right_id": right_id,
        },
    )


@router.get("/partials/versions/{left_id}/{right_id}", response_class=HTMLResponse)
async def compare_versions_partial(
    request: Request,
    left_id: int,
    right_id: int,
    page: int = 1,
    limit: int = 50,
):
    """Return version differences for HTMX swap."""
    comparison = comparison_service.compare_imports(left_id, right_id)

    # Get diffs with different hashes (version changes)
    version_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.DIFFERENT_HASH]

    # Sort by label for consistency
    version_diffs.sort(key=lambda d: d.label)

    # Paginate
    start = (page - 1) * limit
    end = start + limit
    paginated = version_diffs[start:end]

    return templates.TemplateResponse(
        "compare/partials/versions.html",
        {
            "request": request,
            "diffs": paginated,
            "page": page,
            "total": len(version_diffs),
            "pages": (len(version_diffs) + limit - 1) // limit,
            "left_id": left_id,
            "right_id": right_id,
        },
    )


@router.get("/api/{left_id}/{right_id}")
async def compare_api(
    left_id: int,
    right_id: int,
    category: str | None = None,
):
    """Get comparison data as JSON."""
    comparison = comparison_service.compare_imports(left_id, right_id)

    if category:
        # Filter to specific category
        target_category = None
        for cat in DiffCategory:
            if cat.value == category:
                target_category = cat
                break

        if target_category:
            filtered = [d for d in comparison.all_diffs if categorize_diff(d.label) == target_category]
            return {
                "category": category,
                "diffs": [d.model_dump() for d in filtered],
                "count": len(filtered),
            }

    return {
        "left_import": comparison.left_import.model_dump(),
        "right_import": comparison.right_import.model_dump(),
        "left_only_count": comparison.left_only_count,
        "right_only_count": comparison.right_only_count,
        "different_count": comparison.different_count,
        "same_count": comparison.same_count,
        "summary": comparison_service.generate_diff_summary(comparison),
    }


# =============================================================================
# Package Trace Comparison (Task 5-003)
# =============================================================================


def get_reverse_paths(import_id: int, node_id: int, max_depth: int = 10) -> list[list[dict]]:
    """Get paths from root nodes down to a specific node.

    Returns paths as lists of node dicts, showing how a package is reached.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find paths from this node back up to roots (dependents chain)
            cur.execute(
                """
                WITH RECURSIVE paths AS (
                    -- Start from target node
                    SELECT
                        n.id,
                        n.label,
                        n.package_type,
                        ARRAY[n.id] as path_ids,
                        ARRAY[n.label] as path_labels,
                        1 as depth
                    FROM nodes n
                    WHERE n.id = %s AND n.import_id = %s

                    UNION ALL

                    -- Follow edges backwards (find what depends on this)
                    SELECT
                        parent.id,
                        parent.label,
                        parent.package_type,
                        parent.id || p.path_ids,
                        parent.label || p.path_labels,
                        p.depth + 1
                    FROM paths p
                    JOIN edges e ON e.source_id = p.id
                    JOIN nodes parent ON e.target_id = parent.id
                    WHERE p.depth < %s
                      AND parent.id != ALL(p.path_ids)  -- Avoid cycles
                      AND parent.import_id = %s
                )
                SELECT DISTINCT path_labels, path_ids
                FROM paths
                WHERE NOT EXISTS (
                    -- This path ends at a root (nothing depends on head of path)
                    SELECT 1 FROM edges e2
                    WHERE e2.source_id = paths.id
                    AND e2.import_id = %s
                )
                ORDER BY array_length(path_labels, 1) DESC
                LIMIT 10
                """,
                (node_id, import_id, max_depth, import_id, import_id)
            )

            results = []
            for row in cur.fetchall():
                path = []
                for label, nid in zip(row['path_labels'], row['path_ids']):
                    path.append({'label': label, 'id': nid})
                results.append(path)

            return results


def compare_package_traces(
    left_import_id: int,
    right_import_id: int,
    package_label: str,
) -> dict:
    """
    Compare how a package is reached in two configurations.

    Returns paths from root-level packages down to the target package
    in both configurations.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find node in left import
            cur.execute(
                """
                SELECT id, label, drv_hash, package_type
                FROM nodes
                WHERE import_id = %s AND label = %s
                LIMIT 1
                """,
                (left_import_id, package_label)
            )
            left_row = cur.fetchone()

            # Find node in right import
            cur.execute(
                """
                SELECT id, label, drv_hash, package_type
                FROM nodes
                WHERE import_id = %s AND label = %s
                LIMIT 1
                """,
                (right_import_id, package_label)
            )
            right_row = cur.fetchone()

    result = {
        "package": package_label,
        "left_node": None,
        "right_node": None,
        "left_paths": [],
        "right_paths": [],
        "same_hash": False,
        "in_both": False,
    }

    if left_row:
        result["left_node"] = dict(left_row)
        result["left_paths"] = get_reverse_paths(left_import_id, left_row['id'])

    if right_row:
        result["right_node"] = dict(right_row)
        result["right_paths"] = get_reverse_paths(right_import_id, right_row['id'])

    if left_row and right_row:
        result["in_both"] = True
        result["same_hash"] = left_row['drv_hash'] == right_row['drv_hash']

    return result


@router.get("/trace/{left_id}/{right_id}", response_class=HTMLResponse)
async def trace_page(
    request: Request,
    left_id: int,
    right_id: int,
    package: str | None = None,
):
    """Package trace comparison page - shows how a package arrives in each config."""
    left_import = graph_service.get_import(left_id)
    right_import = graph_service.get_import(right_id)

    if not left_import:
        return HTMLResponse(f"Left import {left_id} not found", status_code=404)
    if not right_import:
        return HTMLResponse(f"Right import {right_id} not found", status_code=404)

    trace_result = None
    if package:
        trace_result = compare_package_traces(left_id, right_id, package)

    return templates.TemplateResponse(
        "compare/trace.html",
        {
            "request": request,
            "left": left_import,
            "right": right_import,
            "package": package,
            "trace": trace_result,
        },
    )


@router.get("/api/trace/{left_id}/{right_id}")
async def trace_api(
    left_id: int,
    right_id: int,
    package: str,
):
    """Get package trace comparison as JSON."""
    return compare_package_traces(left_id, right_id, package)


# =============================================================================
# Comparison Report Export (Task 8F-003)
# =============================================================================

from fastapi.responses import Response
import json


@router.get("/export/{left_id}/{right_id}")
async def export_comparison(
    left_id: int,
    right_id: int,
    format: str = "json",
):
    """Export comparison results in various formats.

    Generates downloadable reports of the comparison between two imports.
    Supports JSON, CSV, and Markdown formats with semantic groupings,
    version differences, and full diff details.

    Args:
        left_id: ID of the left (baseline) import
        right_id: ID of the right (comparison) import
        format: Export format - one of 'json', 'csv', 'md' (markdown)

    Returns:
        A downloadable file response with appropriate Content-Type and
        Content-Disposition headers for the requested format.

    Raises:
        HTTPException: If import not found or invalid format
    """
    # Validate imports exist
    left_import = graph_service.get_import(left_id)
    right_import = graph_service.get_import(right_id)

    if not left_import:
        return HTMLResponse(f"Left import {left_id} not found", status_code=404)
    if not right_import:
        return HTMLResponse(f"Right import {right_id} not found", status_code=404)

    # Get comparison data
    comparison = comparison_service.compare_imports(left_id, right_id)

    # Generate export based on format
    format = format.lower()

    if format == "json":
        content = json.dumps(
            comparison_service.comparison_to_json(comparison),
            indent=2,
            ensure_ascii=False,
        )
        media_type = "application/json"
        extension = "json"

    elif format == "csv":
        content = comparison_service.comparison_to_csv(comparison)
        media_type = "text/csv"
        extension = "csv"

    elif format in ("md", "markdown"):
        content = comparison_service.comparison_to_markdown(comparison)
        media_type = "text/markdown"
        extension = "md"

    else:
        return HTMLResponse(
            f"Invalid format: {format}. Supported formats: json, csv, md",
            status_code=400,
        )

    # Generate filename
    filename = comparison_service.get_export_filename(comparison, extension)

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/api/export/{left_id}/{right_id}/preview")
async def export_preview(
    left_id: int,
    right_id: int,
    format: str = "json",
    lines: int = 50,
):
    """Preview export content without downloading.

    Returns the first N lines of the export for preview purposes
    in the UI before committing to a full download.

    Args:
        left_id: ID of the left import
        right_id: ID of the right import
        format: Export format - json, csv, or md
        lines: Number of lines to preview (default 50)

    Returns:
        JSON object with preview content and metadata
    """
    left_import = graph_service.get_import(left_id)
    right_import = graph_service.get_import(right_id)

    if not left_import or not right_import:
        return {"error": "Import not found"}

    comparison = comparison_service.compare_imports(left_id, right_id)

    format = format.lower()

    if format == "json":
        full_content = json.dumps(
            comparison_service.comparison_to_json(comparison),
            indent=2,
        )
    elif format == "csv":
        full_content = comparison_service.comparison_to_csv(comparison)
    elif format in ("md", "markdown"):
        full_content = comparison_service.comparison_to_markdown(comparison)
    else:
        return {"error": f"Invalid format: {format}"}

    # Get preview lines
    all_lines = full_content.split('\n')
    preview_lines = all_lines[:lines]
    is_truncated = len(all_lines) > lines

    return {
        "format": format,
        "total_lines": len(all_lines),
        "preview_lines": lines,
        "is_truncated": is_truncated,
        "preview": '\n'.join(preview_lines),
        "filename": comparison_service.get_export_filename(
            comparison,
            "md" if format == "markdown" else format,
        ),
    }
