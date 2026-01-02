"""Data validation and integrity checks for Phase 8A fields.

This module provides validation functions to ensure data integrity for the
Phase 8A enhancements:
- Edge classification (build-time vs runtime dependencies)
- Top-level package identification
- Closure contribution calculation

These validations can be run after import or on-demand to verify data quality.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from vizzy.database import get_db

logger = logging.getLogger("vizzy.validation")


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""
    ERROR = "error"      # Data is invalid and should be corrected
    WARNING = "warning"  # Data is suspect but may be intentional
    INFO = "info"        # Informational finding


class ValidationCategory(str, Enum):
    """Category of validation check."""
    EDGE_CLASSIFICATION = "edge_classification"
    TOP_LEVEL_IDENTIFICATION = "top_level"
    CLOSURE_CONTRIBUTION = "closure_contribution"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    DATA_CONSISTENCY = "data_consistency"


@dataclass
class ValidationIssue:
    """Represents a single validation issue found during checks."""
    category: ValidationCategory
    severity: ValidationSeverity
    message: str
    affected_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None


@dataclass
class ValidationResult:
    """Result of running validation checks on an import."""
    import_id: int
    validated_at: datetime
    issues: list[ValidationIssue] = field(default_factory=list)
    passed: bool = True

    @property
    def error_count(self) -> int:
        """Number of error-level issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Number of warning-level issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Number of info-level issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.INFO)

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add an issue to the result."""
        self.issues.append(issue)
        if issue.severity == ValidationSeverity.ERROR:
            self.passed = False

    def to_dict(self) -> dict:
        """Convert result to dictionary for JSON serialization."""
        return {
            "import_id": self.import_id,
            "validated_at": self.validated_at.isoformat(),
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [
                {
                    "category": i.category.value,
                    "severity": i.severity.value,
                    "message": i.message,
                    "affected_count": i.affected_count,
                    "details": i.details,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }


# =============================================================================
# Edge Classification Validation (Phase 8A-001)
# =============================================================================

def validate_edge_classification(import_id: int, result: ValidationResult) -> None:
    """Validate edge classification data for an import.

    Checks:
    - All edges have a dependency_type value (not NULL)
    - dependency_type values are valid ('build', 'runtime', 'unknown')
    - Edge classification consistency (same source should have consistent type)
    - No excessive 'unknown' classifications
    """
    logger.info(f"Validating edge classification for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check for NULL dependency_type values
            cur.execute("""
                SELECT COUNT(*) as null_count
                FROM edges
                WHERE import_id = %s AND dependency_type IS NULL
            """, (import_id,))
            null_count = cur.fetchone()['null_count']

            if null_count > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.EDGE_CLASSIFICATION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {null_count} edges with NULL dependency_type",
                    affected_count=null_count,
                    suggestion="Re-import the graph or run reclassify_edges(import_id)",
                ))

            # Check for invalid dependency_type values
            cur.execute("""
                SELECT dependency_type, COUNT(*) as count
                FROM edges
                WHERE import_id = %s
                  AND dependency_type NOT IN ('build', 'runtime', 'unknown')
                  AND dependency_type IS NOT NULL
                GROUP BY dependency_type
            """, (import_id,))
            invalid_types = cur.fetchall()

            for row in invalid_types:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.EDGE_CLASSIFICATION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid dependency_type value: '{row['dependency_type']}'",
                    affected_count=row['count'],
                    details={"invalid_type": row['dependency_type']},
                    suggestion="Fix data to use valid values: 'build', 'runtime', 'unknown'",
                ))

            # Check for excessive 'unknown' classifications
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE dependency_type = 'unknown') as unknown_count,
                    COUNT(*) as total_count
                FROM edges
                WHERE import_id = %s
            """, (import_id,))
            stats = cur.fetchone()

            if stats['total_count'] > 0:
                unknown_ratio = stats['unknown_count'] / stats['total_count']
                if unknown_ratio > 0.5:
                    result.add_issue(ValidationIssue(
                        category=ValidationCategory.EDGE_CLASSIFICATION,
                        severity=ValidationSeverity.WARNING,
                        message=f"High ratio of 'unknown' edge classifications: {unknown_ratio:.1%}",
                        affected_count=stats['unknown_count'],
                        details={
                            "unknown_count": stats['unknown_count'],
                            "total_count": stats['total_count'],
                            "ratio": unknown_ratio,
                        },
                        suggestion="Review classification patterns; may need to enhance BUILD_TIME_PATTERNS",
                    ))
                elif unknown_ratio > 0.2:
                    result.add_issue(ValidationIssue(
                        category=ValidationCategory.EDGE_CLASSIFICATION,
                        severity=ValidationSeverity.INFO,
                        message=f"Moderate ratio of 'unknown' edge classifications: {unknown_ratio:.1%}",
                        affected_count=stats['unknown_count'],
                        details={
                            "unknown_count": stats['unknown_count'],
                            "total_count": stats['total_count'],
                            "ratio": unknown_ratio,
                        },
                    ))

            # Get distribution summary for info
            cur.execute("""
                SELECT
                    dependency_type,
                    COUNT(*) as count
                FROM edges
                WHERE import_id = %s
                GROUP BY dependency_type
                ORDER BY count DESC
            """, (import_id,))
            distribution = {row['dependency_type']: row['count'] for row in cur.fetchall()}

            logger.info(f"Edge classification distribution: {distribution}")


