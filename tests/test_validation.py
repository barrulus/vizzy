"""Tests for data validation and integrity checks (Phase 8A-007)"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from vizzy.services.validation import (
    ValidationSeverity,
    ValidationCategory,
    ValidationIssue,
    ValidationResult,
    validate_edge_classification,
    validate_top_level_identification,
    validate_closure_contribution,
    validate_referential_integrity,
    validate_data_consistency,
    validate_import,
    validate_phase8a_fields,
    get_validation_summary,
)


class TestValidationIssue:
    """Test the ValidationIssue dataclass"""

    def test_basic_issue_creation(self):
        """Should create an issue with required fields"""
        issue = ValidationIssue(
            category=ValidationCategory.EDGE_CLASSIFICATION,
            severity=ValidationSeverity.ERROR,
            message="Test error message",
        )
        assert issue.category == ValidationCategory.EDGE_CLASSIFICATION
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.message == "Test error message"
        assert issue.affected_count == 0
        assert issue.details == {}
        assert issue.suggestion is None

    def test_issue_with_all_fields(self):
        """Should create an issue with all optional fields"""
        issue = ValidationIssue(
            category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
            severity=ValidationSeverity.WARNING,
            message="Test warning",
            affected_count=42,
            details={"key": "value"},
            suggestion="Fix this issue",
        )
        assert issue.affected_count == 42
        assert issue.details == {"key": "value"}
        assert issue.suggestion == "Fix this issue"


class TestValidationResult:
    """Test the ValidationResult dataclass"""

    def test_empty_result_passes(self):
        """Empty result should pass"""
        result = ValidationResult(
            import_id=1,
            validated_at=datetime.now(),
        )
        assert result.passed is True
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.info_count == 0

    def test_add_error_fails_result(self):
        """Adding an error should fail the result"""
        result = ValidationResult(
            import_id=1,
            validated_at=datetime.now(),
        )
        result.add_issue(ValidationIssue(
            category=ValidationCategory.EDGE_CLASSIFICATION,
            severity=ValidationSeverity.ERROR,
            message="Error",
        ))
        assert result.passed is False
        assert result.error_count == 1

    def test_add_warning_keeps_passing(self):
        """Adding a warning should not fail the result"""
        result = ValidationResult(
            import_id=1,
            validated_at=datetime.now(),
        )
        result.add_issue(ValidationIssue(
            category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
            severity=ValidationSeverity.WARNING,
            message="Warning",
        ))
        assert result.passed is True
        assert result.warning_count == 1

    def test_add_info_keeps_passing(self):
        """Adding info should not fail the result"""
        result = ValidationResult(
            import_id=1,
            validated_at=datetime.now(),
        )
        result.add_issue(ValidationIssue(
            category=ValidationCategory.CLOSURE_CONTRIBUTION,
            severity=ValidationSeverity.INFO,
            message="Info",
        ))
        assert result.passed is True
        assert result.info_count == 1

    def test_to_dict_serialization(self):
        """Should serialize to dictionary correctly"""
        result = ValidationResult(
            import_id=123,
            validated_at=datetime(2024, 1, 15, 12, 0, 0),
        )
        result.add_issue(ValidationIssue(
            category=ValidationCategory.EDGE_CLASSIFICATION,
            severity=ValidationSeverity.ERROR,
            message="Test",
            affected_count=5,
        ))

        d = result.to_dict()
        assert d["import_id"] == 123
        assert d["passed"] is False
        assert d["error_count"] == 1
        assert len(d["issues"]) == 1
        assert d["issues"][0]["category"] == "edge_classification"
        assert d["issues"][0]["severity"] == "error"


class TestValidateEdgeClassification:
    """Test edge classification validation"""

    def test_detects_null_dependency_type(self):
        """Should detect edges with NULL dependency_type"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            # Simulate NULL dependency_type values
            mock_cursor.fetchone.side_effect = [
                {'null_count': 100},  # 100 NULL edges
                {'unknown_count': 50, 'total_count': 200},  # stats query
            ]
            mock_cursor.fetchall.side_effect = [
                [],  # no invalid types
                [{'dependency_type': 'build', 'count': 50},
                 {'dependency_type': 'runtime', 'count': 100},
                 {'dependency_type': 'unknown', 'count': 50}],  # distribution
            ]

            validate_edge_classification(1, result)

        assert result.error_count == 1
        assert any("NULL dependency_type" in i.message for i in result.issues)

    def test_detects_invalid_dependency_type(self):
        """Should detect invalid dependency_type values"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'null_count': 0},
                {'unknown_count': 10, 'total_count': 100},
            ]
            mock_cursor.fetchall.side_effect = [
                [{'dependency_type': 'invalid_value', 'count': 5}],  # invalid type
                [],  # distribution
            ]

            validate_edge_classification(1, result)

        assert result.error_count == 1
        assert any("Invalid dependency_type" in i.message for i in result.issues)

    def test_warns_on_high_unknown_ratio(self):
        """Should warn when too many edges are classified as unknown"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'null_count': 0},
                {'unknown_count': 600, 'total_count': 1000},  # 60% unknown
            ]
            mock_cursor.fetchall.side_effect = [
                [],  # no invalid types
                [],  # distribution
            ]

            validate_edge_classification(1, result)

        assert result.warning_count >= 1
        assert any("High ratio" in i.message for i in result.issues)

    def test_passes_clean_data(self):
        """Should pass with valid edge classification data"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'null_count': 0},
                {'unknown_count': 50, 'total_count': 1000},  # 5% unknown - acceptable
            ]
            mock_cursor.fetchall.side_effect = [
                [],  # no invalid types
                [{'dependency_type': 'runtime', 'count': 700},
                 {'dependency_type': 'build', 'count': 250},
                 {'dependency_type': 'unknown', 'count': 50}],
            ]

            validate_edge_classification(1, result)

        assert result.error_count == 0
        assert result.warning_count == 0


class TestValidateTopLevelIdentification:
    """Test top-level identification validation"""

    def test_warns_on_no_top_level_nodes(self):
        """Should warn when no nodes are marked as top-level"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {
                'total_count': 1000,
                'top_level_count': 0,  # No top-level nodes
                'with_source_count': 0,
                'orphan_source_count': 0,
            }
            mock_cursor.fetchall.return_value = []

            validate_top_level_identification(1, result)

        assert result.warning_count >= 1
        assert any("No nodes marked as top-level" in i.message for i in result.issues)

    def test_errors_on_orphan_source(self):
        """Should error when top_level_source is set but is_top_level is FALSE"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {
                'total_count': 1000,
                'top_level_count': 50,
                'with_source_count': 50,
                'orphan_source_count': 10,  # 10 nodes with source but not top-level
            }
            mock_cursor.fetchall.return_value = []

            validate_top_level_identification(1, result)

        assert result.error_count >= 1
        assert any("top_level_source but is_top_level=FALSE" in i.message for i in result.issues)

    def test_warns_on_missing_source(self):
        """Should warn when top-level nodes don't have source set"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {
                'total_count': 1000,
                'top_level_count': 50,
                'with_source_count': 30,  # Only 30 of 50 have source
                'orphan_source_count': 0,
            }
            mock_cursor.fetchall.return_value = []

            validate_top_level_identification(1, result)

        assert result.warning_count >= 1
        assert any("without top_level_source" in i.message for i in result.issues)

    def test_warns_on_high_top_level_ratio(self):
        """Should warn when ratio of top-level nodes is unusually high"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {
                'total_count': 100,
                'top_level_count': 60,  # 60% top-level is suspicious
                'with_source_count': 60,
                'orphan_source_count': 0,
            }
            mock_cursor.fetchall.return_value = []

            validate_top_level_identification(1, result)

        assert result.warning_count >= 1
        assert any("Unusually high ratio" in i.message for i in result.issues)


class TestValidateClosureContribution:
    """Test closure contribution validation"""

    def test_info_on_not_computed(self):
        """Should report info when contributions not yet computed"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = {
                'top_level_count': 50,
                'with_unique': 0,  # Not computed
                'with_shared': 0,
                'with_total': 0,
                'with_timestamp': 0,
            }

            validate_closure_contribution(1, result)

        assert result.info_count >= 1
        assert any("not yet computed" in i.message for i in result.issues)

    def test_errors_on_negative_values(self):
        """Should error on negative contribution values"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {  # stats query
                    'top_level_count': 50,
                    'with_unique': 50,
                    'with_shared': 50,
                    'with_total': 50,
                    'with_timestamp': 50,
                },
                {'negative_count': 5},  # 5 negative values
                {'inconsistent_count': 0},
                {'invalid_count': 0},
                {  # summary stats
                    'sum_unique': 100,
                    'sum_shared': 200,
                    'avg_unique': 2.0,
                    'avg_shared': 4.0,
                    'max_unique': 10,
                    'max_total': 15,
                },
            ]

            validate_closure_contribution(1, result)

        assert result.error_count >= 1
        assert any("negative contribution" in i.message for i in result.issues)

    def test_errors_on_inconsistent_total(self):
        """Should error when total != unique + shared"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {  # stats query
                    'top_level_count': 50,
                    'with_unique': 50,
                    'with_shared': 50,
                    'with_total': 50,
                    'with_timestamp': 50,
                },
                {'negative_count': 0},
                {'inconsistent_count': 3},  # 3 inconsistent
                {'invalid_count': 0},
                {
                    'sum_unique': 100,
                    'sum_shared': 200,
                    'avg_unique': 2.0,
                    'avg_shared': 4.0,
                    'max_unique': 10,
                    'max_total': 15,
                },
            ]

            validate_closure_contribution(1, result)

        assert result.error_count >= 1
        assert any("total != unique + shared" in i.message for i in result.issues)


