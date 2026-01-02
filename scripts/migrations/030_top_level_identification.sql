-- Migration: 030_top_level_identification.sql
-- Phase 8A-002: Implement top-level package identification
--
-- This migration adds columns to track which nodes are "user-facing" (explicitly
-- requested via systemPackages, programs.*.enable, etc.) vs transitive dependencies.
-- This is critical for the Why Chain feature and closure contribution analysis.

BEGIN;

-- Add is_top_level boolean column to mark user-facing packages
-- Default to FALSE since most packages are transitive dependencies
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS is_top_level BOOLEAN DEFAULT FALSE;

-- Add top_level_source to track where the package was defined
-- Values like 'systemPackages', 'programs.git.enable', 'home-manager', etc.
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS top_level_source TEXT;

-- Create partial index for efficient queries on top-level nodes only
-- This supports the dashboard's "top contributors" query
CREATE INDEX IF NOT EXISTS idx_nodes_top_level
    ON nodes(import_id) WHERE is_top_level = TRUE;

-- Create index for querying by top_level_source
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_source
    ON nodes(import_id, top_level_source) WHERE is_top_level = TRUE;

-- Composite index for top-level nodes sorted by closure size
-- Used in dashboard and treemap for showing largest contributors
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_closure
    ON nodes(import_id, closure_size DESC NULLS LAST) WHERE is_top_level = TRUE;

COMMIT;

-- Verification query (run manually to verify migration)
-- SELECT COUNT(*) as total,
--        COUNT(*) FILTER (WHERE is_top_level = TRUE) as top_level_count
-- FROM nodes WHERE import_id = <your_import_id>;
