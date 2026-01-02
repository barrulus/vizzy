"""Tests for import comparison functionality (Phase 5)"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from vizzy.models import (
    DiffType,
    ImportInfo,
    Node,
    NodeDiff,
    ImportComparison,
    ClosureComparison,
)
from vizzy.services.comparison import (
    classify_diff,
    compare_imports,
    compare_with_duplicates,
    get_closure_comparison,
    match_nodes,
    generate_diff_summary,
)
from vizzy.routes.compare import (
    categorize_diff,
    categorize_diffs,
    score_diff_importance,
    sort_diffs_by_importance,
    DiffCategory,
    compare_package_traces,
)
from vizzy.services.comparison import (
    get_category_summaries,
    get_top_changes,
    generate_category_summary_text,
    generate_enhanced_diff_summary,
    CategorySummary,
    DiffCategory as ServiceDiffCategory,
)


class TestClassifyDiff:
    """Test the classify_diff helper function"""

    def test_both_hashes_same(self):
        """When both hashes are present and equal, should be SAME"""
        result = classify_diff("abc123", "abc123")
        assert result == DiffType.SAME

    def test_both_hashes_different(self):
        """When both hashes are present but different, should be DIFFERENT_HASH"""
        result = classify_diff("abc123", "xyz789")
        assert result == DiffType.DIFFERENT_HASH

    def test_only_left_hash(self):
        """When only left hash is present, should be ONLY_LEFT"""
        result = classify_diff("abc123", None)
        assert result == DiffType.ONLY_LEFT

    def test_only_right_hash(self):
        """When only right hash is present, should be ONLY_RIGHT"""
        result = classify_diff(None, "xyz789")
        assert result == DiffType.ONLY_RIGHT

    def test_neither_hash(self):
        """When neither hash is present, should be ONLY_RIGHT (edge case)"""
        # This shouldn't happen in practice, but the logic defaults to ONLY_RIGHT
        result = classify_diff(None, None)
        assert result == DiffType.ONLY_RIGHT


class TestNodeDiff:
    """Test NodeDiff model functionality"""

    def test_closure_impact_addition(self):
        """Closure impact should be positive when right has larger closure"""
        left_node = Node(
            id=1, import_id=1, drv_hash="a", drv_name="a.drv",
            label="pkg", package_type="app", depth=0, closure_size=100, metadata=None
        )
        right_node = Node(
            id=2, import_id=2, drv_hash="b", drv_name="b.drv",
            label="pkg", package_type="app", depth=0, closure_size=150, metadata=None
        )
        diff = NodeDiff(
            label="pkg",
            package_type="app",
            left_node=left_node,
            right_node=right_node,
            diff_type=DiffType.DIFFERENT_HASH,
        )
        assert diff.closure_impact == 50

    def test_closure_impact_removal(self):
        """Closure impact should be negative when left has larger closure"""
        left_node = Node(
            id=1, import_id=1, drv_hash="a", drv_name="a.drv",
            label="pkg", package_type="app", depth=0, closure_size=200, metadata=None
        )
        right_node = Node(
            id=2, import_id=2, drv_hash="b", drv_name="b.drv",
            label="pkg", package_type="app", depth=0, closure_size=100, metadata=None
        )
        diff = NodeDiff(
            label="pkg",
            package_type="app",
            left_node=left_node,
            right_node=right_node,
            diff_type=DiffType.DIFFERENT_HASH,
        )
        assert diff.closure_impact == -100

    def test_closure_impact_only_left(self):
        """Closure impact should be negative when node only exists in left"""
        left_node = Node(
            id=1, import_id=1, drv_hash="a", drv_name="a.drv",
            label="pkg", package_type="app", depth=0, closure_size=100, metadata=None
        )
        diff = NodeDiff(
            label="pkg",
            package_type="app",
            left_node=left_node,
            right_node=None,
            diff_type=DiffType.ONLY_LEFT,
        )
        assert diff.closure_impact == -100

    def test_closure_impact_only_right(self):
        """Closure impact should be positive when node only exists in right"""
        right_node = Node(
            id=2, import_id=2, drv_hash="b", drv_name="b.drv",
            label="pkg", package_type="app", depth=0, closure_size=150, metadata=None
        )
        diff = NodeDiff(
            label="pkg",
            package_type="app",
            left_node=None,
            right_node=right_node,
            diff_type=DiffType.ONLY_RIGHT,
        )
        assert diff.closure_impact == 150


class TestImportComparison:
    """Test ImportComparison model functionality"""

    def _create_sample_comparison(self) -> ImportComparison:
        """Create a sample comparison for testing"""
        left_import = ImportInfo(
            id=1, name="host1", config_path="/etc/nixos",
            drv_path="/nix/store/abc", imported_at=datetime.now(),
            node_count=100, edge_count=200
        )
        right_import = ImportInfo(
            id=2, name="host2", config_path="/etc/nixos",
            drv_path="/nix/store/xyz", imported_at=datetime.now(),
            node_count=120, edge_count=240
        )

        diffs = [
            NodeDiff(label="pkg1", package_type="app", diff_type=DiffType.ONLY_LEFT,
                     left_node=Node(id=1, import_id=1, drv_hash="a", drv_name="a.drv",
                                   label="pkg1", package_type="app", depth=0,
                                   closure_size=10, metadata=None)),
            NodeDiff(label="pkg2", package_type="app", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=2, import_id=2, drv_hash="b", drv_name="b.drv",
                                    label="pkg2", package_type="app", depth=0,
                                    closure_size=20, metadata=None)),
            NodeDiff(label="pkg3", package_type="lib", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=3, import_id=2, drv_hash="c", drv_name="c.drv",
                                    label="pkg3", package_type="lib", depth=1,
                                    closure_size=30, metadata=None)),
            NodeDiff(label="pkg4", package_type="lib", diff_type=DiffType.SAME,
                     left_node=Node(id=4, import_id=1, drv_hash="d", drv_name="d.drv",
                                   label="pkg4", package_type="lib", depth=1,
                                   closure_size=40, metadata=None),
                     right_node=Node(id=5, import_id=2, drv_hash="d", drv_name="d.drv",
                                    label="pkg4", package_type="lib", depth=1,
                                    closure_size=40, metadata=None)),
            NodeDiff(label="pkg5", package_type="service", diff_type=DiffType.DIFFERENT_HASH,
                     left_node=Node(id=6, import_id=1, drv_hash="e", drv_name="e.drv",
                                   label="pkg5", package_type="service", depth=0,
                                   closure_size=50, metadata=None),
                     right_node=Node(id=7, import_id=2, drv_hash="f", drv_name="f.drv",
                                    label="pkg5", package_type="service", depth=0,
                                    closure_size=60, metadata=None)),
        ]

        return ImportComparison(
            left_import=left_import,
            right_import=right_import,
            left_only_count=1,
            right_only_count=2,
            different_count=1,
            same_count=1,
            all_diffs=diffs,
        )

    def test_total_nodes_compared(self):
        """Total should be sum of all diff categories"""
        comparison = self._create_sample_comparison()
        assert comparison.total_nodes_compared == 5  # 1 + 2 + 1 + 1

    def test_net_package_change(self):
        """Net change should be right_only - left_only"""
        comparison = self._create_sample_comparison()
        assert comparison.net_package_change == 1  # 2 - 1

    def test_get_diffs_by_type_only_left(self):
        """Should filter correctly by diff type"""
        comparison = self._create_sample_comparison()
        only_left = comparison.get_diffs_by_type(DiffType.ONLY_LEFT)
        assert len(only_left) == 1
        assert only_left[0].label == "pkg1"

    def test_get_diffs_by_type_only_right(self):
        """Should filter correctly by diff type"""
        comparison = self._create_sample_comparison()
        only_right = comparison.get_diffs_by_type(DiffType.ONLY_RIGHT)
        assert len(only_right) == 2
        labels = {d.label for d in only_right}
        assert labels == {"pkg2", "pkg3"}

    def test_get_diffs_by_package_type(self):
        """Should filter correctly by package type"""
        comparison = self._create_sample_comparison()
        libs = comparison.get_diffs_by_package_type("lib")
        assert len(libs) == 2
        labels = {d.label for d in libs}
        assert labels == {"pkg3", "pkg4"}


class TestCompareImports:
    """Test the compare_imports function"""

    def _mock_import_info(self, id: int, name: str) -> dict:
        """Create mock import info for database returns"""
        return {
            "id": id,
            "name": name,
            "config_path": "/etc/nixos",
            "drv_path": f"/nix/store/{name}",
            "imported_at": datetime.now(),
            "node_count": 100,
            "edge_count": 200,
        }

    def test_compare_identical_imports(self):
        """Compare two imports with identical nodes"""
        mock_left_import = self._mock_import_info(1, "host1")
        mock_right_import = self._mock_import_info(2, "host2")

        mock_rows = [
            {
                "label": "pkg1",
                "left_id": 1, "left_import_id": 1, "left_hash": "abc",
                "left_name": "pkg1.drv", "left_type": "app",
                "left_depth": 0, "left_closure": 100, "left_metadata": None,
                "right_id": 2, "right_import_id": 2, "right_hash": "abc",
                "right_name": "pkg1.drv", "right_type": "app",
                "right_depth": 0, "right_closure": 100, "right_metadata": None,
            },
        ]

        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            with patch('vizzy.services.comparison.get_db') as mock_get_db:
                mock_get_import.side_effect = [
                    ImportInfo(**mock_left_import),
                    ImportInfo(**mock_right_import),
                ]

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_rows

                comparison = compare_imports(1, 2)

                assert comparison.left_only_count == 0
                assert comparison.right_only_count == 0
                assert comparison.different_count == 0
                assert comparison.same_count == 1
                assert len(comparison.all_diffs) == 1
                assert comparison.all_diffs[0].diff_type == DiffType.SAME

    def test_compare_with_only_left(self):
        """Compare when a node exists only in left import"""
        mock_left_import = self._mock_import_info(1, "host1")
        mock_right_import = self._mock_import_info(2, "host2")

        mock_rows = [
            {
                "label": "pkg1",
                "left_id": 1, "left_import_id": 1, "left_hash": "abc",
                "left_name": "pkg1.drv", "left_type": "app",
                "left_depth": 0, "left_closure": 100, "left_metadata": None,
                "right_id": None, "right_import_id": None, "right_hash": None,
                "right_name": None, "right_type": None,
                "right_depth": None, "right_closure": None, "right_metadata": None,
            },
        ]

        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            with patch('vizzy.services.comparison.get_db') as mock_get_db:
                mock_get_import.side_effect = [
                    ImportInfo(**mock_left_import),
                    ImportInfo(**mock_right_import),
                ]

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_rows

                comparison = compare_imports(1, 2)

                assert comparison.left_only_count == 1
                assert comparison.right_only_count == 0
                assert len(comparison.all_diffs) == 1
                assert comparison.all_diffs[0].diff_type == DiffType.ONLY_LEFT
                assert comparison.all_diffs[0].left_node is not None
                assert comparison.all_diffs[0].right_node is None

    def test_compare_with_only_right(self):
        """Compare when a node exists only in right import"""
        mock_left_import = self._mock_import_info(1, "host1")
        mock_right_import = self._mock_import_info(2, "host2")

        mock_rows = [
            {
                "label": "pkg2",
                "left_id": None, "left_import_id": None, "left_hash": None,
                "left_name": None, "left_type": None,
                "left_depth": None, "left_closure": None, "left_metadata": None,
                "right_id": 2, "right_import_id": 2, "right_hash": "xyz",
                "right_name": "pkg2.drv", "right_type": "lib",
                "right_depth": 1, "right_closure": 50, "right_metadata": None,
            },
        ]

        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            with patch('vizzy.services.comparison.get_db') as mock_get_db:
                mock_get_import.side_effect = [
                    ImportInfo(**mock_left_import),
                    ImportInfo(**mock_right_import),
                ]

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_rows

                comparison = compare_imports(1, 2)

                assert comparison.left_only_count == 0
                assert comparison.right_only_count == 1
                assert len(comparison.all_diffs) == 1
                assert comparison.all_diffs[0].diff_type == DiffType.ONLY_RIGHT
                assert comparison.all_diffs[0].left_node is None
                assert comparison.all_diffs[0].right_node is not None

    def test_compare_with_different_hash(self):
        """Compare when same label has different hashes"""
        mock_left_import = self._mock_import_info(1, "host1")
        mock_right_import = self._mock_import_info(2, "host2")

        mock_rows = [
            {
                "label": "pkg1",
                "left_id": 1, "left_import_id": 1, "left_hash": "abc",
                "left_name": "pkg1.drv", "left_type": "app",
                "left_depth": 0, "left_closure": 100, "left_metadata": None,
                "right_id": 2, "right_import_id": 2, "right_hash": "xyz",
                "right_name": "pkg1.drv", "right_type": "app",
                "right_depth": 0, "right_closure": 120, "right_metadata": None,
            },
        ]

        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            with patch('vizzy.services.comparison.get_db') as mock_get_db:
                mock_get_import.side_effect = [
                    ImportInfo(**mock_left_import),
                    ImportInfo(**mock_right_import),
                ]

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_rows

                comparison = compare_imports(1, 2)

                assert comparison.left_only_count == 0
                assert comparison.right_only_count == 0
                assert comparison.different_count == 1
                assert comparison.same_count == 0
                assert len(comparison.all_diffs) == 1
                assert comparison.all_diffs[0].diff_type == DiffType.DIFFERENT_HASH
                assert comparison.all_diffs[0].left_node is not None
                assert comparison.all_diffs[0].right_node is not None

    def test_compare_mixed_diffs(self):
        """Compare with a mix of diff types"""
        mock_left_import = self._mock_import_info(1, "host1")
        mock_right_import = self._mock_import_info(2, "host2")

        mock_rows = [
            # Same node
            {
                "label": "common",
                "left_id": 1, "left_import_id": 1, "left_hash": "abc",
                "left_name": "common.drv", "left_type": "lib",
                "left_depth": 0, "left_closure": 50, "left_metadata": None,
                "right_id": 2, "right_import_id": 2, "right_hash": "abc",
                "right_name": "common.drv", "right_type": "lib",
                "right_depth": 0, "right_closure": 50, "right_metadata": None,
            },
            # Only left
            {
                "label": "left-only",
                "left_id": 3, "left_import_id": 1, "left_hash": "def",
                "left_name": "left-only.drv", "left_type": "app",
                "left_depth": 1, "left_closure": 100, "left_metadata": None,
                "right_id": None, "right_import_id": None, "right_hash": None,
                "right_name": None, "right_type": None,
                "right_depth": None, "right_closure": None, "right_metadata": None,
            },
            # Only right
            {
                "label": "right-only",
                "left_id": None, "left_import_id": None, "left_hash": None,
                "left_name": None, "left_type": None,
                "left_depth": None, "left_closure": None, "left_metadata": None,
                "right_id": 4, "right_import_id": 2, "right_hash": "ghi",
                "right_name": "right-only.drv", "right_type": "service",
                "right_depth": 0, "right_closure": 75, "right_metadata": None,
            },
            # Different hash
            {
                "label": "changed",
                "left_id": 5, "left_import_id": 1, "left_hash": "jkl",
                "left_name": "changed.drv", "left_type": "app",
                "left_depth": 0, "left_closure": 200, "left_metadata": None,
                "right_id": 6, "right_import_id": 2, "right_hash": "mno",
                "right_name": "changed.drv", "right_type": "app",
                "right_depth": 0, "right_closure": 250, "right_metadata": None,
            },
        ]

        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            with patch('vizzy.services.comparison.get_db') as mock_get_db:
                mock_get_import.side_effect = [
                    ImportInfo(**mock_left_import),
                    ImportInfo(**mock_right_import),
                ]

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_rows

                comparison = compare_imports(1, 2)

                assert comparison.same_count == 1
                assert comparison.left_only_count == 1
                assert comparison.right_only_count == 1
                assert comparison.different_count == 1
                assert comparison.total_nodes_compared == 4
                assert comparison.net_package_change == 0  # 1 - 1

    def test_compare_import_not_found(self):
        """Should raise ValueError when import doesn't exist"""
        with patch('vizzy.services.comparison.graph.get_import') as mock_get_import:
            mock_get_import.return_value = None

            with pytest.raises(ValueError, match="Left import 999 not found"):
                compare_imports(999, 1)