# =============================================================================
# Top-Level Identification Validation (Phase 8A-002)
# =============================================================================

def validate_top_level_identification(import_id: int, result: ValidationResult) -> None:
    """Validate top-level package identification data for an import.

    Checks:
    - At least some nodes are marked as top-level
    - top_level_source is set when is_top_level is TRUE
    - No orphan top_level_source values (without is_top_level=TRUE)
    - Reasonable ratio of top-level to total nodes
    """
    logger.info(f"Validating top-level identification for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Count top-level nodes and total nodes
            cur.execute("""
                SELECT
                    COUNT(*) as total_count,
                    COUNT(*) FILTER (WHERE is_top_level = TRUE) as top_level_count,
                    COUNT(*) FILTER (WHERE is_top_level = TRUE AND top_level_source IS NOT NULL) as with_source_count,
                    COUNT(*) FILTER (WHERE is_top_level = FALSE AND top_level_source IS NOT NULL) as orphan_source_count
                FROM nodes
                WHERE import_id = %s
            """, (import_id,))
            stats = cur.fetchone()

            total = stats['total_count']
            top_level = stats['top_level_count']
            with_source = stats['with_source_count']
            orphan_source = stats['orphan_source_count']

            # Check for no top-level nodes
            if total > 0 and top_level == 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
                    severity=ValidationSeverity.WARNING,
                    message="No nodes marked as top-level",
                    affected_count=total,
                    suggestion="Run mark_top_level_nodes(import_id, host) to identify top-level packages",
                ))

            # Check for top-level nodes without source
            missing_source = top_level - with_source
            if missing_source > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {missing_source} top-level nodes without top_level_source set",
                    affected_count=missing_source,
                    suggestion="Ensure top_level_source is set when marking nodes as top-level",
                ))

            # Check for orphan sources (source set but not marked top-level)
            if orphan_source > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {orphan_source} nodes with top_level_source but is_top_level=FALSE",
                    affected_count=orphan_source,
                    suggestion="Set is_top_level=TRUE for nodes with top_level_source",
                ))

            # Check for reasonable ratio (very low or very high is suspicious)
            if total > 0:
                ratio = top_level / total
                if ratio > 0.5:
                    result.add_issue(ValidationIssue(
                        category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
                        severity=ValidationSeverity.WARNING,
                        message=f"Unusually high ratio of top-level nodes: {ratio:.1%} ({top_level}/{total})",
                        affected_count=top_level,
                        details={"ratio": ratio, "top_level": top_level, "total": total},
                        suggestion="Review top-level identification logic; most nodes should be transitive deps",
                    ))

            # Check distribution of sources
            cur.execute("""
                SELECT top_level_source, COUNT(*) as count
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE AND top_level_source IS NOT NULL
                GROUP BY top_level_source
                ORDER BY count DESC
                LIMIT 10
            """, (import_id,))
            source_distribution = {row['top_level_source']: row['count'] for row in cur.fetchall()}

            if source_distribution:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.TOP_LEVEL_IDENTIFICATION,
                    severity=ValidationSeverity.INFO,
                    message=f"Top-level nodes by source: {len(source_distribution)} distinct sources",
                    affected_count=top_level,
                    details={"distribution": source_distribution},
                ))

            logger.info(f"Top-level stats: {top_level}/{total} nodes ({ratio:.1%})" if total > 0 else "No nodes")


