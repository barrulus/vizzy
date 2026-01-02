-- Migration: 035_closure_contribution.sql
-- Phase 8A-003: Add closure contribution calculation
--
-- This migration adds columns to track each package's contribution to the total
-- closure size. This enables answering questions like "why is my closure so big?"
-- and "what packages contribute most to closure size?"
--
-- Contribution is split into:
-- - unique_contribution: Dependencies only reachable via this package
-- - shared_contribution: Dependencies also reachable via other top-level packages
-- - total_contribution: Sum of unique + shared (stored for query convenience)

BEGIN;

-- Add unique_contribution column
-- This represents the number of dependencies ONLY reachable through this package
-- If removed, these deps would also be removed from the closure
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS unique_contribution INT;

-- Add shared_contribution column
-- This represents the number of dependencies also reachable via other packages
-- These would remain in the closure even if this package were removed
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS shared_contribution INT;

-- Add total_contribution for convenience (unique + shared)
-- This equals the package's closure_size for top-level packages
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS total_contribution INT;

-- Add contribution_computed_at timestamp to track when contribution was calculated
-- Allows for selective recomputation when dependencies change
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS contribution_computed_at TIMESTAMP;

-- Create index for querying nodes by unique contribution (largest blockers)
CREATE INDEX IF NOT EXISTS idx_nodes_unique_contribution
    ON nodes(import_id, unique_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;

-- Create index for querying nodes by total contribution
CREATE INDEX IF NOT EXISTS idx_nodes_total_contribution
    ON nodes(import_id, total_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;

-- Create index for finding nodes needing contribution recomputation
CREATE INDEX IF NOT EXISTS idx_nodes_contribution_stale
    ON nodes(import_id)
    WHERE is_top_level = TRUE AND contribution_computed_at IS NULL;

COMMIT;

-- Verification query (run manually to verify migration)
-- SELECT COUNT(*) as total,
--        COUNT(unique_contribution) as with_unique,
--        COUNT(shared_contribution) as with_shared
-- FROM nodes WHERE import_id = <your_import_id>;