class TestClosureComparison:
    """Test the ClosureComparison model"""

    def test_difference_calculation(self):
        """Difference should be right - left"""
        comparison = ClosureComparison(
            left_total=1000,
            right_total=1500,
            largest_additions=[],
            largest_removals=[],
        )
        assert comparison.difference == 500

    def test_percentage_diff_positive(self):
        """Percentage should be positive when right is larger"""
        comparison = ClosureComparison(
            left_total=1000,
            right_total=1500,
            largest_additions=[],
            largest_removals=[],
        )
        assert comparison.percentage_diff == 50.0

    def test_percentage_diff_negative(self):
        """Percentage should be negative when left is larger"""
        comparison = ClosureComparison(
            left_total=1000,
            right_total=800,
            largest_additions=[],
            largest_removals=[],
        )
        assert comparison.percentage_diff == -20.0

    def test_percentage_diff_zero_left(self):
        """Should handle zero left total gracefully"""
        comparison = ClosureComparison(
            left_total=0,
            right_total=100,
            largest_additions=[],
            largest_removals=[],
        )
        assert comparison.percentage_diff == 100.0

    def test_percentage_diff_both_zero(self):
        """Should handle both zero gracefully"""
        comparison = ClosureComparison(
            left_total=0,
            right_total=0,
            largest_additions=[],
            largest_removals=[],
        )
        assert comparison.percentage_diff == 0.0


