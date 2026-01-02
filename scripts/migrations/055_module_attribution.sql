-- Migration: 055_module_attribution.sql
-- Phase 8A-005: Enhanced Module Attribution from Nix CLI
--
-- This migration enhances module attribution to better track which NixOS modules
-- are responsible for adding packages to the system configuration.
--
-- The existing top_level_source column now stores richer module paths like:
-- - 'systemPackages' (environment.systemPackages)
-- - 'programs.git.enable' (programs.git module)
-- - 'services.nginx.enable' (services.nginx module)
--
-- This migration adds:
-- - A module_type column to categorize the source type
-- - An index for efficient querying by module type
--
-- Related tasks:
-- - 8A-005: Enhance module attribution from nix CLI
-- - 8E-009: Add module-level attribution display (depends on this)

BEGIN;

-- =============================================================================
-- Add Module Type Classification
-- =============================================================================

-- Add module_type column to categorize the source of the package
-- Values: 'systemPackages', 'programs', 'services', 'other'
-- This makes it easier to group and filter packages by their origin
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS module_type TEXT;

-- Create index for efficient querying by module type
CREATE INDEX IF NOT EXISTS idx_nodes_module_type
    ON nodes(import_id, module_type) WHERE is_top_level = TRUE;

-- Create composite index for module attribution queries
-- Supports queries like "show all packages from services modules sorted by closure size"
CREATE INDEX IF NOT EXISTS idx_nodes_module_attribution
    ON nodes(import_id, module_type, top_level_source, closure_size DESC NULLS LAST)
    WHERE is_top_level = TRUE;


-- =============================================================================
-- Module Attribution Summary Table
-- =============================================================================

-- Store aggregated module attribution statistics per import
-- This avoids expensive recomputation for dashboard display
CREATE TABLE IF NOT EXISTS module_attribution_summary (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,

    -- Module type breakdown
    system_packages_count INT DEFAULT 0,     -- From environment.systemPackages
    programs_count INT DEFAULT 0,            -- From programs.*.enable
    services_count INT DEFAULT 0,            -- From services.*.enable
    other_count INT DEFAULT 0,               -- From other sources

    -- Detailed module breakdown (stored as JSONB for flexibility)
    -- Format: {"programs.git.enable": 1, "services.nginx.enable": 1, ...}
    by_source JSONB DEFAULT '{}'::jsonb,

    -- Most impactful modules (by closure size contribution)
    -- Format: [{"source": "services.nginx.enable", "packages": ["nginx"], "closure_size": 1234}, ...]
    top_modules JSONB DEFAULT '[]'::jsonb,

    -- Metadata
    computed_at TIMESTAMP DEFAULT NOW(),

    -- One summary per import
    UNIQUE(import_id)
);

CREATE INDEX IF NOT EXISTS idx_module_summary_import ON module_attribution_summary(import_id);


-- =============================================================================
-- Update Existing Data (Backfill module_type)
-- =============================================================================

-- Set module_type based on existing top_level_source values
UPDATE nodes
SET module_type = CASE
    WHEN top_level_source = 'systemPackages' THEN 'systemPackages'
    WHEN top_level_source LIKE 'programs.%' THEN 'programs'
    WHEN top_level_source LIKE 'services.%' THEN 'services'
    WHEN top_level_source IS NOT NULL THEN 'other'
    ELSE NULL
END
WHERE is_top_level = TRUE;


-- =============================================================================
-- Schema Version Tracking
-- =============================================================================

-- Record this migration (idempotent)
INSERT INTO schema_version (migration_name, description)
VALUES ('055_module_attribution', 'Phase 8A-005: Enhanced module attribution from nix CLI')
ON CONFLICT (migration_name) DO NOTHING;


COMMIT;

-- =============================================================================
-- Verification Queries (run manually to verify migration)
-- =============================================================================

-- Check module_type distribution:
-- SELECT module_type, COUNT(*) as count
-- FROM nodes
-- WHERE import_id = <your_import_id> AND is_top_level = TRUE
-- GROUP BY module_type
-- ORDER BY count DESC;

-- Check top_level_source breakdown:
-- SELECT top_level_source, COUNT(*) as count, SUM(closure_size) as total_closure
-- FROM nodes
-- WHERE import_id = <your_import_id> AND is_top_level = TRUE
-- GROUP BY top_level_source
-- ORDER BY total_closure DESC NULLS LAST;

-- Check module_attribution_summary table:
-- SELECT * FROM module_attribution_summary WHERE import_id = <your_import_id>;
