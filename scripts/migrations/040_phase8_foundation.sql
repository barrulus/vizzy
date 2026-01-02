-- Migration: 040_phase8_foundation.sql
-- Phase 8A: Consolidated database migration for Question-Driven Visualizations
--
-- This migration consolidates all Phase 8A schema changes needed for the new
-- question-driven visualization features. It is designed to be idempotent
-- (safe to run multiple times) and can be used for:
-- - Fresh database setup
-- - Upgrading existing databases
-- - Verification that all Phase 8A fields are present
--
-- Related tasks:
-- - 8A-001: Edge classification (build vs runtime)
-- - 8A-002: Top-level package identification
-- - 8A-003: Closure contribution calculation
--
-- Dependencies already covered by individual migrations:
-- - 025_edge_classification.sql
-- - 030_top_level_identification.sql
-- - 035_closure_contribution.sql

BEGIN;

-- =============================================================================
-- Phase 8A-001: Edge Classification (Build-time vs Runtime)
-- =============================================================================

-- Add dependency_type column to distinguish build-time from runtime dependencies
-- Values: 'build' (compilers, build tools), 'runtime' (shared libs), 'unknown'
ALTER TABLE edges ADD COLUMN IF NOT EXISTS
    dependency_type TEXT CHECK (dependency_type IN ('build', 'runtime', 'unknown'));

-- Default any existing null edges to 'unknown' for consistency
UPDATE edges SET dependency_type = 'unknown' WHERE dependency_type IS NULL;

-- Index for filtering by dependency type
CREATE INDEX IF NOT EXISTS idx_edges_dependency_type
    ON edges(import_id, dependency_type);

-- Partial index for runtime-only queries (common case for "what do I ship?")
CREATE INDEX IF NOT EXISTS idx_edges_runtime
    ON edges(import_id)
    WHERE dependency_type = 'runtime';

-- Partial index for build-only queries
CREATE INDEX IF NOT EXISTS idx_edges_build
    ON edges(import_id)
    WHERE dependency_type = 'build';


-- =============================================================================
-- Phase 8A-002: Top-Level Package Identification
-- =============================================================================

-- Mark user-facing packages (systemPackages, programs.*.enable, etc.)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS is_top_level BOOLEAN DEFAULT FALSE;

-- Track where the package was defined ('systemPackages', 'programs.git.enable', etc.)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS top_level_source TEXT;

-- Partial index for efficient queries on top-level nodes only
CREATE INDEX IF NOT EXISTS idx_nodes_top_level
    ON nodes(import_id) WHERE is_top_level = TRUE;

-- Index for querying by source (e.g., find all systemPackages)
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_source
    ON nodes(import_id, top_level_source) WHERE is_top_level = TRUE;

-- Composite index for top-level nodes sorted by closure size (dashboard, treemap)
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_closure
    ON nodes(import_id, closure_size DESC NULLS LAST) WHERE is_top_level = TRUE;


-- =============================================================================
-- Phase 8A-003: Closure Contribution Calculation
-- =============================================================================

-- Dependencies only reachable through this package (removal impact)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS unique_contribution INT;

-- Dependencies also reachable via other packages (shared cost)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS shared_contribution INT;

-- Total contribution (unique + shared) for convenience
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS total_contribution INT;

-- Timestamp for tracking when contribution was last calculated
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS contribution_computed_at TIMESTAMP;

-- Index for querying by unique contribution (find biggest blockers to reduction)
CREATE INDEX IF NOT EXISTS idx_nodes_unique_contribution
    ON nodes(import_id, unique_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;

-- Index for querying by total contribution (find largest packages)
CREATE INDEX IF NOT EXISTS idx_nodes_total_contribution
    ON nodes(import_id, total_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;

-- Index for finding nodes needing contribution recomputation
CREATE INDEX IF NOT EXISTS idx_nodes_contribution_stale
    ON nodes(import_id)
    WHERE is_top_level = TRUE AND contribution_computed_at IS NULL;


-- =============================================================================
-- Schema Version Tracking
-- =============================================================================

-- Create schema_version table if not exists to track applied migrations
CREATE TABLE IF NOT EXISTS schema_version (
    id SERIAL PRIMARY KEY,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT NOW(),
    description TEXT
);

-- Record this migration (idempotent)
INSERT INTO schema_version (migration_name, description)
VALUES ('040_phase8_foundation', 'Phase 8A consolidated migration for question-driven visualizations')
ON CONFLICT (migration_name) DO NOTHING;


COMMIT;

-- =============================================================================
-- Verification Queries (run manually to verify migration)
-- =============================================================================

-- Check edge classification columns:
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'edges' AND column_name = 'dependency_type';

-- Check top-level columns:
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'nodes' AND column_name IN ('is_top_level', 'top_level_source');

-- Check contribution columns:
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'nodes' AND column_name LIKE '%contribution%';

-- Check indexes created:
-- SELECT indexname FROM pg_indexes WHERE tablename IN ('nodes', 'edges')
-- AND indexname LIKE 'idx_nodes_top_level%' OR indexname LIKE 'idx_edges_%';

-- Summary of Phase 8A fields:
-- SELECT
--     (SELECT COUNT(*) FROM edges WHERE dependency_type IS NOT NULL) as classified_edges,
--     (SELECT COUNT(*) FROM nodes WHERE is_top_level = TRUE) as top_level_nodes,
--     (SELECT COUNT(*) FROM nodes WHERE unique_contribution IS NOT NULL) as nodes_with_contribution;
