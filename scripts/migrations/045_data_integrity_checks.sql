-- Migration: 045_data_integrity_checks.sql
-- Phase 8A-007: Data validation and integrity checks
--
-- This migration adds database-level constraints to ensure data integrity
-- for Phase 8A fields. These constraints enforce rules at the database level,
-- complementing the application-level validation service.
--
-- Constraints added:
-- - Edge classification valid values
-- - Contribution values non-negative
-- - Contribution values consistency (unique + shared = total)
-- - Depth non-negative
-- - Closure size non-negative
--
-- Note: These constraints are added conditionally to avoid errors on existing
-- databases that may already have them, and to handle existing data that may
-- not conform to the new constraints.

BEGIN;

-- =============================================================================
-- Edge Classification Constraints
-- =============================================================================

-- The dependency_type CHECK constraint was already added in migration 025.
-- This section ensures it exists and logs any non-conforming data.

-- Create a function to validate dependency_type (for existing data audit)
DO $$
BEGIN
    -- Check if there's any data that violates the constraint
    -- This helps identify issues before they cause problems
    IF EXISTS (
        SELECT 1 FROM edges
        WHERE dependency_type IS NOT NULL
          AND dependency_type NOT IN ('build', 'runtime', 'unknown')
        LIMIT 1
    ) THEN
        RAISE NOTICE 'WARNING: Found edges with invalid dependency_type values. Consider running reclassify_edges().';
    END IF;
END $$;


-- =============================================================================
-- Contribution Value Constraints
-- =============================================================================

-- Add CHECK constraint for non-negative unique_contribution
-- Use DO block to make it idempotent
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'nodes_unique_contribution_nonneg'
    ) THEN
        -- First, fix any existing negative values
        UPDATE nodes SET unique_contribution = 0
        WHERE unique_contribution IS NOT NULL AND unique_contribution < 0;

        ALTER TABLE nodes
        ADD CONSTRAINT nodes_unique_contribution_nonneg
        CHECK (unique_contribution IS NULL OR unique_contribution >= 0);

        RAISE NOTICE 'Added constraint: nodes_unique_contribution_nonneg';
    END IF;
END $$;

-- Add CHECK constraint for non-negative shared_contribution
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'nodes_shared_contribution_nonneg'
    ) THEN
        -- First, fix any existing negative values
        UPDATE nodes SET shared_contribution = 0
        WHERE shared_contribution IS NOT NULL AND shared_contribution < 0;

        ALTER TABLE nodes
        ADD CONSTRAINT nodes_shared_contribution_nonneg
        CHECK (shared_contribution IS NULL OR shared_contribution >= 0);

        RAISE NOTICE 'Added constraint: nodes_shared_contribution_nonneg';
    END IF;
END $$;

-- Add CHECK constraint for non-negative total_contribution
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'nodes_total_contribution_nonneg'
    ) THEN
        -- First, fix any existing negative values
        UPDATE nodes SET total_contribution = 0
        WHERE total_contribution IS NOT NULL AND total_contribution < 0;

        ALTER TABLE nodes
        ADD CONSTRAINT nodes_total_contribution_nonneg
        CHECK (total_contribution IS NULL OR total_contribution >= 0);

        RAISE NOTICE 'Added constraint: nodes_total_contribution_nonneg';
    END IF;
END $$;

-- Add CHECK constraint for contribution consistency: total = unique + shared
-- This is a more complex constraint that we implement as a trigger to allow
-- partial updates (setting one field at a time)
CREATE OR REPLACE FUNCTION check_contribution_consistency()
RETURNS TRIGGER AS $$
BEGIN
    -- Only check if all three fields are set
    IF NEW.unique_contribution IS NOT NULL
       AND NEW.shared_contribution IS NOT NULL
       AND NEW.total_contribution IS NOT NULL THEN
        IF NEW.total_contribution != NEW.unique_contribution + NEW.shared_contribution THEN
            RAISE EXCEPTION 'Contribution inconsistency: total_contribution (%) must equal unique_contribution (%) + shared_contribution (%)',
                NEW.total_contribution, NEW.unique_contribution, NEW.shared_contribution;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists, then create
DROP TRIGGER IF EXISTS trg_check_contribution_consistency ON nodes;
CREATE TRIGGER trg_check_contribution_consistency
    BEFORE INSERT OR UPDATE ON nodes
    FOR EACH ROW
    EXECUTE FUNCTION check_contribution_consistency();


-- =============================================================================
-- Depth and Closure Size Constraints
-- =============================================================================

-- Add CHECK constraint for non-negative depth
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'nodes_depth_nonneg'
    ) THEN
        -- First, fix any existing negative values (set to NULL to indicate not computed)
        UPDATE nodes SET depth = NULL
        WHERE depth IS NOT NULL AND depth < 0;

        ALTER TABLE nodes
        ADD CONSTRAINT nodes_depth_nonneg
        CHECK (depth IS NULL OR depth >= 0);

        RAISE NOTICE 'Added constraint: nodes_depth_nonneg';
    END IF;
END $$;

-- Add CHECK constraint for non-negative closure_size
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'nodes_closure_size_nonneg'
    ) THEN
        -- First, fix any existing negative values (set to NULL to indicate not computed)
        UPDATE nodes SET closure_size = NULL
        WHERE closure_size IS NOT NULL AND closure_size < 0;

        ALTER TABLE nodes
        ADD CONSTRAINT nodes_closure_size_nonneg
        CHECK (closure_size IS NULL OR closure_size >= 0);

        RAISE NOTICE 'Added constraint: nodes_closure_size_nonneg';
    END IF;
