"""Comparison service for diffing two imports.

This module provides functionality to compare two imported configurations
and identify differences between them.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from vizzy.database import get_db
from vizzy.models import (
    DiffType,
    ImportComparison,
    ImportInfo,
    Node,
    NodeDiff,
    ClosureComparison,
)
from vizzy.services import graph


def classify_diff(left_hash: str | None, right_hash: str | None) -> DiffType:
    """Classify the type of difference based on presence and hash values.

    Args:
        left_hash: The derivation hash from the left import (or None if absent)
        right_hash: The derivation hash from the right import (or None if absent)

    Returns:
        The appropriate DiffType for this comparison
    """
    if left_hash and right_hash:
        if left_hash == right_hash:
            return DiffType.SAME
        else:
            return DiffType.DIFFERENT_HASH
    elif left_hash:
        return DiffType.ONLY_LEFT
    else:
        return DiffType.ONLY_RIGHT


def _build_node_from_row(row: dict, prefix: str) -> Node | None:
    """Build a Node object from a row dictionary with a column prefix.

    Args:
        row: Dictionary containing the row data
        prefix: Column prefix ('left' or 'right')

    Returns:
        A Node object if the node exists, None otherwise
    """
    node_id = row.get(f"{prefix}_id")
    if not node_id:
        return None

    return Node(
        id=node_id,
        import_id=row.get(f"{prefix}_import_id") or 0,
        drv_hash=row.get(f"{prefix}_hash") or "",
        drv_name=row.get(f"{prefix}_name") or "",
        label=row.get("label") or "",
        package_type=row.get(f"{prefix}_type"),
        depth=row.get(f"{prefix}_depth"),
        closure_size=row.get(f"{prefix}_closure"),
        metadata=row.get(f"{prefix}_metadata"),
        is_top_level=row.get(f"{prefix}_is_top_level") or False,
        top_level_source=row.get(f"{prefix}_top_level_source"),
    )


def compare_imports(
    left_import_id: int,
    right_import_id: int,
) -> ImportComparison:
    """Compare two imports and return a detailed diff.

    Uses a FULL OUTER JOIN to efficiently match nodes by label across
    both imports, then classifies each match based on hash comparison.

    This approach handles:
    - Nodes that exist only in one import
    - Nodes with the same label but different derivation hashes
    - Identical nodes (same label and hash)

    Args:
        left_import_id: ID of the first (left) import
        right_import_id: ID of the second (right) import

    Returns:
        An ImportComparison object with all diffs and summary metrics

    Raises:
        ValueError: If either import does not exist
    """
    # Get import info for both sides
    left_import = graph.get_import(left_import_id)
    right_import = graph.get_import(right_import_id)

    if not left_import:
        raise ValueError(f"Left import {left_import_id} not found")
    if not right_import:
        raise ValueError(f"Right import {right_import_id} not found")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Use FULL OUTER JOIN to get all nodes from both imports matched by label
            # This handles nodes that exist in only one import as well as
            # nodes that exist in both (with same or different hashes)
            cur.execute(
                """
                SELECT
                    COALESCE(l.label, r.label) as label,
                    l.id as left_id,
                    l.import_id as left_import_id,
                    l.drv_hash as left_hash,
                    l.drv_name as left_name,
                    l.package_type as left_type,
                    l.depth as left_depth,
                    l.closure_size as left_closure,
                    l.metadata as left_metadata,
                    l.is_top_level as left_is_top_level,
                    l.top_level_source as left_top_level_source,
                    r.id as right_id,
                    r.import_id as right_import_id,
                    r.drv_hash as right_hash,
                    r.drv_name as right_name,
                    r.package_type as right_type,
                    r.depth as right_depth,
                    r.closure_size as right_closure,
                    r.metadata as right_metadata,
                    r.is_top_level as right_is_top_level,
                    r.top_level_source as right_top_level_source
                FROM nodes l
                FULL OUTER JOIN nodes r
                    ON l.label = r.label
                    AND r.import_id = %s
                WHERE (l.import_id = %s OR l.import_id IS NULL)
                  AND (r.import_id = %s OR r.import_id IS NULL)
                ORDER BY COALESCE(l.label, r.label)
                """,
                (right_import_id, left_import_id, right_import_id),
            )

            rows = cur.fetchall()

    # Process rows into NodeDiff objects
    diffs: list[NodeDiff] = []
    left_only_count = 0
    right_only_count = 0
    different_count = 0
    same_count = 0

    for row in rows:
        diff_type = classify_diff(row["left_hash"], row["right_hash"])

        # Build node objects
        left_node = _build_node_from_row(row, "left")
        right_node = _build_node_from_row(row, "right")

        # Determine package type (prefer left, fallback to right)
        package_type = row["left_type"] or row["right_type"]

        diff = NodeDiff(
            label=row["label"],
            package_type=package_type,
            left_node=left_node,
            right_node=right_node,
            diff_type=diff_type,
        )
        diffs.append(diff)

        # Count by type
        if diff_type == DiffType.ONLY_LEFT:
            left_only_count += 1
        elif diff_type == DiffType.ONLY_RIGHT:
            right_only_count += 1
        elif diff_type == DiffType.DIFFERENT_HASH:
            different_count += 1
        else:
            same_count += 1

    return ImportComparison(
        left_import=left_import,
        right_import=right_import,
        left_only_count=left_only_count,
        right_only_count=right_only_count,
        different_count=different_count,
        same_count=same_count,
        all_diffs=diffs,
    )


def compare_with_duplicates(
    left_import_id: int,
    right_import_id: int,
) -> ImportComparison:
    """Compare two imports, handling duplicate labels within each import.

    This version handles the case where the same label might appear multiple
    times within a single import (e.g., different versions of the same package).

    Strategy:
    1. Group nodes by label within each import
    2. For each label, match nodes by hash first
    3. Report unmatched nodes as additions/removals

    Args:
        left_import_id: ID of the first (left) import
        right_import_id: ID of the second (right) import

    Returns:
        An ImportComparison object with all diffs and summary metrics
    """
    # Get import info
    left_import = graph.get_import(left_import_id)
    right_import = graph.get_import(right_import_id)

    if not left_import:
        raise ValueError(f"Left import {left_import_id} not found")
    if not right_import:
        raise ValueError(f"Right import {right_import_id} not found")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all nodes from both imports, grouped by label
            # We aggregate hashes and node IDs to handle duplicates
            cur.execute(
                """
                WITH left_nodes AS (
                    SELECT
                        label,
                        array_agg(id) as ids,
                        array_agg(drv_hash) as hashes,
                        MIN(package_type) as package_type,
                        MIN(depth) as depth,
                        SUM(COALESCE(closure_size, 0)) as total_closure
                    FROM nodes
                    WHERE import_id = %s
                    GROUP BY label
                ),
                right_nodes AS (
                    SELECT
                        label,
                        array_agg(id) as ids,
                        array_agg(drv_hash) as hashes,
                        MIN(package_type) as package_type,
                        MIN(depth) as depth,
                        SUM(COALESCE(closure_size, 0)) as total_closure
                    FROM nodes
                    WHERE import_id = %s
                    GROUP BY label
                )
                SELECT
                    COALESCE(l.label, r.label) as label,
                    l.ids as left_ids,
                    l.hashes as left_hashes,
                    l.package_type as left_type,
                    l.depth as left_depth,
                    l.total_closure as left_closure,
                    r.ids as right_ids,
                    r.hashes as right_hashes,
                    r.package_type as right_type,
                    r.depth as right_depth,
                    r.total_closure as right_closure
                FROM left_nodes l
                FULL OUTER JOIN right_nodes r ON l.label = r.label
                ORDER BY COALESCE(l.label, r.label)
                """,
                (left_import_id, right_import_id),
            )

            rows = cur.fetchall()

    # Process into diffs
    diffs: list[NodeDiff] = []
    left_only_count = 0
    right_only_count = 0
    different_count = 0
    same_count = 0

    for row in rows:
        left_hashes = set(row["left_hashes"] or [])
        right_hashes = set(row["right_hashes"] or [])

        if not left_hashes and not right_hashes:
            continue  # Shouldn't happen, but skip if it does

        # Determine the diff type based on hash overlap
        common_hashes = left_hashes & right_hashes
        left_only_hashes = left_hashes - right_hashes
        right_only_hashes = right_hashes - left_hashes

        if not left_hashes:
            diff_type = DiffType.ONLY_RIGHT
            right_only_count += 1
        elif not right_hashes:
            diff_type = DiffType.ONLY_LEFT
            left_only_count += 1
        elif common_hashes and not left_only_hashes and not right_only_hashes:
            diff_type = DiffType.SAME
            same_count += 1
        else:
            diff_type = DiffType.DIFFERENT_HASH
            different_count += 1

        # Build minimal node representations
        # For duplicates, we use the first ID and aggregate closure
        left_node = None
        if row["left_ids"]:
            left_node = Node(
                id=row["left_ids"][0],
                import_id=left_import_id,
                drv_hash=row["left_hashes"][0] if row["left_hashes"] else "",
                drv_name="",
                label=row["label"],
                package_type=row["left_type"],
                depth=row["left_depth"],
                closure_size=row["left_closure"],
                metadata=None,
                is_top_level=False,
                top_level_source=None,
            )

        right_node = None
        if row["right_ids"]:
            right_node = Node(
                id=row["right_ids"][0],
                import_id=right_import_id,
                drv_hash=row["right_hashes"][0] if row["right_hashes"] else "",
                drv_name="",
                label=row["label"],
                package_type=row["right_type"],
                depth=row["right_depth"],
                closure_size=row["right_closure"],
                metadata=None,
                is_top_level=False,
                top_level_source=None,
            )

        package_type = row["left_type"] or row["right_type"]

        diffs.append(
            NodeDiff(
                label=row["label"],
                package_type=package_type,
                left_node=left_node,
                right_node=right_node,
                diff_type=diff_type,
            )
        )

    return ImportComparison(
        left_import=left_import,
        right_import=right_import,
        left_only_count=left_only_count,
        right_only_count=right_only_count,
        different_count=different_count,
        same_count=same_count,
        all_diffs=diffs,
    )


def get_closure_comparison(
    left_import_id: int,
    right_import_id: int,
    limit: int = 10,
) -> ClosureComparison:
    """Compare closure sizes between two imports.

    Identifies the largest additions and removals in terms of closure size.

    Args:
        left_import_id: ID of the first (left) import
        right_import_id: ID of the second (right) import
        limit: Maximum number of additions/removals to return

    Returns:
        A ClosureComparison with totals and largest changes
    """
    comparison = compare_imports(left_import_id, right_import_id)

    # Calculate totals
    left_total = sum(
        (d.left_node.closure_size or 0)
        for d in comparison.all_diffs
        if d.left_node and d.diff_type in (DiffType.ONLY_LEFT, DiffType.SAME, DiffType.DIFFERENT_HASH)
    )
    right_total = sum(
        (d.right_node.closure_size or 0)
        for d in comparison.all_diffs
        if d.right_node and d.diff_type in (DiffType.ONLY_RIGHT, DiffType.SAME, DiffType.DIFFERENT_HASH)
    )

    # Get largest additions (only in right, sorted by closure size)
    additions = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_RIGHT]
    additions.sort(key=lambda d: (d.right_node.closure_size or 0) if d.right_node else 0, reverse=True)

    # Get largest removals (only in left, sorted by closure size)
    removals = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_LEFT]
    removals.sort(key=lambda d: (d.left_node.closure_size or 0) if d.left_node else 0, reverse=True)

    return ClosureComparison(
        left_total=left_total,
        right_total=right_total,
        largest_additions=additions[:limit],
        largest_removals=removals[:limit],
    )


def get_cached_comparison(left_id: int, right_id: int) -> ImportComparison | None:
    """Get a cached comparison if one exists and is still valid.

    The cache key is normalized so that compare(A, B) and compare(B, A)
    share the same cache entry (though the result would need to be inverted).

    Args:
        left_id: ID of the left import
        right_id: ID of the right import

    Returns:
        The cached ImportComparison if found, None otherwise
    """
    # Normalize cache key (smaller ID first)
    cache_key = f"{min(left_id, right_id)}:{max(left_id, right_id)}"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT result
                FROM analysis
                WHERE analysis_type = 'comparison'
                  AND result->>'cache_key' = %s
                """,
                (cache_key,),
            )
            row = cur.fetchone()
            if row:
                try:
                    return ImportComparison(**row["result"]["comparison"])
                except (KeyError, TypeError):
                    return None
    return None


