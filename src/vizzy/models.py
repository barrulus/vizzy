"""Pydantic models for Vizzy"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, computed_field


# =============================================================================
# Comparison Types (Phase 5)
# =============================================================================


class DiffType(str, Enum):
    """Type of difference between two imports for a node"""

    ONLY_LEFT = "only_left"  # Only in left import
    ONLY_RIGHT = "only_right"  # Only in right import
    DIFFERENT_HASH = "different"  # Same label, different derivation hash
    SAME = "same"  # Identical in both imports


class VersionChangeType(str, Enum):
    """Type of version change between two packages with same name"""

    UPGRADE = "upgrade"  # Version increased (e.g., 1.0 -> 2.0)
    DOWNGRADE = "downgrade"  # Version decreased (e.g., 2.0 -> 1.0)
    REBUILD = "rebuild"  # Same version but different hash (rebuild/patch)
    UNKNOWN = "unknown"  # Could not determine version change direction


# =============================================================================
# Core Models
# =============================================================================


class ImportInfo(BaseModel):
    """Information about an imported configuration"""

    id: int
    name: str
    config_path: str
    drv_path: str
    imported_at: datetime
    node_count: int | None
    edge_count: int | None


class Node(BaseModel):
    """A derivation node in the graph"""

    id: int
    import_id: int
    drv_hash: str
    drv_name: str
    label: str
    package_type: str | None
    depth: int | None
    closure_size: int | None
    metadata: dict[str, Any] | None
    is_top_level: bool = False  # True if user-facing (in systemPackages, etc.)
    top_level_source: str | None = None  # Where defined: 'systemPackages', 'programs.git.enable', etc.
    # Phase 8A-005: Module type classification for easier grouping
    module_type: str | None = None  # 'systemPackages', 'programs', 'services', or 'other'
    # Phase 8A-003: Closure contribution fields
    unique_contribution: int | None = None  # Dependencies only reachable via this package
    shared_contribution: int | None = None  # Dependencies also reachable via other packages
    total_contribution: int | None = None  # Sum of unique + shared
    contribution_computed_at: datetime | None = None  # When contribution was last calculated


class Edge(BaseModel):
    """A dependency edge in the graph"""

    id: int
    import_id: int
    source_id: int
    target_id: int
    edge_color: str | None
    is_redundant: bool
    dependency_type: str | None = None  # 'build', 'runtime', or 'unknown'


class NodeWithNeighbors(BaseModel):
    """A node with its dependencies and dependents"""

    node: Node
    dependencies: list[Node]
    dependents: list[Node]


class GraphData(BaseModel):
    """Graph data for rendering"""

    nodes: list[Node]
    edges: list[Edge]


class ClusterInfo(BaseModel):
    """Information about a package type cluster"""

    package_type: str
    node_count: int
    total_closure_size: int


class SearchResult(BaseModel):
    """Search result item"""

    node: Node
    similarity: float


class PathResult(BaseModel):
    """Result of path finding between two nodes"""

    source: Node
    target: Node
    path: list[Node]
    length: int


class AnalysisResult(BaseModel):
    """Cached analysis result"""

    id: int
    import_id: int
    analysis_type: str
    result: dict[str, Any]
    computed_at: datetime


class LoopGroup(BaseModel):
    """A strongly connected component (cycle) in the graph"""

    nodes: list[Node]
    cycle_path: list[int]  # Node IDs forming the cycle

    @property
    def size(self) -> int:
        return len(self.nodes)


class RedundantLink(BaseModel):
    """An edge that can be removed without changing transitive closure"""

    edge: Edge
    source_node: Node
    target_node: Node
    bypass_path: list[Node]  # Alternative path that makes this edge redundant


# =============================================================================
# Comparison Models (Phase 5)
# =============================================================================


class NodeDiff(BaseModel):
    """Represents a node's difference between two imports.

    For SAME and DIFFERENT_HASH types, both left_node and right_node are set.
    For ONLY_LEFT, only left_node is set.
    For ONLY_RIGHT, only right_node is set.
    """

    label: str
    package_type: str | None
    left_node: Node | None = None  # Present in left import
    right_node: Node | None = None  # Present in right import
    diff_type: DiffType

    @computed_field
    @property
    def closure_impact(self) -> int:
        """Calculate the closure size difference between left and right."""
        left_closure = self.left_node.closure_size if self.left_node else 0
        right_closure = self.right_node.closure_size if self.right_node else 0
        return (right_closure or 0) - (left_closure or 0)


class ImportComparison(BaseModel):
    """Complete comparison between two imports.

    Provides summary metrics and grouped diffs for UI consumption.
    """

    left_import: ImportInfo
    right_import: ImportInfo

    # Summary metrics
    left_only_count: int
    right_only_count: int
    different_count: int
    same_count: int

    # All diffs for detailed analysis
    all_diffs: list[NodeDiff]

    @computed_field
    @property
    def total_nodes_compared(self) -> int:
        """Total unique labels compared."""
        return self.left_only_count + self.right_only_count + self.different_count + self.same_count

    @computed_field
    @property
    def net_package_change(self) -> int:
        """Net change in package count (positive means right has more)."""
        return self.right_only_count - self.left_only_count

    def get_diffs_by_type(self, diff_type: DiffType) -> list[NodeDiff]:
        """Get all diffs of a specific type."""
        return [d for d in self.all_diffs if d.diff_type == diff_type]

    def get_diffs_by_package_type(self, package_type: str) -> list[NodeDiff]:
        """Get all diffs for a specific package type."""
        return [d for d in self.all_diffs if d.package_type == package_type]


class ClosureComparison(BaseModel):
    """Comparison of closure sizes and composition between two imports.

    Provides insight into the largest additions and removals.
    """

    left_total: int
    right_total: int

    @computed_field
    @property
    def difference(self) -> int:
        """Absolute difference in total closure size."""
        return self.right_total - self.left_total

    @computed_field
    @property
    def percentage_diff(self) -> float:
        """Percentage difference relative to left total."""
        if self.left_total == 0:
            return 100.0 if self.right_total > 0 else 0.0
        return ((self.right_total - self.left_total) / self.left_total) * 100

    largest_additions: list[NodeDiff]  # Nodes only in right, sorted by closure size
    largest_removals: list[NodeDiff]  # Nodes only in left, sorted by closure size


# =============================================================================
# Version Difference Models (Phase 8F)
# =============================================================================


class VersionDiff(BaseModel):
    """Represents a version difference between two imports for the same package.

    Used when comparing two imports where a package exists in both but with
    different versions or derivation hashes.
    """

    package_name: str  # Base package name without version (e.g., "openssl")
    left_version: str | None  # Version in left import (e.g., "3.0.12")
    right_version: str | None  # Version in right import (e.g., "3.1.0")
    left_label: str  # Full label in left import (e.g., "openssl-3.0.12")
    right_label: str  # Full label in right import (e.g., "openssl-3.1.0")
    left_node_id: int  # Node ID in left import
    right_node_id: int  # Node ID in right import
    change_type: VersionChangeType  # Type of version change
    package_type: str | None  # Package classification (app, lib, etc.)

    @computed_field
    @property
    def version_change_summary(self) -> str:
        """Human-readable summary of the version change."""
        left = self.left_version or "unknown"
        right = self.right_version or "unknown"
        if self.change_type == VersionChangeType.UPGRADE:
            return f"{left} -> {right}"
        elif self.change_type == VersionChangeType.DOWNGRADE:
            return f"{left} -> {right}"
        elif self.change_type == VersionChangeType.REBUILD:
            return f"{left} (rebuilt)"
        else:
            return f"{left} -> {right} (change)"


class VersionComparisonResult(BaseModel):
    """Result of version comparison between two imports.

    Contains categorized version differences for display in the UI.
    """

    left_import_id: int
    right_import_id: int
    upgrades: list[VersionDiff]  # Packages that were upgraded
    downgrades: list[VersionDiff]  # Packages that were downgraded
    rebuilds: list[VersionDiff]  # Same version but different hash
    unknown_changes: list[VersionDiff]  # Could not determine direction

    @computed_field
    @property
    def total_changes(self) -> int:
        """Total number of version changes."""
        return len(self.upgrades) + len(self.downgrades) + len(self.rebuilds) + len(self.unknown_changes)

    @computed_field
    @property
    def upgrade_count(self) -> int:
        """Number of upgrades."""
        return len(self.upgrades)

    @computed_field
    @property
    def downgrade_count(self) -> int:
        """Number of downgrades."""
        return len(self.downgrades)

    @computed_field
    @property
    def rebuild_count(self) -> int:
        """Number of rebuilds."""
        return len(self.rebuilds)


# =============================================================================
# Closure Contribution Models (Phase 8A-003)
# =============================================================================


class ClosureContribution(BaseModel):
    """Represents a package's contribution to the total closure size.

    This model tracks how much each package (especially top-level packages)
    contributes to the overall closure. Contribution is split into:
    - unique: Dependencies only reachable via this package
    - shared: Dependencies also reachable via other packages
    """

    node_id: int
    label: str
    package_type: str | None
    unique_contribution: int  # Deps only reachable through this package
    shared_contribution: int  # Deps also reachable via other packages
    total_contribution: int  # unique + shared
    closure_size: int | None  # The node's own closure size for reference

    @computed_field
    @property
    def unique_percentage(self) -> float:
        """Percentage of contribution that is unique (would be removed if package removed)."""
        if self.total_contribution == 0:
            return 0.0
        return (self.unique_contribution / self.total_contribution) * 100

    @computed_field
    @property
    def removal_impact(self) -> str:
        """Human-readable impact of removing this package."""
        if self.unique_contribution == 0:
            return "No unique dependencies - safe to remove"
        elif self.unique_percentage > 75:
            return f"High impact - {self.unique_contribution} unique deps would be removed"
        elif self.unique_percentage > 25:
            return f"Medium impact - {self.unique_contribution} unique deps would be removed"
        else:
            return f"Low impact - {self.unique_contribution} unique deps would be removed"


class ClosureContributionSummary(BaseModel):
    """Summary of closure contributions for an entire import.

    Provides aggregate metrics and top contributors for dashboard display.
    """

    import_id: int
    total_top_level_packages: int
    total_unique_contributions: int
    total_shared_contributions: int
    computation_time_ms: float | None = None
    computed_at: datetime | None = None

    # Top contributors sorted by unique contribution (packages blocking size reduction)
    top_unique_contributors: list[ClosureContribution]
    # Top contributors sorted by total contribution (largest packages overall)
    top_total_contributors: list[ClosureContribution]

    @computed_field
    @property
    def average_unique_contribution(self) -> float:
        """Average unique contribution per top-level package."""
        if self.total_top_level_packages == 0:
            return 0.0
        return self.total_unique_contributions / self.total_top_level_packages

    @computed_field
    @property
    def sharing_ratio(self) -> float:
        """Ratio of shared to total contributions (higher = more sharing = more efficient)."""
        total = self.total_unique_contributions + self.total_shared_contributions
        if total == 0:
            return 0.0
        return self.total_shared_contributions / total


class ContributionDiff(BaseModel):
    """Comparison of a package's contribution between two imports.

    Used for understanding how closure contribution changed over time.
    """

    label: str
    package_type: str | None
    left_unique: int
    right_unique: int
    left_shared: int
    right_shared: int

    @computed_field
    @property
    def unique_diff(self) -> int:
        """Change in unique contribution (positive = increased)."""
        return self.right_unique - self.left_unique

    @computed_field
    @property
    def total_diff(self) -> int:
        """Change in total contribution."""
        return (self.right_unique + self.right_shared) - (self.left_unique + self.left_shared)


# =============================================================================
# Why Chain Models (Phase 8E-001)
# =============================================================================
#
# The Why Chain feature answers "Why is package X in my closure?" by showing
# attribution paths from top-level packages down to any dependency.
#
# Key concepts:
# - Attribution Path: A chain of dependencies from a top-level package to a target
# - Attribution Group: Multiple paths consolidated by common intermediate packages
# - Why Chain Result: Complete analysis for a target package
#
# Usage patterns:
# 1. "Why is glibc in my closure?" - Find all paths from top-level to glibc
# 2. "What does firefox pull in?" - Forward lookup showing dependencies
# 3. "Is this package essential?" - Determine if removing would break user packages
#
# Data flow:
# - WhyChainQuery -> find_paths_to_node() -> AttributionPath[]
# - AttributionPath[] -> aggregate_paths() -> AttributionGroup[]
# - AttributionGroup[] + metadata -> WhyChainResult
#
# Caching strategy:
# - AttributionCache stores computed paths for expensive queries
# - Cache invalidation on import refresh
# - TTL-based expiration for large closures


class DependencyDirection(str, Enum):
    """Direction of dependency traversal for Why Chain queries.

    REVERSE: Target -> Top-level (why is X here?)
    FORWARD: Top-level -> Target (what does X pull in?)
    """

    REVERSE = "reverse"  # Target to top-level (answering "why is X here?")
    FORWARD = "forward"  # Top-level to target (answering "what does X pull in?")


class EssentialityStatus(str, Enum):
    """Classification of a package's removability status.

    Indicates whether a package can be safely removed from the closure.
    Enhanced with more granular classifications for better user guidance.
    """

    # Essential classifications (cannot be safely removed)
    ESSENTIAL = "essential"  # Required at runtime by multiple top-level packages
    ESSENTIAL_SINGLE = "essential_single"  # Required at runtime by only one top-level package
    ESSENTIAL_DEEP = "essential_deep"  # Essential but deeply nested (indirect dependency)

    # Potentially removable classifications
    REMOVABLE = "removable"  # Only needed by optional top-level packages
    BUILD_ONLY = "build_only"  # Only needed at build time, not runtime
    ORPHAN = "orphan"  # No top-level package depends on it (cleanup candidate)

    @property
    def is_essential_category(self) -> bool:
        """Check if this status belongs to the essential category."""
        return self in (
            EssentialityStatus.ESSENTIAL,
            EssentialityStatus.ESSENTIAL_SINGLE,
            EssentialityStatus.ESSENTIAL_DEEP,
        )

    @property
    def is_removable_category(self) -> bool:
        """Check if this status belongs to the removable category."""
        return self in (
            EssentialityStatus.REMOVABLE,
            EssentialityStatus.BUILD_ONLY,
            EssentialityStatus.ORPHAN,
        )

    @property
    def display_name(self) -> str:
        """Human-readable display name for the status."""
        names = {
            EssentialityStatus.ESSENTIAL: "Essential",
            EssentialityStatus.ESSENTIAL_SINGLE: "Essential (Single Dependent)",
            EssentialityStatus.ESSENTIAL_DEEP: "Essential (Deeply Nested)",
            EssentialityStatus.REMOVABLE: "Removable",
            EssentialityStatus.BUILD_ONLY: "Build Only",
            EssentialityStatus.ORPHAN: "Orphan",
        }
        return names.get(self, self.value.replace("_", " ").title())

    @property
    def description(self) -> str:
        """Detailed description of what this status means."""
        descriptions = {
            EssentialityStatus.ESSENTIAL: "Required at runtime by multiple top-level packages",
            EssentialityStatus.ESSENTIAL_SINGLE: "Required at runtime by only one top-level package",
            EssentialityStatus.ESSENTIAL_DEEP: "Essential dependency but deeply nested in the graph",
            EssentialityStatus.REMOVABLE: "Only needed by optional packages, could be removed",
            EssentialityStatus.BUILD_ONLY: "Only used during build, not in runtime closure",
            EssentialityStatus.ORPHAN: "No path from any top-level package (cleanup candidate)",
        }
        return descriptions.get(self, "")


class AttributionPath(BaseModel):
    """A single dependency path from a top-level package to a target node.

    Represents one complete chain showing how a top-level package (like firefox)
    depends on a target package (like glibc) through intermediate dependencies.

    Example path for "why is glibc in my closure?":
        firefox -> nss -> nspr -> glibc

    The path is ordered from top-level (first) to target (last).

    Attributes:
        path_nodes: Ordered list of nodes from top-level to target
        path_length: Number of edges in this path
        top_level_node_id: ID of the top-level package starting this path
        target_node_id: ID of the target package we're explaining
        dependency_types: Types of each edge ('build', 'runtime', 'unknown')
        is_runtime_path: True if all edges are runtime dependencies

    Usage:
        Used by reverse path computation (8E-002) to represent individual paths.
        Aggregated into AttributionGroup by path aggregation algorithm (8E-003).
    """

    path_nodes: list[Node]
    path_length: int
    top_level_node_id: int
    target_node_id: int
    dependency_types: list[str] = []  # ['runtime', 'runtime', 'build'] for each edge
    is_runtime_path: bool = True  # True if all deps in path are runtime

    @computed_field
    @property
    def top_level_label(self) -> str:
        """Label of the top-level package starting this path."""
        if self.path_nodes:
            return self.path_nodes[0].label
        return ""

    @computed_field
    @property
    def target_label(self) -> str:
        """Label of the target package at the end of this path."""
        if self.path_nodes:
            return self.path_nodes[-1].label
        return ""

    @computed_field
    @property
    def intermediate_labels(self) -> list[str]:
        """Labels of intermediate nodes (excluding top-level and target)."""
        if len(self.path_nodes) <= 2:
            return []
        return [n.label for n in self.path_nodes[1:-1]]

    def get_via_node(self) -> Node | None:
        """Get the node immediately before the target (the 'via' node).

        This is useful for grouping paths by their immediate dependent.
        """
        if len(self.path_nodes) >= 2:
            return self.path_nodes[-2]
        return None


class AttributionGroup(BaseModel):
    """A group of paths that share a common intermediate node.

    When multiple top-level packages depend on a target through the same
    intermediate package, we group them for cleaner display.

    Example for "why is glibc here?":
        Via curl (5 packages):
            firefox, wget, git, cargo, nix
            Path: [package] -> curl -> openssl -> glibc

    Attributes:
        via_node: The common intermediate node before target
        top_level_packages: List of top-level packages reaching target via this node
        shortest_path: The shortest path through via_node to target
        total_dependents: Count of unique top-level packages in this group
        common_path_suffix: Nodes from via_node to target (shared by all paths)

    Usage:
        Created by path aggregation algorithm (8E-003).
        Displayed in Why Chain UI component (8E-006).
    """

    via_node: Node
    top_level_packages: list[Node]
    shortest_path: list[Node]  # Shortest example path through via_node
    total_dependents: int
    common_path_suffix: list[Node] = []  # Path from via_node to target

    @computed_field
    @property
    def via_label(self) -> str:
        """Label of the intermediate node paths go through."""
        return self.via_node.label

    @computed_field
    @property
    def top_level_labels(self) -> list[str]:
        """Labels of all top-level packages in this group."""
        return [n.label for n in self.top_level_packages]

    @computed_field
    @property
    def preview_labels(self) -> list[str]:
        """First 3 top-level labels for preview display."""
        return [n.label for n in self.top_level_packages[:3]]

    @computed_field
    @property
    def additional_count(self) -> int:
        """Count of additional packages beyond preview (for '+N more')."""
        return max(0, len(self.top_level_packages) - 3)


class WhyChainQuery(BaseModel):
    """Input parameters for a Why Chain query.

    Encapsulates the query parameters for finding attribution paths.

    Attributes:
        target_node_id: The node we want to explain (why is this here?)
        import_id: The import context for the query
        direction: REVERSE (why here) or FORWARD (what pulls in)
        max_depth: Maximum path length to search
        max_paths: Maximum number of paths to return
        include_build_deps: Whether to include build-time dependencies

    Usage:
        Passed to Why Chain API endpoint (8E-005).
        Used by reverse path computation (8E-002).
    """

    target_node_id: int
    import_id: int
    direction: DependencyDirection = DependencyDirection.REVERSE
    max_depth: int = 10
    max_paths: int = 100
    include_build_deps: bool = True


class WhyChainResult(BaseModel):
    """Complete result of a Why Chain query.

    Contains all information needed to explain why a package exists in the
    closure and display it in the UI.

    Attributes:
        target: The package being explained
        query: The original query parameters
        direct_dependents: Nodes that directly depend on target
        attribution_groups: Paths grouped by intermediate nodes
        total_top_level_dependents: Count of unique top-level packages
        total_paths_found: Total number of paths discovered
        essentiality: Whether this package is essential/removable
        computation_time_ms: Time taken to compute (for performance monitoring)
        cached_at: When this result was cached (None if fresh)

    Usage:
        Returned by Why Chain API endpoint (8E-005).
        Consumed by Why Chain frontend visualization (8E-006).
    """

    target: Node
    query: WhyChainQuery
    direct_dependents: list[Node]
    attribution_groups: list[AttributionGroup]
    total_top_level_dependents: int
    total_paths_found: int
    essentiality: EssentialityStatus = EssentialityStatus.ESSENTIAL
    computation_time_ms: float | None = None
    cached_at: datetime | None = None

    @computed_field
    @property
    def is_essential(self) -> bool:
        """True if this package is required by user packages."""
        return self.essentiality == EssentialityStatus.ESSENTIAL

    @computed_field
    @property
    def is_removable(self) -> bool:
        """True if this package could potentially be removed."""
        return self.essentiality in (
            EssentialityStatus.REMOVABLE,
            EssentialityStatus.ORPHAN,
        )

    @computed_field
    @property
    def is_build_only(self) -> bool:
        """True if this package is only needed at build time."""
        return self.essentiality == EssentialityStatus.BUILD_ONLY

    @computed_field
    @property
    def summary_text(self) -> str:
        """Human-readable summary of the result."""
        if self.total_top_level_dependents == 0:
            return f"{self.target.label} is not required by any top-level package"
        groups = len(self.attribution_groups)
        return (
            f"{self.target.label} is needed by {self.total_top_level_dependents} "
            f"top-level packages through {groups} paths"
        )


class ForwardChainResult(BaseModel):
    """Result of a forward chain query (what does X pull in?).

    Shows the transitive dependencies a top-level package adds to the closure.

    Attributes:
        source: The top-level package being analyzed
        query: The original query parameters
        direct_dependencies: Nodes this package directly depends on
        unique_dependencies: Dependencies only this package brings
        shared_dependencies: Dependencies also pulled by other packages
        total_contribution: Total closure contribution
        depth_distribution: Count of deps at each depth level

    Usage:
        Alternative view for Why Chain - shows impact of a package.
        Useful for understanding "what would removing X remove from closure?"
    """

    source: Node
    query: WhyChainQuery
    direct_dependencies: list[Node]
    unique_dependencies: list[Node]
    shared_dependencies: list[Node]
    total_contribution: int
    depth_distribution: dict[int, int] = {}  # depth -> count of deps at that depth

    @computed_field
    @property
    def unique_count(self) -> int:
        """Count of dependencies only reachable via this package."""
        return len(self.unique_dependencies)

    @computed_field
    @property
    def shared_count(self) -> int:
        """Count of dependencies also reachable via other packages."""
        return len(self.shared_dependencies)

    @computed_field
    @property
    def removal_impact_summary(self) -> str:
        """Human-readable summary of what removing this package would do."""
        if self.unique_count == 0:
            return "Removing this would not reduce closure size"
        return f"Removing this would remove {self.unique_count} unique dependencies"


# =============================================================================
# Removal Impact Models (Phase 8E-007)
# =============================================================================
#
# These models support the "essential vs removable" classification feature,
# providing detailed analysis of what would happen if a package were removed.


class RemovalImpact(BaseModel):
    """Detailed analysis of the impact of removing a package.

    Helps users understand the consequences of removing a package from their
    closure, including what packages would be affected and how much the
    closure size would decrease.

    Attributes:
        target: The package being analyzed for removal
        essentiality: Classification of the package's removability
        affected_packages: Top-level packages that would be broken by removal
        unique_deps_removed: Dependencies only reachable through this package
        closure_reduction: Number of packages that would be removed from closure
        removal_safe: Whether removal is considered safe
        removal_warning: Warning message if removal is risky
        alternative_providers: Other packages that provide similar functionality

    Usage:
        Displayed in the Why Chain UI to help users make informed decisions
        about whether to keep or remove a package.
    """

    target: Node
    essentiality: EssentialityStatus
    affected_packages: list[Node]  # Top-level packages that would break
    unique_deps_removed: list[Node]  # Unique dependencies that would be removed
    closure_reduction: int  # Number of packages removed from closure
    removal_safe: bool  # True if removal would not break functionality
    removal_warning: str | None = None  # Warning message if risky
    alternative_providers: list[Node] = []  # Packages that provide similar deps

    @computed_field
    @property
    def affected_count(self) -> int:
        """Count of top-level packages that would be affected."""
        return len(self.affected_packages)

    @computed_field
    @property
    def unique_deps_count(self) -> int:
        """Count of unique dependencies that would be removed."""
        return len(self.unique_deps_removed)

    @computed_field
    @property
    def impact_level(self) -> str:
        """Categorize the impact level for display purposes."""
        if self.removal_safe:
            return "safe"
        elif self.affected_count == 0:
            return "low"
        elif self.affected_count == 1:
            return "medium"
        else:
            return "high"

    @computed_field
    @property
    def summary(self) -> str:
        """Human-readable summary of the removal impact."""
        if self.removal_safe:
            if self.closure_reduction > 0:
                return f"Safe to remove. Would reduce closure by {self.closure_reduction} packages."
            return "Safe to remove. No closure impact."

        if self.affected_count == 1:
            pkg = self.affected_packages[0].label if self.affected_packages else "1 package"
            return f"Would break {pkg}."
        elif self.affected_count > 1:
            return f"Would break {self.affected_count} packages."
        else:
            return "Cannot determine impact."

    @computed_field
    @property
    def detailed_summary(self) -> str:
        """Detailed multi-line summary of removal impact."""
        lines = []

        if self.removal_safe:
            lines.append("This package can be safely removed.")
        else:
            lines.append("Removing this package would affect your system.")

        if self.affected_count > 0:
            if self.affected_count <= 3:
                names = [p.label for p in self.affected_packages]
                lines.append(f"Affected packages: {', '.join(names)}")
            else:
                lines.append(f"{self.affected_count} top-level packages depend on this.")

        if self.closure_reduction > 0:
            lines.append(f"Closure reduction: {self.closure_reduction} packages")

        if self.removal_warning:
            lines.append(f"Warning: {self.removal_warning}")

        return "\n".join(lines)


class EssentialityAnalysis(BaseModel):
    """Complete essentiality analysis for a package.

    Combines the classification status with detailed impact analysis,
    path statistics, and actionable guidance.

    Attributes:
        target: The package being analyzed
        status: The essentiality classification
        removal_impact: Detailed removal impact analysis
        runtime_dependents: Count of packages with runtime dependencies
        build_dependents: Count of packages with build dependencies only
        path_depth_avg: Average path depth from top-level packages
        path_depth_max: Maximum path depth
        is_direct_dependency: True if any top-level package directly depends on it
        top_dependent_summary: Summary of top-level packages that depend on it

    Usage:
        Provides a comprehensive view of a package's role in the closure.
        Used by the Why Chain UI for the enhanced essentiality display.
    """

    target: Node
    status: EssentialityStatus
    removal_impact: RemovalImpact
    runtime_dependents: int = 0
    build_dependents: int = 0
    path_depth_avg: float = 0.0
    path_depth_max: int = 0
    is_direct_dependency: bool = False
    top_dependent_summary: str = ""

    @computed_field
    @property
    def total_dependents(self) -> int:
        """Total count of packages depending on this (runtime + build)."""
        return self.runtime_dependents + self.build_dependents

    @computed_field
    @property
    def dependency_type_summary(self) -> str:
        """Summary of how this package is depended upon."""
        if self.runtime_dependents > 0 and self.build_dependents > 0:
            return f"{self.runtime_dependents} runtime, {self.build_dependents} build-only"
        elif self.runtime_dependents > 0:
            return f"{self.runtime_dependents} runtime dependencies"
        elif self.build_dependents > 0:
            return f"{self.build_dependents} build-only dependencies"
        else:
            return "No dependencies found"

    @computed_field
    @property
    def depth_category(self) -> str:
        """Categorize the dependency depth for display."""
        if self.is_direct_dependency:
            return "direct"
        elif self.path_depth_avg <= 2:
            return "shallow"
        elif self.path_depth_avg <= 5:
            return "moderate"
        else:
            return "deep"

    @computed_field
    @property
    def action_guidance(self) -> str:
        """Provide actionable guidance based on the analysis."""
        if self.status == EssentialityStatus.ORPHAN:
            return "This package appears unused. Consider removing it to reduce closure size."
        elif self.status == EssentialityStatus.BUILD_ONLY:
            return "This package is only needed at build time. It won't affect runtime."
        elif self.status == EssentialityStatus.REMOVABLE:
            return "This package could be removed if you don't need its dependent packages."
        elif self.status == EssentialityStatus.ESSENTIAL_SINGLE:
            return f"This package is required by {self.top_dependent_summary}. Remove that to remove this."
        elif self.status == EssentialityStatus.ESSENTIAL_DEEP:
            return "This package is a deep dependency. It's needed but through many layers."
        else:  # ESSENTIAL
            return "This package is essential and cannot be removed without breaking your system."


class AttributionCache(BaseModel):
    """Cached attribution data for a node.

    Stores pre-computed attribution paths to avoid expensive recomputation.
    Used by attribution caching task (8E-008).

    Attributes:
        node_id: The target node ID
        import_id: The import context
        paths_json: Serialized path data (stored as JSON for DB)
        top_level_count: Number of top-level dependents
        computed_at: When the cache was created
        expires_at: When the cache should be invalidated

    Usage:
        Stored in analysis table with type 'attribution:{node_id}'.
        Retrieved before computing paths to short-circuit expensive queries.
    """

    node_id: int
    import_id: int
    paths_json: str  # JSON-serialized paths for DB storage
    top_level_count: int
    computed_at: datetime
    expires_at: datetime | None = None

    @computed_field
    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


class WhyChainSummary(BaseModel):
    """Summary statistics for Why Chain across an entire import.

    Provides aggregate metrics about attribution patterns in the closure.

    Attributes:
        import_id: The import being summarized
        total_packages: Total packages in the import
        packages_with_top_level: Packages reachable from top-level
        orphan_packages: Packages not reachable from any top-level
        average_path_depth: Average depth of attribution paths
        max_path_depth: Maximum path depth found
        most_depended_packages: Packages with most top-level dependents
        computed_at: When this summary was computed

    Usage:
        Displayed on System Health Dashboard (8B).
        Provides overview of attribution patterns.
    """

    import_id: int
    total_packages: int
    packages_with_top_level: int
    orphan_packages: int
    average_path_depth: float
    max_path_depth: int
    most_depended_packages: list[tuple[str, int]]  # (label, dependent_count)
    computed_at: datetime | None = None

    @computed_field
    @property
    def orphan_percentage(self) -> float:
        """Percentage of packages that are orphaned (not reachable from top-level)."""
        if self.total_packages == 0:
            return 0.0
        return (self.orphan_packages / self.total_packages) * 100

    @computed_field
    @property
    def reachability_percentage(self) -> float:
        """Percentage of packages reachable from top-level."""
        return 100.0 - self.orphan_percentage


# =============================================================================
# Baseline Models (Phase 8A-004)
# =============================================================================
#
# The Baseline system allows users to save snapshots of imports for later
# comparison. This enables tracking closure growth over time and comparing
# against reference configurations.
#
# Key concepts:
# - Baseline: A lightweight snapshot of import metrics (node/edge counts, type distribution)
# - BaselineComparison: Result of comparing an import against a baseline
# - Baselines persist even if the source import is deleted
#
# Use cases:
# - "How much has my closure grown since last month?"
# - "How does my desktop config compare to a minimal NixOS?"
# - "What package types are driving closure growth?"


class Baseline(BaseModel):
    """A baseline reference configuration for comparison.

    Baselines store snapshot metrics from imports that persist even if
    the source import is deleted. They provide reference points for
    tracking closure growth over time.

    Attributes:
        id: Unique baseline identifier
        name: User-friendly name (e.g., "Minimal NixOS 24.05")
        description: Optional description of what this baseline represents
        source_import_id: ID of the import this was created from (nullable)
        node_count: Total number of derivations at creation time
        edge_count: Total number of dependencies at creation time
        closure_by_type: Breakdown by package type (e.g., {"library": 1234})
        top_level_count: Number of top-level packages
        runtime_edge_count: Number of runtime dependencies
        build_edge_count: Number of build-time dependencies
        max_depth: Maximum dependency depth
        avg_depth: Average dependency depth
        top_contributors: List of top packages by closure size
        created_at: When the baseline was created
        updated_at: Last metadata update
        is_system_baseline: True for built-in reference baselines
        tags: Flexible tags for categorization

    Usage:
        Created via create_baseline_from_import() service function.
        Used by compare_to_baseline() and dashboard comparison features.
    """

    id: int
    name: str
    description: str | None = None
    source_import_id: int | None = None
    node_count: int
    edge_count: int
    closure_by_type: dict[str, int] = {}
    top_level_count: int | None = None
    runtime_edge_count: int | None = None
    build_edge_count: int | None = None
    max_depth: int | None = None
    avg_depth: float | None = None
    top_contributors: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime
    is_system_baseline: bool = False
    tags: list[str] = []

    @computed_field
    @property
    def total_packages_by_type(self) -> int:
        """Total packages counted across all types."""
        return sum(self.closure_by_type.values())

    @computed_field
    @property
    def runtime_percentage(self) -> float:
        """Percentage of edges that are runtime dependencies."""
        if not self.runtime_edge_count or self.edge_count == 0:
            return 0.0
        return (self.runtime_edge_count / self.edge_count) * 100


class BaselineComparisonResult(BaseModel):
    """Result of comparing an import against a baseline.

    Contains summary metrics and detailed differences for display
    in the dashboard and comparison views.

    Attributes:
        import_id: The import being compared
        baseline_id: The baseline being compared against
        baseline_name: Name of the baseline for display
        node_difference: import.nodes - baseline.nodes (positive = larger)
        edge_difference: import.edges - baseline.edges
        percentage_difference: ((import - baseline) / baseline) * 100
        differences_by_type: Difference counts per package type
        is_larger: True if import has more nodes than baseline
        growth_category: "minimal", "moderate", "significant", "excessive"
        computed_at: When the comparison was computed

    Usage:
        Returned by compare_to_baseline() service function.
        Displayed in dashboard and comparison UI.
    """

    import_id: int
    baseline_id: int
    baseline_name: str
    node_difference: int
    edge_difference: int
    percentage_difference: float
    differences_by_type: dict[str, int] = {}
    is_larger: bool = False
    growth_category: str = "minimal"
    computed_at: datetime

    @computed_field
    @property
    def growth_summary(self) -> str:
        """Human-readable summary of the comparison."""
        if self.node_difference == 0:
            return f"Same size as {self.baseline_name}"
        elif self.is_larger:
            return f"{abs(self.node_difference):,} more packages than {self.baseline_name} ({self.percentage_difference:+.1f}%)"
        else:
            return f"{abs(self.node_difference):,} fewer packages than {self.baseline_name} ({self.percentage_difference:+.1f}%)"

    @computed_field
    @property
    def is_concerning(self) -> bool:
        """True if the growth is in 'significant' or 'excessive' category."""
        return self.growth_category in ("significant", "excessive")

    @computed_field
    @property
    def top_type_differences(self) -> list[tuple[str, int]]:
        """Top 5 package types by absolute difference."""
        sorted_diffs = sorted(
            self.differences_by_type.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        return sorted_diffs[:5]


class BaselineCreateRequest(BaseModel):
    """Request model for creating a baseline.

    Used by API endpoints to validate baseline creation requests.
    """

    name: str
    description: str | None = None
    tags: list[str] = []
    is_system_baseline: bool = False


class BaselineUpdateRequest(BaseModel):
    """Request model for updating baseline metadata.

    Note: Metrics cannot be updated after creation.
    """

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


# =============================================================================
# Module Attribution Models (Phase 8E-009)
# =============================================================================
#
# These models support the module-level attribution display feature.
# They show users WHERE top-level packages are defined in the NixOS configuration:
# - environment.systemPackages
# - programs.*.enable (e.g., programs.git.enable)
# - services.*.enable (e.g., services.nginx.enable)
#
# This helps users understand "why is this here AND where did it come from?"


class ModuleType(str, Enum):
    """Classification of NixOS module types that add packages."""

    SYSTEM_PACKAGES = "systemPackages"  # environment.systemPackages
    PROGRAMS = "programs"  # programs.*.enable
    SERVICES = "services"  # services.*.enable
    OTHER = "other"  # Other sources

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        names = {
            ModuleType.SYSTEM_PACKAGES: "System Packages",
            ModuleType.PROGRAMS: "Programs",
            ModuleType.SERVICES: "Services",
            ModuleType.OTHER: "Other",
        }
        return names.get(self, self.value)

    @property
    def icon(self) -> str:
        """Icon character for display."""
        icons = {
            ModuleType.SYSTEM_PACKAGES: "pkg",
            ModuleType.PROGRAMS: "app",
            ModuleType.SERVICES: "svc",
            ModuleType.OTHER: "other",
        }
        return icons.get(self, "?")

    @property
    def description(self) -> str:
        """Description of what this module type means."""
        descriptions = {
            ModuleType.SYSTEM_PACKAGES: "Added via environment.systemPackages",
            ModuleType.PROGRAMS: "Added via programs.*.enable option",
            ModuleType.SERVICES: "Added via services.*.enable option",
            ModuleType.OTHER: "Added via other configuration",
        }
        return descriptions.get(self, "")

    @property
    def css_class(self) -> str:
        """CSS class name for styling."""
        return f"module-type-{self.value.lower().replace('_', '-')}"


class ModuleAttribution(BaseModel):
    """Attribution information for a single top-level package.

    Links a package to the NixOS module configuration that adds it.

    Attributes:
        node: The top-level package node
        module_type: Type of module (systemPackages, programs, services)
        source: Full source path (e.g., 'programs.git.enable')
        display_source: Formatted source for display
    """

    node: Node
    module_type: ModuleType
    source: str  # e.g., 'programs.git.enable', 'systemPackages'
    display_source: str  # Formatted for display

    @computed_field
    @property
    def is_explicit(self) -> bool:
        """True if this is an explicitly declared package (not a dependency)."""
        return self.module_type != ModuleType.OTHER

    @computed_field
    @property
    def short_source(self) -> str:
        """Shortened source for compact display."""
        if self.source == "systemPackages":
            return "pkgs"
        if self.source.startswith("programs."):
            # programs.git.enable -> git
            parts = self.source.split(".")
            if len(parts) >= 2:
                return parts[1]
        if self.source.startswith("services."):
            # services.nginx.enable -> nginx
            parts = self.source.split(".")
            if len(parts) >= 2:
                return parts[1]
        return self.source


class ModuleAttributionGroup(BaseModel):
    """Group of top-level packages from the same module type.

    Used to organize the display of module attribution in the UI.

    Attributes:
        module_type: The type of module
        packages: List of packages from this module type
        count: Number of packages in this group
    """

    module_type: ModuleType
    packages: list[ModuleAttribution]

    @computed_field
    @property
    def count(self) -> int:
        """Number of packages in this group."""
        return len(self.packages)

    @computed_field
    @property
    def display_name(self) -> str:
        """Display name for the group header."""
        return self.module_type.display_name


class ModuleAttributionSummary(BaseModel):
    """Summary of module attribution for Why Chain display.

    Provides grouped and sorted attribution information for all
    top-level packages that lead to a target node.

    Attributes:
        target_node_id: The node we're explaining
        groups: Attribution grouped by module type
        total_packages: Total number of top-level packages
        by_source: Breakdown by exact source string
    """

    target_node_id: int
    groups: list[ModuleAttributionGroup]
    total_packages: int
    by_source: dict[str, int]  # source -> count

    @computed_field
    @property
    def has_explicit_sources(self) -> bool:
        """True if any packages have explicit module attribution."""
        for group in self.groups:
            if group.module_type != ModuleType.OTHER:
                return True
        return False

    @computed_field
    @property
    def primary_source(self) -> str | None:
        """The most common source, if one dominates."""
        if not self.by_source:
            return None
        max_source = max(self.by_source.items(), key=lambda x: x[1])
        if max_source[1] > self.total_packages * 0.5:
            return max_source[0]
        return None

    def get_source_breakdown_text(self) -> str:
        """Human-readable breakdown of sources."""
        if self.total_packages == 0:
            return "No top-level packages"

        parts = []
        for group in sorted(self.groups, key=lambda g: g.count, reverse=True):
            if group.count > 0:
                parts.append(f"{group.count} from {group.module_type.display_name}")

        return ", ".join(parts) if parts else "No attribution data"
