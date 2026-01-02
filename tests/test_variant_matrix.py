"""Tests for variant matrix data service (Task 8D-002)

This module tests the variant matrix functionality that answers:
"Which of my packages are causing duplicate derivations?"
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test to ensure test isolation."""
    from vizzy.services.cache import cache
    cache.invalidate()
    yield
    cache.invalidate()


class TestBuildVariantMatrix:
    """Test the build_variant_matrix function"""

    def test_basic_variant_matrix(self):
        """Test building a matrix for a package with 2 variants"""
        # Mock nodes representing two variants of openssl
        mock_nodes = [
            {"id": 1, "drv_hash": "aaa111222333", "label": "openssl",
             "package_type": "library", "closure_size": 100},
            {"id": 2, "drv_hash": "bbb444555666", "label": "openssl",
             "package_type": "library", "closure_size": 120},
        ]

        # Mock dependents - firefox uses variant 1, curl uses variant 2
        mock_deps_v1 = [
            {"dep_id": 10, "label": "firefox", "package_type": "application",
             "is_top_level": True, "dependency_type": "runtime"},
        ]
        mock_deps_v2 = [
            {"dep_id": 11, "label": "curl", "package_type": "application",
             "is_top_level": True, "dependency_type": "runtime"},
        ]

        # Mock dependent node info
        mock_dep_nodes = [
            {"id": 10, "label": "firefox", "package_type": "application", "is_top_level": True},
            {"id": 11, "label": "curl", "package_type": "application", "is_top_level": True},
        ]

        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # Setup mock cursor to return expected data
            mock_cursor.fetchall.side_effect = [
                mock_nodes,          # Get variants
                mock_deps_v1,        # Get deps for variant 1
                mock_deps_v2,        # Get deps for variant 2
                mock_dep_nodes,      # Get all dependent node info
            ]
            mock_cursor.fetchone.side_effect = [
                {"classified": 1},   # Has edge classification
                {"total": 1},        # Total deps for variant 1
                {"total": 1},        # Total deps for variant 2
                {"total": 2},        # Total variant count
            ]

            from vizzy.services.variant_matrix import build_variant_matrix
            matrix = build_variant_matrix(1, "openssl")

            # Verify structure
            assert matrix.label == "openssl"
            assert matrix.import_id == 1
            assert len(matrix.variants) == 2
            assert matrix.total_variants == 2
            assert matrix.total_dependents == 2
            assert matrix.has_build_runtime_info is True

    def test_empty_variant_matrix(self):
        """Test building a matrix for a package with no variants"""
        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # No variants found
            mock_cursor.fetchall.return_value = []

            from vizzy.services.variant_matrix import build_variant_matrix
            matrix = build_variant_matrix(1, "nonexistent-package")

            assert matrix.label == "nonexistent-package"
            assert len(matrix.variants) == 0
            assert len(matrix.applications) == 0
            assert matrix.total_variants == 0
            assert matrix.total_dependents == 0

    def test_variant_info_short_hash(self):
        """Test that short hashes are correctly generated"""
        mock_nodes = [
            {"id": 1, "drv_hash": "abc123def456789", "label": "openssl",
             "package_type": "library", "closure_size": 100},
        ]

        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                mock_nodes,  # variants
                [],          # deps for variant 1
            ]
            mock_cursor.fetchone.side_effect = [
                {"classified": 0},
                {"total": 0},
                {"total": 1},
            ]

            from vizzy.services.variant_matrix import build_variant_matrix
            matrix = build_variant_matrix(1, "openssl")

            # Short hash should be first 12 characters
            assert matrix.variants[0].short_hash == "abc123def456"
            assert matrix.variants[0].drv_hash == "abc123def456789"


class TestVariantMatrixFiltering:
    """Test filtering capabilities of variant matrix"""

    def test_runtime_filter(self):
        """Test filtering by runtime dependencies only"""
        from vizzy.services.variant_matrix import _get_dependency_type_filter

        filter_clause = _get_dependency_type_filter("runtime")
        assert "dependency_type = 'runtime'" in filter_clause

    def test_build_filter(self):
        """Test filtering by build dependencies only"""
        from vizzy.services.variant_matrix import _get_dependency_type_filter

        filter_clause = _get_dependency_type_filter("build")
        assert "dependency_type = 'build'" in filter_clause

    def test_all_filter(self):
        """Test that 'all' filter returns empty clause"""
        from vizzy.services.variant_matrix import _get_dependency_type_filter

        filter_clause = _get_dependency_type_filter("all")
        assert filter_clause == ""


