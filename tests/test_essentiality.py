"""Tests for enhanced essentiality classification (Phase 8E-007)

These tests validate the enhanced EssentialityStatus enum, RemovalImpact model,
EssentialityAnalysis model, and the determine_essentiality() function with its
new granular classifications.
"""

import pytest
from datetime import datetime

from vizzy.models import (
    Node,
    EssentialityStatus,
    RemovalImpact,
    EssentialityAnalysis,
    AttributionPath,
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
    path_nodes: list[Node],
    is_runtime: bool = True,
) -> AttributionPath:
    """Helper to create an AttributionPath for testing."""
    dep_types = ["runtime" if is_runtime else "build"] * (len(path_nodes) - 1)
    return AttributionPath(
        path_nodes=path_nodes,
        path_length=len(path_nodes) - 1,
        top_level_node_id=path_nodes[0].id,
        target_node_id=path_nodes[-1].id,
        dependency_types=dep_types,
        is_runtime_path=is_runtime,
    )


# =============================================================================
# EssentialityStatus Enum Tests
# =============================================================================


class TestEssentialityStatusEnum:
    """Test the enhanced EssentialityStatus enum"""

    def test_essential_value(self):
        """ESSENTIAL should have correct value"""
        assert EssentialityStatus.ESSENTIAL.value == "essential"

    def test_essential_single_value(self):
        """ESSENTIAL_SINGLE should have correct value"""
        assert EssentialityStatus.ESSENTIAL_SINGLE.value == "essential_single"

    def test_essential_deep_value(self):
        """ESSENTIAL_DEEP should have correct value"""
        assert EssentialityStatus.ESSENTIAL_DEEP.value == "essential_deep"

    def test_removable_value(self):
        """REMOVABLE should have correct value"""
        assert EssentialityStatus.REMOVABLE.value == "removable"

    def test_build_only_value(self):
        """BUILD_ONLY should have correct value"""
        assert EssentialityStatus.BUILD_ONLY.value == "build_only"

    def test_orphan_value(self):
        """ORPHAN should have correct value"""
        assert EssentialityStatus.ORPHAN.value == "orphan"

    def test_is_essential_category_essential(self):
        """ESSENTIAL should be in essential category"""
        assert EssentialityStatus.ESSENTIAL.is_essential_category is True

    def test_is_essential_category_essential_single(self):
        """ESSENTIAL_SINGLE should be in essential category"""
        assert EssentialityStatus.ESSENTIAL_SINGLE.is_essential_category is True

    def test_is_essential_category_essential_deep(self):
        """ESSENTIAL_DEEP should be in essential category"""
        assert EssentialityStatus.ESSENTIAL_DEEP.is_essential_category is True

    def test_is_essential_category_removable(self):
        """REMOVABLE should not be in essential category"""
        assert EssentialityStatus.REMOVABLE.is_essential_category is False

    def test_is_removable_category_removable(self):
        """REMOVABLE should be in removable category"""
        assert EssentialityStatus.REMOVABLE.is_removable_category is True

    def test_is_removable_category_build_only(self):
        """BUILD_ONLY should be in removable category"""
        assert EssentialityStatus.BUILD_ONLY.is_removable_category is True

    def test_is_removable_category_orphan(self):
        """ORPHAN should be in removable category"""
        assert EssentialityStatus.ORPHAN.is_removable_category is True

    def test_is_removable_category_essential(self):
        """ESSENTIAL should not be in removable category"""
        assert EssentialityStatus.ESSENTIAL.is_removable_category is False

    def test_display_name_essential(self):
        """ESSENTIAL should have correct display name"""
        assert EssentialityStatus.ESSENTIAL.display_name == "Essential"

    def test_display_name_essential_single(self):
        """ESSENTIAL_SINGLE should have correct display name"""
        assert EssentialityStatus.ESSENTIAL_SINGLE.display_name == "Essential (Single Dependent)"

    def test_display_name_essential_deep(self):
        """ESSENTIAL_DEEP should have correct display name"""
        assert EssentialityStatus.ESSENTIAL_DEEP.display_name == "Essential (Deeply Nested)"

    def test_display_name_orphan(self):
        """ORPHAN should have correct display name"""
        assert EssentialityStatus.ORPHAN.display_name == "Orphan"

    def test_description_essential(self):
        """ESSENTIAL should have correct description"""
        assert "multiple top-level" in EssentialityStatus.ESSENTIAL.description

    def test_description_essential_single(self):
        """ESSENTIAL_SINGLE should have correct description"""
        assert "only one top-level" in EssentialityStatus.ESSENTIAL_SINGLE.description

    def test_description_orphan(self):
        """ORPHAN should have correct description"""
        assert "No path" in EssentialityStatus.ORPHAN.description


