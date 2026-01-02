"""Tests for top-level package identification functionality (Phase 8A-002)"""

import pytest
from unittest.mock import patch, MagicMock

from vizzy.models import Node
from vizzy.services.importer import classify_edge_type


class TestEdgeClassification:
    """Test the classify_edge_type function used for build vs runtime classification"""

    def test_gcc_is_build_dependency(self):
        """GCC compiler should be classified as build-time dependency"""
        result = classify_edge_type("gcc-13.2.0", "myapp")
        assert result == 'build'

    def test_clang_is_build_dependency(self):
        """Clang compiler should be classified as build-time dependency"""
        result = classify_edge_type("clang-17.0.6", "myapp")
        assert result == 'build'

    def test_cmake_is_build_dependency(self):
        """CMake should be classified as build-time dependency"""
        result = classify_edge_type("cmake-3.28.1", "myapp")
        assert result == 'build'

    def test_hook_is_build_dependency(self):
        """Build hooks should be classified as build-time dependency"""
        # The pattern matches -hook suffix
        result = classify_edge_type("autoPatchelf-hook", "myapp")
        assert result == 'build'

    def test_dev_package_is_build_dependency(self):
        """Dev packages should be classified as build-time dependency"""
        result = classify_edge_type("openssl-dev", "myapp")
        assert result == 'build'

    def test_regular_library_is_runtime(self):
        """Regular libraries should be classified as runtime dependency"""
        result = classify_edge_type("openssl-3.2.0", "myapp")
        assert result == 'runtime'

    def test_application_is_runtime(self):
        """Applications should be classified as runtime dependency"""
        result = classify_edge_type("firefox-121.0", "system")
        assert result == 'runtime'


class TestNodeModel:
    """Test the Node model with top-level fields"""

    def test_node_defaults_not_top_level(self):
        """Node should default to not being top-level"""
        node = Node(
            id=1,
            import_id=1,
            drv_hash="abc123",
            drv_name="test-1.0.drv",
            label="test-1.0",
            package_type="app",
            depth=1,
            closure_size=10,
            metadata=None,
        )
        assert node.is_top_level is False
        assert node.top_level_source is None

    def test_node_can_be_marked_top_level(self):
        """Node can be marked as top-level with source"""
        node = Node(
            id=1,
            import_id=1,
            drv_hash="abc123",
            drv_name="firefox-121.0.drv",
            label="firefox-121.0",
            package_type="app",
            depth=1,
            closure_size=500,
            metadata=None,
            is_top_level=True,
            top_level_source="systemPackages",
        )
        assert node.is_top_level is True
        assert node.top_level_source == "systemPackages"


class TestMarkTopLevelNodes:
    """Test the mark_top_level_nodes function"""

    def test_mark_top_level_with_no_host(self):
        """Should return 0 when host cannot be determined"""
        from vizzy.services.importer import mark_top_level_nodes

        with patch('vizzy.services.importer.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # No import found
            mock_cursor.fetchone.return_value = None

            result = mark_top_level_nodes(import_id=999, host=None)

            assert result == 0

    def test_mark_top_level_with_empty_packages(self):
        """Should return 0 when no top-level packages found from nix"""
        from vizzy.services.importer import mark_top_level_nodes

        with patch('vizzy.services.importer.nix') as mock_nix:
            mock_nix.get_top_level_packages_extended.return_value = {}

            result = mark_top_level_nodes(import_id=1, host="testhost")

            assert result == 0

    def test_mark_top_level_marks_matching_nodes(self):
        """Should mark nodes that match top-level package names"""
        from vizzy.services.importer import mark_top_level_nodes

        with patch('vizzy.services.importer.nix') as mock_nix:
            with patch('vizzy.services.importer.get_db') as mock_get_db:
                mock_nix.get_top_level_packages_extended.return_value = {
                    'firefox': 'systemPackages',
                    'git': 'systemPackages',
                }

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                # First call marks firefox (1 row), second marks git (1 row)
                mock_cursor.rowcount = 1

                result = mark_top_level_nodes(import_id=1, host="testhost")

                # Should have marked 2 packages
                assert result == 2

                # Verify UPDATE was called for each package
                assert mock_cursor.execute.call_count == 2


class TestGetTopLevelNodes:
    """Test the get_top_level_nodes function"""

    def test_get_top_level_nodes_returns_list(self):
        """Should return list of top-level Node objects"""
        from vizzy.services.graph import get_top_level_nodes

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'id': 1,
                        'import_id': 1,
                        'drv_hash': 'abc123',
                        'drv_name': 'firefox-121.0.drv',
                        'label': 'firefox-121.0',
                        'package_type': 'app',
                        'depth': 1,
                        'closure_size': 500,
                        'metadata': None,
                        'is_top_level': True,
                        'top_level_source': 'systemPackages',
                    }
                ]

                result = get_top_level_nodes(1)

                assert len(result) == 1
                assert isinstance(result[0], Node)
                assert result[0].is_top_level is True
                assert result[0].label == 'firefox-121.0'

    def test_get_top_level_nodes_filters_by_source(self):
        """Should filter by top_level_source when provided"""
        from vizzy.services.graph import get_top_level_nodes

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = []

                get_top_level_nodes(1, source='systemPackages')

                # Verify SQL includes source filter
                call_args = mock_cursor.execute.call_args[0]
                assert 'top_level_source = %s' in call_args[0]
                assert call_args[1][1] == 'systemPackages'

    def test_get_top_level_nodes_uses_cache(self):
        """Should return cached data when available"""
        from vizzy.services.graph import get_top_level_nodes

        cached_result = [
            Node(
                id=1,
                import_id=1,
                drv_hash='cached123',
                drv_name='cached-pkg.drv',
                label='cached-pkg',
                package_type='app',
                depth=1,
                closure_size=100,
                metadata=None,
                is_top_level=True,
                top_level_source='systemPackages',
            )
        ]

        with patch('vizzy.services.graph.cache') as mock_cache:
            mock_cache.get.return_value = cached_result

            result = get_top_level_nodes(1)

            assert result == cached_result
            assert result[0].label == 'cached-pkg'