def cache_comparison(comparison: ImportComparison) -> None:
    """Cache a comparison result for future use.

    Args:
        comparison: The comparison result to cache
    """
    # Normalize cache key
    left_id = comparison.left_import.id
    right_id = comparison.right_import.id
    cache_key = f"{min(left_id, right_id)}:{max(left_id, right_id)}"

    with get_db() as conn:
        with conn.cursor() as cur:
            # Delete any existing cache for this pair
            cur.execute(
                """
                DELETE FROM analysis
                WHERE analysis_type = 'comparison'
                  AND result->>'cache_key' = %s
                """,
                (cache_key,),
            )

            # Insert new cache entry
            cur.execute(
                """
                INSERT INTO analysis (import_id, analysis_type, result)
                VALUES (%s, 'comparison', %s)
                """,
                (
                    left_id,
                    {
                        "cache_key": cache_key,
                        "comparison": comparison.model_dump(mode="json"),
                    },
                ),
            )


def match_nodes(
    left_nodes: list[Node],
    right_nodes: list[Node],
) -> list[NodeDiff]:
    """Match nodes between two lists and return diffs.

    This is a utility function for matching pre-fetched node lists.
    Useful for testing or when nodes are already loaded.

    Algorithm:
    1. Build hash -> node maps for both sides
    2. Build label -> nodes maps for both sides
    3. For each left node:
       - If hash in right -> SAME
       - Elif label in right with different hash -> DIFFERENT_HASH
       - Else -> ONLY_LEFT
    4. Remaining right nodes -> ONLY_RIGHT

    Args:
        left_nodes: Nodes from the left import
        right_nodes: Nodes from the right import

    Returns:
        List of NodeDiff objects describing all differences
    """
    # Build lookup maps
    left_by_hash: dict[str, Node] = {n.drv_hash: n for n in left_nodes}
    right_by_hash: dict[str, Node] = {n.drv_hash: n for n in right_nodes}
    left_by_label: dict[str, list[Node]] = {}
    right_by_label: dict[str, list[Node]] = {}

    for node in left_nodes:
        if node.label not in left_by_label:
            left_by_label[node.label] = []
        left_by_label[node.label].append(node)

    for node in right_nodes:
        if node.label not in right_by_label:
            right_by_label[node.label] = []
        right_by_label[node.label].append(node)

    diffs: list[NodeDiff] = []
    matched_right_hashes: set[str] = set()

    # Process left nodes
    for left_node in left_nodes:
        if left_node.drv_hash in right_by_hash:
            # Same hash exists in right - SAME
            right_node = right_by_hash[left_node.drv_hash]
            matched_right_hashes.add(left_node.drv_hash)
            diffs.append(NodeDiff(
                label=left_node.label,
                package_type=left_node.package_type,
                left_node=left_node,
                right_node=right_node,
                diff_type=DiffType.SAME,
            ))
        elif left_node.label in right_by_label:
            # Same label but different hash - DIFFERENT_HASH
            right_candidates = right_by_label[left_node.label]
            # Pick first unmatched right node with same label
            right_node = None
            for candidate in right_candidates:
                if candidate.drv_hash not in matched_right_hashes:
                    right_node = candidate
                    matched_right_hashes.add(candidate.drv_hash)
                    break
            if right_node:
                diffs.append(NodeDiff(
                    label=left_node.label,
                    package_type=left_node.package_type or right_node.package_type,
                    left_node=left_node,
                    right_node=right_node,
                    diff_type=DiffType.DIFFERENT_HASH,
                ))
            else:
                # All right nodes with this label already matched
                diffs.append(NodeDiff(
                    label=left_node.label,
                    package_type=left_node.package_type,
                    left_node=left_node,
                    right_node=None,
                    diff_type=DiffType.ONLY_LEFT,
                ))
        else:
            # Not in right at all - ONLY_LEFT
            diffs.append(NodeDiff(
                label=left_node.label,
                package_type=left_node.package_type,
                left_node=left_node,
                right_node=None,
                diff_type=DiffType.ONLY_LEFT,
            ))

    # Process remaining right nodes (not matched)
    for right_node in right_nodes:
        if right_node.drv_hash not in matched_right_hashes:
            diffs.append(NodeDiff(
                label=right_node.label,
                package_type=right_node.package_type,
                left_node=None,
                right_node=right_node,
                diff_type=DiffType.ONLY_RIGHT,
            ))

    return diffs


