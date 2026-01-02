"""Tests for Why Chain data models (Phase 8E-001)

These tests validate the Pydantic models used by the Why Chain feature,
which answers "Why is package X in my closure?" by showing attribution
paths from top-level packages down to any dependency.
"""

import pytest
from datetime import datetime, timedelta

from vizzy.models import (
    Node,
    DependencyDirection,
    EssentialityStatus,
    AttributionPath,
    AttributionGroup,
    WhyChainQuery,
    WhyChainResult,
    ForwardChainResult,
    AttributionCache,
    WhyChainSummary,
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


# =============================================================================
# DependencyDirection Tests
# =============================================================================


class TestDependencyDirection:
    """Test the DependencyDirection enum"""

    def test_reverse_direction_value(self):
        """REVERSE direction should have correct value"""
        assert DependencyDirection.REVERSE.value == "reverse"

    def test_forward_direction_value(self):
        """FORWARD direction should have correct value"""
        assert DependencyDirection.FORWARD.value == "forward"

    def test_direction_is_string_enum(self):
        """DependencyDirection should be usable as string"""
        direction = DependencyDirection.REVERSE
        # The .value property gives the string value
        assert f"Direction: {direction.value}" == "Direction: reverse"


# =============================================================================
# EssentialityStatus Tests
# =============================================================================


class TestEssentialityStatus:
    """Test the EssentialityStatus enum"""

    def test_essential_status_value(self):
        """ESSENTIAL status should have correct value"""
        assert EssentialityStatus.ESSENTIAL.value == "essential"

    def test_removable_status_value(self):
        """REMOVABLE status should have correct value"""
        assert EssentialityStatus.REMOVABLE.value == "removable"

    def test_build_only_status_value(self):
        """BUILD_ONLY status should have correct value"""
        assert EssentialityStatus.BUILD_ONLY.value == "build_only"

    def test_orphan_status_value(self):
        """ORPHAN status should have correct value"""
        assert EssentialityStatus.ORPHAN.value == "orphan"


# =============================================================================
# AttributionPath Tests
# =============================================================================


class TestAttributionPath:
    """Test the AttributionPath model"""

    def test_basic_path_creation(self):
        """Should create a basic attribution path"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss", package_type="lib")
        glibc = make_node(3, "glibc", package_type="lib")

        path = AttributionPath(
            path_nodes=[firefox, nss, glibc],
            path_length=2,
            top_level_node_id=1,
            target_node_id=3,
        )

        assert len(path.path_nodes) == 3
        assert path.path_length == 2
        assert path.top_level_node_id == 1
        assert path.target_node_id == 3

    def test_top_level_label(self):
        """Should return label of first node in path"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, glibc],
            path_length=1,
            top_level_node_id=1,
            target_node_id=2,
        )

        assert path.top_level_label == "firefox"

    def test_target_label(self):
        """Should return label of last node in path"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, glibc],
            path_length=1,
            top_level_node_id=1,
            target_node_id=2,
        )

        assert path.target_label == "glibc"

    def test_intermediate_labels_with_intermediates(self):
        """Should return labels of nodes between top-level and target"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        nspr = make_node(3, "nspr")
        glibc = make_node(4, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, nss, nspr, glibc],
            path_length=3,
            top_level_node_id=1,
            target_node_id=4,
        )

        assert path.intermediate_labels == ["nss", "nspr"]

    def test_intermediate_labels_empty_for_direct_dependency(self):
        """Should return empty list when path has no intermediates"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, glibc],
            path_length=1,
            top_level_node_id=1,
            target_node_id=2,
        )

        assert path.intermediate_labels == []

    def test_get_via_node(self):
        """Should return the node before target"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        glibc = make_node(3, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, nss, glibc],
            path_length=2,
            top_level_node_id=1,
            target_node_id=3,
        )

        via = path.get_via_node()
        assert via is not None
        assert via.label == "nss"

    def test_get_via_node_direct_path(self):
        """Should return top-level node for direct dependency"""
        firefox = make_node(1, "firefox", is_top_level=True)
        glibc = make_node(2, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, glibc],
            path_length=1,
            top_level_node_id=1,
            target_node_id=2,
        )

        via = path.get_via_node()
        assert via is not None
        assert via.label == "firefox"

    def test_get_via_node_single_node(self):
        """Should return None for single-node path"""
        glibc = make_node(1, "glibc")

        path = AttributionPath(
            path_nodes=[glibc],
            path_length=0,
            top_level_node_id=1,
            target_node_id=1,
        )

        assert path.get_via_node() is None

    def test_empty_path_labels(self):
        """Should handle empty path gracefully"""
        path = AttributionPath(
            path_nodes=[],
            path_length=0,
            top_level_node_id=0,
            target_node_id=0,
        )

        assert path.top_level_label == ""
        assert path.target_label == ""
        assert path.intermediate_labels == []

    def test_dependency_types_tracking(self):
        """Should track dependency types for each edge"""
        firefox = make_node(1, "firefox", is_top_level=True)
        nss = make_node(2, "nss")
        glibc = make_node(3, "glibc")

        path = AttributionPath(
            path_nodes=[firefox, nss, glibc],
            path_length=2,
            top_level_node_id=1,
            target_node_id=3,
            dependency_types=["runtime", "runtime"],
            is_runtime_path=True,
        )

        assert path.dependency_types == ["runtime", "runtime"]
        assert path.is_runtime_path is True

    def test_build_path_detection(self):
        """Should detect paths containing build dependencies"""
        rustc = make_node(1, "rustc", is_top_level=True)
        cargo = make_node(2, "cargo-build-hook")
        llvm = make_node(3, "llvm")

        path = AttributionPath(
            path_nodes=[rustc, cargo, llvm],
            path_length=2,
            top_level_node_id=1,
            target_node_id=3,
            dependency_types=["build", "build"],
            is_runtime_path=False,
        )

        assert path.is_runtime_path is False


