-- Migration: 025_edge_classification.sql
-- Phase 8A-001: Add build-time vs runtime edge classification
--
-- This migration adds a dependency_type column to edges table to distinguish
-- between build-time dependencies (compilers, build tools) and runtime
-- dependencies (shared libraries, runtime interpreters).

BEGIN;

-- Add dependency_type column with constraint
ALTER TABLE edges ADD COLUMN IF NOT EXISTS
    dependency_type TEXT CHECK (dependency_type IN ('build', 'runtime', 'unknown'));

-- Default existing edges to 'unknown' - they will be reclassified on re-import
-- or can be batch-updated using UPDATE statement
UPDATE edges SET dependency_type = 'unknown' WHERE dependency_type IS NULL;

-- Create index for filtering by dependency type
CREATE INDEX IF NOT EXISTS idx_edges_dependency_type
    ON edges(import_id, dependency_type);

-- Create index for runtime-only queries (common case)
CREATE INDEX IF NOT EXISTS idx_edges_runtime
    ON edges(import_id)
    WHERE dependency_type = 'runtime';

-- Create index for build-only queries
CREATE INDEX IF NOT EXISTS idx_edges_build
    ON edges(import_id)
    WHERE dependency_type = 'build';

COMMIT;

-- Verification query (run manually to verify migration)
-- SELECT dependency_type, COUNT(*) FROM edges GROUP BY dependency_type;
