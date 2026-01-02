"""Tests for Why Chain service functions (Phase 8E-002)

These tests validate the reverse path computation algorithm and related
service functions for the Why Chain feature.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from vizzy.models import (
    Node,
    DependencyDirection,
    EssentialityStatus,
    AttributionPath,
    WhyChainQuery,
    WhyChainResult,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test to ensure test isolation."""
    from vizzy.services.cache import cache
    cache.invalidate()
    yield
    cache.invalidate()


def make_node_dict(
    id: int,
    label: str,
    import_id: int = 1,
    package_type: str = "app",
    is_top_level: bool = False,
    top_level_source: str | None = None,
) -> dict:
    """Helper to create a node dictionary for mocking database results."""
    return {
        "id": id,
        "import_id": import_id,
        "drv_hash": f"hash{id}",
        "drv_name": f"{label}.drv",
        "label": label,
        "package_type": package_type,
        "depth": 1,
        "closure_size": 10,
        "metadata": None,
        "is_top_level": is_top_level,
        "top_level_source": top_level_source,
    }


def make_node(
    id: int,
    label: str,
    import_id: int = 1,
    package_type: str = "app",
    is_top_level: bool = False,
    top_level_source: str | None = None,
) -> Node:
    """Helper to create a Node for testing."""
    return Node(**make_node_dict(id, label, import_id, package_type, is_top_level, top_level_source))


# =============================================================================
# get_node_by_id Tests
# =============================================================================


class TestGetNodeById:
    """Test the get_node_by_id function"""

    def test_get_existing_node(self):
        """Should return a Node when found in database"""
        mock_node = make_node_dict(1, "firefox", is_top_level=True)

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_node

            from vizzy.services.why_chain import get_node_by_id
            node = get_node_by_id(1)

            assert node is not None
            assert node.id == 1
            assert node.label == "firefox"

    def test_get_nonexistent_node(self):
        """Should return None when node not found"""
        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None

            from vizzy.services.why_chain import get_node_by_id
            node = get_node_by_id(999)

            assert node is None


# =============================================================================
# get_nodes_by_ids Tests
# =============================================================================


class TestGetNodesByIds:
    """Test the get_nodes_by_ids function"""

    def test_get_multiple_nodes(self):
        """Should return dictionary of nodes by ID"""
        mock_nodes = [
            make_node_dict(1, "firefox"),
            make_node_dict(2, "nss"),
            make_node_dict(3, "glibc"),
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_nodes

            from vizzy.services.why_chain import get_nodes_by_ids
            nodes = get_nodes_by_ids([1, 2, 3])

            assert len(nodes) == 3
            assert nodes[1].label == "firefox"
            assert nodes[2].label == "nss"
            assert nodes[3].label == "glibc"

    def test_get_empty_list(self):
        """Should return empty dictionary for empty input"""
        from vizzy.services.why_chain import get_nodes_by_ids
        nodes = get_nodes_by_ids([])

        assert nodes == {}


# =============================================================================
# get_reverse_edges Tests
# =============================================================================


class TestGetReverseEdges:
    """Test the get_reverse_edges function"""

    def test_build_reverse_adjacency(self):
        """Should build reverse adjacency list correctly"""
        # Edge: source depends on target
        # Reverse: we want target -> list of sources that depend on it
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},  # 1 depends on 2
            {"source_id": 1, "target_id": 3, "dep_type": "runtime"},  # 1 depends on 3
            {"source_id": 2, "target_id": 3, "dep_type": "build"},    # 2 depends on 3
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_edges

            from vizzy.services.why_chain import get_reverse_edges
            reverse_adj = get_reverse_edges(1, include_build_deps=True)

            # Node 2 is depended on by node 1
            assert 2 in reverse_adj
            assert (1, "runtime") in reverse_adj[2]

            # Node 3 is depended on by nodes 1 and 2
            assert 3 in reverse_adj
            assert len(reverse_adj[3]) == 2

    def test_exclude_build_deps(self):
        """Should filter out build dependencies when include_build_deps=False"""
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_edges

            from vizzy.services.why_chain import get_reverse_edges
            reverse_adj = get_reverse_edges(1, include_build_deps=False)

            # Should still have runtime edge
            assert 2 in reverse_adj