# =============================================================================
# Closure Contribution Validation (Phase 8A-003)
# =============================================================================

def validate_closure_contribution(import_id: int, result: ValidationResult) -> None:
    """Validate closure contribution data for an import.

    Checks:
    - Top-level nodes have contribution data computed
    - Contribution values are non-negative
    - total_contribution = unique_contribution + shared_contribution
    - contribution_computed_at timestamp is set when contributions exist
    - unique_contribution <= total_contribution
    - shared_contribution <= total_contribution
    """
    logger.info(f"Validating closure contribution for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check how many top-level nodes have contribution data
            cur.execute("""
                SELECT
                    COUNT(*) as top_level_count,
                    COUNT(*) FILTER (WHERE unique_contribution IS NOT NULL) as with_unique,
                    COUNT(*) FILTER (WHERE shared_contribution IS NOT NULL) as with_shared,
                    COUNT(*) FILTER (WHERE total_contribution IS NOT NULL) as with_total,
                    COUNT(*) FILTER (WHERE contribution_computed_at IS NOT NULL) as with_timestamp
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
            """, (import_id,))
            stats = cur.fetchone()

            top_level = stats['top_level_count']
            with_unique = stats['with_unique']
            with_shared = stats['with_shared']
            with_total = stats['with_total']
            with_timestamp = stats['with_timestamp']

            # Check if contributions have been computed
            if top_level > 0 and with_unique == 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.INFO,
                    message=f"Closure contributions not yet computed for {top_level} top-level nodes",
                    affected_count=top_level,
                    suggestion="Run compute_contributions(import_id) to calculate contributions",
                ))
                return  # Skip other checks if not computed

            # Check for incomplete contribution data
            if with_unique != with_shared or with_unique != with_total:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.ERROR,
                    message="Inconsistent contribution fields - some columns NULL while others are set",
                    affected_count=max(with_unique, with_shared, with_total) - min(with_unique, with_shared, with_total),
                    details={
                        "with_unique": with_unique,
                        "with_shared": with_shared,
                        "with_total": with_total,
                    },
                    suggestion="Re-run compute_contributions(import_id) to ensure all fields are populated",
                ))

            # Check for missing timestamps when contributions exist
            if with_unique > 0 and with_timestamp < with_unique:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {with_unique - with_timestamp} nodes with contributions but no timestamp",
                    affected_count=with_unique - with_timestamp,
                    suggestion="contribution_computed_at should be set when contributions are calculated",
                ))

            # Check for negative values
            cur.execute("""
                SELECT COUNT(*) as negative_count
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND (unique_contribution < 0 OR shared_contribution < 0 OR total_contribution < 0)
            """, (import_id,))
            negative = cur.fetchone()['negative_count']

            if negative > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {negative} nodes with negative contribution values",
                    affected_count=negative,
                    suggestion="Contribution values must be non-negative; re-run computation",
                ))

            # Check total = unique + shared constraint
            cur.execute("""
                SELECT COUNT(*) as inconsistent_count
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                  AND shared_contribution IS NOT NULL
                  AND total_contribution IS NOT NULL
                  AND total_contribution != (unique_contribution + shared_contribution)
            """, (import_id,))
            inconsistent = cur.fetchone()['inconsistent_count']

            if inconsistent > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {inconsistent} nodes where total != unique + shared",
                    affected_count=inconsistent,
                    suggestion="total_contribution should equal unique_contribution + shared_contribution",
                ))

            # Check unique <= total and shared <= total
            cur.execute("""
                SELECT COUNT(*) as invalid_count
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
                  AND total_contribution IS NOT NULL
                  AND (unique_contribution > total_contribution OR shared_contribution > total_contribution)
            """, (import_id,))
            invalid = cur.fetchone()['invalid_count']

            if invalid > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {invalid} nodes where unique or shared exceeds total",
                    affected_count=invalid,
                    suggestion="unique and shared contributions cannot exceed total",
                ))

            # Get summary stats for info
            cur.execute("""
                SELECT
                    SUM(unique_contribution) as sum_unique,
                    SUM(shared_contribution) as sum_shared,
                    AVG(unique_contribution) as avg_unique,
                    AVG(shared_contribution) as avg_shared,
                    MAX(unique_contribution) as max_unique,
                    MAX(total_contribution) as max_total
                FROM nodes
                WHERE import_id = %s
                  AND is_top_level = TRUE
                  AND unique_contribution IS NOT NULL
            """, (import_id,))
            summary = cur.fetchone()

            if summary['sum_unique'] is not None:
                total_contributions = (summary['sum_unique'] or 0) + (summary['sum_shared'] or 0)
                sharing_ratio = (summary['sum_shared'] or 0) / total_contributions if total_contributions > 0 else 0

                result.add_issue(ValidationIssue(
                    category=ValidationCategory.CLOSURE_CONTRIBUTION,
                    severity=ValidationSeverity.INFO,
                    message=f"Contribution stats: sharing ratio {sharing_ratio:.1%}, max unique {summary['max_unique']}, max total {summary['max_total']}",
                    affected_count=with_unique,
                    details={
                        "sum_unique": summary['sum_unique'],
                        "sum_shared": summary['sum_shared'],
                        "avg_unique": float(summary['avg_unique'] or 0),
                        "avg_shared": float(summary['avg_shared'] or 0),
                        "sharing_ratio": sharing_ratio,
                    },
                ))


