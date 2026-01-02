-- Performance optimization indexes for Vizzy
-- Migration: 020_performance_indexes.sql
-- Created: 2024-12-30
-- Task: 7-003 Performance optimization

-- Optimize queries that sort by closure_size descending
-- Used in: get_subgraph, get_nodes_by_type
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_closure_desc
    ON nodes(import_id, closure_size DESC NULLS LAST);

-- Optimize label pattern matching for search
-- Complements the existing trigram index for prefix/pattern searches
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_label_pattern
    ON nodes(import_id, label text_pattern_ops);

-- Optimize queries filtering on is_top_level (when added in future)
-- Partial index for top-level nodes only
-- Note: This will be useful after 8A-002 adds is_top_level column
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_toplevel
--     ON nodes(import_id) WHERE is_top_level = true;

-- Optimize edge lookups with both source and target (for subgraph queries)
-- Used in: get_subgraph when fetching edges between node sets
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_edges_both
    ON edges(import_id, source_id, target_id);

-- Optimize edge lookups by import_id with source for neighbor queries
-- Helps with get_node_with_neighbors dependent lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_edges_source_import
    ON edges(import_id, source_id);

-- Optimize edge lookups by import_id with target for neighbor queries
-- Helps with get_node_with_neighbors dependency lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_edges_target_import
    ON edges(import_id, target_id);

-- Optimize drv_hash lookups (used in get_node_by_hash)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_drv_hash
    ON nodes(import_id, drv_hash);

-- Add index for package_type filtering with closure size ordering
-- Used in: get_nodes_by_type
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_type_closure
    ON nodes(import_id, package_type, closure_size DESC NULLS LAST);