# =============================================================================
# RemovalImpact Model Tests
# =============================================================================


class TestRemovalImpactModel:
    """Test the RemovalImpact model"""

    def test_basic_creation(self):
        """Should create a basic RemovalImpact"""
        target = make_node(1, "glibc")
        affected = [make_node(2, "firefox", is_top_level=True)]
        unique_deps = [make_node(3, "nspr"), make_node(4, "nss")]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=affected,
            unique_deps_removed=unique_deps,
            closure_reduction=3,
            removal_safe=False,
        )

        assert impact.target.label == "glibc"
        assert impact.essentiality == EssentialityStatus.ESSENTIAL
        assert len(impact.affected_packages) == 1
        assert len(impact.unique_deps_removed) == 2
        assert impact.closure_reduction == 3
        assert impact.removal_safe is False

    def test_affected_count(self):
        """Should count affected packages correctly"""
        target = make_node(1, "openssl")
        affected = [
            make_node(2, "firefox", is_top_level=True),
            make_node(3, "wget", is_top_level=True),
            make_node(4, "curl", is_top_level=True),
        ]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=affected,
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert impact.affected_count == 3

    def test_unique_deps_count(self):
        """Should count unique dependencies correctly"""
        target = make_node(1, "python")
        unique = [make_node(i, f"dep{i}") for i in range(2, 12)]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL_SINGLE,
            affected_packages=[],
            unique_deps_removed=unique,
            closure_reduction=11,
            removal_safe=False,
        )

        assert impact.unique_deps_count == 10

    def test_impact_level_safe(self):
        """Should return 'safe' when removal is safe"""
        target = make_node(1, "orphan-pkg")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ORPHAN,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=True,
        )

        assert impact.impact_level == "safe"

    def test_impact_level_low(self):
        """Should return 'low' when no affected packages"""
        target = make_node(1, "build-dep")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.BUILD_ONLY,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert impact.impact_level == "low"

    def test_impact_level_medium(self):
        """Should return 'medium' when one package affected"""
        target = make_node(1, "lib-x")
        affected = [make_node(2, "app", is_top_level=True)]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL_SINGLE,
            affected_packages=affected,
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert impact.impact_level == "medium"

    def test_impact_level_high(self):
        """Should return 'high' when multiple packages affected"""
        target = make_node(1, "glibc")
        affected = [
            make_node(2, "firefox", is_top_level=True),
            make_node(3, "wget", is_top_level=True),
        ]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=affected,
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert impact.impact_level == "high"

    def test_summary_safe_with_reduction(self):
        """Should generate correct summary for safe removal with closure reduction"""
        target = make_node(1, "orphan")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ORPHAN,
            affected_packages=[],
            unique_deps_removed=[make_node(2, "dep1")],
            closure_reduction=5,
            removal_safe=True,
        )

        assert "Safe to remove" in impact.summary
        assert "5 packages" in impact.summary

    def test_summary_safe_no_reduction(self):
        """Should generate correct summary for safe removal without closure reduction"""
        target = make_node(1, "orphan")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ORPHAN,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=0,
            removal_safe=True,
        )

        assert "Safe to remove" in impact.summary
        assert "No closure impact" in impact.summary

    def test_summary_would_break_single(self):
        """Should show specific package name when one package affected"""
        target = make_node(1, "critical-lib")
        affected = [make_node(2, "firefox", is_top_level=True)]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL_SINGLE,
            affected_packages=affected,
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert "Would break firefox" in impact.summary

    def test_summary_would_break_multiple(self):
        """Should show count when multiple packages affected"""
        target = make_node(1, "glibc")
        affected = [
            make_node(2, "firefox", is_top_level=True),
            make_node(3, "wget", is_top_level=True),
            make_node(4, "curl", is_top_level=True),
        ]

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=affected,
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )

        assert "Would break 3 packages" in impact.summary

    def test_detailed_summary_safe(self):
        """Should include 'safely removed' in detailed summary for safe packages"""
        target = make_node(1, "orphan")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ORPHAN,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=0,
            removal_safe=True,
        )

        assert "safely removed" in impact.detailed_summary

    def test_detailed_summary_with_warning(self):
        """Should include warning in detailed summary"""
        target = make_node(1, "lib")

        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
            removal_warning="Required by system packages",
        )

        assert "Warning: Required by system packages" in impact.detailed_summary