class DiffCategory(str, Enum):
    """High-level diff categories for UI display."""

    DESKTOP_ENV = "Desktop Environment"
    SYSTEM_SERVICES = "System Services"
    DEVELOPMENT = "Development Tools"
    NETWORKING = "Networking"
    MULTIMEDIA = "Multimedia"
    LIBRARIES = "Core Libraries"
    SECURITY = "Security"
    FONTS = "Fonts"
    DOCUMENTATION = "Documentation"
    PYTHON = "Python Packages"
    OTHER = "Other"


# Pattern matching for categorizing packages
CATEGORY_PATTERNS: dict[DiffCategory, list[str]] = {
    DiffCategory.DESKTOP_ENV: [
        r"^gnome-",
        r"^kde-",
        r"^plasma-",
        r"^gtk[234]",
        r"^wayland",
        r"^xorg-",
        r"^mutter",
        r"^kwin",
        r"^qt[56]-",
        r"^sddm",
        r"^gdm",
        r"^lightdm",
    ],
    DiffCategory.SYSTEM_SERVICES: [
        r"^systemd-",
        r"-service$",
        r"^dbus",
        r"^polkit",
        r"^udev",
        r"^acpid",
        r"^cron",
        r"^logrotate",
    ],
    DiffCategory.DEVELOPMENT: [
        r"^gcc-",
        r"^clang-",
        r"^rustc",
        r"^cargo",
        r"^nodejs",
        r"^go-",
        r"^cmake",
        r"^make-",
        r"^autoconf",
        r"^automake",
        r"^pkg-config",
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
        r"^nss",
        r"^iptables",
        r"^nftables",
        r"^wireguard",
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
        r"^bzip2",
        r"^xz",
        r"^lz4",
        r"^zstd",
    ],
    DiffCategory.SECURITY: [
        r"^gnupg",
        r"^gpg",
        r"^libgcrypt",
        r"^pam",
        r"^sudo",
        r"^shadow",
        r"^audit",
    ],
    DiffCategory.FONTS: [
        r"^font-",
        r"-font$",
        r"^noto-",
        r"^liberation-",
        r"^dejavu-",
        r"^roboto",
        r"^freefont",
    ],
    DiffCategory.DOCUMENTATION: [
        r"^man-",
        r"-man$",
        r"-doc$",
        r"^texinfo",
        r"^groff",
    ],
    DiffCategory.PYTHON: [
        r"^python\d",
        r"^python3\.\d+-",
    ],
}