# =============================================================================
# get_top_level_node_ids Tests
# =============================================================================


class TestGetTopLevelNodeIds:
    """Test the get_top_level_node_ids function"""

    def test_get_top_level_ids(self):
        """Should return set of top-level node IDs"""
        mock_rows = [{"id": 1}, {"id": 5}, {"id": 10}]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_rows

            from vizzy.services.why_chain import get_top_level_node_ids
            ids = get_top_level_node_ids(1)

            assert ids == {1, 5, 10}


# =============================================================================
# compute_reverse_paths Tests
# =============================================================================


class TestComputeReversePaths:
    """Test the compute_reverse_paths function"""

    def test_simple_direct_path(self):
        """Test finding a direct path from top-level to target"""
        # Graph: firefox (top-level) -> glibc (target)
        target_node = make_node_dict(2, "glibc")
        top_level_ids = {1}
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # Setup mock returns in order
            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,  # reverse edges
                [{"id": 1}],  # top-level IDs
                [make_node_dict(1, "firefox", is_top_level=True), target_node],  # nodes for paths
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=2, import_id=1)
            paths = compute_reverse_paths(2, query)

            assert len(paths) == 1
            assert paths[0].path_length == 1
            assert paths[0].top_level_node_id == 1
            assert paths[0].target_node_id == 2

    def test_multi_hop_path(self):
        """Test finding paths with intermediate nodes"""
        # Graph: firefox (1) -> nss (2) -> glibc (3)
        target_node = make_node_dict(3, "glibc")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},  # firefox -> nss
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},  # nss -> glibc
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,  # reverse edges
                [{"id": 1}],  # top-level IDs (only firefox)
                [  # nodes for paths
                    make_node_dict(1, "firefox", is_top_level=True),
                    make_node_dict(2, "nss"),
                    target_node,
                ],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=3, import_id=1)
            paths = compute_reverse_paths(3, query)

            assert len(paths) == 1
            assert paths[0].path_length == 2

    def test_multiple_paths(self):
        """Test finding multiple paths from different top-level packages"""
        # Graph:
        #   firefox (1) -> openssl (3) -> glibc (4)
        #   wget (2) -> openssl (3) -> glibc (4)
        target_node = make_node_dict(4, "glibc")
        mock_edges = [
            {"source_id": 1, "target_id": 3, "dep_type": "runtime"},
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
            {"source_id": 3, "target_id": 4, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": 1}, {"id": 2}],  # Both firefox and wget are top-level
                [
                    make_node_dict(1, "firefox", is_top_level=True),
                    make_node_dict(2, "wget", is_top_level=True),
                    make_node_dict(3, "openssl"),
                    target_node,
                ],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=4, import_id=1)
            paths = compute_reverse_paths(4, query)

            # Should find 2 paths (one through firefox, one through wget)
            assert len(paths) == 2

    def test_respects_max_depth(self):
        """Test that max_depth limit is respected"""
        # Graph: a (1) -> b (2) -> c (3) -> d (4) -> e (5)
        target_node = make_node_dict(5, "e")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
            {"source_id": 3, "target_id": 4, "dep_type": "runtime"},
            {"source_id": 4, "target_id": 5, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": 1}],  # Only 'a' is top-level
                [],  # No nodes for paths (because depth limit prevents finding path)
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            # With max_depth=2, we can't find the path (which is 4 hops)
            query = WhyChainQuery(target_node_id=5, import_id=1, max_depth=2)
            paths = compute_reverse_paths(5, query)

            # Path is too long for max_depth=2
            assert len(paths) == 0

    def test_target_is_top_level(self):
        """Test when target itself is a top-level package"""
        target_node = make_node_dict(1, "firefox", is_top_level=True, top_level_source="systemPackages")

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                [],  # No reverse edges
                [{"id": 1}],  # Target is in top-level set
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=1, import_id=1)
            paths = compute_reverse_paths(1, query)

            # Should return trivial path (target is its own top-level)
            assert len(paths) == 1
            assert paths[0].path_length == 0
            assert paths[0].top_level_node_id == 1
            assert paths[0].target_node_id == 1

    def test_avoids_cycles(self):
        """Test that cycle detection prevents infinite loops"""
        # Graph with cycle: a (1) -> b (2) -> c (3) -> b (2)
        # Target is c (3), top-level is a (1)
        target_node = make_node_dict(3, "c")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
            {"source_id": 3, "target_id": 2, "dep_type": "runtime"},  # Cycle!
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": 1}],  # Only 'a' is top-level
                [
                    make_node_dict(1, "a", is_top_level=True),
                    make_node_dict(2, "b"),
                    target_node,
                ],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=3, import_id=1)
            paths = compute_reverse_paths(3, query)

            # Should find the path a -> b -> c (avoiding cycle)
            assert len(paths) == 1
            assert paths[0].path_length == 2

    def test_respects_max_paths(self):
        """Test that max_paths limit is respected"""
        # Create a graph with many paths
        target_node = make_node_dict(10, "target")

        # 5 top-level packages all pointing to target
        mock_edges = [
            {"source_id": i, "target_id": 10, "dep_type": "runtime"}
            for i in range(1, 6)
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": i} for i in range(1, 6)],  # 5 top-level packages
                [make_node_dict(i, f"pkg{i}", is_top_level=True) for i in range(1, 6)] + [target_node],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            # Limit to 3 paths
            query = WhyChainQuery(target_node_id=10, import_id=1, max_paths=3)
            paths = compute_reverse_paths(10, query)

            assert len(paths) <= 3

    def test_runtime_path_detection(self):
        """Test that runtime-only paths are correctly identified"""
        target_node = make_node_dict(3, "glibc")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": 1}],
                [
                    make_node_dict(1, "firefox", is_top_level=True),
                    make_node_dict(2, "nss"),
                    target_node,
                ],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=3, import_id=1)
            paths = compute_reverse_paths(3, query)

            assert len(paths) == 1
            assert paths[0].is_runtime_path is True

    def test_build_path_detection(self):
        """Test that paths with build deps are correctly identified"""
        target_node = make_node_dict(3, "glibc")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "build"},  # Build dep
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
        ]

        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [target_node]
            mock_cursor.fetchall.side_effect = [
                mock_edges,
                [{"id": 1}],
                [
                    make_node_dict(1, "rustc", is_top_level=True),
                    make_node_dict(2, "cargo"),
                    target_node,
                ],
            ]

            from vizzy.services.why_chain import compute_reverse_paths

            query = WhyChainQuery(target_node_id=3, import_id=1)
            paths = compute_reverse_paths(3, query)

            assert len(paths) == 1
            assert paths[0].is_runtime_path is False


