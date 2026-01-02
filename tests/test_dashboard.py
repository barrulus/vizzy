"""Tests for dashboard metrics API endpoints (Task 8B-002).

These tests verify that the dashboard API endpoints return the correct
schema and handle edge cases properly.
"""

import pytest
from unittest.mock import patch, MagicMock

from vizzy.services.dashboard import (
    DashboardSummary,
    DepthStats,
    TopContributor,
    TypeDistributionEntry,
    get_dashboard_summary,
    get_top_contributors,
    get_type_distribution,
    get_health_indicators,
)


# =============================================================================
# Dashboard Service Unit Tests
# =============================================================================


class TestDashboardSummary:
    """Tests for DashboardSummary dataclass."""

    def test_summary_creation(self):
        """Test creating a DashboardSummary with all fields."""
        depth_stats = DepthStats(max_depth=10, avg_depth=4.5, median_depth=4.0)
        summary = DashboardSummary(
            import_id=1,
            total_nodes=45000,
            total_edges=120000,
            redundancy_score=0.12,
            runtime_ratio=0.67,
            depth_stats=depth_stats,
        )

        assert summary.import_id == 1
        assert summary.total_nodes == 45000
        assert summary.total_edges == 120000
        assert summary.redundancy_score == 0.12
        assert summary.runtime_ratio == 0.67
        assert summary.depth_stats.max_depth == 10
        assert summary.baseline_comparison is None


class TestDepthStats:
    """Tests for DepthStats dataclass."""

    def test_depth_stats_creation(self):
        """Test creating DepthStats."""
        stats = DepthStats(max_depth=15, avg_depth=5.2, median_depth=4.5)

        assert stats.max_depth == 15
        assert stats.avg_depth == 5.2
        assert stats.median_depth == 4.5


class TestTopContributor:
    """Tests for TopContributor dataclass."""

    def test_top_contributor_creation(self):
        """Test creating a TopContributor."""
        contributor = TopContributor(
            node_id=123,
            label="firefox",
            closure_size=2340,
            package_type="application",
            unique_contribution=1200,
        )

        assert contributor.node_id == 123
        assert contributor.label == "firefox"
        assert contributor.closure_size == 2340
        assert contributor.package_type == "application"
        assert contributor.unique_contribution == 1200


class TestTypeDistributionEntry:
    """Tests for TypeDistributionEntry dataclass."""

    def test_type_distribution_creation(self):
        """Test creating a TypeDistributionEntry."""
        entry = TypeDistributionEntry(
            package_type="library",
            count=20000,
            percentage=45.5,
            total_closure_size=150000,
        )

        assert entry.package_type == "library"
        assert entry.count == 20000
        assert entry.percentage == 45.5
        assert entry.total_closure_size == 150000


# =============================================================================
# Dashboard Service Function Tests (Mocked DB)
# =============================================================================


class TestGetDashboardSummary:
    """Tests for get_dashboard_summary function."""

    @patch('vizzy.services.dashboard.get_db')
    @patch('vizzy.services.dashboard.cache')
    def test_returns_none_for_missing_import(self, mock_cache, mock_get_db):
        """Test that None is returned when import doesn't exist."""
        mock_cache.get.return_value = None
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        result = get_dashboard_summary(999)

        assert result is None

    @patch('vizzy.services.dashboard.get_db')
    @patch('vizzy.services.dashboard.cache')
    def test_returns_cached_summary(self, mock_cache, mock_get_db):
        """Test that cached summary is returned when available."""
        cached_summary = DashboardSummary(
            import_id=1,
            total_nodes=100,
            total_edges=200,
            redundancy_score=0.05,
            runtime_ratio=0.8,
            depth_stats=DepthStats(max_depth=5, avg_depth=2.5, median_depth=2.0),
        )
        mock_cache.get.return_value = cached_summary

        result = get_dashboard_summary(1)

        assert result == cached_summary
        mock_get_db.assert_not_called()


class TestGetTopContributors:
    """Tests for get_top_contributors function."""

    @patch('vizzy.services.dashboard.get_db')
    @patch('vizzy.services.dashboard.cache')
    def test_returns_cached_contributors(self, mock_cache, mock_get_db):
        """Test that cached contributors are returned when available."""
        cached_contributors = [
            TopContributor(
                node_id=1, label="firefox", closure_size=2340,
                package_type="application", unique_contribution=1200
            )
        ]
        mock_cache.get.return_value = cached_contributors

        result = get_top_contributors(1, limit=10)

        assert result == cached_contributors
        mock_get_db.assert_not_called()


