"""Tests for baseline comparison presets (Phase 8F-004)"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from vizzy.services.baseline import (
    BaselinePreset,
    get_previous_import,
    get_available_presets,
    get_imports_for_host,
    create_baseline_with_auto_name,
    get_baseline_by_source_import,
    compare_to_previous_import,
    Baseline,
    BaselineCreateResult,
    BaselineComparison,
)


class TestGetPreviousImport:
    """Test the get_previous_import function"""

    def test_no_current_import(self):
        """Should return None if current import doesn't exist"""
        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None

            result = get_previous_import(999)
            assert result is None

    def test_no_previous_import(self):
        """Should return None if no previous import exists"""
        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # First call returns current import, second returns None (no previous)
            mock_cursor.fetchone.side_effect = [
                {'name': 'myhost', 'imported_at': datetime.now()},
                None,
            ]

            result = get_previous_import(1)
            assert result is None

    def test_previous_import_found(self):
        """Should return previous import when it exists"""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'name': 'myhost', 'imported_at': now},
                {
                    'id': 1,
                    'name': 'myhost',
                    'config_path': '/etc/nixos',
                    'drv_path': '/nix/store/abc',
                    'imported_at': yesterday,
                    'node_count': 100,
                    'edge_count': 200,
                },
            ]

            result = get_previous_import(2)
            assert result is not None
            assert result['id'] == 1
            assert result['name'] == 'myhost'
            assert result['imported_at'] == yesterday


class TestGetAvailablePresets:
    """Test the get_available_presets function"""

    def test_presets_include_previous_import(self):
        """Should include previous import as first preset if available"""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            with patch('vizzy.services.baseline.list_baselines') as mock_list:
                mock_prev.return_value = {
                    'id': 1,
                    'name': 'myhost',
                    'imported_at': yesterday,
                    'node_count': 100,
                    'edge_count': 200,
                }
                mock_list.return_value = []

                presets = get_available_presets(2)

                assert len(presets) == 1
                assert presets[0].preset_type == 'previous_import'
                assert presets[0].name == 'Previous Import'
                assert presets[0].target_id == 1

    def test_presets_include_system_baselines(self):
        """Should include system baselines after previous import"""
        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            with patch('vizzy.services.baseline.list_baselines') as mock_list:
                mock_prev.return_value = None
                mock_list.return_value = [
                    Baseline(
                        id=1,
                        name='Minimal NixOS',
                        description='Minimal baseline',
                        source_import_id=None,
                        node_count=1000,
                        edge_count=2000,
                        closure_by_type={},
                        top_level_count=None,
                        runtime_edge_count=None,
                        build_edge_count=None,
                        max_depth=None,
                        avg_depth=None,
                        top_contributors=[],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        is_system_baseline=True,
                        tags=['system'],
                    ),
                ]

                presets = get_available_presets(2)

                assert len(presets) == 1
                assert presets[0].preset_type == 'system_baseline'
                assert presets[0].name == 'Minimal NixOS'

    def test_presets_include_user_baselines(self):
        """Should include user baselines after system baselines"""
        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            with patch('vizzy.services.baseline.list_baselines') as mock_list:
                mock_prev.return_value = None
                mock_list.return_value = [
                    Baseline(
                        id=1,
                        name='My Saved Config',
                        description='User baseline',
                        source_import_id=10,
                        node_count=5000,
                        edge_count=10000,
                        closure_by_type={},
                        top_level_count=None,
                        runtime_edge_count=None,
                        build_edge_count=None,
                        max_depth=None,
                        avg_depth=None,
                        top_contributors=[],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        is_system_baseline=False,
                        tags=[],
                    ),
                ]

                presets = get_available_presets(2)

                assert len(presets) == 1
                assert presets[0].preset_type == 'baseline'
                assert presets[0].name == 'My Saved Config'

    def test_presets_order(self):
        """Presets should be ordered: previous, system baselines, user baselines"""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            with patch('vizzy.services.baseline.list_baselines') as mock_list:
                mock_prev.return_value = {
                    'id': 1,
                    'name': 'myhost',
                    'imported_at': yesterday,
                    'node_count': 100,
                    'edge_count': 200,
                }
                mock_list.return_value = [
                    Baseline(
                        id=10,
                        name='Minimal',
                        description=None,
                        source_import_id=None,
                        node_count=1000,
                        edge_count=2000,
                        closure_by_type={},
                        top_level_count=None,
                        runtime_edge_count=None,
                        build_edge_count=None,
                        max_depth=None,
                        avg_depth=None,
                        top_contributors=[],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        is_system_baseline=True,
                        tags=[],
                    ),
                    Baseline(
                        id=20,
                        name='User Baseline',
                        description=None,
                        source_import_id=5,
                        node_count=5000,
                        edge_count=10000,
                        closure_by_type={},
                        top_level_count=None,
                        runtime_edge_count=None,
                        build_edge_count=None,
                        max_depth=None,
                        avg_depth=None,
                        top_contributors=[],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        is_system_baseline=False,
                        tags=[],
                    ),
                ]

                presets = get_available_presets(2)

                assert len(presets) == 3
                assert presets[0].preset_type == 'previous_import'
                assert presets[1].preset_type == 'system_baseline'
                assert presets[2].preset_type == 'baseline'


