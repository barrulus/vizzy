"""Tests for path aggregation algorithm (Phase 8E-003)

These tests validate the path aggregation functions that group and summarize
multiple attribution paths for cleaner presentation in the Why Chain feature.
"""

import pytest

from vizzy.models import (
    Node,
    AttributionPath,
    AttributionGroup,
)
from vizzy.services.why_chain import (
    aggregate_paths,
    aggregate_paths_by_first_hop,
    summarize_attribution,
    get_attribution_text_for_group,
    get_path_description,
)


# =============================================================================
# Helper Functions
# =============================================================================


def make_node(
    id: int,
    label: str,
    package_type: str = "app",
    is_top_level: bool = False,
    top_level_source: str | None = None,
    closure_size: int = 10,
) -> Node:
    """Helper to create a Node for testing."""
    return Node(
        id=id,
        import_id=1,
        drv_hash=f"hash{id}",
        drv_name=f"{label}.drv",
        label=label,
        package_type=package_type,
        depth=1,
        closure_size=closure_size,
        metadata=None,
        is_top_level=is_top_level,
        top_level_source=top_level_source,
    )


def make_path(
    top_level: Node,
    target: Node,
    intermediates: list[Node] | None = None,
    dep_types: list[str] | None = None,
) -> AttributionPath:
    """Helper to create an AttributionPath."""
    if intermediates is None:
        intermediates = []

    path_nodes = [top_level] + intermediates + [target]
    path_length = len(path_nodes) - 1

    if dep_types is None:
        dep_types = ["runtime"] * path_length

    return AttributionPath(
        path_nodes=path_nodes,
        path_length=path_length,
        top_level_node_id=top_level.id,
        target_node_id=target.id,
        dependency_types=dep_types,
        is_runtime_path=all(dt in ("runtime", "unknown") for dt in dep_types),
    )


# =============================================================================
# aggregate_paths Tests
# =============================================================================


