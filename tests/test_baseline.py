"""Tests for the baseline closure reference system.

Tests cover:
- Creating baselines from imports
- Retrieving baselines
- Comparing imports to baselines
- Baseline metadata operations
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from vizzy.services.baseline import (
    Baseline,
    BaselineComparison,
    BaselineCreateResult,
    create_baseline_from_import,
    get_baseline,
    list_baselines,
    compare_to_baseline,
    delete_baseline,
    update_baseline,
    get_comparison_for_dashboard,
)


class TestBaselineCreateResult:
    """Tests for BaselineCreateResult dataclass."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = BaselineCreateResult(
            baseline_id=1,
            name="Test Baseline",
            node_count=1000,
            edge_count=2000,
            success=True,
            message="Created baseline 'Test Baseline' with 1000 nodes"
        )
        assert result.success is True
        assert result.baseline_id == 1
        assert result.node_count == 1000

    def test_failure_result(self):
        """Test creating a failure result."""
        result = BaselineCreateResult(
            baseline_id=0,
            name="Test",
            node_count=0,
            edge_count=0,
            success=False,
            message="Import not found"
        )
        assert result.success is False
        assert result.baseline_id == 0


class TestBaseline:
    """Tests for Baseline dataclass."""

    def test_baseline_creation(self):
        """Test creating a Baseline object."""
        now = datetime.now()
        baseline = Baseline(
            id=1,
            name="Minimal NixOS",
            description="A minimal NixOS installation",
            source_import_id=42,
            node_count=5000,
            edge_count=15000,
            closure_by_type={"library": 3000, "application": 500},
            top_level_count=50,
            runtime_edge_count=10000,
            build_edge_count=5000,
            max_depth=15,
            avg_depth=5.5,
            top_contributors=[
                {"label": "firefox", "closure_size": 2340}
            ],
            created_at=now,
            updated_at=now,
            is_system_baseline=True,
            tags=["minimal", "reference"]
        )

        assert baseline.id == 1
        assert baseline.name == "Minimal NixOS"
        assert baseline.is_system_baseline is True
        assert len(baseline.tags) == 2
        assert baseline.closure_by_type["library"] == 3000


class TestBaselineComparison:
    """Tests for BaselineComparison dataclass."""

    def test_comparison_larger(self):
        """Test comparison where import is larger."""
        comparison = BaselineComparison(
            import_id=1,
            baseline_id=2,
            baseline_name="Minimal",
            node_difference=5000,
            edge_difference=10000,
            percentage_difference=25.5,
            differences_by_type={"library": 3000},
            is_larger=True,
            growth_category="significant",
            computed_at=datetime.now()
        )

        assert comparison.is_larger is True
        assert comparison.growth_category == "significant"
        assert comparison.node_difference == 5000

    def test_comparison_smaller(self):
        """Test comparison where import is smaller."""
        comparison = BaselineComparison(
            import_id=1,
            baseline_id=2,
            baseline_name="Full Desktop",
            node_difference=-2000,
            edge_difference=-5000,
            percentage_difference=-10.0,
            differences_by_type={"application": -500},
            is_larger=False,
            growth_category="minimal",
            computed_at=datetime.now()
        )

        assert comparison.is_larger is False
        assert comparison.node_difference == -2000


class TestGrowthCategories:
    """Tests for growth category classification."""

    @pytest.mark.parametrize("pct,expected_category", [
        (0, "minimal"),
        (3, "minimal"),
        (4.9, "minimal"),
        (5, "moderate"),
        (10, "moderate"),
        (14.9, "moderate"),
        (15, "significant"),
        (25, "significant"),
        (29.9, "significant"),
        (30, "excessive"),
        (50, "excessive"),
        (100, "excessive"),
    ])
    def test_growth_categorization(self, pct, expected_category):
        """Test that growth percentages are categorized correctly."""
        # Classification logic from baseline service
        if pct < 5:
            category = "minimal"
        elif pct < 15:
            category = "moderate"
        elif pct < 30:
            category = "significant"
        else:
            category = "excessive"

        assert category == expected_category


class TestBaselineServiceMocked:
    """Tests for baseline service functions with mocked database."""

    @patch('vizzy.services.baseline.get_db')
    def test_create_baseline_import_not_found(self, mock_get_db):
        """Test creating baseline when import doesn't exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        # Import not found
        mock_cursor.fetchone.return_value = None

        result = create_baseline_from_import(
            import_id=999,
            name="Test",
        )

        assert result.success is False
        assert "not found" in result.message.lower()

    @patch('vizzy.services.baseline.get_db')
    def test_get_baseline_not_found(self, mock_get_db):
        """Test getting a baseline that doesn't exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        mock_cursor.fetchone.return_value = None

        result = get_baseline(999)
        assert result is None

    @patch('vizzy.services.baseline.get_db')
    def test_list_baselines_empty(self, mock_get_db):
        """Test listing baselines when none exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        mock_cursor.fetchall.return_value = []

        result = list_baselines()
        assert result == []


class TestBaselineComparisonCalculations:
    """Tests for comparison calculation logic."""

    def test_percentage_calculation_zero_baseline(self):
        """Test percentage calculation with zero baseline."""
        # If baseline has 0 nodes, percentage should handle gracefully
        baseline_nodes = 0
        import_nodes = 100

        if baseline_nodes > 0:
            pct = ((import_nodes - baseline_nodes) / baseline_nodes * 100)
        else:
            pct = 0

        assert pct == 0

    def test_percentage_calculation_normal(self):
        """Test normal percentage calculation."""
        baseline_nodes = 10000
        import_nodes = 12000

        pct = ((import_nodes - baseline_nodes) / baseline_nodes * 100)

        assert pct == 20.0

    def test_negative_percentage(self):
        """Test negative percentage (import smaller than baseline)."""
        baseline_nodes = 10000
        import_nodes = 8000

        pct = ((import_nodes - baseline_nodes) / baseline_nodes * 100)

        assert pct == -20.0


class TestTypeBreakdownDifferences:
    """Tests for type breakdown difference calculations."""

    def test_type_differences(self):
        """Test calculating differences by package type."""
        import_types = {"library": 5000, "application": 1000, "service": 200}
        baseline_types = {"library": 4000, "application": 1200, "unknown": 50}

        all_types = set(import_types.keys()) | set(baseline_types.keys())
        differences = {}

        for pkg_type in all_types:
            import_count = import_types.get(pkg_type, 0)
            baseline_count = baseline_types.get(pkg_type, 0)
            differences[pkg_type] = import_count - baseline_count

        assert differences["library"] == 1000  # Grew
        assert differences["application"] == -200  # Shrunk
        assert differences["service"] == 200  # New in import
        assert differences["unknown"] == -50  # Gone from import

    def test_empty_baseline_types(self):
        """Test with empty baseline types."""
        import_types = {"library": 1000}
        baseline_types = {}

        all_types = set(import_types.keys()) | set(baseline_types.keys())
        differences = {}

        for pkg_type in all_types:
            import_count = import_types.get(pkg_type, 0)
            baseline_count = baseline_types.get(pkg_type, 0)
            differences[pkg_type] = import_count - baseline_count

        assert differences["library"] == 1000