class TestGetTypeDistribution:
    """Tests for get_type_distribution function."""

    @patch('vizzy.services.dashboard.get_db')
    @patch('vizzy.services.dashboard.cache')
    def test_returns_cached_distribution(self, mock_cache, mock_get_db):
        """Test that cached distribution is returned when available."""
        cached_distribution = [
            TypeDistributionEntry(
                package_type="library", count=20000,
                percentage=45.0, total_closure_size=150000
            )
        ]
        mock_cache.get.return_value = cached_distribution

        result = get_type_distribution(1)

        assert result == cached_distribution
        mock_get_db.assert_not_called()


class TestGetHealthIndicators:
    """Tests for get_health_indicators function."""

    @patch('vizzy.services.dashboard.get_dashboard_summary')
    def test_returns_empty_for_missing_summary(self, mock_get_summary):
        """Test that empty dict is returned when summary is None."""
        mock_get_summary.return_value = None

        result = get_health_indicators(999)

        assert result == {}

    @patch('vizzy.services.dashboard.get_dashboard_summary')
    def test_returns_good_status_for_low_redundancy(self, mock_get_summary):
        """Test that good status is returned for low redundancy."""
        mock_get_summary.return_value = DashboardSummary(
            import_id=1,
            total_nodes=1000,
            total_edges=2000,
            redundancy_score=0.03,  # 3% - should be "good"
            runtime_ratio=0.7,
            depth_stats=DepthStats(max_depth=10, avg_depth=3.0, median_depth=2.5),
        )

        result = get_health_indicators(1)

        assert result['redundancy']['status'] == 'good'

    @patch('vizzy.services.dashboard.get_dashboard_summary')
    def test_returns_warning_status_for_medium_redundancy(self, mock_get_summary):
        """Test that warning status is returned for medium redundancy."""
        mock_get_summary.return_value = DashboardSummary(
            import_id=1,
            total_nodes=1000,
            total_edges=2000,
            redundancy_score=0.07,  # 7% - should be "warning"
            runtime_ratio=0.7,
            depth_stats=DepthStats(max_depth=10, avg_depth=3.0, median_depth=2.5),
        )

        result = get_health_indicators(1)

        assert result['redundancy']['status'] == 'warning'

    @patch('vizzy.services.dashboard.get_dashboard_summary')
    def test_returns_critical_status_for_high_redundancy(self, mock_get_summary):
        """Test that critical status is returned for high redundancy."""
        mock_get_summary.return_value = DashboardSummary(
            import_id=1,
            total_nodes=1000,
            total_edges=2000,
            redundancy_score=0.15,  # 15% - should be "critical"
            runtime_ratio=0.7,
            depth_stats=DepthStats(max_depth=10, avg_depth=3.0, median_depth=2.5),
        )

        result = get_health_indicators(1)

        assert result['redundancy']['status'] == 'critical'


# =============================================================================
# API Response Schema Tests
# =============================================================================


class TestAPIResponseSchemas:
    """Tests for API response models."""

    def test_dashboard_summary_response_schema(self):
        """Verify DashboardSummaryResponse matches spec."""
        from vizzy.routes.api import (
            DashboardSummaryResponse,
            DepthStatsResponse,
        )

        response = DashboardSummaryResponse(
            total_nodes=45234,
            total_edges=123456,
            redundancy_score=0.123,
            build_runtime_ratio=0.67,
            depth_stats=DepthStatsResponse(max=12, avg=4.2, median=4.0),
            baseline_comparison=None,
        )

        # Verify schema matches designs/dashboard-spec.md
        assert response.total_nodes == 45234
        assert response.total_edges == 123456
        assert response.redundancy_score == 0.123
        assert response.build_runtime_ratio == 0.67
        assert response.depth_stats.max == 12
        assert response.depth_stats.avg == 4.2
        assert response.depth_stats.median == 4.0
        assert response.baseline_comparison is None

    def test_top_contributor_response_schema(self):
        """Verify TopContributorResponse matches spec."""
        from vizzy.routes.api import TopContributorResponse

        response = TopContributorResponse(
            node_id=123,
            label="firefox",
            closure_size=2340,
            package_type="application",
            unique_contribution=1200,
        )

        # Verify schema matches designs/dashboard-spec.md
        assert response.node_id == 123
        assert response.label == "firefox"
        assert response.closure_size == 2340
        assert response.package_type == "application"
        assert response.unique_contribution == 1200

    def test_type_distribution_response_schema(self):
        """Verify TypeDistributionResponse matches spec."""
        from vizzy.routes.api import (
            TypeDistributionResponse,
            TypeDistributionEntryResponse,
        )

        response = TypeDistributionResponse(
            types=[
                TypeDistributionEntryResponse(type="library", count=20000, percentage=45.0),
                TypeDistributionEntryResponse(type="application", count=11000, percentage=25.0),
            ]
        )

        # Verify schema matches designs/dashboard-spec.md
        assert len(response.types) == 2
        assert response.types[0].type == "library"
        assert response.types[0].count == 20000
        assert response.types[0].percentage == 45.0