def categorize_diff(label: str, package_type: str | None) -> DiffCategory:
    """Categorize a single diff based on its label and package type.

    Args:
        label: The package label
        package_type: The package type classification (if available)

    Returns:
        The appropriate DiffCategory for this package
    """
    # Check pattern-based categorization first
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, label, re.IGNORECASE):
                return category

    # Fall back to package type if available
    if package_type:
        type_mapping = {
            "font": DiffCategory.FONTS,
            "documentation": DiffCategory.DOCUMENTATION,
            "python-package": DiffCategory.PYTHON,
            "development": DiffCategory.DEVELOPMENT,
            "service": DiffCategory.SYSTEM_SERVICES,
            "library": DiffCategory.LIBRARIES,
        }
        if package_type in type_mapping:
            return type_mapping[package_type]

    return DiffCategory.OTHER


def categorize_diffs(diffs: list[NodeDiff]) -> dict[DiffCategory, list[NodeDiff]]:
    """Group diffs by semantic category.

    Args:
        diffs: List of NodeDiff objects to categorize

    Returns:
        Dictionary mapping categories to lists of diffs in that category
    """
    categorized: dict[DiffCategory, list[NodeDiff]] = {cat: [] for cat in DiffCategory}

    for diff in diffs:
        category = categorize_diff(diff.label, diff.package_type)
        categorized[category].append(diff)

    # Remove empty categories and sort by count
    result = {k: v for k, v in categorized.items() if v}
    return dict(sorted(result.items(), key=lambda x: len(x[1]), reverse=True))


def score_diff_importance(diff: NodeDiff) -> float:
    """Score how important a diff is to the user.

    High importance:
    - Top-level packages
    - Large closure impact
    - User-facing applications

    Low importance:
    - Libraries
    - Build-time only
    - Small closure

    Args:
        diff: The NodeDiff to score

    Returns:
        A float score (higher = more important)
    """
    score = 0.0

    # Package type scoring
    if diff.package_type == "application":
        score += 5
    elif diff.package_type == "service":
        score += 4
    elif diff.package_type == "font":
        score += 2
    elif diff.package_type == "library":
        score -= 2
    elif diff.package_type == "documentation":
        score -= 1

    # Closure impact scoring
    left_closure = diff.left_node.closure_size if diff.left_node else 0
    right_closure = diff.right_node.closure_size if diff.right_node else 0
    closure_impact = abs((left_closure or 0) - (right_closure or 0))
    score += min(closure_impact / 100, 5)  # Cap contribution at 5

    return score


def sort_diffs_by_importance(diffs: list[NodeDiff]) -> list[NodeDiff]:
    """Sort diffs with most important first.

    Args:
        diffs: List of diffs to sort

    Returns:
        Sorted list of diffs (most important first)
    """
    return sorted(diffs, key=score_diff_importance, reverse=True)


def generate_diff_summary(comparison: ImportComparison) -> str:
    """Generate a human-readable summary of the comparison.

    Creates a concise description of the key differences between
    two imports suitable for display in the UI.

    Args:
        comparison: The ImportComparison to summarize

    Returns:
        A string describing the key differences
    """
    left_name = comparison.left_import.name
    right_name = comparison.right_import.name
    left_count = comparison.left_import.node_count or 0
    right_count = comparison.right_import.node_count or 0

    diff = right_count - left_count
    direction = "more" if diff > 0 else "fewer"

    parts = []

    if diff != 0:
        parts.append(f"{right_name} has {abs(diff):,} {direction} packages than {left_name}.")
    else:
        parts.append(f"{right_name} and {left_name} have the same number of packages.")

    if comparison.different_count > 0:
        parts.append(f"{comparison.different_count:,} packages have different versions.")

    if comparison.left_only_count > 0:
        parts.append(f"{comparison.left_only_count:,} packages only in {left_name}.")

    if comparison.right_only_count > 0:
        parts.append(f"{comparison.right_only_count:,} packages only in {right_name}.")

    return " ".join(parts)


@dataclass
class CategorySummary:
    """Summary of diffs within a semantic category."""
    category: DiffCategory
    display_name: str
    diffs: list[NodeDiff]
    left_only_count: int
    right_only_count: int
    different_count: int
    same_count: int
    net_change: int  # positive means right has more
    total_closure_impact: int  # total closure size change