class TestVariantSorting:
    """Test sorting options for variants"""

    def test_sort_by_hash(self):
        """Test sorting by hash"""
        from vizzy.services.variant_matrix import _get_sort_order

        order = _get_sort_order("hash")
        assert order == "drv_hash"

    def test_sort_by_closure_size(self):
        """Test sorting by closure size"""
        from vizzy.services.variant_matrix import _get_sort_order

        order = _get_sort_order("closure_size")
        assert "closure_size" in order
        assert "DESC" in order

    def test_sort_by_dependent_count(self):
        """Test sorting by dependent count (default)"""
        from vizzy.services.variant_matrix import _get_sort_order

        order = _get_sort_order("dependent_count")
        # Default uses hash for stable sorting
        assert order == "drv_hash"


class TestDetermineVariantDepType:
    """Test dependency type classification for variants"""

    def test_all_runtime(self):
        """Test when all deps are runtime"""
        from vizzy.services.variant_matrix import _determine_variant_dep_type

        result = _determine_variant_dep_type(["runtime", "runtime", "runtime"])
        assert result == "runtime"

    def test_all_build(self):
        """Test when all deps are build"""
        from vizzy.services.variant_matrix import _determine_variant_dep_type

        result = _determine_variant_dep_type(["build", "build"])
        assert result == "build"

    def test_mixed_deps(self):
        """Test when deps are mixed"""
        from vizzy.services.variant_matrix import _determine_variant_dep_type

        result = _determine_variant_dep_type(["runtime", "build", "runtime"])
        assert result == "mixed"

    def test_empty_deps(self):
        """Test when there are no deps"""
        from vizzy.services.variant_matrix import _determine_variant_dep_type

        result = _determine_variant_dep_type([])
        assert result is None

    def test_none_deps(self):
        """Test when deps list contains None values"""
        from vizzy.services.variant_matrix import _determine_variant_dep_type

        result = _determine_variant_dep_type([None, None])
        assert result is None


class TestGetVariantLabels:
    """Test the get_variant_labels function"""

    def test_get_packages_with_variants(self):
        """Test getting list of packages with multiple variants"""
        mock_results = [
            {"label": "openssl", "variant_count": 3, "total_dependents": 15},
            {"label": "zlib", "variant_count": 2, "total_dependents": 20},
        ]

        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.return_value = mock_results

            from vizzy.services.variant_matrix import get_variant_labels
            labels = get_variant_labels(1)

            assert len(labels) == 2
            assert labels[0]["label"] == "openssl"
            assert labels[0]["variant_count"] == 3
            assert labels[1]["label"] == "zlib"

    def test_respects_min_count(self):
        """Test that min_count parameter is respected"""
        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.return_value = []

            from vizzy.services.variant_matrix import get_variant_labels
            labels = get_variant_labels(1, min_count=5)

            # Verify min_count was passed in query
            call_args = mock_cursor.execute.call_args
            assert 5 in call_args[0][1]  # min_count in query params


class TestGetVariantSummary:
    """Test the get_variant_summary function"""

    def test_get_summary_for_package(self):
        """Test getting summary for a package with variants"""
        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {"variant_count": 3, "total_nodes": 3, "total_closure": 500},
                {"unique_dependents": 10},
            ]

            from vizzy.services.variant_matrix import get_variant_summary
            summary = get_variant_summary(1, "openssl")

            assert summary["label"] == "openssl"
            assert summary["variant_count"] == 3
            assert summary["total_closure"] == 500
            assert summary["unique_dependents"] == 10

    def test_summary_for_nonexistent_package(self):
        """Test getting summary for a package that doesn't exist"""
        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {"variant_count": 0, "total_nodes": 0, "total_closure": 0}

            from vizzy.services.variant_matrix import get_variant_summary
            summary = get_variant_summary(1, "nonexistent")

            assert summary is None


class TestVariantMatrixSerialization:
    """Test serialization of variant matrix to dict"""

    def test_to_dict_structure(self):
        """Test that to_dict returns correct structure"""
        from vizzy.services.variant_matrix import (
            VariantMatrix, VariantInfo, ApplicationRow
        )

        variant = VariantInfo(
            node_id=1,
            drv_hash="abc123",
            short_hash="abc123",
            label="openssl",
            package_type="library",
            dependency_type="runtime",
            dependent_count=5,
            closure_size=100,
        )

        app = ApplicationRow(
            label="firefox",
            node_id=10,
            package_type="application",
            is_top_level=True,
            cells={1: {"has_dep": True, "dep_type": "runtime"}},
        )

        matrix = VariantMatrix(
            label="openssl",
            import_id=1,
            variants=[variant],
            applications=[app],
            total_variants=1,
            total_dependents=1,
            has_build_runtime_info=True,
        )

        result = matrix.to_dict()

        # Check structure
        assert result["label"] == "openssl"
        assert result["import_id"] == 1
        assert len(result["variants"]) == 1
        assert len(result["applications"]) == 1
        assert result["total_variants"] == 1
        assert result["total_dependents"] == 1
        assert result["has_build_runtime_info"] is True

        # Check variant serialization
        v = result["variants"][0]
        assert v["node_id"] == 1
        assert v["drv_hash"] == "abc123"
        assert v["label"] == "openssl"
        assert v["dependency_type"] == "runtime"

        # Check application serialization
        a = result["applications"][0]
        assert a["label"] == "firefox"
        assert a["is_top_level"] is True
        assert 1 in a["cells"]
        assert a["cells"][1]["has_dep"] is True