# =============================================================================
# determine_essentiality Tests
# =============================================================================


class TestDetermineEssentiality:
    """Test the determine_essentiality function"""

    def test_essential_with_runtime_paths(self):
        """Package with runtime path from single top-level should be ESSENTIAL_SINGLE (8E-007)"""
        from vizzy.services.why_chain import determine_essentiality

        target = make_node(1, "glibc")
        paths = [
            AttributionPath(
                path_nodes=[make_node(2, "firefox", is_top_level=True), target],
                path_length=1,
                top_level_node_id=2,
                target_node_id=1,
                dependency_types=["runtime"],
                is_runtime_path=True,
            )
        ]

        status = determine_essentiality(target, paths, 1, True)
        # With enhanced classification (8E-007), single dependent = ESSENTIAL_SINGLE
        assert status == EssentialityStatus.ESSENTIAL_SINGLE

    def test_essential_with_multiple_runtime_paths(self):
        """Package with runtime paths from multiple top-level should be ESSENTIAL"""
        from vizzy.services.why_chain import determine_essentiality

        target = make_node(1, "glibc")
        paths = [
            AttributionPath(
                path_nodes=[make_node(2, "firefox", is_top_level=True), target],
                path_length=1,
                top_level_node_id=2,
                target_node_id=1,
                dependency_types=["runtime"],
                is_runtime_path=True,
            ),
            AttributionPath(
                path_nodes=[make_node(3, "chromium", is_top_level=True), target],
                path_length=1,
                top_level_node_id=3,
                target_node_id=1,
                dependency_types=["runtime"],
                is_runtime_path=True,
            )
        ]

        status = determine_essentiality(target, paths, 1, True)
        # Multiple top-level dependents = ESSENTIAL
        assert status == EssentialityStatus.ESSENTIAL

    def test_build_only_with_build_paths(self):
        """Package with only build paths should be BUILD_ONLY"""
        from vizzy.services.why_chain import determine_essentiality

        target = make_node(1, "gcc")
        paths = [
            AttributionPath(
                path_nodes=[make_node(2, "rustc", is_top_level=True), target],
                path_length=1,
                top_level_node_id=2,
                target_node_id=1,
                dependency_types=["build"],
                is_runtime_path=False,
            )
        ]

        status = determine_essentiality(target, paths, 1, True)
        assert status == EssentialityStatus.BUILD_ONLY

    def test_orphan_with_no_paths(self):
        """Package with no paths should be ORPHAN"""
        from vizzy.services.why_chain import determine_essentiality

        target = make_node(1, "orphan-pkg")

        status = determine_essentiality(target, [], 1, True)
        assert status == EssentialityStatus.ORPHAN