# =============================================================================
# AttributionGroup Tests
# =============================================================================


class TestAttributionGroup:
    """Test the AttributionGroup model"""

    def test_basic_group_creation(self):
        """Should create a basic attribution group"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)
        wget = make_node(3, "wget", is_top_level=True)
        openssl = make_node(4, "openssl")

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox, wget],
            shortest_path=[firefox, curl, openssl],
            total_dependents=2,
        )

        assert group.via_node.label == "curl"
        assert len(group.top_level_packages) == 2
        assert group.total_dependents == 2

    def test_via_label(self):
        """Should return label of via node"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox],
            shortest_path=[firefox, curl],
            total_dependents=1,
        )

        assert group.via_label == "curl"

    def test_top_level_labels(self):
        """Should return all top-level package labels"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)
        wget = make_node(3, "wget", is_top_level=True)
        chromium = make_node(4, "chromium", is_top_level=True)

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox, wget, chromium],
            shortest_path=[firefox, curl],
            total_dependents=3,
        )

        assert group.top_level_labels == ["firefox", "wget", "chromium"]

    def test_preview_labels_under_limit(self):
        """Should return all labels when under 3"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)
        wget = make_node(3, "wget", is_top_level=True)

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox, wget],
            shortest_path=[firefox, curl],
            total_dependents=2,
        )

        assert group.preview_labels == ["firefox", "wget"]

    def test_preview_labels_at_limit(self):
        """Should return first 3 labels when at limit"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)
        wget = make_node(3, "wget", is_top_level=True)
        chromium = make_node(4, "chromium", is_top_level=True)

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox, wget, chromium],
            shortest_path=[firefox, curl],
            total_dependents=3,
        )

        assert group.preview_labels == ["firefox", "wget", "chromium"]
        assert group.additional_count == 0

    def test_preview_labels_over_limit(self):
        """Should return first 3 labels when over limit"""
        curl = make_node(1, "curl")
        packages = [
            make_node(i, f"pkg{i}", is_top_level=True) for i in range(2, 7)
        ]

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=packages,
            shortest_path=[packages[0], curl],
            total_dependents=5,
        )

        assert group.preview_labels == ["pkg2", "pkg3", "pkg4"]
        assert group.additional_count == 2

    def test_additional_count_zero(self):
        """Should return 0 when all packages fit in preview"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox],
            shortest_path=[firefox, curl],
            total_dependents=1,
        )

        assert group.additional_count == 0

    def test_common_path_suffix(self):
        """Should store common path from via to target"""
        curl = make_node(1, "curl")
        firefox = make_node(2, "firefox", is_top_level=True)
        openssl = make_node(3, "openssl")
        glibc = make_node(4, "glibc")

        group = AttributionGroup(
            via_node=curl,
            top_level_packages=[firefox],
            shortest_path=[firefox, curl, openssl, glibc],
            total_dependents=1,
            common_path_suffix=[curl, openssl, glibc],
        )

        assert len(group.common_path_suffix) == 3
        assert group.common_path_suffix[0].label == "curl"


# =============================================================================
# WhyChainQuery Tests
# =============================================================================


