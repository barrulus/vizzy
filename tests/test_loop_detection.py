"""Tests for loop detection (Tarjan's SCC algorithm)"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test to ensure test isolation."""
    from vizzy.services.cache import cache
    cache.invalidate()
    yield
    cache.invalidate()


class TestTarjanAlgorithm:
    """Test the Tarjan's SCC algorithm implementation"""

    def test_find_cycle_in_simple_graph(self):
        """Test cycle detection in a simple A -> B -> A cycle"""
        # Mock the database responses
        mock_nodes = {
            1: {"id": 1, "import_id": 1, "drv_hash": "aaa", "drv_name": "a.drv",
                "label": "a", "package_type": "app", "depth": 0, "closure_size": 0, "metadata": None},
            2: {"id": 2, "import_id": 1, "drv_hash": "bbb", "drv_name": "b.drv",
                "label": "b", "package_type": "app", "depth": 1, "closure_size": 0, "metadata": None},
        }
        mock_edges = [
            {"source_id": 1, "target_id": 2},  # A -> B
            {"source_id": 2, "target_id": 1},  # B -> A (creates cycle)
        ]

        with patch('vizzy.services.analysis.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # Setup mock cursor to return nodes then edges
            mock_cursor.fetchall.side_effect = [
                [mock_nodes[1], mock_nodes[2]],  # nodes query
                mock_edges,  # edges query
            ]

            from vizzy.services.analysis import find_loops
            loops = find_loops(1)

            # Should find one cycle with 2 nodes
            assert len(loops) == 1
            assert loops[0].size == 2

    def test_no_cycles_in_dag(self):
        """Test that no cycles are found in a DAG"""
        mock_nodes = {
            1: {"id": 1, "import_id": 1, "drv_hash": "aaa", "drv_name": "a.drv",
                "label": "a", "package_type": "app", "depth": 0, "closure_size": 0, "metadata": None},
            2: {"id": 2, "import_id": 1, "drv_hash": "bbb", "drv_name": "b.drv",
                "label": "b", "package_type": "app", "depth": 1, "closure_size": 0, "metadata": None},
            3: {"id": 3, "import_id": 1, "drv_hash": "ccc", "drv_name": "c.drv",
                "label": "c", "package_type": "lib", "depth": 2, "closure_size": 0, "metadata": None},
        }
        mock_edges = [
            {"source_id": 1, "target_id": 2},  # A -> B
            {"source_id": 1, "target_id": 3},  # A -> C
            {"source_id": 2, "target_id": 3},  # B -> C
        ]

        with patch('vizzy.services.analysis.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                list(mock_nodes.values()),
                mock_edges,
            ]

            from vizzy.services.analysis import find_loops
            loops = find_loops(1)

            # Should find no cycles
            assert len(loops) == 0

    def test_find_multiple_cycles(self):
        """Test detection of multiple independent cycles"""
        mock_nodes = {
            1: {"id": 1, "import_id": 1, "drv_hash": "aaa", "drv_name": "a.drv",
                "label": "a", "package_type": "app", "depth": 0, "closure_size": 0, "metadata": None},
            2: {"id": 2, "import_id": 1, "drv_hash": "bbb", "drv_name": "b.drv",
                "label": "b", "package_type": "app", "depth": 1, "closure_size": 0, "metadata": None},
            3: {"id": 3, "import_id": 1, "drv_hash": "ccc", "drv_name": "c.drv",
                "label": "c", "package_type": "lib", "depth": 0, "closure_size": 0, "metadata": None},
            4: {"id": 4, "import_id": 1, "drv_hash": "ddd", "drv_name": "d.drv",
                "label": "d", "package_type": "lib", "depth": 1, "closure_size": 0, "metadata": None},
        }
        mock_edges = [
            {"source_id": 1, "target_id": 2},  # A -> B
            {"source_id": 2, "target_id": 1},  # B -> A (cycle 1)
            {"source_id": 3, "target_id": 4},  # C -> D
            {"source_id": 4, "target_id": 3},  # D -> C (cycle 2)
        ]

        with patch('vizzy.services.analysis.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                list(mock_nodes.values()),
                mock_edges,
            ]

            from vizzy.services.analysis import find_loops
            loops = find_loops(1)

            # Should find two cycles
            assert len(loops) == 2

    def test_three_node_cycle(self):
        """Test detection of a 3-node cycle: A -> B -> C -> A"""
        mock_nodes = {
            1: {"id": 1, "import_id": 1, "drv_hash": "aaa", "drv_name": "a.drv",
                "label": "a", "package_type": "app", "depth": 0, "closure_size": 0, "metadata": None},
            2: {"id": 2, "import_id": 1, "drv_hash": "bbb", "drv_name": "b.drv",
                "label": "b", "package_type": "app", "depth": 1, "closure_size": 0, "metadata": None},
            3: {"id": 3, "import_id": 1, "drv_hash": "ccc", "drv_name": "c.drv",
                "label": "c", "package_type": "lib", "depth": 2, "closure_size": 0, "metadata": None},
        }
        mock_edges = [
            {"source_id": 1, "target_id": 2},  # A -> B
            {"source_id": 2, "target_id": 3},  # B -> C
            {"source_id": 3, "target_id": 1},  # C -> A (completes cycle)
        ]

        with patch('vizzy.services.analysis.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                list(mock_nodes.values()),
                mock_edges,
            ]

            from vizzy.services.analysis import find_loops
            loops = find_loops(1)

            # Should find one cycle with 3 nodes
            assert len(loops) == 1
            assert loops[0].size == 3


class TestFindCycleInSCC:
    """Test the helper function for finding cycle path within an SCC"""

    def test_find_cycle_path(self):
        """Test that cycle path is correctly extracted"""
        from vizzy.services.analysis import _find_cycle_in_scc

        scc_nodes = [1, 2, 3]
        adjacency = {
            1: [2],
            2: [3],
            3: [1],
        }

        path = _find_cycle_in_scc(scc_nodes, adjacency)

        # Path should form a cycle back to start
        assert len(path) >= 2
        # First and last should be the same (completing the cycle)
        assert path[0] == path[-1] or set(path) == set(scc_nodes)

    def test_empty_scc(self):
        """Test handling of empty SCC"""
        from vizzy.services.analysis import _find_cycle_in_scc

        path = _find_cycle_in_scc([], {})
        assert path == []