# =============================================================================
# Referential Integrity Checks
# =============================================================================

def validate_referential_integrity(import_id: int, result: ValidationResult) -> None:
    """Validate referential integrity between tables.

    Checks:
    - All edges reference valid nodes in the same import
    - All nodes belong to a valid import
    - No orphan edges (edges without valid source or target)
    """
    logger.info(f"Validating referential integrity for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check that import exists
            cur.execute("""
                SELECT id, name, node_count, edge_count
                FROM imports
                WHERE id = %s
            """, (import_id,))
            import_info = cur.fetchone()

            if not import_info:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Import {import_id} does not exist",
                    affected_count=0,
                ))
                return

            # Check actual vs recorded counts
            cur.execute("""
                SELECT COUNT(*) as actual_nodes FROM nodes WHERE import_id = %s
            """, (import_id,))
            actual_nodes = cur.fetchone()['actual_nodes']

            cur.execute("""
                SELECT COUNT(*) as actual_edges FROM edges WHERE import_id = %s
            """, (import_id,))
            actual_edges = cur.fetchone()['actual_edges']

            recorded_nodes = import_info['node_count']
            recorded_edges = import_info['edge_count']

            if recorded_nodes is not None and actual_nodes != recorded_nodes:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.WARNING,
                    message=f"Node count mismatch: recorded {recorded_nodes}, actual {actual_nodes}",
                    affected_count=abs(actual_nodes - recorded_nodes),
                    details={"recorded": recorded_nodes, "actual": actual_nodes},
                    suggestion="Update imports table with correct node_count",
                ))

            if recorded_edges is not None and actual_edges != recorded_edges:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.WARNING,
                    message=f"Edge count mismatch: recorded {recorded_edges}, actual {actual_edges}",
                    affected_count=abs(actual_edges - recorded_edges),
                    details={"recorded": recorded_edges, "actual": actual_edges},
                    suggestion="Update imports table with correct edge_count",
                ))

            # Check for edges with invalid source_id
            cur.execute("""
                SELECT COUNT(*) as orphan_count
                FROM edges e
                LEFT JOIN nodes n ON e.source_id = n.id AND n.import_id = %s
                WHERE e.import_id = %s AND n.id IS NULL
            """, (import_id, import_id))
            orphan_source = cur.fetchone()['orphan_count']

            if orphan_source > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {orphan_source} edges with invalid source_id references",
                    affected_count=orphan_source,
                    suggestion="Remove orphan edges or re-import the graph",
                ))

            # Check for edges with invalid target_id
            cur.execute("""
                SELECT COUNT(*) as orphan_count
                FROM edges e
                LEFT JOIN nodes n ON e.target_id = n.id AND n.import_id = %s
                WHERE e.import_id = %s AND n.id IS NULL
            """, (import_id, import_id))
            orphan_target = cur.fetchone()['orphan_count']

            if orphan_target > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {orphan_target} edges with invalid target_id references",
                    affected_count=orphan_target,
                    suggestion="Remove orphan edges or re-import the graph",
                ))

            # Check for cross-import edges (edge import_id doesn't match node import_id)
            cur.execute("""
                SELECT COUNT(*) as cross_count
                FROM edges e
                JOIN nodes n_src ON e.source_id = n_src.id
                WHERE e.import_id = %s AND n_src.import_id != %s
            """, (import_id, import_id))
            cross_import = cur.fetchone()['cross_count']

            if cross_import > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.REFERENTIAL_INTEGRITY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {cross_import} edges referencing nodes from different imports",
                    affected_count=cross_import,
                    suggestion="Edges should only reference nodes from the same import",
                ))