def get_category_summaries(
    comparison: ImportComparison,
    diff_type_filter: DiffType | None = None,
) -> list[CategorySummary]:
    """Get summaries of all categories with their diffs.

    This function provides a complete overview of differences grouped
    by semantic category, with counts and net changes for each.

    Args:
        comparison: The ImportComparison to summarize
        diff_type_filter: Optional filter to only include specific diff types

    Returns:
        List of CategorySummary objects, sorted by impact (largest changes first)
    """
    # Filter diffs if needed
    diffs = comparison.all_diffs
    if diff_type_filter:
        diffs = [d for d in diffs if d.diff_type == diff_type_filter]

    # Categorize all diffs
    categorized = categorize_diffs(diffs)

    summaries = []
    for category, category_diffs in categorized.items():
        left_only = sum(1 for d in category_diffs if d.diff_type == DiffType.ONLY_LEFT)
        right_only = sum(1 for d in category_diffs if d.diff_type == DiffType.ONLY_RIGHT)
        different = sum(1 for d in category_diffs if d.diff_type == DiffType.DIFFERENT_HASH)
        same = sum(1 for d in category_diffs if d.diff_type == DiffType.SAME)

        # Calculate closure impact (sum of all closure_impact values)
        closure_impact = sum(d.closure_impact for d in category_diffs)

        summaries.append(CategorySummary(
            category=category,
            display_name=category.value,
            diffs=category_diffs,
            left_only_count=left_only,
            right_only_count=right_only,
            different_count=different,
            same_count=same,
            net_change=right_only - left_only,
            total_closure_impact=closure_impact,
        ))

    # Sort by absolute net change (biggest changes first)
    summaries.sort(key=lambda s: abs(s.net_change), reverse=True)

    return summaries


def get_top_changes(
    comparison: ImportComparison,
    limit: int = 10,
) -> list[NodeDiff]:
    """Get the most important changes from a comparison.

    Args:
        comparison: The comparison to analyze
        limit: Maximum number of changes to return

    Returns:
        List of most important NodeDiffs
    """
    # Only look at actual changes (not SAME)
    changes = [d for d in comparison.all_diffs if d.diff_type != DiffType.SAME]
    sorted_changes = sort_diffs_by_importance(changes)
    return sorted_changes[:limit]


def generate_category_summary_text(summaries: list[CategorySummary]) -> str:
    """Generate a human-readable summary of category changes.

    Args:
        summaries: List of category summaries

    Returns:
        A string describing the main changes by category
    """
    parts = []

    # Find categories with significant additions/removals
    additions = [(s.display_name, s.right_only_count) for s in summaries if s.right_only_count > 0]
    removals = [(s.display_name, s.left_only_count) for s in summaries if s.left_only_count > 0]

    additions.sort(key=lambda x: x[1], reverse=True)
    removals.sort(key=lambda x: x[1], reverse=True)

    if additions:
        top_additions = additions[:3]
        additions_str = ", ".join(f"{name} (+{count})" for name, count in top_additions)
        parts.append(f"Main additions: {additions_str}.")

    if removals:
        top_removals = removals[:3]
        removals_str = ", ".join(f"{name} (-{count})" for name, count in top_removals)
        parts.append(f"Main removals: {removals_str}.")

    return " ".join(parts) if parts else "No significant category changes."


def generate_enhanced_diff_summary(comparison: ImportComparison) -> str:
    """Generate an enhanced summary including category breakdown.

    Args:
        comparison: The ImportComparison to summarize

    Returns:
        A string describing key differences with category context
    """
    base_summary = generate_diff_summary(comparison)

    # Add category summary
    summaries = get_category_summaries(comparison)
    category_text = generate_category_summary_text(summaries)

    if category_text and category_text != "No significant category changes.":
        return f"{base_summary} {category_text}"

    return base_summary


# =============================================================================
# Version Difference Detection (Phase 8F)
# =============================================================================

# Import additional models for version detection
from typing import Tuple
from vizzy.models import (
    VersionChangeType,
    VersionDiff,
    VersionComparisonResult,
)


def extract_version(label: str) -> Tuple[str, str | None]:
    """Extract package name and version from a derivation label.

    Parses NixOS-style derivation labels to separate the package name
    from its version string. Handles various version formats commonly
    found in Nix derivations.

    Args:
        label: The full derivation label (e.g., "openssl-3.0.12", "glibc-2.40-66")

    Returns:
        A tuple of (package_name, version) where version may be None if
        no version pattern is found.

    Examples:
        >>> extract_version("openssl-3.0.12")
        ("openssl", "3.0.12")
        >>> extract_version("glibc-2.40-66")
        ("glibc", "2.40-66")
        >>> extract_version("python3-3.11.7")
        ("python3", "3.11.7")
        >>> extract_version("bootstrap-tools")
        ("bootstrap-tools", None)
        >>> extract_version("gcc-wrapper-13.2.0")
        ("gcc-wrapper", "13.2.0")
        >>> extract_version("nix-2.18.1")
        ("nix", "2.18.1")
        >>> extract_version("linux-6.6.8")
        ("linux", "6.6.8")
        >>> extract_version("firefox-120.0.1")
        ("firefox", "120.0.1")
        >>> extract_version("perl5.38.2-URI-5.21")
        ("perl5.38.2-URI", "5.21")
    """
    # Pattern to match version at the end of the label
    # Versions typically start with a digit and can contain digits, dots, and hyphens
    # We need to find the last occurrence of -<version> pattern

    # Try multiple patterns in order of specificity
    patterns = [
        # Standard version: name-1.2.3 or name-1.2.3-4
        r'^(.+?)-(\d+(?:\.\d+)*(?:-\d+)?)$',
        # Version with release suffix: name-1.2.3rc1 or name-1.2.3_beta
        r'^(.+?)-(\d+(?:\.\d+)*(?:[-_]?(?:alpha|beta|rc|pre|post|dev|git|svn|hg|p)\d*)?)$',
        # Date-based version: name-20231215 or name-2023-12-15
        r'^(.+?)-(\d{8}|\d{4}-\d{2}-\d{2})$',
        # Git/commit hash version: name-unstable-2023-12-15
        r'^(.+?)-(unstable-\d{4}-\d{2}-\d{2})$',
        # Short numeric version: name-1 or name-13
        r'^(.+?)-(\d+)$',
    ]

    for pattern in patterns:
        match = re.match(pattern, label, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)

    # No version pattern found
    return label, None