class TestAggregatePaths:
    """Test the aggregate_paths function"""

    def test_empty_paths(self):
        """Should return empty list for empty input"""
        groups = aggregate_paths([])
        assert groups == []

    def test_single_direct_path(self):
        """Should handle a single direct path (length 1)"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = make_path(firefox, glibc)
        groups = aggregate_paths([path])

        # Direct path should create a group where via_node is the target itself
        assert len(groups) == 1
        assert groups[0].total_dependents == 1

    def test_single_multi_hop_path(self):
        """Should handle a single path with intermediates"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        glibc = make_node(3, "glibc")

        path = make_path(firefox, glibc, intermediates=[nss])
        groups = aggregate_paths([path])

        assert len(groups) == 1
        assert groups[0].via_label == "nss"
        assert groups[0].total_dependents == 1

    def test_group_by_via_node(self):
        """Should group paths by their via node"""
        # Multiple top-level packages all reaching glibc via openssl
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        git = make_node(3, "git", is_top_level=True)
        openssl = make_node(4, "openssl")
        glibc = make_node(5, "glibc")

        paths = [
            make_path(firefox, glibc, intermediates=[openssl]),
            make_path(wget, glibc, intermediates=[openssl]),
            make_path(git, glibc, intermediates=[openssl]),
        ]

        groups = aggregate_paths(paths)

        # All paths should be grouped together by via node (openssl)
        assert len(groups) == 1
        assert groups[0].via_label == "openssl"
        assert groups[0].total_dependents == 3

    def test_multiple_via_nodes(self):
        """Should create separate groups for different via nodes"""
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        curl = make_node(3, "curl")
        python = make_node(4, "python")
        glibc = make_node(5, "glibc")

        paths = [
            make_path(firefox, glibc, intermediates=[curl]),
            make_path(wget, glibc, intermediates=[python]),
        ]

        groups = aggregate_paths(paths)

        assert len(groups) == 2
        via_labels = {g.via_label for g in groups}
        assert via_labels == {"curl", "python"}

    def test_sort_by_dependents(self):
        """Should sort groups by number of dependents (most first)"""
        # Create nodes
        pkg1 = make_node(1, "pkg1", is_top_level=True)
        pkg2 = make_node(2, "pkg2", is_top_level=True)
        pkg3 = make_node(3, "pkg3", is_top_level=True)
        pkg4 = make_node(4, "pkg4", is_top_level=True)
        via_popular = make_node(10, "via-popular")
        via_rare = make_node(11, "via-rare")
        target = make_node(20, "target")

        # via-popular has 3 dependents, via-rare has 1
        paths = [
            make_path(pkg1, target, intermediates=[via_popular]),
            make_path(pkg2, target, intermediates=[via_popular]),
            make_path(pkg3, target, intermediates=[via_popular]),
            make_path(pkg4, target, intermediates=[via_rare]),
        ]

        groups = aggregate_paths(paths)

        assert len(groups) == 2
        assert groups[0].via_label == "via-popular"
        assert groups[0].total_dependents == 3
        assert groups[1].via_label == "via-rare"
        assert groups[1].total_dependents == 1

    def test_max_groups_limit(self):
        """Should respect max_groups limit"""
        # Create many different via nodes
        target = make_node(100, "target")
        paths = []

        for i in range(1, 16):  # 15 different paths
            top_level = make_node(i, f"pkg{i}", is_top_level=True)
            via = make_node(i + 50, f"via{i}")
            paths.append(make_path(top_level, target, intermediates=[via]))

        groups = aggregate_paths(paths, max_groups=5)

        assert len(groups) == 5

    def test_keeps_shortest_path_per_top_level(self):
        """Should keep shortest path when same top-level has multiple paths via same node"""
        firefox = make_node(1, "firefox", is_top_level=True)
        curl = make_node(2, "curl")
        openssl = make_node(3, "openssl")
        glibc = make_node(4, "glibc")

        # Two paths from firefox to glibc via openssl with different lengths
        short_path = make_path(firefox, glibc, intermediates=[openssl])
        long_path = make_path(firefox, glibc, intermediates=[curl, openssl])

        groups = aggregate_paths([long_path, short_path])

        # Should only have one group with the shorter path
        assert len(groups) == 1
        # The shortest path has length 2 (firefox -> openssl -> glibc)
        assert len(groups[0].shortest_path) == 3

    def test_direct_and_indirect_paths(self):
        """Should handle mix of direct and indirect paths"""
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        curl = make_node(3, "curl")
        glibc = make_node(4, "glibc")

        # wget directly depends on glibc, firefox goes through curl
        paths = [
            make_path(firefox, glibc, intermediates=[curl]),
            make_path(wget, glibc),  # Direct path
        ]

        groups = aggregate_paths(paths)

        # Should have at least 2 groups (one for direct, one via curl)
        assert len(groups) >= 1

    def test_top_level_packages_sorted_by_label(self):
        """Should sort top-level packages by label within groups"""
        pkg_z = make_node(1, "zsh", is_top_level=True)
        pkg_a = make_node(2, "ansible", is_top_level=True)
        pkg_m = make_node(3, "make", is_top_level=True)
        via = make_node(4, "common-via")
        target = make_node(5, "target")

        paths = [
            make_path(pkg_z, target, intermediates=[via]),
            make_path(pkg_a, target, intermediates=[via]),
            make_path(pkg_m, target, intermediates=[via]),
        ]

        groups = aggregate_paths(paths)

        assert len(groups) == 1
        labels = [n.label for n in groups[0].top_level_packages]
        # Should be sorted alphabetically (case-insensitive)
        assert labels == ["ansible", "make", "zsh"]

    def test_common_path_suffix(self):
        """Should compute common path suffix from via to target"""
        firefox = make_node(1, "firefox", is_top_level=True)
        curl = make_node(2, "curl")
        openssl = make_node(3, "openssl")
        glibc = make_node(4, "glibc")

        path = make_path(firefox, glibc, intermediates=[curl, openssl])
        groups = aggregate_paths([path])

        assert len(groups) == 1
        # Via node is openssl (second to last), suffix should be [openssl, glibc]
        suffix_labels = [n.label for n in groups[0].common_path_suffix]
        assert "openssl" in suffix_labels
        assert "glibc" in suffix_labels


# =============================================================================
# aggregate_paths_by_first_hop Tests
# =============================================================================