END $$;


-- =============================================================================
-- Top-Level Consistency Constraint
-- =============================================================================

-- Ensure top_level_source is only set when is_top_level = TRUE
-- We implement this as a trigger rather than a CHECK to allow easier debugging
CREATE OR REPLACE FUNCTION check_top_level_consistency()
RETURNS TRIGGER AS $$
BEGIN
    -- If setting top_level_source, ensure is_top_level is TRUE
    IF NEW.top_level_source IS NOT NULL AND NEW.is_top_level = FALSE THEN
        RAISE EXCEPTION 'Cannot set top_level_source when is_top_level is FALSE';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists, then create
DROP TRIGGER IF EXISTS trg_check_top_level_consistency ON nodes;
CREATE TRIGGER trg_check_top_level_consistency
    BEFORE INSERT OR UPDATE ON nodes
    FOR EACH ROW
    EXECUTE FUNCTION check_top_level_consistency();


-- =============================================================================
-- Edge Self-Reference Prevention (Optional - Warning Only)
-- =============================================================================

-- Create a trigger that warns about self-referencing edges but doesn't prevent them
-- (they may be valid in some edge cases)
CREATE OR REPLACE FUNCTION warn_self_reference()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.source_id = NEW.target_id THEN
        RAISE WARNING 'Self-referencing edge detected: source_id = target_id = %', NEW.source_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists, then create
DROP TRIGGER IF EXISTS trg_warn_self_reference ON edges;
CREATE TRIGGER trg_warn_self_reference
    BEFORE INSERT OR UPDATE ON edges
    FOR EACH ROW
    EXECUTE FUNCTION warn_self_reference();


-- =============================================================================
-- Validation Helper Functions
-- =============================================================================

-- Function to validate Phase 8A data for an import
CREATE OR REPLACE FUNCTION validate_phase8a_data(p_import_id INT)
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    affected_count INT,
    details TEXT
) AS $$
BEGIN
    -- Check edge classification
    RETURN QUERY
    SELECT
        'edge_classification_null'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        COUNT(*)::INT,
        'Edges with NULL dependency_type'::TEXT
    FROM edges
    WHERE import_id = p_import_id AND dependency_type IS NULL;

    -- Check edge classification values
    RETURN QUERY
    SELECT
        'edge_classification_valid'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        COUNT(*)::INT,
        'Edges with invalid dependency_type'::TEXT
    FROM edges
    WHERE import_id = p_import_id
      AND dependency_type NOT IN ('build', 'runtime', 'unknown')
      AND dependency_type IS NOT NULL;

    -- Check top-level identification
    RETURN QUERY
    SELECT
        'top_level_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'WARN' END,
        COUNT(*)::INT,
        'Nodes marked as top-level'::TEXT
    FROM nodes
    WHERE import_id = p_import_id AND is_top_level = TRUE;

    -- Check top-level source consistency
    RETURN QUERY
    SELECT
        'top_level_source_consistency'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        COUNT(*)::INT,
        'Nodes with source but not marked top-level'::TEXT
    FROM nodes
    WHERE import_id = p_import_id
      AND is_top_level = FALSE
      AND top_level_source IS NOT NULL;

    -- Check contribution consistency
    RETURN QUERY
    SELECT
        'contribution_consistency'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        COUNT(*)::INT,
        'Nodes where total != unique + shared'::TEXT
    FROM nodes
    WHERE import_id = p_import_id
      AND is_top_level = TRUE
      AND unique_contribution IS NOT NULL
      AND shared_contribution IS NOT NULL
      AND total_contribution IS NOT NULL
      AND total_contribution != unique_contribution + shared_contribution;

    -- Check for negative values
    RETURN QUERY
    SELECT
        'contribution_nonnegative'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        COUNT(*)::INT,
        'Nodes with negative contribution values'::TEXT
    FROM nodes
    WHERE import_id = p_import_id
      AND (unique_contribution < 0
           OR shared_contribution < 0
           OR total_contribution < 0);

    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Add comment explaining the function
COMMENT ON FUNCTION validate_phase8a_data(INT) IS
'Validates Phase 8A data for an import. Returns a table of check results including:
- edge_classification_null: Checks for NULL dependency_type values
- edge_classification_valid: Checks for invalid dependency_type values
- top_level_exists: Checks if any nodes are marked as top-level
- top_level_source_consistency: Checks for orphan top_level_source values
- contribution_consistency: Checks if total = unique + shared
- contribution_nonnegative: Checks for negative contribution values

Usage: SELECT * FROM validate_phase8a_data(1);';


-- =============================================================================
-- Schema Version Tracking
-- =============================================================================

INSERT INTO schema_version (migration_name, description)
VALUES (
    '045_data_integrity_checks',
    'Phase 8A-007: Database constraints and validation functions for data integrity'
)
ON CONFLICT (migration_name) DO NOTHING;


COMMIT;

-- =============================================================================
-- Verification Queries (run manually to verify migration)
-- =============================================================================

-- Check all constraints are in place:
-- SELECT conname, contype, conrelid::regclass
-- FROM pg_constraint
-- WHERE conname LIKE 'nodes_%' OR conname LIKE 'edges_%';

-- Check triggers are in place:
-- SELECT tgname, tgrelid::regclass, tgtype, tgenabled
-- FROM pg_trigger
-- WHERE tgname LIKE 'trg_%';

-- Run validation on an import:
-- SELECT * FROM validate_phase8a_data(1);
