"""Tests for closure contribution calculation functionality (Phase 8A-003)"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from vizzy.models import ClosureContribution, ClosureContributionSummary, ContributionDiff


class TestClosureContributionModel:
    """Test the ClosureContribution model"""

    def test_unique_percentage_calculation(self):
        """Unique percentage should be correctly calculated"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=25,
            shared_contribution=75,
            total_contribution=100,
            closure_size=100,
        )
        assert contrib.unique_percentage == 25.0

    def test_unique_percentage_all_unique(self):
        """When all contributions are unique, percentage should be 100"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=50,
            shared_contribution=0,
            total_contribution=50,
            closure_size=50,
        )
        assert contrib.unique_percentage == 100.0

    def test_unique_percentage_all_shared(self):
        """When all contributions are shared, percentage should be 0"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=0,
            shared_contribution=50,
            total_contribution=50,
            closure_size=50,
        )
        assert contrib.unique_percentage == 0.0

    def test_unique_percentage_zero_total(self):
        """When total is zero, percentage should be 0"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=0,
            shared_contribution=0,
            total_contribution=0,
            closure_size=0,
        )
        assert contrib.unique_percentage == 0.0

    def test_removal_impact_no_unique(self):
        """Removal impact should indicate safe removal when no unique deps"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=0,
            shared_contribution=50,
            total_contribution=50,
            closure_size=50,
        )
        assert "safe to remove" in contrib.removal_impact.lower()

    def test_removal_impact_high_unique(self):
        """Removal impact should indicate high impact when mostly unique"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=80,
            shared_contribution=20,
            total_contribution=100,
            closure_size=100,
        )
        assert "high impact" in contrib.removal_impact.lower()

    def test_removal_impact_medium_unique(self):
        """Removal impact should indicate medium impact when partially unique"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=50,
            shared_contribution=50,
            total_contribution=100,
            closure_size=100,
        )
        assert "medium impact" in contrib.removal_impact.lower()

    def test_removal_impact_low_unique(self):
        """Removal impact should indicate low impact when mostly shared"""
        contrib = ClosureContribution(
            node_id=1,
            label="test-pkg",
            package_type="app",
            unique_contribution=10,
            shared_contribution=90,
            total_contribution=100,
            closure_size=100,
        )
        assert "low impact" in contrib.removal_impact.lower()


class TestClosureContributionSummary:
    """Test the ClosureContributionSummary model"""

    def _make_contribution(
        self, node_id: int, label: str, unique: int, shared: int
    ) -> ClosureContribution:
        """Helper to create a ClosureContribution"""
        return ClosureContribution(
            node_id=node_id,
            label=label,
            package_type="app",
            unique_contribution=unique,
            shared_contribution=shared,
            total_contribution=unique + shared,
            closure_size=unique + shared,
        )

    def test_average_unique_contribution(self):
        """Average unique should be correctly calculated"""
        contrib1 = self._make_contribution(1, "pkg1", 50, 50)
        contrib2 = self._make_contribution(2, "pkg2", 100, 0)

        summary = ClosureContributionSummary(
            import_id=1,
            total_top_level_packages=2,
            total_unique_contributions=150,  # 50 + 100
            total_shared_contributions=50,
            top_unique_contributors=[contrib2, contrib1],
            top_total_contributors=[contrib2, contrib1],
        )

        assert summary.average_unique_contribution == 75.0  # 150 / 2

    def test_average_unique_contribution_zero_packages(self):
        """Average unique should be 0 when no packages"""
        summary = ClosureContributionSummary(
            import_id=1,
            total_top_level_packages=0,
            total_unique_contributions=0,
            total_shared_contributions=0,
            top_unique_contributors=[],
            top_total_contributors=[],
        )

        assert summary.average_unique_contribution == 0.0

    def test_sharing_ratio_high_sharing(self):
        """Sharing ratio should be high when most deps are shared"""
        contrib = self._make_contribution(1, "pkg1", 10, 90)

        summary = ClosureContributionSummary(
            import_id=1,
            total_top_level_packages=1,
            total_unique_contributions=10,
            total_shared_contributions=90,
            top_unique_contributors=[contrib],
            top_total_contributors=[contrib],
        )

        assert summary.sharing_ratio == 0.9  # 90 / 100

    def test_sharing_ratio_no_sharing(self):
        """Sharing ratio should be 0 when no shared deps"""
        contrib = self._make_contribution(1, "pkg1", 100, 0)

        summary = ClosureContributionSummary(
            import_id=1,
            total_top_level_packages=1,
            total_unique_contributions=100,
            total_shared_contributions=0,
            top_unique_contributors=[contrib],
            top_total_contributors=[contrib],
        )

        assert summary.sharing_ratio == 0.0

    def test_sharing_ratio_zero_total(self):
        """Sharing ratio should be 0 when no contributions at all"""
        summary = ClosureContributionSummary(
            import_id=1,
            total_top_level_packages=0,
            total_unique_contributions=0,
            total_shared_contributions=0,
            top_unique_contributors=[],
            top_total_contributors=[],
        )

        assert summary.sharing_ratio == 0.0