class TestGetTopLevelSources:
    """Test the get_top_level_sources function"""

    def test_get_top_level_sources_returns_summary(self):
        """Should return summary of sources with counts"""
        from vizzy.services.graph import get_top_level_sources

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {'source': 'systemPackages', 'count': 50},
                    {'source': 'programs.git.enable', 'count': 1},
                ]

                result = get_top_level_sources(1)

                assert len(result) == 2
                assert result[0]['source'] == 'systemPackages'
                assert result[0]['count'] == 50


class TestGetTopLevelCount:
    """Test the get_top_level_count function"""

    def test_get_top_level_count_returns_count(self):
        """Should return count of top-level packages"""
        from vizzy.services.graph import get_top_level_count

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = {'count': 42}

                result = get_top_level_count(1)

                assert result == 42

    def test_get_top_level_count_returns_zero_when_none(self):
        """Should return 0 when no top-level packages"""
        from vizzy.services.graph import get_top_level_count

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = None

                result = get_top_level_count(1)

                assert result == 0


class TestGetGraphRoots:
    """Test the get_graph_roots function"""

    def test_get_graph_roots_returns_nodes_without_incoming_edges(self):
        """Should return nodes that have no incoming edges"""
        from vizzy.services.graph import get_graph_roots

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'id': 1,
                        'import_id': 1,
                        'drv_hash': 'root123',
                        'drv_name': 'system.drv',
                        'label': 'nixos-system-test',
                        'package_type': 'configuration',
                        'depth': 0,
                        'closure_size': 10000,
                        'metadata': None,
                        'is_top_level': False,
                        'top_level_source': None,
                    }
                ]

                result = get_graph_roots(1)

                assert len(result) == 1
                assert isinstance(result[0], Node)
                assert result[0].label == 'nixos-system-test'

    def test_get_graph_roots_respects_limit(self):
        """Should respect the limit parameter"""
        from vizzy.services.graph import get_graph_roots

        with patch('vizzy.services.graph.cache') as mock_cache:
            with patch('vizzy.services.graph.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = []

                get_graph_roots(1, limit=10)

                # Verify SQL contains LIMIT 10
                call_args = mock_cursor.execute.call_args[0]
                assert call_args[1] == (1, 10)


class TestTopLevelPackagesExtended:
    """Test the get_top_level_packages_extended function from nix service"""

    def test_returns_empty_when_nix_fails(self):
        """Should return empty dict when nix command fails"""
        from vizzy.services.nix import get_top_level_packages_extended

        with patch('vizzy.services.nix.get_system_packages') as mock_get_pkgs:
            mock_get_pkgs.return_value = []

            result = get_top_level_packages_extended("testhost")

            assert result == {}

    def test_returns_packages_with_source(self):
        """Should return packages with their source"""
        from vizzy.services.nix import get_top_level_packages_extended

        with patch('vizzy.services.nix.get_system_packages') as mock_get_pkgs:
            mock_get_pkgs.return_value = ['firefox', 'git', 'vim']

            result = get_top_level_packages_extended("testhost")

            assert result == {
                'firefox': 'systemPackages',
                'git': 'systemPackages',
                'vim': 'systemPackages',
            }