class TestGetImportsForHost:
    """Test the get_imports_for_host function"""

    def test_returns_imports_for_host(self):
        """Should return all imports for a host, newest first"""
        now = datetime.now()

        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.return_value = [
                {
                    'id': 3,
                    'name': 'myhost',
                    'config_path': '/etc/nixos',
                    'drv_path': '/nix/store/c',
                    'imported_at': now,
                    'node_count': 3000,
                    'edge_count': 6000,
                },
                {
                    'id': 2,
                    'name': 'myhost',
                    'config_path': '/etc/nixos',
                    'drv_path': '/nix/store/b',
                    'imported_at': now - timedelta(days=1),
                    'node_count': 2900,
                    'edge_count': 5800,
                },
            ]

            result = get_imports_for_host('myhost')

            assert len(result) == 2
            assert result[0]['id'] == 3  # Newest first
            assert result[1]['id'] == 2

    def test_respects_limit(self):
        """Should respect the limit parameter"""
        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.return_value = []

            get_imports_for_host('myhost', limit=5)

            # Check that limit was passed to query as a parameter
            call_args = mock_cursor.execute.call_args
            # The second element of the args tuple contains the parameters
            assert call_args[0][1] == ('myhost', 5)


class TestCreateBaselineWithAutoName:
    """Test the create_baseline_with_auto_name function"""

    def test_auto_generates_name(self):
        """Should generate name from import name and date"""
        now = datetime(2024, 1, 15, 12, 0, 0)

        with patch('vizzy.services.baseline.get_db') as mock_db:
            with patch('vizzy.services.baseline.create_baseline_from_import') as mock_create:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = {
                    'name': 'myhost',
                    'imported_at': now,
                }
                mock_create.return_value = BaselineCreateResult(
                    baseline_id=1,
                    name='myhost - 2024-01-15',
                    node_count=1000,
                    edge_count=2000,
                    success=True,
                    message='Created',
                )

                result = create_baseline_with_auto_name(1)

                # Verify the generated name format
                mock_create.assert_called_once()
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs['name'] == 'myhost - 2024-01-15'
                assert 'myhost' in call_kwargs['description']

    def test_includes_suffix(self):
        """Should include suffix in name when provided"""
        now = datetime(2024, 1, 15, 12, 0, 0)

        with patch('vizzy.services.baseline.get_db') as mock_db:
            with patch('vizzy.services.baseline.create_baseline_from_import') as mock_create:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = {
                    'name': 'myhost',
                    'imported_at': now,
                }
                mock_create.return_value = BaselineCreateResult(
                    baseline_id=1,
                    name='myhost - 2024-01-15 (stable)',
                    node_count=1000,
                    edge_count=2000,
                    success=True,
                    message='Created',
                )

                result = create_baseline_with_auto_name(1, suffix='stable')

                call_kwargs = mock_create.call_args[1]
                assert '(stable)' in call_kwargs['name']

    def test_import_not_found(self):
        """Should return error result if import doesn't exist"""
        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = None

            result = create_baseline_with_auto_name(999)

            assert result.success is False
            assert '999' in result.message