class TestMatchNodes:
    """Test the match_nodes utility function"""

    def _make_node(self, id: int, drv_hash: str, label: str, package_type: str = "app") -> Node:
        """Helper to create a Node for testing"""
        return Node(
            id=id, import_id=1, drv_hash=drv_hash, drv_name=f"{label}.drv",
            label=label, package_type=package_type, depth=0, closure_size=100, metadata=None
        )

    def test_match_identical_nodes(self):
        """Nodes with same hash should be SAME"""
        left = [self._make_node(1, "abc", "pkg1")]
        right = [self._make_node(2, "abc", "pkg1")]

        diffs = match_nodes(left, right)

        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.SAME
        assert diffs[0].left_node is not None
        assert diffs[0].right_node is not None

    def test_match_different_hash_same_label(self):
        """Nodes with same label but different hash should be DIFFERENT_HASH"""
        left = [self._make_node(1, "abc", "pkg1")]
        right = [self._make_node(2, "xyz", "pkg1")]

        diffs = match_nodes(left, right)

        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.DIFFERENT_HASH
        assert diffs[0].left_node is not None
        assert diffs[0].right_node is not None

    def test_match_only_left(self):
        """Nodes only in left should be ONLY_LEFT"""
        left = [self._make_node(1, "abc", "pkg1")]
        right = []

        diffs = match_nodes(left, right)

        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.ONLY_LEFT
        assert diffs[0].left_node is not None
        assert diffs[0].right_node is None

    def test_match_only_right(self):
        """Nodes only in right should be ONLY_RIGHT"""
        left = []
        right = [self._make_node(2, "xyz", "pkg1")]

        diffs = match_nodes(left, right)

        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.ONLY_RIGHT
        assert diffs[0].left_node is None
        assert diffs[0].right_node is not None

    def test_match_mixed_nodes(self):
        """Test matching with multiple nodes of different types"""
        left = [
            self._make_node(1, "aaa", "same-pkg"),
            self._make_node(2, "bbb", "different-pkg"),
            self._make_node(3, "ccc", "left-only-pkg"),
        ]
        right = [
            self._make_node(4, "aaa", "same-pkg"),
            self._make_node(5, "ddd", "different-pkg"),
            self._make_node(6, "eee", "right-only-pkg"),
        ]

        diffs = match_nodes(left, right)

        # Check counts by type
        same_count = len([d for d in diffs if d.diff_type == DiffType.SAME])
        different_count = len([d for d in diffs if d.diff_type == DiffType.DIFFERENT_HASH])
        left_only_count = len([d for d in diffs if d.diff_type == DiffType.ONLY_LEFT])
        right_only_count = len([d for d in diffs if d.diff_type == DiffType.ONLY_RIGHT])

        assert same_count == 1
        assert different_count == 1
        assert left_only_count == 1
        assert right_only_count == 1

    def test_match_with_duplicates(self):
        """Test that duplicates in right are handled correctly"""
        left = [
            self._make_node(1, "aaa", "pkg1"),
            self._make_node(2, "bbb", "pkg1"),  # Same label, different hash
        ]
        right = [
            self._make_node(3, "aaa", "pkg1"),
            self._make_node(4, "ccc", "pkg1"),  # Same label, yet another hash
        ]

        diffs = match_nodes(left, right)

        # aaa matches aaa (SAME), bbb matches ccc (DIFFERENT_HASH)
        same_count = len([d for d in diffs if d.diff_type == DiffType.SAME])
        different_count = len([d for d in diffs if d.diff_type == DiffType.DIFFERENT_HASH])

        assert same_count == 1
        assert different_count == 1

    def test_match_empty_lists(self):
        """Empty lists should produce empty result"""
        diffs = match_nodes([], [])
        assert len(diffs) == 0