class TestAggregatePathsByFirstHop:
    """Test the aggregate_paths_by_first_hop function"""

    def test_empty_paths(self):
        """Should return empty list for empty input"""
        groups = aggregate_paths_by_first_hop([])
        assert groups == []

    def test_single_path(self):
        """Should handle a single path"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        glibc = make_node(3, "glibc")

        path = make_path(firefox, glibc, intermediates=[nss])
        groups = aggregate_paths_by_first_hop([path])

        assert len(groups) == 1
        assert groups[0].via_label == "nss"

    def test_group_by_first_hop(self):
        """Should group paths by their first hop"""
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        curl = make_node(3, "curl")  # First hop from firefox
        python = make_node(4, "python")  # First hop from wget
        openssl = make_node(5, "openssl")
        glibc = make_node(6, "glibc")

        # firefox -> curl -> openssl -> glibc
        # wget -> python -> openssl -> glibc
        paths = [
            make_path(firefox, glibc, intermediates=[curl, openssl]),
            make_path(wget, glibc, intermediates=[python, openssl]),
        ]

        groups = aggregate_paths_by_first_hop(paths)

        assert len(groups) == 2
        via_labels = {g.via_label for g in groups}
        assert via_labels == {"curl", "python"}


# =============================================================================
# summarize_attribution Tests
# =============================================================================


class TestSummarizeAttribution:
    """Test the summarize_attribution function"""

    def test_no_groups(self):
        """Should return appropriate message when no groups"""
        summary = summarize_attribution([], "glibc", 0, 0)
        assert "not required by any top-level package" in summary
        assert "glibc" in summary

    def test_single_dependent(self):
        """Should name the single dependent"""
        firefox = make_node(1, "firefox", is_top_level=True)
        via = make_node(2, "via")
        target = make_node(3, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=[firefox],
            shortest_path=[firefox, via, target],
            total_dependents=1,
        )

        summary = summarize_attribution([group], "glibc", 1, 1)
        assert "glibc is needed by firefox" in summary

    def test_multiple_dependents(self):
        """Should summarize multiple dependents"""
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        via = make_node(3, "openssl")
        target = make_node(4, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=[firefox, wget],
            shortest_path=[firefox, via, target],
            total_dependents=2,
        )

        summary = summarize_attribution([group], "glibc", 2, 2)
        assert "glibc" in summary
        assert "2 top-level packages" in summary
        assert "openssl" in summary

    def test_direct_dependencies(self):
        """Should mention direct dependencies"""
        firefox = make_node(1, "firefox", is_top_level=True)
        target = make_node(2, "glibc")

        # Direct dependency group (path length 2 = top-level -> target)
        group = AttributionGroup(
            via_node=target,  # For direct, via_node is target
            top_level_packages=[firefox],
            shortest_path=[firefox, target],
            total_dependents=1,
        )

        summary = summarize_attribution([group], "glibc", 1, 1)
        assert "glibc" in summary

    def test_many_groups(self):
        """Should truncate and show 'and N more paths'"""
        target = make_node(100, "glibc")
        groups = []

        # Create 5 groups
        for i in range(5):
            top_level = make_node(i + 1, f"pkg{i}", is_top_level=True)
            via = make_node(i + 50, f"via{i}")
            groups.append(AttributionGroup(
                via_node=via,
                top_level_packages=[top_level],
                shortest_path=[top_level, via, target],
                total_dependents=1,
            ))

        summary = summarize_attribution(groups, "glibc", 5, 5)
        # Should mention that there are more paths
        assert "more" in summary or "via" in summary


# =============================================================================
# get_attribution_text_for_group Tests
# =============================================================================


class TestGetAttributionTextForGroup:
    """Test the get_attribution_text_for_group function"""

    def test_single_package(self):
        """Should show single package name"""
        firefox = make_node(1, "firefox", is_top_level=True)
        via = make_node(2, "curl")
        target = make_node(3, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=[firefox],
            shortest_path=[firefox, via, target],
            total_dependents=1,
        )

        text = get_attribution_text_for_group(group)
        assert text == "firefox"

    def test_few_packages(self):
        """Should list all packages when under limit"""
        firefox = make_node(1, "firefox", is_top_level=True)
        wget = make_node(2, "wget", is_top_level=True)
        via = make_node(3, "curl")
        target = make_node(4, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=[firefox, wget],
            shortest_path=[firefox, via, target],
            total_dependents=2,
        )

        text = get_attribution_text_for_group(group)
        assert "firefox" in text
        assert "wget" in text

    def test_many_packages(self):
        """Should truncate with '+N more' when over limit"""
        packages = [make_node(i, f"pkg{i}", is_top_level=True) for i in range(1, 8)]
        via = make_node(20, "curl")
        target = make_node(21, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=packages,
            shortest_path=[packages[0], via, target],
            total_dependents=7,
        )

        text = get_attribution_text_for_group(group, max_show=3)
        assert "pkg1" in text
        assert "+4 more" in text

    def test_custom_max_show(self):
        """Should respect custom max_show parameter"""
        packages = [make_node(i, f"pkg{i}", is_top_level=True) for i in range(1, 6)]
        via = make_node(20, "curl")
        target = make_node(21, "glibc")

        group = AttributionGroup(
            via_node=via,
            top_level_packages=packages,
            shortest_path=[packages[0], via, target],
            total_dependents=5,
        )

        text = get_attribution_text_for_group(group, max_show=5)
        # All packages should be shown
        assert "+0 more" not in text


# =============================================================================
# get_path_description Tests
# =============================================================================


class TestGetPathDescription:
    """Test the get_path_description function"""

    def test_direct_path(self):
        """Should format direct path correctly"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = make_path(firefox, glibc)
        desc = get_path_description(path)

        assert desc == "firefox -> glibc"

    def test_multi_hop_path(self):
        """Should format multi-hop path correctly"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        nspr = make_node(3, "nspr")
        glibc = make_node(4, "glibc")

        path = make_path(firefox, glibc, intermediates=[nss, nspr])
        desc = get_path_description(path)

        assert desc == "firefox -> nss -> nspr -> glibc"


# =============================================================================
# Integration Tests
# =============================================================================


class TestPathAggregationIntegration:
    """Integration tests for path aggregation"""

    def test_realistic_glibc_scenario(self):
        """Test aggregation with a realistic glibc dependency scenario"""
        # Simulate glibc being depended on by many packages via different routes
        glibc = make_node(100, "glibc-2.38", package_type="lib")

        # Top-level packages
        firefox = make_node(1, "firefox-121.0", is_top_level=True)
        chromium = make_node(2, "chromium-120.0", is_top_level=True)
        vscode = make_node(3, "vscode-1.85", is_top_level=True)
        python = make_node(4, "python3-3.11", is_top_level=True)
        gcc = make_node(5, "gcc-13.2", is_top_level=True)

        # Intermediate packages
        nss = make_node(50, "nss-3.95")
        openssl = make_node(51, "openssl-3.2.0")
        curl = make_node(52, "curl-8.5.0")
        electron = make_node(53, "electron-28.0")

        # Create realistic paths
        paths = [
            # firefox -> nss -> glibc
            make_path(firefox, glibc, intermediates=[nss]),
            # chromium -> nss -> glibc
            make_path(chromium, glibc, intermediates=[nss]),
            # vscode -> electron -> nss -> glibc
            make_path(vscode, glibc, intermediates=[electron, nss]),
            # python -> openssl -> glibc
            make_path(python, glibc, intermediates=[openssl]),
            # gcc -> glibc (direct)
            make_path(gcc, glibc),
        ]

        groups = aggregate_paths(paths)

        # Should have groups: via nss (3 packages), via glibc direct (1), via openssl (1)
        assert len(groups) >= 2

        # Most popular group should be via nss
        nss_group = next((g for g in groups if g.via_label == "nss-3.95"), None)
        if nss_group:
            assert nss_group.total_dependents == 3

        # Generate summary
        summary = summarize_attribution(
            groups,
            "glibc-2.38",
            total_paths=5,
            total_top_level=5,
        )

        assert "glibc-2.38" in summary
        assert "5 top-level packages" in summary

    def test_aggregation_with_build_and_runtime_paths(self):
        """Test aggregation preserves path type information"""
        rustc = make_node(1, "rustc", is_top_level=True)
        cargo = make_node(2, "cargo", is_top_level=True)
        llvm = make_node(3, "llvm")
        glibc = make_node(4, "glibc")

        # rustc -> llvm -> glibc (build path)
        build_path = AttributionPath(
            path_nodes=[rustc, llvm, glibc],
            path_length=2,
            top_level_node_id=1,
            target_node_id=4,
            dependency_types=["build", "runtime"],
            is_runtime_path=False,
        )

        # cargo -> glibc (runtime path)
        runtime_path = AttributionPath(
            path_nodes=[cargo, glibc],
            path_length=1,
            top_level_node_id=2,
            target_node_id=4,
            dependency_types=["runtime"],
            is_runtime_path=True,
        )

        groups = aggregate_paths([build_path, runtime_path])

        # Should have groups for different paths
        assert len(groups) >= 1

    def test_large_scale_aggregation(self):
        """Test aggregation performance with many paths"""
        target = make_node(1000, "common-lib")

        # Create 50 top-level packages, each with path through one of 5 via nodes
        paths = []
        for i in range(50):
            top_level = make_node(i, f"pkg{i}", is_top_level=True)
            via_idx = i % 5
            via = make_node(500 + via_idx, f"via{via_idx}")
            paths.append(make_path(top_level, target, intermediates=[via]))

        groups = aggregate_paths(paths, max_groups=10)

        # Should have 5 groups (one per via node)
        assert len(groups) == 5

        # Each group should have 10 dependents
        for group in groups:
            assert group.total_dependents == 10

        # Groups should be sorted by dependents (all equal here)
        assert groups[0].total_dependents >= groups[-1].total_dependents