class TestGetBaselineBySourceImport:
    """Test the get_baseline_by_source_import function"""

    def test_returns_baseline_if_exists(self):
        """Should return baseline when one exists for the source import"""
        now = datetime.now()

        with patch('vizzy.services.baseline.get_db') as mock_db:
            with patch('vizzy.services.baseline._row_to_baseline') as mock_convert:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = {
                    'id': 1,
                    'name': 'Test Baseline',
                }
                mock_baseline = Baseline(
                    id=1,
                    name='Test Baseline',
                    description=None,
                    source_import_id=5,
                    node_count=1000,
                    edge_count=2000,
                    closure_by_type={},
                    top_level_count=None,
                    runtime_edge_count=None,
                    build_edge_count=None,
                    max_depth=None,
                    avg_depth=None,
                    top_contributors=[],
                    created_at=now,
                    updated_at=now,
                    is_system_baseline=False,
                    tags=[],
                )
                mock_convert.return_value = mock_baseline

                result = get_baseline_by_source_import(5)

                assert result is not None
                assert result.id == 1

    def test_returns_none_if_not_exists(self):
        """Should return None when no baseline exists for source import"""
        with patch('vizzy.services.baseline.get_db') as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = None

            result = get_baseline_by_source_import(999)

            assert result is None


class TestCompareToPreviousImport:
    """Test the compare_to_previous_import function"""

    def test_returns_none_if_no_previous(self):
        """Should return None if no previous import exists"""
        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            mock_prev.return_value = None

            result = compare_to_previous_import(1)

            assert result is None

    def test_computes_comparison(self):
        """Should compute comparison metrics between imports"""
        yesterday = datetime.now() - timedelta(days=1)

        with patch('vizzy.services.baseline.get_previous_import') as mock_prev:
            with patch('vizzy.services.baseline.get_db') as mock_db:
                mock_prev.return_value = {
                    'id': 1,
                    'name': 'myhost',
                    'imported_at': yesterday,
                    'node_count': 1000,
                    'edge_count': 2000,
                }

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                # Mock current import query
                mock_cursor.fetchone.side_effect = [
                    {'name': 'myhost', 'node_count': 1100, 'edge_count': 2200},
                ]
                mock_cursor.fetchall.side_effect = [
                    [{'package_type': 'library', 'count': 600}, {'package_type': 'app', 'count': 500}],
                    [{'package_type': 'library', 'count': 550}, {'package_type': 'app', 'count': 450}],
                ]

                result = compare_to_previous_import(2)

                assert result is not None
                assert result.import_id == 2
                assert result.baseline_id == 1
                assert result.node_difference == 100  # 1100 - 1000
                assert result.percentage_difference == 10.0  # 10% increase
                assert result.is_larger is True


class TestBaselinePresetDataclass:
    """Test the BaselinePreset dataclass"""

    def test_preset_creation(self):
        """Should create preset with all required fields"""
        preset = BaselinePreset(
            id='baseline:1',
            name='Test Baseline',
            description='A test baseline',
            preset_type='baseline',
            target_id=1,
            node_count=1000,
            edge_count=2000,
            created_at=datetime.now(),
        )

        assert preset.id == 'baseline:1'
        assert preset.name == 'Test Baseline'
        assert preset.preset_type == 'baseline'
        assert preset.target_id == 1

    def test_preset_with_none_values(self):
        """Should handle None values for optional fields"""
        preset = BaselinePreset(
            id='import:1',
            name='Previous',
            description=None,
            preset_type='previous_import',
            target_id=1,
            node_count=None,
            edge_count=None,
            created_at=None,
        )

        assert preset.description is None
        assert preset.node_count is None