class TestGenerateDiffSummary:
    """Test the generate_diff_summary function"""

    def _create_comparison(
        self,
        left_name: str,
        right_name: str,
        left_count: int,
        right_count: int,
        left_only: int = 0,
        right_only: int = 0,
        different: int = 0,
    ) -> ImportComparison:
        """Helper to create a comparison for testing"""
        left_import = ImportInfo(
            id=1, name=left_name, config_path="/etc/nixos",
            drv_path="/nix/store/left", imported_at=datetime.now(),
            node_count=left_count, edge_count=0
        )
        right_import = ImportInfo(
            id=2, name=right_name, config_path="/etc/nixos",
            drv_path="/nix/store/right", imported_at=datetime.now(),
            node_count=right_count, edge_count=0
        )
        return ImportComparison(
            left_import=left_import,
            right_import=right_import,
            left_only_count=left_only,
            right_only_count=right_only,
            different_count=different,
            same_count=0,
            all_diffs=[],
        )

    def test_summary_more_packages(self):
        """Summary should describe when right has more packages"""
        comparison = self._create_comparison("host1", "host2", 100, 150, right_only=50)
        summary = generate_diff_summary(comparison)

        assert "host2 has 50 more packages than host1" in summary
        assert "50 packages only in host2" in summary

    def test_summary_fewer_packages(self):
        """Summary should describe when right has fewer packages"""
        comparison = self._create_comparison("host1", "host2", 150, 100, left_only=50)
        summary = generate_diff_summary(comparison)

        assert "host2 has 50 fewer packages than host1" in summary
        assert "50 packages only in host1" in summary

    def test_summary_same_count(self):
        """Summary should describe when counts are equal"""
        comparison = self._create_comparison("host1", "host2", 100, 100)
        summary = generate_diff_summary(comparison)

        assert "host2 and host1 have the same number of packages" in summary

    def test_summary_different_versions(self):
        """Summary should mention different versions"""
        comparison = self._create_comparison("host1", "host2", 100, 100, different=25)
        summary = generate_diff_summary(comparison)

        assert "25 packages have different versions" in summary

    def test_summary_comprehensive(self):
        """Summary should include all relevant information"""
        comparison = self._create_comparison(
            "host1", "host2", 100, 120,
            left_only=10, right_only=30, different=5
        )
        summary = generate_diff_summary(comparison)

        assert "host2 has 20 more packages than host1" in summary
        assert "5 packages have different versions" in summary
        assert "10 packages only in host1" in summary
        assert "30 packages only in host2" in summary