class TestWhyChainQuery:
    """Test the WhyChainQuery model"""

    def test_basic_query_creation(self):
        """Should create a basic query with defaults"""
        query = WhyChainQuery(
            target_node_id=123,
            import_id=1,
        )

        assert query.target_node_id == 123
        assert query.import_id == 1
        assert query.direction == DependencyDirection.REVERSE
        assert query.max_depth == 10
        assert query.max_paths == 100
        assert query.include_build_deps is True

    def test_custom_query_options(self):
        """Should accept custom options"""
        query = WhyChainQuery(
            target_node_id=123,
            import_id=1,
            direction=DependencyDirection.FORWARD,
            max_depth=5,
            max_paths=50,
            include_build_deps=False,
        )

        assert query.direction == DependencyDirection.FORWARD
        assert query.max_depth == 5
        assert query.max_paths == 50
        assert query.include_build_deps is False


# =============================================================================
# WhyChainResult Tests
# =============================================================================


class TestWhyChainResult:
    """Test the WhyChainResult model"""

    def _make_basic_result(
        self,
        essentiality: EssentialityStatus = EssentialityStatus.ESSENTIAL,
        top_level_dependents: int = 5,
        groups_count: int = 2,
    ) -> WhyChainResult:
        """Helper to create a basic result"""
        target = make_node(1, "glibc", package_type="lib")
        query = WhyChainQuery(target_node_id=1, import_id=1)

        # Create attribution groups
        groups = []
        for i in range(groups_count):
            via = make_node(10 + i, f"via{i}")
            tl = make_node(20 + i, f"pkg{i}", is_top_level=True)
            groups.append(
                AttributionGroup(
                    via_node=via,
                    top_level_packages=[tl],
                    shortest_path=[tl, via, target],
                    total_dependents=1,
                )
            )

        return WhyChainResult(
            target=target,
            query=query,
            direct_dependents=[make_node(100, "direct-dep")],
            attribution_groups=groups,
            total_top_level_dependents=top_level_dependents,
            total_paths_found=10,
            essentiality=essentiality,
        )

    def test_basic_result_creation(self):
        """Should create a basic result"""
        result = self._make_basic_result()

        assert result.target.label == "glibc"
        assert len(result.direct_dependents) == 1
        assert len(result.attribution_groups) == 2
        assert result.total_top_level_dependents == 5

    def test_is_essential(self):
        """Should identify essential packages"""
        result = self._make_basic_result(
            essentiality=EssentialityStatus.ESSENTIAL
        )
        assert result.is_essential is True
        assert result.is_removable is False
        assert result.is_build_only is False

    def test_is_removable(self):
        """Should identify removable packages"""
        result = self._make_basic_result(
            essentiality=EssentialityStatus.REMOVABLE
        )
        assert result.is_essential is False
        assert result.is_removable is True

    def test_is_orphan_removable(self):
        """Should identify orphan packages as removable"""
        result = self._make_basic_result(
            essentiality=EssentialityStatus.ORPHAN
        )
        assert result.is_essential is False
        assert result.is_removable is True

    def test_is_build_only(self):
        """Should identify build-only packages"""
        result = self._make_basic_result(
            essentiality=EssentialityStatus.BUILD_ONLY
        )
        assert result.is_essential is False
        assert result.is_removable is False
        assert result.is_build_only is True

    def test_summary_text_with_dependents(self):
        """Should generate summary for packages with dependents"""
        result = self._make_basic_result(
            top_level_dependents=5, groups_count=3
        )

        assert "glibc is needed by 5 top-level packages" in result.summary_text
        assert "3 paths" in result.summary_text

    def test_summary_text_no_dependents(self):
        """Should generate summary for packages without dependents"""
        target = make_node(1, "orphan-pkg")
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = WhyChainResult(
            target=target,
            query=query,
            direct_dependents=[],
            attribution_groups=[],
            total_top_level_dependents=0,
            total_paths_found=0,
            essentiality=EssentialityStatus.ORPHAN,
        )

        assert "not required by any top-level package" in result.summary_text

    def test_computation_time_tracking(self):
        """Should track computation time"""
        result = self._make_basic_result()
        assert result.computation_time_ms is None

        result_with_time = WhyChainResult(
            **{
                **result.model_dump(),
                "computation_time_ms": 123.45,
            }
        )
        assert result_with_time.computation_time_ms == 123.45

    def test_cached_at_tracking(self):
        """Should track cache timestamp"""
        result = self._make_basic_result()
        assert result.cached_at is None

        now = datetime.now()
        result_cached = WhyChainResult(
            **{
                **result.model_dump(),
                "cached_at": now,
            }
        )
        assert result_cached.cached_at == now


# =============================================================================
# ForwardChainResult Tests
# =============================================================================