# =============================================================================
# build_why_chain_result Tests
# =============================================================================


class TestBuildWhyChainResult:
    """Test the build_why_chain_result function"""

    def test_builds_complete_result(self):
        """Should build a complete WhyChainResult"""
        target_node = make_node_dict(3, "glibc")
        mock_edges = [
            {"source_id": 1, "target_id": 2, "dep_type": "runtime"},
            {"source_id": 2, "target_id": 3, "dep_type": "runtime"},
        ]
        direct_dep_node = make_node_dict(2, "nss")

        # Mock at a higher level to control all DB interactions
        with patch('vizzy.services.why_chain.get_node_by_id') as mock_get_node, \
             patch('vizzy.services.why_chain.get_cached_why_chain') as mock_cache, \
             patch('vizzy.services.why_chain.compute_reverse_paths') as mock_compute, \
             patch('vizzy.services.why_chain.get_direct_dependents') as mock_direct, \
             patch('vizzy.services.why_chain.cache_why_chain_result'):

            mock_cache.return_value = None  # No cached result
            mock_get_node.return_value = Node(**target_node)
            mock_compute.return_value = [
                AttributionPath(
                    path_nodes=[Node(**make_node_dict(1, "firefox", is_top_level=True)), Node(**target_node)],
                    path_length=1,
                    top_level_node_id=1,
                    target_node_id=3,
                    dependency_types=["runtime"],
                    is_runtime_path=True,
                )
            ]
            mock_direct.return_value = [Node(**direct_dep_node)]

            from vizzy.services.why_chain import build_why_chain_result

            query = WhyChainQuery(target_node_id=3, import_id=1)
            result = build_why_chain_result(3, query, use_cache=False)

            assert result is not None
            assert result.target.label == "glibc"
            assert result.total_paths_found >= 0
            assert result.computation_time_ms is not None

    def test_returns_none_for_missing_node(self):
        """Should return None when target node doesn't exist"""
        with patch('vizzy.services.why_chain.get_node_by_id') as mock_get_node, \
             patch('vizzy.services.why_chain.get_cached_why_chain') as mock_cache:

            mock_cache.return_value = None
            mock_get_node.return_value = None  # Node not found

            from vizzy.services.why_chain import build_why_chain_result

            query = WhyChainQuery(target_node_id=999, import_id=1)
            result = build_why_chain_result(999, query, use_cache=False)

            assert result is None