def parse_version_components(version: str) -> list[int | str]:
    """Parse a version string into comparable components.

    Splits version strings into numeric and non-numeric parts for
    comparison. Numeric parts are converted to integers for proper
    numerical comparison.

    Args:
        version: A version string (e.g., "3.0.12", "2.40-66", "1.0rc1")

    Returns:
        A list of integers and strings representing version components.

    Examples:
        >>> parse_version_components("3.0.12")
        [3, 0, 12]
        >>> parse_version_components("2.40-66")
        [2, 40, 66]
        >>> parse_version_components("1.0rc1")
        [1, 0, 'rc', 1]
    """
    # Split on dots and hyphens, but keep alpha parts separate
    components: list[int | str] = []

    # Split on common separators
    parts = re.split(r'[.\-_]', version)

    for part in parts:
        if not part:
            continue
        # Further split on numeric/alpha boundaries
        subparts = re.findall(r'\d+|[a-zA-Z]+', part)
        for subpart in subparts:
            if subpart.isdigit():
                components.append(int(subpart))
            else:
                components.append(subpart.lower())

    return components


def compare_versions(left_version: str | None, right_version: str | None) -> int:
    """Compare two version strings.

    Performs a semantic comparison of version strings, handling
    numeric and alphabetic components appropriately.

    Args:
        left_version: The first version string (or None)
        right_version: The second version string (or None)

    Returns:
        -1 if left < right (upgrade from left to right)
         0 if left == right (same version)
         1 if left > right (downgrade from left to right)

    Examples:
        >>> compare_versions("3.0.12", "3.1.0")
        -1  # 3.0.12 < 3.1.0 (upgrade)
        >>> compare_versions("2.0", "1.9")
        1   # 2.0 > 1.9 (downgrade)
        >>> compare_versions("1.0", "1.0")
        0   # same version
    """
    if left_version is None or right_version is None:
        return 0  # Cannot compare if either is missing

    if left_version == right_version:
        return 0

    left_parts = parse_version_components(left_version)
    right_parts = parse_version_components(right_version)

    # Compare component by component
    max_len = max(len(left_parts), len(right_parts))

    for i in range(max_len):
        # Get components, defaulting to 0 for numeric or empty string for alpha
        if i >= len(left_parts):
            left_comp: int | str = 0 if (i < len(right_parts) and isinstance(right_parts[i], int)) else ""
        else:
            left_comp = left_parts[i]

        if i >= len(right_parts):
            right_comp: int | str = 0 if isinstance(left_comp, int) else ""
        else:
            right_comp = right_parts[i]

        # Compare based on type
        if isinstance(left_comp, int) and isinstance(right_comp, int):
            if left_comp < right_comp:
                return -1
            elif left_comp > right_comp:
                return 1
        elif isinstance(left_comp, str) and isinstance(right_comp, str):
            # Alpha comparison - special handling for pre-release tags
            prerelease_order = {'alpha': 0, 'beta': 1, 'rc': 2, 'pre': 0, 'dev': -1, 'post': 3, '': 4}
            left_order = prerelease_order.get(left_comp, 5)
            right_order = prerelease_order.get(right_comp, 5)

            if left_order != right_order:
                if left_order < right_order:
                    return -1
                else:
                    return 1
            elif left_comp < right_comp:
                return -1
            elif left_comp > right_comp:
                return 1
        else:
            # Mixed types - numeric is considered greater than string (release > prerelease)
            if isinstance(left_comp, int):
                return 1
            else:
                return -1

    return 0


def classify_version_change(
    left_version: str | None,
    right_version: str | None,
    left_hash: str,
    right_hash: str,
) -> VersionChangeType:
    """Classify the type of version change between two packages.

    Determines whether a package change represents an upgrade, downgrade,
    rebuild, or unknown change based on version comparison.

    Args:
        left_version: Version in the left import (or None)
        right_version: Version in the right import (or None)
        left_hash: Derivation hash in the left import
        right_hash: Derivation hash in the right import

    Returns:
        The type of version change detected.
    """
    # If hashes are the same, there's no change (shouldn't happen but handle it)
    if left_hash == right_hash:
        return VersionChangeType.REBUILD  # Same hash means rebuild/identical

    # If both versions are the same (or both None), it's a rebuild
    if left_version == right_version:
        return VersionChangeType.REBUILD

    # If one or both versions are None, we can't determine direction
    if left_version is None or right_version is None:
        return VersionChangeType.UNKNOWN

    # Compare versions
    comparison = compare_versions(left_version, right_version)

    if comparison < 0:
        return VersionChangeType.UPGRADE  # left < right, so upgrading
    elif comparison > 0:
        return VersionChangeType.DOWNGRADE  # left > right, so downgrading
    else:
        return VersionChangeType.REBUILD  # Versions equal but hashes differ


def detect_version_changes(
    left_import_id: int,
    right_import_id: int,
) -> VersionComparisonResult:
    """Detect version changes between two imports.

    Analyzes packages that exist in both imports but with different
    derivation hashes, and categorizes the changes as upgrades,
    downgrades, rebuilds, or unknown.

    This function uses the existing comparison infrastructure and
    adds version extraction and classification on top.

    Args:
        left_import_id: ID of the first (left/baseline) import
        right_import_id: ID of the second (right/target) import

    Returns:
        A VersionComparisonResult containing categorized version differences.
    """
    # Get the base comparison
    comparison = compare_imports(left_import_id, right_import_id)

    # Filter to only nodes that exist in both but have different hashes
    different_diffs = [
        d for d in comparison.all_diffs
        if d.diff_type == DiffType.DIFFERENT_HASH
        and d.left_node is not None
        and d.right_node is not None
    ]

    # Categorize each difference
    upgrades: list[VersionDiff] = []
    downgrades: list[VersionDiff] = []
    rebuilds: list[VersionDiff] = []
    unknown_changes: list[VersionDiff] = []

    for diff in different_diffs:
        left_node = diff.left_node
        right_node = diff.right_node

        # These should never be None due to the filter above, but check anyway
        if left_node is None or right_node is None:
            continue

        # Extract versions from labels
        left_name, left_version = extract_version(left_node.label)
        right_name, right_version = extract_version(right_node.label)

        # Classify the change
        change_type = classify_version_change(
            left_version,
            right_version,
            left_node.drv_hash,
            right_node.drv_hash,
        )

        # Create the version diff
        version_diff = VersionDiff(
            package_name=left_name,  # Use left name as the base package name
            left_version=left_version,
            right_version=right_version,
            left_label=left_node.label,
            right_label=right_node.label,
            left_node_id=left_node.id,
            right_node_id=right_node.id,
            change_type=change_type,
            package_type=diff.package_type,
        )

        # Add to appropriate category
        if change_type == VersionChangeType.UPGRADE:
            upgrades.append(version_diff)
        elif change_type == VersionChangeType.DOWNGRADE:
            downgrades.append(version_diff)
        elif change_type == VersionChangeType.REBUILD:
            rebuilds.append(version_diff)
        else:
            unknown_changes.append(version_diff)

    # Sort each category by package name for consistent output
    upgrades.sort(key=lambda v: v.package_name.lower())
    downgrades.sort(key=lambda v: v.package_name.lower())
    rebuilds.sort(key=lambda v: v.package_name.lower())
    unknown_changes.sort(key=lambda v: v.package_name.lower())

    return VersionComparisonResult(
        left_import_id=left_import_id,
        right_import_id=right_import_id,
        upgrades=upgrades,
        downgrades=downgrades,
        rebuilds=rebuilds,
        unknown_changes=unknown_changes,
    )