class TestForwardChainResult:
    """Test the ForwardChainResult model"""

    def test_basic_forward_result(self):
        """Should create a basic forward chain result"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(
            target_node_id=1,
            import_id=1,
            direction=DependencyDirection.FORWARD,
        )

        direct = [make_node(2, "nss"), make_node(3, "gtk")]
        unique = [make_node(4, "unique-dep")]
        shared = [make_node(5, "glibc"), make_node(6, "openssl")]

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=direct,
            unique_dependencies=unique,
            shared_dependencies=shared,
            total_contribution=150,
        )

        assert result.source.label == "firefox"
        assert len(result.direct_dependencies) == 2
        assert result.total_contribution == 150

    def test_unique_count(self):
        """Should count unique dependencies"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=[],
            unique_dependencies=[
                make_node(2, "unique1"),
                make_node(3, "unique2"),
            ],
            shared_dependencies=[],
            total_contribution=50,
        )

        assert result.unique_count == 2

    def test_shared_count(self):
        """Should count shared dependencies"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=[],
            unique_dependencies=[],
            shared_dependencies=[
                make_node(2, "shared1"),
                make_node(3, "shared2"),
                make_node(4, "shared3"),
            ],
            total_contribution=100,
        )

        assert result.shared_count == 3

    def test_removal_impact_summary_with_unique(self):
        """Should describe removal impact when unique deps exist"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=[],
            unique_dependencies=[
                make_node(2, "unique1"),
                make_node(3, "unique2"),
            ],
            shared_dependencies=[],
            total_contribution=50,
        )

        assert "2 unique dependencies" in result.removal_impact_summary

    def test_removal_impact_summary_no_unique(self):
        """Should describe no impact when no unique deps"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=[],
            unique_dependencies=[],
            shared_dependencies=[make_node(2, "shared")],
            total_contribution=50,
        )

        assert "not reduce closure size" in result.removal_impact_summary

    def test_depth_distribution(self):
        """Should track depth distribution"""
        source = make_node(1, "firefox", is_top_level=True)
        query = WhyChainQuery(target_node_id=1, import_id=1)

        result = ForwardChainResult(
            source=source,
            query=query,
            direct_dependencies=[],
            unique_dependencies=[],
            shared_dependencies=[],
            total_contribution=100,
            depth_distribution={1: 5, 2: 20, 3: 50, 4: 25},
        )

        assert result.depth_distribution[1] == 5
        assert result.depth_distribution[3] == 50


# =============================================================================
# AttributionCache Tests
# =============================================================================


class TestAttributionCache:
    """Test the AttributionCache model"""

    def test_basic_cache_creation(self):
        """Should create a basic cache entry"""
        now = datetime.now()
        cache = AttributionCache(
            node_id=123,
            import_id=1,
            paths_json='[{"path": [1, 2, 3]}]',
            top_level_count=5,
            computed_at=now,
        )

        assert cache.node_id == 123
        assert cache.import_id == 1
        assert cache.top_level_count == 5
        assert cache.computed_at == now
        assert cache.expires_at is None

    def test_is_expired_no_expiry(self):
        """Should not be expired when no expiry set"""
        cache = AttributionCache(
            node_id=123,
            import_id=1,
            paths_json="[]",
            top_level_count=0,
            computed_at=datetime.now(),
        )

        assert cache.is_expired is False

    def test_is_expired_future_expiry(self):
        """Should not be expired when expiry is in future"""
        cache = AttributionCache(
            node_id=123,
            import_id=1,
            paths_json="[]",
            top_level_count=0,
            computed_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=1),
        )

        assert cache.is_expired is False

    def test_is_expired_past_expiry(self):
        """Should be expired when expiry is in past"""
        cache = AttributionCache(
            node_id=123,
            import_id=1,
            paths_json="[]",
            top_level_count=0,
            computed_at=datetime.now() - timedelta(hours=2),
            expires_at=datetime.now() - timedelta(hours=1),
        )

        assert cache.is_expired is True


# =============================================================================
# WhyChainSummary Tests
# =============================================================================


class TestWhyChainSummary:
    """Test the WhyChainSummary model"""

    def test_basic_summary_creation(self):
        """Should create a basic summary"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=1000,
            packages_with_top_level=950,
            orphan_packages=50,
            average_path_depth=3.5,
            max_path_depth=10,
            most_depended_packages=[("glibc", 100), ("openssl", 80)],
        )

        assert summary.import_id == 1
        assert summary.total_packages == 1000
        assert summary.orphan_packages == 50
        assert summary.max_path_depth == 10

    def test_orphan_percentage(self):
        """Should calculate orphan percentage correctly"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=1000,
            packages_with_top_level=900,
            orphan_packages=100,
            average_path_depth=3.0,
            max_path_depth=8,
            most_depended_packages=[],
        )

        assert summary.orphan_percentage == 10.0

    def test_orphan_percentage_zero_total(self):
        """Should handle zero total packages"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=0,
            packages_with_top_level=0,
            orphan_packages=0,
            average_path_depth=0.0,
            max_path_depth=0,
            most_depended_packages=[],
        )

        assert summary.orphan_percentage == 0.0

    def test_reachability_percentage(self):
        """Should calculate reachability percentage correctly"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=1000,
            packages_with_top_level=900,
            orphan_packages=100,
            average_path_depth=3.0,
            max_path_depth=8,
            most_depended_packages=[],
        )

        assert summary.reachability_percentage == 90.0

    def test_most_depended_packages_order(self):
        """Should preserve order of most depended packages"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=1000,
            packages_with_top_level=1000,
            orphan_packages=0,
            average_path_depth=3.0,
            max_path_depth=10,
            most_depended_packages=[
                ("glibc", 500),
                ("openssl", 300),
                ("zlib", 200),
            ],
        )

        assert summary.most_depended_packages[0] == ("glibc", 500)
        assert summary.most_depended_packages[1] == ("openssl", 300)
        assert summary.most_depended_packages[2] == ("zlib", 200)

    def test_computed_at_optional(self):
        """Should allow None for computed_at"""
        summary = WhyChainSummary(
            import_id=1,
            total_packages=100,
            packages_with_top_level=100,
            orphan_packages=0,
            average_path_depth=2.0,
            max_path_depth=5,
            most_depended_packages=[],
        )

        assert summary.computed_at is None

        summary_with_time = WhyChainSummary(
            import_id=1,
            total_packages=100,
            packages_with_top_level=100,
            orphan_packages=0,
            average_path_depth=2.0,
            max_path_depth=5,
            most_depended_packages=[],
            computed_at=datetime.now(),
        )

        assert summary_with_time.computed_at is not None


