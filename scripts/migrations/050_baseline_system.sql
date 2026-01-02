-- Migration: 050_baseline_system.sql
-- Phase 8A-004: Baseline Closure Reference System
--
-- This migration creates the baselines table for storing reference configurations
-- that can be used for comparative context. Baselines allow users to compare
-- their current system closure against known reference points.
--
-- Use cases:
-- - Compare against a minimal NixOS configuration
-- - Track closure growth over time
-- - Compare against previous system states
-- - Share standardized baselines across teams
--
-- Related tasks:
-- - 8A-004: Create baseline closure reference system
-- - 8F-004: Add baseline comparison presets (depends on this)

BEGIN;

-- =============================================================================
-- Baselines Table
-- =============================================================================

-- Baselines store snapshot metrics from imports for later comparison.
-- Unlike imports (which store full graph data), baselines are lightweight
-- summary records that persist even if the source import is deleted.
CREATE TABLE IF NOT EXISTS baselines (
    id SERIAL PRIMARY KEY,

    -- Basic metadata
    name TEXT NOT NULL,                         -- User-friendly name (e.g., "Minimal NixOS 24.05")
    description TEXT,                           -- Optional description of what this baseline represents

    -- Source tracking (optional - may be manually created)
    source_import_id INT REFERENCES imports(id) ON DELETE SET NULL,

    -- Summary metrics (snapshot at creation time)
    node_count INT NOT NULL,                    -- Total number of derivations
    edge_count INT NOT NULL,                    -- Total number of dependencies

    -- Breakdown by package type (stored as JSONB for flexibility)
    -- Format: {"library": 1234, "application": 567, "service": 89, ...}
    closure_by_type JSONB DEFAULT '{}'::jsonb,

    -- Additional metrics for rich comparison
    top_level_count INT,                        -- Number of top-level packages
    runtime_edge_count INT,                     -- Number of runtime dependencies
    build_edge_count INT,                       -- Number of build-time dependencies
    max_depth INT,                              -- Maximum dependency depth
    avg_depth FLOAT,                            -- Average dependency depth

    -- Top contributors snapshot (for quick display without recomputation)
    -- Format: [{"label": "firefox", "closure_size": 2340}, ...]
    top_contributors JSONB DEFAULT '[]'::jsonb,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_system_baseline BOOLEAN DEFAULT FALSE,  -- True for built-in reference baselines
    tags TEXT[] DEFAULT '{}'                   -- Flexible tagging for categorization
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_baselines_name ON baselines(name);
CREATE INDEX IF NOT EXISTS idx_baselines_created ON baselines(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_baselines_source ON baselines(source_import_id);
CREATE INDEX IF NOT EXISTS idx_baselines_system ON baselines(is_system_baseline) WHERE is_system_baseline = TRUE;
CREATE INDEX IF NOT EXISTS idx_baselines_tags ON baselines USING gin(tags);

-- Partial index for non-system baselines (user created)
CREATE INDEX IF NOT EXISTS idx_baselines_user ON baselines(created_at DESC) WHERE is_system_baseline = FALSE;


-- =============================================================================
-- Baseline Comparisons Cache Table (Optional)
-- =============================================================================

-- Cache table for storing computed comparisons to avoid recalculation.
-- This is optional but improves performance for frequently compared baselines.
CREATE TABLE IF NOT EXISTS baseline_comparisons (
    id SERIAL PRIMARY KEY,

    -- What we're comparing
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    baseline_id INT REFERENCES baselines(id) ON DELETE CASCADE,

    -- Comparison results (snapshot)
    node_difference INT NOT NULL,              -- import.nodes - baseline.nodes
    edge_difference INT NOT NULL,              -- import.edges - baseline.edges
    percentage_difference FLOAT NOT NULL,      -- ((import - baseline) / baseline) * 100

    -- Detailed differences by type
    differences_by_type JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    computed_at TIMESTAMP DEFAULT NOW(),

    -- Ensure one comparison per import/baseline pair
    UNIQUE(import_id, baseline_id)
);

CREATE INDEX IF NOT EXISTS idx_baseline_comparisons_import ON baseline_comparisons(import_id);
CREATE INDEX IF NOT EXISTS idx_baseline_comparisons_baseline ON baseline_comparisons(baseline_id);


-- =============================================================================
-- Schema Version Tracking
-- =============================================================================

-- Record this migration (idempotent)
INSERT INTO schema_version (migration_name, description)
VALUES ('050_baseline_system', 'Phase 8A-004: Baseline closure reference system')
ON CONFLICT (migration_name) DO NOTHING;


COMMIT;

-- =============================================================================
-- Verification Queries (run manually to verify migration)
-- =============================================================================

-- Check baselines table structure:
-- SELECT column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'baselines'
-- ORDER BY ordinal_position;

-- Check baseline_comparisons table structure:
-- SELECT column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'baseline_comparisons'
-- ORDER BY ordinal_position;

-- Check indexes:
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN ('baselines', 'baseline_comparisons');

-- Test insertion (manual):
-- INSERT INTO baselines (name, description, node_count, edge_count, closure_by_type)
-- VALUES ('Test Baseline', 'A test baseline', 1000, 2000, '{"library": 500, "application": 300}');