def generate_version_summary(result: VersionComparisonResult) -> str:
    """Generate a human-readable summary of version changes.

    Creates a concise description of the version changes suitable
    for display in the UI.

    Args:
        result: The VersionComparisonResult to summarize

    Returns:
        A string describing the version changes
    """
    parts = []

    if result.upgrade_count > 0:
        parts.append(f"{result.upgrade_count} upgrade{'s' if result.upgrade_count != 1 else ''}")

    if result.downgrade_count > 0:
        parts.append(f"{result.downgrade_count} downgrade{'s' if result.downgrade_count != 1 else ''}")

    if result.rebuild_count > 0:
        parts.append(f"{result.rebuild_count} rebuild{'s' if result.rebuild_count != 1 else ''}")

    if len(result.unknown_changes) > 0:
        parts.append(f"{len(result.unknown_changes)} other change{'s' if len(result.unknown_changes) != 1 else ''}")

    if not parts:
        return "No version changes detected."

    return f"Found {result.total_changes} version changes: " + ", ".join(parts) + "."


# =============================================================================
# Comparison Report Export (Phase 8F-003)
# =============================================================================


def comparison_to_markdown(comparison: ImportComparison) -> str:
    """Generate a Markdown report from a comparison.

    Creates a detailed, human-readable Markdown document describing
    all differences between two imports, grouped by category and type.

    Args:
        comparison: The ImportComparison to export

    Returns:
        A Markdown-formatted string with the complete comparison report
    """
    lines = []

    # Header
    lines.append("# Configuration Comparison Report")
    lines.append("")
    lines.append(f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Configuration | Packages |")
    lines.append("|--------------|----------|")
    lines.append(f"| **{comparison.left_import.name}** | {comparison.left_import.node_count or 0:,} |")
    lines.append(f"| **{comparison.right_import.name}** | {comparison.right_import.node_count or 0:,} |")
    lines.append("")

    # Statistics
    lines.append("### Comparison Statistics")
    lines.append("")
    lines.append(f"- **Packages only in {comparison.left_import.name}:** {comparison.left_only_count:,}")
    lines.append(f"- **Packages only in {comparison.right_import.name}:** {comparison.right_only_count:,}")
    lines.append(f"- **Packages with different versions:** {comparison.different_count:,}")
    lines.append(f"- **Identical packages:** {comparison.same_count:,}")
    lines.append("")

    # Net change
    net_change = comparison.right_only_count - comparison.left_only_count
    if net_change > 0:
        lines.append(f"**Net change:** +{net_change:,} packages in {comparison.right_import.name}")
    elif net_change < 0:
        lines.append(f"**Net change:** {net_change:,} packages ({comparison.left_import.name} has more)")
    else:
        lines.append("**Net change:** Same package count")
    lines.append("")

    # Only in left section
    left_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_LEFT]
    if left_diffs:
        lines.append(f"## Packages Only in {comparison.left_import.name}")
        lines.append("")
        lines.append(f"*{len(left_diffs):,} packages*")
        lines.append("")

        # Group by category
        categorized = categorize_diffs(left_diffs)
        for category, diffs in categorized.items():
            lines.append(f"### {category.value} ({len(diffs)})")
            lines.append("")
            for diff in sorted(diffs, key=lambda d: d.label):
                closure_info = ""
                if diff.left_node and diff.left_node.closure_size:
                    closure_info = f" (closure: {diff.left_node.closure_size:,})"
                lines.append(f"- `{diff.label}`{closure_info}")
            lines.append("")

    # Only in right section
    right_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_RIGHT]
    if right_diffs:
        lines.append(f"## Packages Only in {comparison.right_import.name}")
        lines.append("")
        lines.append(f"*{len(right_diffs):,} packages*")
        lines.append("")

        # Group by category
        categorized = categorize_diffs(right_diffs)
        for category, diffs in categorized.items():
            lines.append(f"### {category.value} ({len(diffs)})")
            lines.append("")
            for diff in sorted(diffs, key=lambda d: d.label):
                closure_info = ""
                if diff.right_node and diff.right_node.closure_size:
                    closure_info = f" (closure: {diff.right_node.closure_size:,})"
                lines.append(f"- `{diff.label}`{closure_info}")
            lines.append("")

    # Version differences section
    different_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.DIFFERENT_HASH]
    if different_diffs:
        lines.append("## Version Differences")
        lines.append("")
        lines.append(f"*{len(different_diffs):,} packages with different derivations*")
        lines.append("")
        lines.append("| Package | Left Version | Right Version |")
        lines.append("|---------|-------------|---------------|")

        for diff in sorted(different_diffs, key=lambda d: d.label):
            left_label = diff.left_node.label if diff.left_node else "-"
            right_label = diff.right_node.label if diff.right_node else "-"
            # Extract versions if different from package label
            _, left_ver = extract_version(left_label)
            _, right_ver = extract_version(right_label)
            left_ver = left_ver or "-"
            right_ver = right_ver or "-"
            lines.append(f"| `{diff.label}` | {left_ver} | {right_ver} |")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by Vizzy - NixOS Derivation Graph Visualizer*")

    return "\n".join(lines)