# =============================================================================
# EssentialityAnalysis Model Tests
# =============================================================================


class TestEssentialityAnalysisModel:
    """Test the EssentialityAnalysis model"""

    def _make_basic_analysis(
        self,
        status: EssentialityStatus = EssentialityStatus.ESSENTIAL,
        runtime_dependents: int = 5,
        build_dependents: int = 0,
        path_depth_avg: float = 3.0,
        is_direct: bool = False,
    ) -> EssentialityAnalysis:
        """Helper to create a basic EssentialityAnalysis"""
        target = make_node(1, "glibc", package_type="lib")

        impact = RemovalImpact(
            target=target,
            essentiality=status,
            affected_packages=[make_node(2, "firefox", is_top_level=True)],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=status.is_removable_category,
        )

        return EssentialityAnalysis(
            target=target,
            status=status,
            removal_impact=impact,
            runtime_dependents=runtime_dependents,
            build_dependents=build_dependents,
            path_depth_avg=path_depth_avg,
            path_depth_max=int(path_depth_avg * 1.5),
            is_direct_dependency=is_direct,
            top_dependent_summary="5 packages" if runtime_dependents > 1 else "firefox",
        )

    def test_basic_creation(self):
        """Should create a basic EssentialityAnalysis"""
        analysis = self._make_basic_analysis()

        assert analysis.target.label == "glibc"
        assert analysis.status == EssentialityStatus.ESSENTIAL
        assert analysis.removal_impact is not None

    def test_total_dependents(self):
        """Should calculate total dependents correctly"""
        analysis = self._make_basic_analysis(runtime_dependents=5, build_dependents=3)

        assert analysis.total_dependents == 8

    def test_dependency_type_summary_runtime_only(self):
        """Should show runtime only summary"""
        analysis = self._make_basic_analysis(runtime_dependents=5, build_dependents=0)

        assert "5 runtime dependencies" in analysis.dependency_type_summary

    def test_dependency_type_summary_build_only(self):
        """Should show build only summary"""
        analysis = self._make_basic_analysis(
            status=EssentialityStatus.BUILD_ONLY,
            runtime_dependents=0,
            build_dependents=3
        )

        assert "3 build-only dependencies" in analysis.dependency_type_summary

    def test_dependency_type_summary_mixed(self):
        """Should show mixed summary"""
        analysis = self._make_basic_analysis(runtime_dependents=5, build_dependents=3)

        assert "5 runtime" in analysis.dependency_type_summary
        assert "3 build" in analysis.dependency_type_summary

    def test_depth_category_direct(self):
        """Should return 'direct' for direct dependencies"""
        analysis = self._make_basic_analysis(is_direct=True)

        assert analysis.depth_category == "direct"

    def test_depth_category_shallow(self):
        """Should return 'shallow' for low depth"""
        analysis = self._make_basic_analysis(path_depth_avg=1.5, is_direct=False)

        assert analysis.depth_category == "shallow"

    def test_depth_category_moderate(self):
        """Should return 'moderate' for moderate depth"""
        analysis = self._make_basic_analysis(path_depth_avg=3.5, is_direct=False)

        assert analysis.depth_category == "moderate"

    def test_depth_category_deep(self):
        """Should return 'deep' for high depth"""
        analysis = self._make_basic_analysis(path_depth_avg=7.0, is_direct=False)

        assert analysis.depth_category == "deep"

    def test_action_guidance_orphan(self):
        """Should provide orphan guidance"""
        analysis = self._make_basic_analysis(status=EssentialityStatus.ORPHAN)

        assert "unused" in analysis.action_guidance.lower()
        assert "removing" in analysis.action_guidance.lower()

    def test_action_guidance_build_only(self):
        """Should provide build-only guidance"""
        analysis = self._make_basic_analysis(status=EssentialityStatus.BUILD_ONLY)

        assert "build time" in analysis.action_guidance.lower()

    def test_action_guidance_essential(self):
        """Should provide essential guidance"""
        analysis = self._make_basic_analysis(status=EssentialityStatus.ESSENTIAL)

        assert "essential" in analysis.action_guidance.lower()
        assert "cannot be removed" in analysis.action_guidance.lower()

    def test_action_guidance_essential_single(self):
        """Should provide single dependent guidance"""
        target = make_node(1, "lib")
        impact = RemovalImpact(
            target=target,
            essentiality=EssentialityStatus.ESSENTIAL_SINGLE,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
        )
        analysis = EssentialityAnalysis(
            target=target,
            status=EssentialityStatus.ESSENTIAL_SINGLE,
            removal_impact=impact,
            runtime_dependents=1,
            top_dependent_summary="firefox",
        )

        assert "firefox" in analysis.action_guidance

    def test_action_guidance_essential_deep(self):
        """Should provide deep dependency guidance"""
        analysis = self._make_basic_analysis(status=EssentialityStatus.ESSENTIAL_DEEP)

        assert "deep" in analysis.action_guidance.lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestEssentialityIntegration:
    """Integration tests for essentiality models working together"""

    def test_full_analysis_workflow(self):
        """Test models work together in a realistic scenario"""
        # Create nodes
        firefox = make_node(1, "firefox-121.0", is_top_level=True)
        wget = make_node(2, "wget-1.21", is_top_level=True)
        curl = make_node(3, "curl-8.5.0")
        openssl = make_node(4, "openssl-3.2.0")
        glibc = make_node(5, "glibc-2.38")

        # Create paths
        path1 = make_path([firefox, curl, openssl, glibc], is_runtime=True)
        path2 = make_path([wget, curl, openssl, glibc], is_runtime=True)

        # Create removal impact
        impact = RemovalImpact(
            target=glibc,
            essentiality=EssentialityStatus.ESSENTIAL,
            affected_packages=[firefox, wget],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=False,
            removal_warning="Required by 2 packages",
        )

        # Create analysis
        analysis = EssentialityAnalysis(
            target=glibc,
            status=EssentialityStatus.ESSENTIAL,
            removal_impact=impact,
            runtime_dependents=2,
            build_dependents=0,
            path_depth_avg=3.0,
            path_depth_max=3,
            is_direct_dependency=False,
            top_dependent_summary="2 packages",
        )

        # Verify the chain works
        assert analysis.target.label == "glibc-2.38"
        assert analysis.status == EssentialityStatus.ESSENTIAL
        assert analysis.status.is_essential_category is True
        assert analysis.status.is_removable_category is False
        assert analysis.removal_impact.impact_level == "high"
        assert analysis.removal_impact.affected_count == 2
        assert "Would break 2 packages" in analysis.removal_impact.summary
        assert "essential" in analysis.action_guidance.lower()
        assert analysis.depth_category == "moderate"

    def test_orphan_package_analysis(self):
        """Test analysis for an orphan package"""
        orphan = make_node(1, "unused-lib", package_type="lib")
        unique_dep = make_node(2, "orphan-dep")

        impact = RemovalImpact(
            target=orphan,
            essentiality=EssentialityStatus.ORPHAN,
            affected_packages=[],
            unique_deps_removed=[unique_dep],
            closure_reduction=2,
            removal_safe=True,
        )

        analysis = EssentialityAnalysis(
            target=orphan,
            status=EssentialityStatus.ORPHAN,
            removal_impact=impact,
            runtime_dependents=0,
            build_dependents=0,
            path_depth_avg=0.0,
            path_depth_max=0,
            is_direct_dependency=False,
            top_dependent_summary="No runtime dependents",
        )

        assert analysis.status == EssentialityStatus.ORPHAN
        assert analysis.status.is_removable_category is True
        assert analysis.removal_impact.removal_safe is True
        assert analysis.removal_impact.impact_level == "safe"
        assert "Safe to remove" in analysis.removal_impact.summary
        assert "2 packages" in analysis.removal_impact.summary
        assert "unused" in analysis.action_guidance.lower()

    def test_build_only_package_analysis(self):
        """Test analysis for a build-only package"""
        build_tool = make_node(1, "cmake", package_type="tool")

        impact = RemovalImpact(
            target=build_tool,
            essentiality=EssentialityStatus.BUILD_ONLY,
            affected_packages=[],
            unique_deps_removed=[],
            closure_reduction=1,
            removal_safe=True,
        )

        analysis = EssentialityAnalysis(
            target=build_tool,
            status=EssentialityStatus.BUILD_ONLY,
            removal_impact=impact,
            runtime_dependents=0,
            build_dependents=5,
            path_depth_avg=2.0,
            path_depth_max=3,
            is_direct_dependency=False,
            top_dependent_summary="No runtime dependents",
        )

        assert analysis.status == EssentialityStatus.BUILD_ONLY
        assert analysis.status.display_name == "Build Only"
        assert analysis.build_dependents == 5
        assert analysis.runtime_dependents == 0
        assert "build-only dependencies" in analysis.dependency_type_summary
        assert "build time" in analysis.action_guidance.lower()