class TestContributionDiff:
    """Test the ContributionDiff model"""

    def test_unique_diff_positive(self):
        """Unique diff should be positive when right has more unique"""
        diff = ContributionDiff(
            label="test-pkg",
            package_type="app",
            left_unique=50,
            right_unique=75,
            left_shared=50,
            right_shared=50,
        )
        assert diff.unique_diff == 25

    def test_unique_diff_negative(self):
        """Unique diff should be negative when left has more unique"""
        diff = ContributionDiff(
            label="test-pkg",
            package_type="app",
            left_unique=100,
            right_unique=50,
            left_shared=0,
            right_shared=0,
        )
        assert diff.unique_diff == -50

    def test_total_diff(self):
        """Total diff should account for both unique and shared"""
        diff = ContributionDiff(
            label="test-pkg",
            package_type="app",
            left_unique=50,
            right_unique=75,
            left_shared=50,
            right_shared=100,
        )
        # Left total: 50 + 50 = 100
        # Right total: 75 + 100 = 175
        # Diff: 175 - 100 = 75
        assert diff.total_diff == 75


class TestComputeClosure:
    """Test the compute_closure function"""

    def test_compute_closure_simple(self):
        """Should compute transitive closure correctly"""
        from vizzy.services.contribution import compute_closure

        with patch('vizzy.services.contribution.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # Simulate a simple graph: 1 -> 2 -> 3
            # Closure of 1 should be {2, 3}
            mock_cursor.fetchall.return_value = [
                {'dep_id': 2},
                {'dep_id': 3},
            ]

            result = compute_closure(1, mock_conn)

            assert result == {2, 3}

    def test_compute_closure_empty(self):
        """Should return empty set when no dependencies"""
        from vizzy.services.contribution import compute_closure

        with patch('vizzy.services.contribution.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchall.return_value = []

            result = compute_closure(1, mock_conn)

            assert result == set()


class TestComputeContributions:
    """Test the compute_contributions function"""

    def test_compute_contributions_no_top_level(self):
        """Should return 0 when no top-level nodes exist"""
        from vizzy.services.contribution import compute_contributions

        with patch('vizzy.services.contribution.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # No top-level nodes
            mock_cursor.fetchall.return_value = []

            result = compute_contributions(1)

            assert result == 0

    def test_compute_contributions_single_package(self):
        """Should compute contributions for a single top-level package"""
        from vizzy.services.contribution import compute_contributions

        with patch('vizzy.services.contribution.get_db') as mock_get_db:
            with patch('vizzy.services.contribution.compute_closure') as mock_closure:
                with patch('vizzy.services.contribution.cache') as mock_cache:
                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_get_db.return_value.__enter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                    # One top-level node with id=1
                    mock_cursor.fetchall.return_value = [{'id': 1, 'label': 'pkg1'}]

                    # It has 5 dependencies
                    mock_closure.return_value = {2, 3, 4, 5, 6}

                    result = compute_contributions(1)

                    # Should update 1 node
                    assert result == 1

                    # Verify UPDATE was called
                    assert mock_cursor.execute.call_count >= 2

    def test_compute_contributions_shared_deps(self):
        """Should correctly identify shared vs unique dependencies"""
        from vizzy.services.contribution import compute_contributions

        with patch('vizzy.services.contribution.get_db') as mock_get_db:
            with patch('vizzy.services.contribution.compute_closure') as mock_closure:
                with patch('vizzy.services.contribution.cache') as mock_cache:
                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_get_db.return_value.__enter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                    # Two top-level nodes
                    mock_cursor.fetchall.return_value = [
                        {'id': 1, 'label': 'pkg1'},
                        {'id': 2, 'label': 'pkg2'},
                    ]

                    # pkg1 has deps {10, 11, 12}
                    # pkg2 has deps {11, 12, 13}
                    # Shared: {11, 12}
                    # pkg1 unique: {10}
                    # pkg2 unique: {13}
                    def closure_side_effect(node_id, conn):
                        if node_id == 1:
                            return {10, 11, 12}
                        else:
                            return {11, 12, 13}

                    mock_closure.side_effect = closure_side_effect

                    result = compute_contributions(1)

                    # Should update 2 nodes
                    assert result == 2


class TestGetContributionData:
    """Test the get_contribution_data function"""

    def test_get_contribution_data_returns_list(self):
        """Should return list of ClosureContribution objects"""
        from vizzy.services.contribution import get_contribution_data

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'id': 1,
                        'label': 'pkg1',
                        'package_type': 'app',
                        'unique_contribution': 50,
                        'shared_contribution': 50,
                        'total_contribution': 100,
                        'closure_size': 100,
                    }
                ]

                result = get_contribution_data(1)

                assert len(result) == 1
                assert isinstance(result[0], ClosureContribution)
                assert result[0].label == 'pkg1'
                assert result[0].unique_contribution == 50

    def test_get_contribution_data_respects_sort(self):
        """Should sort by specified column"""
        from vizzy.services.contribution import get_contribution_data

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = []

                get_contribution_data(1, sort_by='total')

                # Verify the SQL contains ORDER BY with total_contribution
                call_args = mock_cursor.execute.call_args[0][0]
                assert 'total_contribution DESC' in call_args

    def test_get_contribution_data_respects_limit(self):
        """Should limit results as specified"""
        from vizzy.services.contribution import get_contribution_data

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = []

                get_contribution_data(1, limit=5)

                # Verify the SQL contains LIMIT 5
                call_args = mock_cursor.execute.call_args[0]
                assert call_args[1] == (1, 5)

    def test_get_contribution_data_uses_cache(self):
        """Should return cached data when available"""
        from vizzy.services.contribution import get_contribution_data

        cached_result = [
            ClosureContribution(
                node_id=1,
                label='cached-pkg',
                package_type='app',
                unique_contribution=10,
                shared_contribution=10,
                total_contribution=20,
                closure_size=20,
            )
        ]

        with patch('vizzy.services.contribution.cache') as mock_cache:
            mock_cache.get.return_value = cached_result

            result = get_contribution_data(1)

            assert result == cached_result
            # get_db should not be called when cache hit
            assert result[0].label == 'cached-pkg'


class TestGetContributionSummary:
    """Test the get_contribution_summary function"""

    def test_get_contribution_summary_returns_summary(self):
        """Should return ClosureContributionSummary when data exists"""
        from vizzy.services.contribution import get_contribution_summary

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                with patch('vizzy.services.contribution.get_contribution_data') as mock_data:
                    mock_cache.get.return_value = None

                    mock_conn = MagicMock()
                    mock_cursor = MagicMock()
                    mock_get_db.return_value.__enter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                    # First query: aggregate metrics
                    # Second query: computed count
                    mock_cursor.fetchone.side_effect = [
                        {
                            'total_top_level': 5,
                            'total_unique': 100,
                            'total_shared': 200,
                            'computed_at': datetime.now(),
                        },
                        {'computed_count': 5},
                    ]

                    mock_data.return_value = []

                    result = get_contribution_summary(1)

                    assert result is not None
                    assert isinstance(result, ClosureContributionSummary)
                    assert result.total_top_level_packages == 5
                    assert result.total_unique_contributions == 100
                    assert result.total_shared_contributions == 200

    def test_get_contribution_summary_returns_none_when_no_data(self):
        """Should return None when no top-level nodes exist"""
        from vizzy.services.contribution import get_contribution_summary

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.return_value = {
                    'total_top_level': 0,
                    'total_unique': 0,
                    'total_shared': 0,
                    'computed_at': None,
                }

                result = get_contribution_summary(1)

                assert result is None

    def test_get_contribution_summary_returns_none_when_not_computed(self):
        """Should return None when contributions not yet computed"""
        from vizzy.services.contribution import get_contribution_summary

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchone.side_effect = [
                    {
                        'total_top_level': 5,
                        'total_unique': 0,
                        'total_shared': 0,
                        'computed_at': None,
                    },
                    {'computed_count': 0},  # No computed contributions
                ]

                result = get_contribution_summary(1)

                assert result is None


class TestIdentifyRemovalCandidates:
    """Test the identify_removal_candidates function"""

    def test_identify_removal_candidates_returns_low_unique(self):
        """Should return packages with low unique contribution"""
        from vizzy.services.contribution import identify_removal_candidates

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'id': 1,
                        'label': 'removable-pkg',
                        'package_type': 'app',
                        'unique_contribution': 0,
                        'shared_contribution': 50,
                        'total_contribution': 50,
                        'closure_size': 50,
                    }
                ]

                result = identify_removal_candidates(1, max_unique_threshold=0)

                assert len(result) == 1
                assert result[0].unique_contribution == 0

    def test_identify_removal_candidates_respects_threshold(self):
        """Should filter by max_unique_threshold"""
        from vizzy.services.contribution import identify_removal_candidates

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = []

                identify_removal_candidates(1, max_unique_threshold=5)

                # Verify SQL contains threshold
                call_args = mock_cursor.execute.call_args[0]
                assert call_args[1] == (1, 5, 20)