class TestCategorizeDiff:
    """Test the diff categorization functions (Task 5-003)"""

    def test_categorize_desktop_env(self):
        """Desktop environment packages should be categorized correctly"""
        assert categorize_diff("gnome-shell-42", None) == DiffCategory.DESKTOP_ENV
        assert categorize_diff("kde-plasma-5.24", None) == DiffCategory.DESKTOP_ENV
        assert categorize_diff("gtk3-3.24", None) == DiffCategory.DESKTOP_ENV
        assert categorize_diff("wayland-1.20", None) == DiffCategory.DESKTOP_ENV

    def test_categorize_system_services(self):
        """System service packages should be categorized correctly"""
        assert categorize_diff("systemd-253", None) == DiffCategory.SYSTEM_SERVICES
        assert categorize_diff("dbus-1.14", None) == DiffCategory.SYSTEM_SERVICES
        assert categorize_diff("polkit-0.120", None) == DiffCategory.SYSTEM_SERVICES

    def test_categorize_development(self):
        """Development tools should be categorized correctly"""
        assert categorize_diff("gcc-13.2", None) == DiffCategory.DEVELOPMENT
        assert categorize_diff("rustc-1.72", None) == DiffCategory.DEVELOPMENT
        assert categorize_diff("python3-3.11", None) == DiffCategory.DEVELOPMENT
        assert categorize_diff("libfoo-dev", None) == DiffCategory.DEVELOPMENT

    def test_categorize_networking(self):
        """Networking packages should be categorized correctly"""
        assert categorize_diff("openssh-9.4", None) == DiffCategory.NETWORKING
        assert categorize_diff("curl-8.0", None) == DiffCategory.NETWORKING
        assert categorize_diff("openssl-3.1", None) == DiffCategory.NETWORKING

    def test_categorize_multimedia(self):
        """Multimedia packages should be categorized correctly"""
        assert categorize_diff("pipewire-0.3", None) == DiffCategory.MULTIMEDIA
        assert categorize_diff("ffmpeg-6.0", None) == DiffCategory.MULTIMEDIA
        assert categorize_diff("alsa-lib-1.2", None) == DiffCategory.MULTIMEDIA

    def test_categorize_libraries(self):
        """Library packages should be categorized correctly"""
        assert categorize_diff("glibc-2.38", None) == DiffCategory.LIBRARIES
        assert categorize_diff("zlib-1.3", None) == DiffCategory.LIBRARIES
        assert categorize_diff("ncurses-6.4", None) == DiffCategory.LIBRARIES

    def test_categorize_fonts(self):
        """Font packages should be categorized correctly"""
        assert categorize_diff("noto-fonts-24", None) == DiffCategory.FONTS
        assert categorize_diff("dejavu-fonts-2.37", None) == DiffCategory.FONTS
        assert categorize_diff("font-awesome", None) == DiffCategory.FONTS

    def test_categorize_by_package_type(self):
        """Should use package_type when available"""
        assert categorize_diff("some-font", "font") == DiffCategory.FONTS
        assert categorize_diff("mypackage", "python-package") == DiffCategory.PYTHON

    def test_categorize_other(self):
        """Unknown packages should be categorized as OTHER"""
        assert categorize_diff("random-package-1.0", None) == DiffCategory.OTHER
        assert categorize_diff("some-unknown-thing", None) == DiffCategory.OTHER

    def test_categorize_diffs_groups_correctly(self):
        """categorize_diffs should group diffs by category"""
        diffs = [
            NodeDiff(label="gnome-shell", package_type=None, diff_type=DiffType.ONLY_LEFT),
            NodeDiff(label="systemd-253", package_type=None, diff_type=DiffType.ONLY_LEFT),
            NodeDiff(label="unknown-pkg", package_type=None, diff_type=DiffType.ONLY_LEFT),
        ]

        categorized = categorize_diffs(diffs)

        assert DiffCategory.DESKTOP_ENV in categorized
        assert DiffCategory.SYSTEM_SERVICES in categorized
        assert DiffCategory.OTHER in categorized
        assert len(categorized[DiffCategory.DESKTOP_ENV]) == 1
        assert len(categorized[DiffCategory.SYSTEM_SERVICES]) == 1
        assert len(categorized[DiffCategory.OTHER]) == 1