# =============================================================================
# Integration Tests
# =============================================================================


class TestWhyChainModelIntegration:
    """Integration tests for Why Chain models working together"""

    def test_full_why_chain_workflow(self):
        """Test models work together in a realistic scenario"""
        # Create nodes
        firefox = make_node(1, "firefox-121.0", is_top_level=True, top_level_source="systemPackages")
        wget = make_node(2, "wget-1.21", is_top_level=True, top_level_source="systemPackages")
        curl = make_node(3, "curl-8.5.0", package_type="lib")
        openssl = make_node(4, "openssl-3.2.0", package_type="lib")
        glibc = make_node(5, "glibc-2.38", package_type="lib")

        # Create paths
        path1 = AttributionPath(
            path_nodes=[firefox, curl, openssl, glibc],
            path_length=3,
            top_level_node_id=1,
            target_node_id=5,
            dependency_types=["runtime", "runtime", "runtime"],
            is_runtime_path=True,
        )

        path2 = AttributionPath(
            path_nodes=[wget, curl, openssl, glibc],
            path_length=3,
            top_level_node_id=2,
            target_node_id=5,
            dependency_types=["runtime", "runtime", "runtime"],
            is_runtime_path=True,
        )

        # Create attribution group
        group = AttributionGroup(
            via_node=openssl,
            top_level_packages=[firefox, wget],
            shortest_path=[firefox, curl, openssl, glibc],
            total_dependents=2,
            common_path_suffix=[openssl, glibc],
        )

        # Create query
        query = WhyChainQuery(
            target_node_id=5,
            import_id=1,
            direction=DependencyDirection.REVERSE,
            max_depth=10,
        )

        # Create result
        result = WhyChainResult(
            target=glibc,
            query=query,
            direct_dependents=[openssl],
            attribution_groups=[group],
            total_top_level_dependents=2,
            total_paths_found=2,
            essentiality=EssentialityStatus.ESSENTIAL,
            computation_time_ms=45.3,
        )

        # Verify the chain works
        assert result.target.label == "glibc-2.38"
        assert result.is_essential is True
        assert result.summary_text == "glibc-2.38 is needed by 2 top-level packages through 1 paths"
        assert group.via_label == "openssl-3.2.0"
        assert group.preview_labels == ["firefox-121.0", "wget-1.21"]
        assert group.additional_count == 0

        # Verify paths
        assert path1.top_level_label == "firefox-121.0"
        assert path1.target_label == "glibc-2.38"
        assert path1.get_via_node().label == "openssl-3.2.0"
        assert path1.intermediate_labels == ["curl-8.5.0", "openssl-3.2.0"]