class TestValidateReferentialIntegrity:
    """Test referential integrity validation"""

    def test_errors_on_missing_import(self):
        """Should error when import doesn't exist"""
        result = ValidationResult(import_id=999, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.return_value = None  # Import not found

            validate_referential_integrity(999, result)

        assert result.error_count >= 1
        assert any("does not exist" in i.message for i in result.issues)

    def test_warns_on_count_mismatch(self):
        """Should warn when actual counts differ from recorded"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'id': 1, 'name': 'test', 'node_count': 1000, 'edge_count': 5000},
                {'actual_nodes': 950},  # Mismatch
                {'actual_edges': 5000},
                {'orphan_count': 0},
                {'orphan_count': 0},
                {'cross_count': 0},
            ]

            validate_referential_integrity(1, result)

        assert result.warning_count >= 1
        assert any("Node count mismatch" in i.message for i in result.issues)

    def test_errors_on_orphan_edges(self):
        """Should error when edges reference non-existent nodes"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'id': 1, 'name': 'test', 'node_count': 1000, 'edge_count': 5000},
                {'actual_nodes': 1000},
                {'actual_edges': 5000},
                {'orphan_count': 10},  # 10 orphan source refs
                {'orphan_count': 5},   # 5 orphan target refs
                {'cross_count': 0},
            ]

            validate_referential_integrity(1, result)

        assert result.error_count >= 2
        assert any("invalid source_id" in i.message for i in result.issues)
        assert any("invalid target_id" in i.message for i in result.issues)