class TestScoreDiffImportance:
    """Test the importance scoring function"""

    def test_score_application_higher(self):
        """Applications should score higher than libraries"""
        app_diff = NodeDiff(
            label="firefox",
            package_type="application",
            diff_type=DiffType.ONLY_RIGHT,
            right_node=Node(
                id=1, import_id=1, drv_hash="a", drv_name="a.drv",
                label="firefox", package_type="application", depth=0,
                closure_size=100, metadata=None
            )
        )
        lib_diff = NodeDiff(
            label="libfoo",
            package_type="library",
            diff_type=DiffType.ONLY_RIGHT,
            right_node=Node(
                id=2, import_id=1, drv_hash="b", drv_name="b.drv",
                label="libfoo", package_type="library", depth=0,
                closure_size=100, metadata=None
            )
        )

        assert score_diff_importance(app_diff) > score_diff_importance(lib_diff)

    def test_score_kernel_highest(self):
        """Kernel packages should score very high"""
        kernel_diff = NodeDiff(
            label="linux-kernel",
            package_type="kernel",
            diff_type=DiffType.ONLY_RIGHT,
            right_node=Node(
                id=1, import_id=1, drv_hash="a", drv_name="a.drv",
                label="linux-kernel", package_type="kernel", depth=0,
                closure_size=100, metadata=None
            )
        )

        assert score_diff_importance(kernel_diff) >= 6

    def test_sort_by_importance(self):
        """sort_diffs_by_importance should order diffs correctly"""
        diffs = [
            NodeDiff(label="libfoo", package_type="library", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=1, import_id=1, drv_hash="a", drv_name="a.drv",
                                    label="libfoo", package_type="library", depth=0,
                                    closure_size=10, metadata=None)),
            NodeDiff(label="linux-kernel", package_type="kernel", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=2, import_id=1, drv_hash="b", drv_name="b.drv",
                                    label="linux-kernel", package_type="kernel", depth=0,
                                    closure_size=1000, metadata=None)),
            NodeDiff(label="firefox", package_type="application", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=3, import_id=1, drv_hash="c", drv_name="c.drv",
                                    label="firefox", package_type="application", depth=0,
                                    closure_size=500, metadata=None)),
        ]

        sorted_diffs = sort_diffs_by_importance(diffs)

        # Kernel should be first (highest score)
        assert sorted_diffs[0].label == "linux-kernel"
        # Library should be last (lowest score)
        assert sorted_diffs[-1].label == "libfoo"