def comparison_to_json(comparison: ImportComparison) -> dict:
    """Export comparison data as a structured JSON dictionary.

    Creates a complete JSON representation of the comparison suitable
    for programmatic consumption and further analysis.

    Args:
        comparison: The ImportComparison to export

    Returns:
        A dictionary containing all comparison data in JSON-serializable format
    """
    import json
    from datetime import datetime

    # Build structured output
    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "report_version": "1.0",
            "generator": "vizzy",
        },
        "summary": {
            "left_import": {
                "id": comparison.left_import.id,
                "name": comparison.left_import.name,
                "config_path": comparison.left_import.config_path,
                "node_count": comparison.left_import.node_count or 0,
                "imported_at": comparison.left_import.imported_at.isoformat(),
            },
            "right_import": {
                "id": comparison.right_import.id,
                "name": comparison.right_import.name,
                "config_path": comparison.right_import.config_path,
                "node_count": comparison.right_import.node_count or 0,
                "imported_at": comparison.right_import.imported_at.isoformat(),
            },
            "statistics": {
                "left_only_count": comparison.left_only_count,
                "right_only_count": comparison.right_only_count,
                "different_count": comparison.different_count,
                "same_count": comparison.same_count,
                "net_change": comparison.right_only_count - comparison.left_only_count,
            },
        },
        "diffs": {
            "only_left": [],
            "only_right": [],
            "different": [],
        },
        "by_category": {},
    }

    # Process diffs
    for diff in comparison.all_diffs:
        diff_entry = {
            "label": diff.label,
            "package_type": diff.package_type,
            "category": categorize_diff(diff.label, diff.package_type).value,
        }

        if diff.diff_type == DiffType.ONLY_LEFT:
            if diff.left_node:
                diff_entry["node"] = {
                    "id": diff.left_node.id,
                    "drv_hash": diff.left_node.drv_hash,
                    "closure_size": diff.left_node.closure_size,
                    "depth": diff.left_node.depth,
                    "is_top_level": diff.left_node.is_top_level,
                }
            output["diffs"]["only_left"].append(diff_entry)

        elif diff.diff_type == DiffType.ONLY_RIGHT:
            if diff.right_node:
                diff_entry["node"] = {
                    "id": diff.right_node.id,
                    "drv_hash": diff.right_node.drv_hash,
                    "closure_size": diff.right_node.closure_size,
                    "depth": diff.right_node.depth,
                    "is_top_level": diff.right_node.is_top_level,
                }
            output["diffs"]["only_right"].append(diff_entry)

        elif diff.diff_type == DiffType.DIFFERENT_HASH:
            _, left_ver = extract_version(diff.left_node.label if diff.left_node else "")
            _, right_ver = extract_version(diff.right_node.label if diff.right_node else "")

            diff_entry["left_version"] = left_ver
            diff_entry["right_version"] = right_ver
            diff_entry["closure_impact"] = diff.closure_impact

            if diff.left_node:
                diff_entry["left_node"] = {
                    "id": diff.left_node.id,
                    "drv_hash": diff.left_node.drv_hash,
                    "closure_size": diff.left_node.closure_size,
                }
            if diff.right_node:
                diff_entry["right_node"] = {
                    "id": diff.right_node.id,
                    "drv_hash": diff.right_node.drv_hash,
                    "closure_size": diff.right_node.closure_size,
                }
            output["diffs"]["different"].append(diff_entry)

    # Build category grouping
    all_diffs = comparison.all_diffs
    categorized = categorize_diffs([d for d in all_diffs if d.diff_type != DiffType.SAME])
    for category, cat_diffs in categorized.items():
        output["by_category"][category.value] = {
            "total": len(cat_diffs),
            "only_left": sum(1 for d in cat_diffs if d.diff_type == DiffType.ONLY_LEFT),
            "only_right": sum(1 for d in cat_diffs if d.diff_type == DiffType.ONLY_RIGHT),
            "different": sum(1 for d in cat_diffs if d.diff_type == DiffType.DIFFERENT_HASH),
        }

    return output


def comparison_to_csv(comparison: ImportComparison) -> str:
    """Export comparison data as CSV format.

    Creates a flat CSV representation suitable for spreadsheet analysis.
    Each row represents one package with its diff status.

    Args:
        comparison: The ImportComparison to export

    Returns:
        A CSV-formatted string with headers and all diff data
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "package_label",
        "diff_type",
        "category",
        "package_type",
        "left_version",
        "right_version",
        "left_drv_hash",
        "right_drv_hash",
        "left_closure_size",
        "right_closure_size",
        "closure_impact",
        "left_is_top_level",
        "right_is_top_level",
    ])

    # Data rows - only include actual differences (not SAME)
    for diff in comparison.all_diffs:
        if diff.diff_type == DiffType.SAME:
            continue

        # Extract versions
        left_ver = None
        right_ver = None
        if diff.left_node:
            _, left_ver = extract_version(diff.left_node.label)
        if diff.right_node:
            _, right_ver = extract_version(diff.right_node.label)

        writer.writerow([
            diff.label,
            diff.diff_type.value,
            categorize_diff(diff.label, diff.package_type).value,
            diff.package_type or "",
            left_ver or "",
            right_ver or "",
            diff.left_node.drv_hash if diff.left_node else "",
            diff.right_node.drv_hash if diff.right_node else "",
            diff.left_node.closure_size if diff.left_node else "",
            diff.right_node.closure_size if diff.right_node else "",
            diff.closure_impact,
            "true" if diff.left_node and diff.left_node.is_top_level else "false",
            "true" if diff.right_node and diff.right_node.is_top_level else "false",
        ])

    return output.getvalue()


def get_export_filename(
    comparison: ImportComparison,
    format: str,
) -> str:
    """Generate a descriptive filename for an export.

    Args:
        comparison: The comparison being exported
        format: The export format (json, csv, md)

    Returns:
        A sanitized filename string
    """
    import re
    from datetime import datetime

    # Sanitize import names for use in filename
    left_name = re.sub(r'[^\w\-]', '_', comparison.left_import.name)
    right_name = re.sub(r'[^\w\-]', '_', comparison.right_import.name)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    return f"comparison_{left_name}_vs_{right_name}_{timestamp}.{format}"