class TestValidateDataConsistency:
    """Test data consistency validation"""

    def test_warns_on_self_referencing_edges(self):
        """Should warn on self-referencing edges"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'self_ref_count': 3},  # 3 self-refs
                {'negative_depth': 0},
                {'negative_closure': 0},
                {'empty_hash': 0},
                {'empty_label': 0},
                {'total': 1000, 'with_depth': 1000, 'with_closure': 1000},
            ]

            validate_data_consistency(1, result)

        assert result.warning_count >= 1
        assert any("self-referencing" in i.message for i in result.issues)

    def test_errors_on_negative_depth(self):
        """Should error on negative depth values"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'self_ref_count': 0},
                {'negative_depth': 5},  # 5 negative depth
                {'negative_closure': 0},
                {'empty_hash': 0},
                {'empty_label': 0},
                {'total': 1000, 'with_depth': 1000, 'with_closure': 1000},
            ]

            validate_data_consistency(1, result)

        assert result.error_count >= 1
        assert any("negative depth" in i.message for i in result.issues)

    def test_errors_on_empty_hash(self):
        """Should error on empty drv_hash"""
        result = ValidationResult(import_id=1, validated_at=datetime.now())

        with patch('vizzy.services.validation.get_db') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            mock_cursor.fetchone.side_effect = [
                {'self_ref_count': 0},
                {'negative_depth': 0},
                {'negative_closure': 0},
                {'empty_hash': 2},  # 2 empty hashes
                {'empty_label': 0},
                {'total': 1000, 'with_depth': 1000, 'with_closure': 1000},
            ]

            validate_data_consistency(1, result)

        assert result.error_count >= 1
        assert any("empty or NULL drv_hash" in i.message for i in result.issues)