class TestDirectOnlyFilter:
    """Test the direct_only filter (Task 8D-004)"""

    def test_direct_only_filters_to_top_level(self):
        """Test that direct_only=True filters to only top-level packages"""
        # Mock nodes representing two variants of openssl
        mock_nodes = [
            {"id": 1, "drv_hash": "aaa111222333", "label": "openssl",
             "package_type": "library", "closure_size": 100},
        ]

        # Mock dependents - includes both top-level and non-top-level
        mock_deps = [
            {"dep_id": 10, "label": "firefox", "package_type": "application",
             "is_top_level": True, "dependency_type": "runtime"},
            {"dep_id": 11, "label": "curl-lib", "package_type": "library",
             "is_top_level": False, "dependency_type": "runtime"},
        ]

        # When direct_only=True, only top-level should be returned
        mock_dep_nodes_filtered = [
            {"id": 10, "label": "firefox", "package_type": "application", "is_top_level": True},
        ]

        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                mock_nodes,              # Get variants
                mock_deps,               # Get deps for variant
                mock_dep_nodes_filtered, # Get filtered dependent node info (only top-level)
            ]
            mock_cursor.fetchone.side_effect = [
                {"classified": 1},   # Has edge classification
                {"total": 2},        # Total deps for variant
                {"total": 1},        # Total variant count
            ]

            from vizzy.services.variant_matrix import build_variant_matrix
            matrix = build_variant_matrix(1, "openssl", direct_only=True)

            # Should only have the top-level application
            assert len(matrix.applications) == 1
            assert matrix.applications[0].label == "firefox"
            assert matrix.applications[0].is_top_level is True

    def test_direct_only_false_includes_all(self):
        """Test that direct_only=False includes all dependents"""
        mock_nodes = [
            {"id": 1, "drv_hash": "aaa111222333", "label": "openssl",
             "package_type": "library", "closure_size": 100},
        ]

        mock_deps = [
            {"dep_id": 10, "label": "firefox", "package_type": "application",
             "is_top_level": True, "dependency_type": "runtime"},
            {"dep_id": 11, "label": "curl-lib", "package_type": "library",
             "is_top_level": False, "dependency_type": "runtime"},
        ]

        # When direct_only=False, all deps should be returned
        mock_dep_nodes_all = [
            {"id": 10, "label": "firefox", "package_type": "application", "is_top_level": True},
            {"id": 11, "label": "curl-lib", "package_type": "library", "is_top_level": False},
        ]

        with patch('vizzy.services.variant_matrix.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.side_effect = [
                mock_nodes,          # Get variants
                mock_deps,           # Get deps for variant
                mock_dep_nodes_all,  # Get all dependent node info
            ]
            mock_cursor.fetchone.side_effect = [
                {"classified": 1},   # Has edge classification
                {"total": 2},        # Total deps for variant
                {"total": 1},        # Total variant count
            ]

            from vizzy.services.variant_matrix import build_variant_matrix
            matrix = build_variant_matrix(1, "openssl", direct_only=False)

            # Should have both applications
            assert len(matrix.applications) == 2
            labels = [app.label for app in matrix.applications]
            assert "firefox" in labels
            assert "curl-lib" in labels


class TestCacheInvalidation:
    """Test cache invalidation for variant matrix"""

    def test_invalidate_cache(self):
        """Test that cache invalidation works"""
        from vizzy.services.variant_matrix import invalidate_variant_matrix_cache
        from vizzy.services.cache import cache

        # Set some cache entries
        cache.set("import:1:variant_matrix:test", "value", ttl=300)
        cache.set("import:1:variant_labels:test", "value", ttl=300)
        cache.set("import:1:variant_summary:test", "value", ttl=300)

        # Invalidate
        invalidate_variant_matrix_cache(1)

        # Entries should be cleared
        assert cache.get("import:1:variant_matrix:test") is None
        assert cache.get("import:1:variant_labels:test") is None
        assert cache.get("import:1:variant_summary:test") is None