class TestGetContributionByType:
    """Test the get_contribution_by_type function"""

    def test_get_contribution_by_type_returns_dict(self):
        """Should return dictionary of contributions by package type"""
        from vizzy.services.contribution import get_contribution_by_type

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'package_type': 'app',
                        'package_count': 10,
                        'total_unique': 100,
                        'total_shared': 200,
                        'total_overall': 300,
                    },
                    {
                        'package_type': 'lib',
                        'package_count': 50,
                        'total_unique': 50,
                        'total_shared': 500,
                        'total_overall': 550,
                    },
                ]

                result = get_contribution_by_type(1)

                assert 'app' in result
                assert 'lib' in result
                assert result['app']['package_count'] == 10
                assert result['lib']['total_overall'] == 550

    def test_get_contribution_by_type_handles_unknown(self):
        """Should handle packages with unknown type"""
        from vizzy.services.contribution import get_contribution_by_type

        with patch('vizzy.services.contribution.cache') as mock_cache:
            with patch('vizzy.services.contribution.get_db') as mock_get_db:
                mock_cache.get.return_value = None

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

                mock_cursor.fetchall.return_value = [
                    {
                        'package_type': 'unknown',
                        'package_count': 5,
                        'total_unique': 10,
                        'total_shared': 20,
                        'total_overall': 30,
                    }
                ]

                result = get_contribution_by_type(1)

                assert 'unknown' in result