class TestValidateImport:
    """Test the main validate_import function"""

    def test_runs_all_categories_by_default(self):
        """Should run all validation categories"""
        with patch('vizzy.services.validation.validate_referential_integrity') as mock_ref:
            with patch('vizzy.services.validation.validate_data_consistency') as mock_data:
                with patch('vizzy.services.validation.validate_edge_classification') as mock_edge:
                    with patch('vizzy.services.validation.validate_top_level_identification') as mock_top:
                        with patch('vizzy.services.validation.validate_closure_contribution') as mock_closure:
                            result = validate_import(1)

                            assert mock_ref.called
                            assert mock_data.called
                            assert mock_edge.called
                            assert mock_top.called
                            assert mock_closure.called

    def test_respects_skip_categories(self):
        """Should skip specified categories"""
        with patch('vizzy.services.validation.validate_referential_integrity') as mock_ref:
            with patch('vizzy.services.validation.validate_data_consistency') as mock_data:
                with patch('vizzy.services.validation.validate_edge_classification') as mock_edge:
                    with patch('vizzy.services.validation.validate_top_level_identification') as mock_top:
                        with patch('vizzy.services.validation.validate_closure_contribution') as mock_closure:
                            result = validate_import(
                                1,
                                skip_categories=[
                                    ValidationCategory.REFERENTIAL_INTEGRITY,
                                    ValidationCategory.DATA_CONSISTENCY,
                                ]
                            )

                            assert not mock_ref.called
                            assert not mock_data.called
                            assert mock_edge.called
                            assert mock_top.called
                            assert mock_closure.called


class TestValidatePhase8aFields:
    """Test the Phase 8A focused validation function"""

    def test_only_validates_phase8a_categories(self):
        """Should only validate Phase 8A specific fields"""
        with patch('vizzy.services.validation.validate_referential_integrity') as mock_ref:
            with patch('vizzy.services.validation.validate_data_consistency') as mock_data:
                with patch('vizzy.services.validation.validate_edge_classification') as mock_edge:
                    with patch('vizzy.services.validation.validate_top_level_identification') as mock_top:
                        with patch('vizzy.services.validation.validate_closure_contribution') as mock_closure:
                            result = validate_phase8a_fields(1)

                            # Should NOT run these
                            assert not mock_ref.called
                            assert not mock_data.called

                            # SHOULD run these (Phase 8A specific)
                            assert mock_edge.called
                            assert mock_top.called
                            assert mock_closure.called


class TestGetValidationSummary:
    """Test the validation summary function"""

    def test_returns_summary_dict(self):
        """Should return a summary dictionary"""
        with patch('vizzy.services.validation.validate_import') as mock_validate:
            mock_result = ValidationResult(
                import_id=1,
                validated_at=datetime(2024, 1, 15, 12, 0, 0),
            )
            mock_result.add_issue(ValidationIssue(
                category=ValidationCategory.EDGE_CLASSIFICATION,
                severity=ValidationSeverity.WARNING,
                message="Test warning",
            ))
            mock_validate.return_value = mock_result

            summary = get_validation_summary(1)

            assert summary["import_id"] == 1
            assert summary["passed"] is True
            assert summary["error_count"] == 0
            assert summary["warning_count"] == 1
            assert summary["info_count"] == 0
            assert "categories_checked" in summary
            assert "validated_at" in summary