class TestPackageTraceComparison:
    """Test the package trace comparison functionality (Task 5-003)"""

    def test_compare_package_traces_package_not_found(self):
        """When package doesn't exist in either, should return empty result"""
        with patch('vizzy.routes.compare.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None

            result = compare_package_traces(1, 2, "nonexistent-package")

            assert result["package"] == "nonexistent-package"
            assert result["left_node"] is None
            assert result["right_node"] is None
            assert result["left_paths"] == []
            assert result["right_paths"] == []
            assert result["same_hash"] is False
            assert result["in_both"] is False

    def test_compare_package_traces_only_left(self):
        """When package only exists in left, should return left info only"""
        left_node = {
            "id": 1,
            "label": "openssl-3.0",
            "drv_hash": "abc123",
            "package_type": "library"
        }

        with patch('vizzy.routes.compare.get_db') as mock_get_db:
            with patch('vizzy.routes.compare.get_reverse_paths') as mock_paths:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                # First call returns left node, second returns None (not in right)
                mock_cursor.fetchone.side_effect = [left_node, None]
                mock_paths.return_value = [[{"id": 1, "label": "openssl-3.0"}]]

                result = compare_package_traces(1, 2, "openssl-3.0")

                assert result["package"] == "openssl-3.0"
                assert result["left_node"] is not None
                assert result["left_node"]["drv_hash"] == "abc123"
                assert result["right_node"] is None
                assert len(result["left_paths"]) == 1
                assert result["right_paths"] == []
                assert result["in_both"] is False

    def test_compare_package_traces_same_hash(self):
        """When package exists in both with same hash, should indicate same_hash"""
        left_node = {
            "id": 1,
            "label": "openssl-3.0",
            "drv_hash": "abc123",
            "package_type": "library"
        }
        right_node = {
            "id": 2,
            "label": "openssl-3.0",
            "drv_hash": "abc123",  # Same hash
            "package_type": "library"
        }

        with patch('vizzy.routes.compare.get_db') as mock_get_db:
            with patch('vizzy.routes.compare.get_reverse_paths') as mock_paths:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.side_effect = [left_node, right_node]
                mock_paths.return_value = [[{"id": 1, "label": "openssl-3.0"}]]

                result = compare_package_traces(1, 2, "openssl-3.0")

                assert result["in_both"] is True
                assert result["same_hash"] is True

    def test_compare_package_traces_different_hash(self):
        """When package exists in both with different hash, should indicate different"""
        left_node = {
            "id": 1,
            "label": "openssl-3.0",
            "drv_hash": "abc123",
            "package_type": "library"
        }
        right_node = {
            "id": 2,
            "label": "openssl-3.0",
            "drv_hash": "xyz789",  # Different hash
            "package_type": "library"
        }

        with patch('vizzy.routes.compare.get_db') as mock_get_db:
            with patch('vizzy.routes.compare.get_reverse_paths') as mock_paths:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.side_effect = [left_node, right_node]
                mock_paths.return_value = [[{"id": 1, "label": "openssl-3.0"}]]

                result = compare_package_traces(1, 2, "openssl-3.0")

                assert result["in_both"] is True
                assert result["same_hash"] is False


class TestSemanticDiffGrouping:
    """Test the semantic diff grouping functions (Task 8F-001)"""

    def _create_sample_comparison(self) -> ImportComparison:
        """Create a sample comparison for testing semantic grouping"""
        left_import = ImportInfo(
            id=1, name="host1", config_path="/etc/nixos",
            drv_path="/nix/store/abc", imported_at=datetime.now(),
            node_count=100, edge_count=200
        )
        right_import = ImportInfo(
            id=2, name="host2", config_path="/etc/nixos",
            drv_path="/nix/store/xyz", imported_at=datetime.now(),
            node_count=120, edge_count=240
        )

        diffs = [
            # Desktop environment packages (only in left)
            NodeDiff(label="gnome-shell-42", package_type="app", diff_type=DiffType.ONLY_LEFT,
                     left_node=Node(id=1, import_id=1, drv_hash="a", drv_name="a.drv",
                                   label="gnome-shell-42", package_type="app", depth=0,
                                   closure_size=500, metadata=None)),
            # System services (only in right)
            NodeDiff(label="systemd-253", package_type="service", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=2, import_id=2, drv_hash="b", drv_name="b.drv",
                                    label="systemd-253", package_type="service", depth=0,
                                    closure_size=100, metadata=None)),
            NodeDiff(label="dbus-1.14", package_type="service", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=3, import_id=2, drv_hash="c", drv_name="c.drv",
                                    label="dbus-1.14", package_type="service", depth=0,
                                    closure_size=50, metadata=None)),
            # Libraries (different hash)
            NodeDiff(label="glibc-2.38", package_type="lib", diff_type=DiffType.DIFFERENT_HASH,
                     left_node=Node(id=4, import_id=1, drv_hash="d", drv_name="d.drv",
                                   label="glibc-2.38", package_type="lib", depth=0,
                                   closure_size=200, metadata=None),
                     right_node=Node(id=5, import_id=2, drv_hash="e", drv_name="e.drv",
                                    label="glibc-2.38", package_type="lib", depth=0,
                                    closure_size=220, metadata=None)),
            # Fonts (only in right)
            NodeDiff(label="noto-fonts-24", package_type="font", diff_type=DiffType.ONLY_RIGHT,
                     right_node=Node(id=6, import_id=2, drv_hash="f", drv_name="f.drv",
                                    label="noto-fonts-24", package_type="font", depth=0,
                                    closure_size=30, metadata=None)),
            # Same packages (should be counted but not as changes)
            NodeDiff(label="zlib-1.3", package_type="lib", diff_type=DiffType.SAME,
                     left_node=Node(id=7, import_id=1, drv_hash="g", drv_name="g.drv",
                                   label="zlib-1.3", package_type="lib", depth=0,
                                   closure_size=10, metadata=None),
                     right_node=Node(id=8, import_id=2, drv_hash="g", drv_name="g.drv",
                                    label="zlib-1.3", package_type="lib", depth=0,
                                    closure_size=10, metadata=None)),
        ]

        return ImportComparison(
            left_import=left_import,
            right_import=right_import,
            left_only_count=1,
            right_only_count=3,
            different_count=1,
            same_count=1,
            all_diffs=diffs,
        )

    def test_get_category_summaries_returns_summaries(self):
        """get_category_summaries should return list of CategorySummary objects"""
        comparison = self._create_sample_comparison()
        summaries = get_category_summaries(comparison)

        assert len(summaries) > 0
        assert all(isinstance(s, CategorySummary) for s in summaries)

    def test_get_category_summaries_correct_counts(self):
        """Category summaries should have correct counts per category"""
        comparison = self._create_sample_comparison()
        summaries = get_category_summaries(comparison)

        # Find system services category
        system_services = next(
            (s for s in summaries if "System" in s.display_name or "service" in s.category.value.lower()),
            None
        )
        assert system_services is not None
        assert system_services.right_only_count == 2  # systemd and dbus

    def test_get_category_summaries_sorted_by_impact(self):
        """Category summaries should be sorted by absolute net change"""
        comparison = self._create_sample_comparison()
        summaries = get_category_summaries(comparison)

        # Categories with bigger changes should come first
        if len(summaries) >= 2:
            for i in range(len(summaries) - 1):
                assert abs(summaries[i].net_change) >= abs(summaries[i + 1].net_change)

    def test_get_top_changes_returns_most_important(self):
        """get_top_changes should return diffs sorted by importance"""
        comparison = self._create_sample_comparison()
        top_changes = get_top_changes(comparison, limit=5)

        # Should not include SAME diffs
        for diff in top_changes:
            assert diff.diff_type != DiffType.SAME

        # Should be sorted by importance
        if len(top_changes) >= 2:
            # Applications/services should generally rank higher than fonts
            labels = [d.label for d in top_changes]
            # gnome-shell (application) should rank before noto-fonts
            if "gnome-shell-42" in labels and "noto-fonts-24" in labels:
                gnome_idx = labels.index("gnome-shell-42")
                font_idx = labels.index("noto-fonts-24")
                assert gnome_idx < font_idx

    def test_get_top_changes_respects_limit(self):
        """get_top_changes should respect the limit parameter"""
        comparison = self._create_sample_comparison()
        top_changes = get_top_changes(comparison, limit=2)

        assert len(top_changes) <= 2

    def test_generate_category_summary_text_describes_additions(self):
        """generate_category_summary_text should mention additions"""
        comparison = self._create_sample_comparison()
        summaries = get_category_summaries(comparison)
        text = generate_category_summary_text(summaries)

        # Should mention additions since we have right_only packages
        assert "additions" in text.lower() or "+" in text

    def test_generate_category_summary_text_describes_removals(self):
        """generate_category_summary_text should mention removals"""
        comparison = self._create_sample_comparison()
        summaries = get_category_summaries(comparison)
        text = generate_category_summary_text(summaries)

        # Should mention removals since we have left_only packages
        assert "removals" in text.lower() or "-" in text

    def test_generate_enhanced_diff_summary_includes_base_summary(self):
        """Enhanced summary should include base comparison info"""
        comparison = self._create_sample_comparison()
        enhanced = generate_enhanced_diff_summary(comparison)

        # Should include info about which has more packages
        assert "host1" in enhanced or "host2" in enhanced

    def test_generate_enhanced_diff_summary_includes_category_info(self):
        """Enhanced summary should include category breakdown"""
        comparison = self._create_sample_comparison()
        enhanced = generate_enhanced_diff_summary(comparison)

        # Should mention main additions or removals by category
        # The exact text depends on the categorization, but should have some category info
        assert len(enhanced) > len(generate_diff_summary(comparison))

    def test_category_filter_works(self):
        """get_category_summaries should respect diff_type_filter"""
        comparison = self._create_sample_comparison()

        # Only get summaries for ONLY_RIGHT diffs
        summaries = get_category_summaries(comparison, diff_type_filter=DiffType.ONLY_RIGHT)

        # Should only count right_only diffs
        for summary in summaries:
            assert summary.left_only_count == 0
            assert summary.different_count == 0
            assert summary.same_count == 0