# =============================================================================
# Data Consistency Checks
# =============================================================================

def validate_data_consistency(import_id: int, result: ValidationResult) -> None:
    """Validate general data consistency.

    Checks:
    - No self-referencing edges (source_id = target_id)
    - depth values are non-negative when set
    - closure_size values are non-negative when set
    - No duplicate edges (same source, target)
    """
    logger.info(f"Validating data consistency for import {import_id}")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check for self-referencing edges
            cur.execute("""
                SELECT COUNT(*) as self_ref_count
                FROM edges
                WHERE import_id = %s AND source_id = target_id
            """, (import_id,))
            self_ref = cur.fetchone()['self_ref_count']

            if self_ref > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.DATA_CONSISTENCY,
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {self_ref} self-referencing edges (source_id = target_id)",
                    affected_count=self_ref,
                    suggestion="Self-references are unusual; may indicate data issue",
                ))

            # Check for negative depth values
            cur.execute("""
                SELECT COUNT(*) as negative_depth
                FROM nodes
                WHERE import_id = %s AND depth IS NOT NULL AND depth < 0
            """, (import_id,))
            neg_depth = cur.fetchone()['negative_depth']

            if neg_depth > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.DATA_CONSISTENCY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {neg_depth} nodes with negative depth values",
                    affected_count=neg_depth,
                    suggestion="Depth must be non-negative; re-run compute_depths(import_id)",
                ))

            # Check for negative closure_size values
            cur.execute("""
                SELECT COUNT(*) as negative_closure
                FROM nodes
                WHERE import_id = %s AND closure_size IS NOT NULL AND closure_size < 0
            """, (import_id,))
            neg_closure = cur.fetchone()['negative_closure']

            if neg_closure > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.DATA_CONSISTENCY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {neg_closure} nodes with negative closure_size values",
                    affected_count=neg_closure,
                    suggestion="Closure size must be non-negative; re-run compute_closure_sizes(import_id)",
                ))

            # Check for empty drv_hash
            cur.execute("""
                SELECT COUNT(*) as empty_hash
                FROM nodes
                WHERE import_id = %s AND (drv_hash IS NULL OR drv_hash = '')
            """, (import_id,))
            empty_hash = cur.fetchone()['empty_hash']

            if empty_hash > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.DATA_CONSISTENCY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {empty_hash} nodes with empty or NULL drv_hash",
                    affected_count=empty_hash,
                    suggestion="drv_hash is required for all nodes",
                ))

            # Check for empty labels
            cur.execute("""
                SELECT COUNT(*) as empty_label
                FROM nodes
                WHERE import_id = %s AND (label IS NULL OR label = '')
            """, (import_id,))
            empty_label = cur.fetchone()['empty_label']

            if empty_label > 0:
                result.add_issue(ValidationIssue(
                    category=ValidationCategory.DATA_CONSISTENCY,
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {empty_label} nodes with empty or NULL label",
                    affected_count=empty_label,
                    suggestion="Labels help identify packages; consider setting them",
                ))

            # Check depth vs closure_size coverage
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(depth) as with_depth,
                    COUNT(closure_size) as with_closure
                FROM nodes
                WHERE import_id = %s
            """, (import_id,))
            coverage = cur.fetchone()

            total = coverage['total']
            with_depth = coverage['with_depth']
            with_closure = coverage['with_closure']

            if total > 0:
                depth_coverage = with_depth / total
                closure_coverage = with_closure / total

                if depth_coverage < 0.9:
                    result.add_issue(ValidationIssue(
                        category=ValidationCategory.DATA_CONSISTENCY,
                        severity=ValidationSeverity.WARNING,
                        message=f"Only {depth_coverage:.1%} of nodes have depth computed",
                        affected_count=total - with_depth,
                        suggestion="Run compute_depths(import_id) to calculate missing depths",
                    ))

                if closure_coverage < 0.9:
                    result.add_issue(ValidationIssue(
                        category=ValidationCategory.DATA_CONSISTENCY,
                        severity=ValidationSeverity.WARNING,
                        message=f"Only {closure_coverage:.1%} of nodes have closure_size computed",
                        affected_count=total - with_closure,
                        suggestion="Run compute_closure_sizes(import_id) to calculate missing closure sizes",
                    ))


# =============================================================================
# Main Validation Entry Points
# =============================================================================

def validate_import(import_id: int, skip_categories: list[ValidationCategory] | None = None) -> ValidationResult:
    """Run all validation checks on an import.

    Args:
        import_id: The import to validate
        skip_categories: Optional list of validation categories to skip

    Returns:
        ValidationResult containing all issues found
    """
    skip = set(skip_categories or [])
    result = ValidationResult(
        import_id=import_id,
        validated_at=datetime.now(),
    )

    logger.info(f"Starting validation for import {import_id}")

    # Run each validation category
    if ValidationCategory.REFERENTIAL_INTEGRITY not in skip:
        validate_referential_integrity(import_id, result)

    if ValidationCategory.DATA_CONSISTENCY not in skip:
        validate_data_consistency(import_id, result)

    if ValidationCategory.EDGE_CLASSIFICATION not in skip:
        validate_edge_classification(import_id, result)

    if ValidationCategory.TOP_LEVEL_IDENTIFICATION not in skip:
        validate_top_level_identification(import_id, result)

    if ValidationCategory.CLOSURE_CONTRIBUTION not in skip:
        validate_closure_contribution(import_id, result)

    logger.info(
        f"Validation complete for import {import_id}: "
        f"{result.error_count} errors, {result.warning_count} warnings, {result.info_count} info"
    )

    return result


def validate_phase8a_fields(import_id: int) -> ValidationResult:
    """Run validation checks specifically for Phase 8A fields.

    This is a convenience function that focuses only on the Phase 8A enhancements:
    - Edge classification
    - Top-level identification
    - Closure contribution

    Args:
        import_id: The import to validate

    Returns:
        ValidationResult containing issues found in Phase 8A fields
    """
    return validate_import(
        import_id,
        skip_categories=[
            ValidationCategory.REFERENTIAL_INTEGRITY,
            ValidationCategory.DATA_CONSISTENCY,
        ]
    )


def get_validation_summary(import_id: int) -> dict:
    """Get a quick validation summary without full details.

    Returns a dictionary suitable for API responses and dashboards.
    """
    result = validate_import(import_id)

    return {
        "import_id": import_id,
        "passed": result.passed,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "info_count": result.info_count,
        "categories_checked": [c.value for c in ValidationCategory],
        "validated_at": result.validated_at.isoformat(),
    }