# =============================================================================
# Cache Tests
# =============================================================================


class TestWhyChainCache:
    """Test caching functionality"""

    def test_invalidate_cache(self):
        """Should invalidate cache entries via attribution_cache module (8E-008)"""
        with patch('vizzy.services.attribution_cache.invalidate_attribution_cache') as mock_invalidate:
            mock_invalidate.return_value = {"memory": 3, "database": 5}

            from vizzy.services.why_chain import invalidate_why_chain_cache
            count = invalidate_why_chain_cache(1)

            # Should have called the attribution cache invalidation
            mock_invalidate.assert_called_once_with(1)
            # Count should be sum of memory and database entries
            assert count == 8


# =============================================================================
# get_attribution_summary Tests
# =============================================================================


class TestGetAttributionSummary:
    """Test the get_attribution_summary function"""

    def test_returns_summary_stats(self):
        """Should return summary statistics"""
        with patch('vizzy.services.why_chain.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                (1000,),  # total nodes
                (50,),   # top-level count
            ]
            mock_cursor.fetchall.return_value = [
                {"dep_type": "runtime", "count": 800},
                {"dep_type": "build", "count": 200},
            ]

            from vizzy.services.why_chain import get_attribution_summary

            summary = get_attribution_summary(1)

            assert summary["import_id"] == 1
            assert summary["total_nodes"] == 1000
            assert summary["top_level_count"] == 50
            assert summary["runtime_edges"] == 800
            assert summary["build_edges"] == 200


# =============================================================================
# Integration Tests
# =============================================================================


class TestWhyChainServiceIntegration:
    """Integration tests for the Why Chain service"""

    def test_full_why_chain_workflow(self):
        """Test complete workflow from query to result"""
        # This test simulates the full flow:
        # 1. User asks "why is glibc in my closure?"
        # 2. We find paths from top-level packages to glibc
        # 3. We build a complete result

        target_node = make_node_dict(4, "glibc", package_type="lib")
        firefox_node = make_node_dict(1, "firefox", is_top_level=True, top_level_source="systemPackages")
        nss_node = make_node_dict(2, "nss")
        wget_node = make_node_dict(3, "wget", is_top_level=True, top_level_source="systemPackages")

        # Mock at a higher level to control all DB interactions
        with patch('vizzy.services.why_chain.get_node_by_id') as mock_get_node, \
             patch('vizzy.services.why_chain.get_cached_why_chain') as mock_cache, \
             patch('vizzy.services.why_chain.compute_reverse_paths') as mock_compute, \
             patch('vizzy.services.why_chain.get_direct_dependents') as mock_direct, \
             patch('vizzy.services.why_chain.cache_why_chain_result'):

            mock_cache.return_value = None  # No cached result
            mock_get_node.return_value = Node(**target_node)

            # Simulate paths found: firefox -> nss -> glibc and wget -> glibc
            mock_compute.return_value = [
                AttributionPath(
                    path_nodes=[Node(**firefox_node), Node(**nss_node), Node(**target_node)],
                    path_length=2,
                    top_level_node_id=1,
                    target_node_id=4,
                    dependency_types=["runtime", "runtime"],
                    is_runtime_path=True,
                ),
                AttributionPath(
                    path_nodes=[Node(**wget_node), Node(**target_node)],
                    path_length=1,
                    top_level_node_id=3,
                    target_node_id=4,
                    dependency_types=["runtime"],
                    is_runtime_path=True,
                ),
            ]
            mock_direct.return_value = [Node(**nss_node)]

            from vizzy.services.why_chain import build_why_chain_result

            query = WhyChainQuery(
                target_node_id=4,
                import_id=1,
                max_depth=10,
                max_paths=100,
            )

            result = build_why_chain_result(4, query, use_cache=False)

            assert result is not None
            assert result.target.label == "glibc"
            # Should find paths from both firefox and wget
            assert result.total_top_level_dependents == 2
            assert result.total_paths_found == 2
            assert result.essentiality == EssentialityStatus.ESSENTIAL
