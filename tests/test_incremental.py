"""Tests for incremental recomputation service (Task 8A-008)"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from vizzy.services.incremental import (
    ChangeType,
    GraphChange,
    StalenessReport,
    RecomputationResult,
    get_staleness_report,
    mark_contributions_stale,
    find_affected_nodes_by_edge_change,
    find_affected_nodes_by_node_change,
    find_affected_by_top_level_change,
    recompute_stale_contributions,
    recompute_selective,
    recompute_for_graph_change,
    recompute_all_imports_stale,
    estimate_recomputation_cost,
    should_trigger_recomputation,
    handle_import_completed,
    handle_node_change,
    handle_edge_change,
    handle_top_level_change,
)


class TestStalenessReport:
    """Test the StalenessReport dataclass"""

    def test_stale_percentage_with_nodes(self):
        """Stale percentage should be calculated correctly"""
        report = StalenessReport(
            import_id=1,
            total_top_level=100,
            stale_count=25,
            never_computed_count=10,
            oldest_computation=None,
            newest_computation=None,
            freshness_threshold=timedelta(hours=24),
            is_fresh=False,
        )
        assert report.stale_percentage == 25.0

    def test_stale_percentage_zero_total(self):
        """Stale percentage should be 0 when no top-level nodes"""
        report = StalenessReport(
            import_id=1,
            total_top_level=0,
            stale_count=0,
            never_computed_count=0,
            oldest_computation=None,
            newest_computation=None,
            freshness_threshold=timedelta(hours=24),
            is_fresh=True,
        )
        assert report.stale_percentage == 0.0

    def test_needs_recomputation_stale(self):
        """Needs recomputation when stale count > 0"""
        report = StalenessReport(
            import_id=1,
            total_top_level=100,
            stale_count=5,
            never_computed_count=0,
            oldest_computation=None,
            newest_computation=None,
            freshness_threshold=timedelta(hours=24),
            is_fresh=False,
        )
        assert report.needs_recomputation is True

    def test_needs_recomputation_never_computed(self):
        """Needs recomputation when never_computed_count > 0"""
        report = StalenessReport(
            import_id=1,
            total_top_level=100,
            stale_count=0,
            never_computed_count=10,
            oldest_computation=None,
            newest_computation=None,
            freshness_threshold=timedelta(hours=24),
            is_fresh=False,
        )
        assert report.needs_recomputation is True

    def test_needs_recomputation_fresh(self):
        """Does not need recomputation when fresh"""
        report = StalenessReport(
            import_id=1,
            total_top_level=100,
            stale_count=0,
            never_computed_count=0,
            oldest_computation=datetime.now(),
            newest_computation=datetime.now(),
            freshness_threshold=timedelta(hours=24),
            is_fresh=True,
        )
        assert report.needs_recomputation is False


class TestRecomputationResult:
    """Test the RecomputationResult dataclass"""

    def test_success_no_errors(self):
        """Success should be True when no errors"""
        result = RecomputationResult(
            import_id=1,
            nodes_updated=10,
            nodes_skipped=0,
            computation_time_ms=100.0,
            strategy_used='incremental',
            errors=[],
        )
        assert result.success is True

    def test_success_with_errors(self):
        """Success should be False when errors present"""
        result = RecomputationResult(
            import_id=1,
            nodes_updated=5,
            nodes_skipped=5,
            computation_time_ms=100.0,
            strategy_used='incremental',
            errors=['Failed to compute node 123'],
        )
        assert result.success is False


class TestGraphChange:
    """Test the GraphChange dataclass"""

    def test_default_timestamp(self):
        """Timestamp should default to now"""
        before = datetime.now()
        change = GraphChange(
            change_type=ChangeType.NODE_ADDED,
            import_id=1,
            node_id=123,
        )
        after = datetime.now()
        assert before <= change.timestamp <= after

    def test_edge_change_fields(self):
        """Edge change should have source and target"""
        change = GraphChange(
            change_type=ChangeType.EDGE_ADDED,
            import_id=1,
            source_id=10,
            target_id=20,
        )
        assert change.source_id == 10
        assert change.target_id == 20


class TestGetStalenessReport:
    """Test the get_staleness_report function"""

    def test_staleness_report_all_fresh(self):
        """Report should show fresh when all nodes are recently computed"""
        mock_stats = {
            'total_top_level': 50,
            'never_computed': 0,
            'stale': 0,
            'oldest': datetime.now() - timedelta(hours=1),
            'newest': datetime.now(),
        }
        mock_breakdown = [
            {'source': 'systemPackages', 'total': 50, 'never_computed': 0, 'stale': 0}
        ]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_stats
            mock_cursor.fetchall.return_value = mock_breakdown

            report = get_staleness_report(1, timedelta(hours=24))

            assert report.total_top_level == 50
            assert report.stale_count == 0
            assert report.never_computed_count == 0
            assert report.is_fresh is True
            assert report.needs_recomputation is False

    def test_staleness_report_all_stale(self):
        """Report should show stale when all nodes are old"""
        mock_stats = {
            'total_top_level': 50,
            'never_computed': 10,
            'stale': 40,
            'oldest': datetime.now() - timedelta(days=7),
            'newest': datetime.now() - timedelta(days=2),
        }
        mock_breakdown = []

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_stats
            mock_cursor.fetchall.return_value = mock_breakdown

            report = get_staleness_report(1, timedelta(hours=24))

            assert report.stale_count == 40
            assert report.never_computed_count == 10
            assert report.is_fresh is False
            assert report.needs_recomputation is True


class TestMarkContributionsStale:
    """Test the mark_contributions_stale function"""

    def test_mark_all_stale(self):
        """Should mark all top-level nodes stale when no node_ids specified"""
        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.cache') as mock_cache:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.rowcount = 25

                count = mark_contributions_stale(1)

                assert count == 25
                mock_cursor.execute.assert_called_once()
                assert 'contribution_computed_at = NULL' in mock_cursor.execute.call_args[0][0]
                mock_conn.commit.assert_called_once()
                mock_cache.invalidate.assert_called_once()

    def test_mark_specific_nodes_stale(self):
        """Should mark only specified nodes stale"""
        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.cache') as mock_cache:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.rowcount = 3

                count = mark_contributions_stale(1, node_ids=[10, 20, 30])

                assert count == 3
                call_args = mock_cursor.execute.call_args[0]
                assert 'id = ANY' in call_args[0]


class TestFindAffectedNodes:
    """Test the affected node finding functions"""

    def test_find_affected_by_edge_change(self):
        """Should find top-level nodes affected by edge change"""
        mock_results = [
            {'top_level_id': 1},
            {'top_level_id': 5},
            {'top_level_id': 10},
        ]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_results

            affected = find_affected_nodes_by_edge_change(1, 100, 200)

            assert affected == {1, 5, 10}
            mock_cursor.execute.assert_called_once()

    def test_find_affected_by_node_change(self):
        """Should find top-level nodes affected by node change"""
        mock_results = [
            {'id': 1},
            {'id': 2},
        ]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # First call for is_top_level check, second for affected nodes
            mock_cursor.fetchone.return_value = {'is_top_level': False}
            mock_cursor.fetchall.return_value = mock_results

            affected = find_affected_nodes_by_node_change(1, 100)

            assert affected == {1, 2}

    def test_find_affected_by_top_level_change(self):
        """Top-level change should affect all top-level nodes"""
        mock_results = [
            {'id': 1},
            {'id': 2},
            {'id': 3},
            {'id': 4},
        ]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = mock_results

            affected = find_affected_by_top_level_change(1, 100)

            assert affected == {1, 2, 3, 4}


class TestRecomputeStaleContributions:
    """Test the recompute_stale_contributions function"""

    def test_no_stale_nodes(self):
        """Should return early when no stale nodes"""
        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []  # No stale nodes

            result = recompute_stale_contributions(1)

            assert result.nodes_updated == 0
            assert result.strategy_used == 'none_needed'

    def test_high_staleness_uses_full_recomputation(self):
        """Should use full recomputation when > 50% nodes are stale"""
        stale_nodes = [{'id': i} for i in range(60)]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.get_top_level_count_internal') as mock_count:
                with patch('vizzy.services.incremental.compute_contributions') as mock_compute:
                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_get_db.return_value.__enter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                    mock_cursor.fetchall.return_value = stale_nodes

                    mock_count.return_value = 100  # 60/100 = 60% stale
                    mock_compute.return_value = 100

                    result = recompute_stale_contributions(1)

                    assert result.strategy_used == 'full'
                    mock_compute.assert_called_once_with(1)


class TestRecomputeSelective:
    """Test the recompute_selective function"""

    def test_selective_recomputation(self):
        """Should selectively recompute only specified nodes"""
        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.compute_closure') as mock_closure:
                with patch('vizzy.services.incremental.cache') as mock_cache:
                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_get_db.return_value.__enter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                    # Mock top-level nodes
                    mock_cursor.fetchall.return_value = [{'id': 1}, {'id': 2}, {'id': 3}]
                    # Mock closures
                    mock_closure.return_value = {10, 20, 30}

                    result = recompute_selective(1, [1, 2])

                    assert result.strategy_used == 'selective'
                    assert result.nodes_updated == 2
                    mock_cache.invalidate.assert_called_once()


class TestRecomputeForGraphChange:
    """Test the recompute_for_graph_change function"""

    def test_full_reimport_triggers_full_recomputation(self):
        """Full reimport should trigger full recomputation"""
        change = GraphChange(
            change_type=ChangeType.FULL_REIMPORT,
            import_id=1,
        )

        with patch('vizzy.services.incremental.compute_contributions') as mock_compute:
            mock_compute.return_value = 50

            result = recompute_for_graph_change(change)

            assert result.strategy_used == 'full'
            mock_compute.assert_called_once_with(1)

    def test_edge_added_triggers_incremental(self):
        """Edge addition should trigger incremental recomputation"""
        change = GraphChange(
            change_type=ChangeType.EDGE_ADDED,
            import_id=1,
            source_id=10,
            target_id=20,
        )

        with patch('vizzy.services.incremental.find_affected_nodes_by_edge_change') as mock_find:
            with patch('vizzy.services.incremental.recompute_selective') as mock_recompute:
                mock_find.return_value = {1, 2, 3}
                mock_recompute.return_value = RecomputationResult(
                    import_id=1,
                    nodes_updated=3,
                    nodes_skipped=0,
                    computation_time_ms=100.0,
                    strategy_used='selective',
                )

                result = recompute_for_graph_change(change)

                mock_find.assert_called_once()
                mock_recompute.assert_called_once()

    def test_no_affected_nodes(self):
        """When no nodes affected, should return early"""
        change = GraphChange(
            change_type=ChangeType.NODE_ADDED,
            import_id=1,
            node_id=100,
        )

        with patch('vizzy.services.incremental.find_affected_nodes_by_node_change') as mock_find:
            mock_find.return_value = set()

            result = recompute_for_graph_change(change)

            assert result.nodes_updated == 0
            assert result.strategy_used == 'incremental'


class TestEstimateRecomputationCost:
    """Test the estimate_recomputation_cost function"""

    def test_cost_estimate_no_stale(self):
        """Should recommend no recomputation when nothing is stale"""
        mock_metrics = {
            'total_nodes': 1000,
            'total_edges': 5000,
            'top_level_count': 50,
            'avg_closure': 100.0,
            'stale_count': 0,
        }

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_metrics

            estimate = estimate_recomputation_cost(1)

            assert estimate['stale_count'] == 0
            assert estimate['recommendation'] == 'no_recomputation_needed'

    def test_cost_estimate_high_staleness(self):
        """Should recommend full recomputation for high staleness"""
        mock_metrics = {
            'total_nodes': 1000,
            'total_edges': 5000,
            'top_level_count': 50,
            'avg_closure': 100.0,
            'stale_count': 40,  # 80% stale
        }

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_metrics

            estimate = estimate_recomputation_cost(1)

            assert estimate['stale_count'] == 40
            assert estimate['recommendation'] == 'full_recomputation'

    def test_cost_estimate_low_staleness(self):
        """Should recommend incremental for low staleness"""
        mock_metrics = {
            'total_nodes': 1000,
            'total_edges': 5000,
            'top_level_count': 50,
            'avg_closure': 100.0,
            'stale_count': 5,  # 10% stale
        }

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_metrics

            estimate = estimate_recomputation_cost(1)

            assert estimate['stale_count'] == 5
            assert estimate['recommendation'] == 'incremental_recomputation'
            assert estimate['savings_percentage'] > 0


class TestApiIntegrationHelpers:
    """Test the API integration helper functions"""

    def test_handle_import_completed_new(self):
        """New import should trigger full computation"""
        with patch('vizzy.services.incremental.recompute_for_graph_change') as mock_recompute:
            mock_recompute.return_value = RecomputationResult(
                import_id=1,
                nodes_updated=50,
                nodes_skipped=0,
                computation_time_ms=500.0,
                strategy_used='full',
            )

            result = handle_import_completed(1, is_reimport=False)

            mock_recompute.assert_called_once()
            call_arg = mock_recompute.call_args[0][0]
            assert call_arg.change_type == ChangeType.FULL_REIMPORT

    def test_handle_import_completed_reimport(self):
        """Reimport should mark stale and recompute"""
        with patch('vizzy.services.incremental.mark_contributions_stale') as mock_mark:
            with patch('vizzy.services.incremental.recompute_stale_contributions') as mock_recompute:
                mock_recompute.return_value = RecomputationResult(
                    import_id=1,
                    nodes_updated=30,
                    nodes_skipped=0,
                    computation_time_ms=300.0,
                    strategy_used='incremental',
                )

                result = handle_import_completed(1, is_reimport=True)

                mock_mark.assert_called_once_with(1)
                mock_recompute.assert_called_once()

    def test_handle_node_change(self):
        """Node change should trigger appropriate recomputation"""
        with patch('vizzy.services.incremental.recompute_for_graph_change') as mock_recompute:
            mock_recompute.return_value = RecomputationResult(
                import_id=1,
                nodes_updated=5,
                nodes_skipped=0,
                computation_time_ms=100.0,
                strategy_used='selective',
            )

            result = handle_node_change(1, 100, ChangeType.NODE_MODIFIED)

            mock_recompute.assert_called_once()
            call_arg = mock_recompute.call_args[0][0]
            assert call_arg.change_type == ChangeType.NODE_MODIFIED
            assert call_arg.node_id == 100

    def test_handle_edge_change_added(self):
        """Edge addition should trigger recomputation"""
        with patch('vizzy.services.incremental.recompute_for_graph_change') as mock_recompute:
            mock_recompute.return_value = RecomputationResult(
                import_id=1,
                nodes_updated=3,
                nodes_skipped=0,
                computation_time_ms=50.0,
                strategy_used='selective',
            )

            result = handle_edge_change(1, 10, 20, added=True)

            mock_recompute.assert_called_once()
            call_arg = mock_recompute.call_args[0][0]
            assert call_arg.change_type == ChangeType.EDGE_ADDED
            assert call_arg.source_id == 10
            assert call_arg.target_id == 20

    def test_handle_edge_change_removed(self):
        """Edge removal should trigger recomputation"""
        with patch('vizzy.services.incremental.recompute_for_graph_change') as mock_recompute:
            mock_recompute.return_value = RecomputationResult(
                import_id=1,
                nodes_updated=3,
                nodes_skipped=0,
                computation_time_ms=50.0,
                strategy_used='selective',
            )

            result = handle_edge_change(1, 10, 20, added=False)

            mock_recompute.assert_called_once()
            call_arg = mock_recompute.call_args[0][0]
            assert call_arg.change_type == ChangeType.EDGE_REMOVED

    def test_handle_top_level_change(self):
        """Top-level change should trigger full recomputation of all"""
        with patch('vizzy.services.incremental.recompute_for_graph_change') as mock_recompute:
            mock_recompute.return_value = RecomputationResult(
                import_id=1,
                nodes_updated=50,
                nodes_skipped=0,
                computation_time_ms=500.0,
                strategy_used='selective',
            )

            result = handle_top_level_change(1, 100)

            mock_recompute.assert_called_once()
            call_arg = mock_recompute.call_args[0][0]
            assert call_arg.change_type == ChangeType.TOP_LEVEL_CHANGED


class TestShouldTriggerRecomputation:
    """Test the should_trigger_recomputation function"""

    def test_should_trigger_when_stale(self):
        """Should return True when recomputation is needed"""
        with patch('vizzy.services.incremental.get_staleness_report') as mock_report:
            mock_report.return_value = StalenessReport(
                import_id=1,
                total_top_level=50,
                stale_count=10,
                never_computed_count=5,
                oldest_computation=None,
                newest_computation=None,
                freshness_threshold=timedelta(hours=1),
                is_fresh=False,
            )

            result = should_trigger_recomputation(1, timedelta(hours=1))

            assert result is True

    def test_should_not_trigger_when_fresh(self):
        """Should return False when data is fresh"""
        with patch('vizzy.services.incremental.get_staleness_report') as mock_report:
            mock_report.return_value = StalenessReport(
                import_id=1,
                total_top_level=50,
                stale_count=0,
                never_computed_count=0,
                oldest_computation=datetime.now(),
                newest_computation=datetime.now(),
                freshness_threshold=timedelta(hours=1),
                is_fresh=True,
            )

            result = should_trigger_recomputation(1, timedelta(hours=1))

            assert result is False


class TestRecomputeAllImportsStale:
    """Test the batch recomputation function"""

    def test_recomputes_all_stale_imports(self):
        """Should recompute all imports with stale data"""
        mock_import_ids = [{'import_id': 1}, {'import_id': 2}, {'import_id': 3}]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.recompute_stale_contributions') as mock_recompute:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_import_ids

                mock_recompute.return_value = RecomputationResult(
                    import_id=1,
                    nodes_updated=10,
                    nodes_skipped=0,
                    computation_time_ms=100.0,
                    strategy_used='incremental',
                )

                results = recompute_all_imports_stale()

                assert len(results) == 3
                assert 1 in results
                assert 2 in results
                assert 3 in results

    def test_handles_recomputation_errors(self):
        """Should handle errors gracefully and continue"""
        mock_import_ids = [{'import_id': 1}, {'import_id': 2}]

        with patch('vizzy.services.incremental.get_db') as mock_get_db:
            with patch('vizzy.services.incremental.recompute_stale_contributions') as mock_recompute:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.fetchall.return_value = mock_import_ids

                # First import fails, second succeeds
                mock_recompute.side_effect = [
                    Exception("Database error"),
                    RecomputationResult(
                        import_id=2,
                        nodes_updated=10,
                        nodes_skipped=0,
                        computation_time_ms=100.0,
                        strategy_used='incremental',
                    ),
                ]

                results = recompute_all_imports_stale()

                assert len(results) == 2
                assert results[1].success is False
                assert "Database error" in results[1].errors[0]
                assert results[2].success is True
