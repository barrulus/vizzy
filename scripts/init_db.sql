-- Vizzy Database Schema
-- Run with: psql vizzy < scripts/init_db.sql

-- Enable trigram extension for fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Imports tracking (which configurations have been loaded)
CREATE TABLE IF NOT EXISTS imports (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    config_path TEXT NOT NULL,
    drv_path TEXT NOT NULL,
    imported_at TIMESTAMP DEFAULT NOW(),
    node_count INT,
    edge_count INT
);

-- Nodes (derivations)
CREATE TABLE IF NOT EXISTS nodes (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    drv_hash TEXT NOT NULL,
    drv_name TEXT NOT NULL,
    label TEXT NOT NULL,
    package_type TEXT,
    depth INT,
    closure_size INT,
    metadata JSONB,
    -- Phase 8A-002: Top-level package identification
    is_top_level BOOLEAN DEFAULT FALSE,  -- True if user-facing (in systemPackages, etc.)
    top_level_source TEXT,               -- Where defined: 'systemPackages', 'programs.git.enable', etc.
    -- Phase 8A-005: Module type classification
    module_type TEXT,                    -- 'systemPackages', 'programs', 'services', or 'other'
    -- Phase 8A-003: Closure contribution calculation
    unique_contribution INT,             -- Dependencies only reachable via this package
    shared_contribution INT,             -- Dependencies also reachable via other packages
    total_contribution INT,              -- Sum of unique + shared
    contribution_computed_at TIMESTAMP,  -- When contribution was last calculated
    UNIQUE(import_id, drv_hash)
);

-- Edges (dependencies)
CREATE TABLE IF NOT EXISTS edges (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    source_id INT REFERENCES nodes(id) ON DELETE CASCADE,
    target_id INT REFERENCES nodes(id) ON DELETE CASCADE,
    edge_color TEXT,
    is_redundant BOOLEAN DEFAULT FALSE,
    -- Phase 8A-001: Edge classification
    dependency_type TEXT,  -- 'build', 'runtime', or 'unknown'
    UNIQUE(import_id, source_id, target_id)
);

-- Analysis results cache
CREATE TABLE IF NOT EXISTS analysis (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL,
    result JSONB NOT NULL,
    computed_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_nodes_import ON nodes(import_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(import_id, package_type);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(import_id, drv_name);
CREATE INDEX IF NOT EXISTS idx_nodes_label_trgm ON nodes USING gin(label gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_import ON edges(import_id);
CREATE INDEX IF NOT EXISTS idx_analysis_import ON analysis(import_id);
CREATE INDEX IF NOT EXISTS idx_analysis_type ON analysis(import_id, analysis_type);

-- Phase 8A-002: Top-level package indexes
CREATE INDEX IF NOT EXISTS idx_nodes_top_level
    ON nodes(import_id) WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_source
    ON nodes(import_id, top_level_source) WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_nodes_top_level_closure
    ON nodes(import_id, closure_size DESC NULLS LAST) WHERE is_top_level = TRUE;

-- Phase 8A-001: Edge classification indexes
CREATE INDEX IF NOT EXISTS idx_edges_dependency_type
    ON edges(import_id, dependency_type);
CREATE INDEX IF NOT EXISTS idx_edges_runtime
    ON edges(import_id) WHERE dependency_type = 'runtime';
CREATE INDEX IF NOT EXISTS idx_edges_build
    ON edges(import_id) WHERE dependency_type = 'build';

-- Phase 8A-003: Closure contribution indexes
CREATE INDEX IF NOT EXISTS idx_nodes_unique_contribution
    ON nodes(import_id, unique_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_nodes_total_contribution
    ON nodes(import_id, total_contribution DESC NULLS LAST)
    WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_nodes_contribution_stale
    ON nodes(import_id)
    WHERE is_top_level = TRUE AND contribution_computed_at IS NULL;

-- Schema version tracking for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    id SERIAL PRIMARY KEY,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT NOW(),
    description TEXT
);

-- Phase 8A-004: Baseline closure reference system
-- Baselines store snapshot metrics from imports for later comparison.
CREATE TABLE IF NOT EXISTS baselines (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,                         -- User-friendly name
    description TEXT,                           -- Optional description
    source_import_id INT REFERENCES imports(id) ON DELETE SET NULL,
    node_count INT NOT NULL,                    -- Total derivations
    edge_count INT NOT NULL,                    -- Total dependencies
    closure_by_type JSONB DEFAULT '{}'::jsonb,  -- Breakdown by package type
    top_level_count INT,                        -- Number of top-level packages
    runtime_edge_count INT,                     -- Runtime dependencies
    build_edge_count INT,                       -- Build-time dependencies
    max_depth INT,                              -- Maximum dependency depth
    avg_depth FLOAT,                            -- Average dependency depth
    top_contributors JSONB DEFAULT '[]'::jsonb, -- Top contributors snapshot
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_system_baseline BOOLEAN DEFAULT FALSE,   -- True for built-in baselines
    tags TEXT[] DEFAULT '{}'                    -- Flexible tagging
);

-- Baseline comparison cache
CREATE TABLE IF NOT EXISTS baseline_comparisons (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    baseline_id INT REFERENCES baselines(id) ON DELETE CASCADE,
    node_difference INT NOT NULL,
    edge_difference INT NOT NULL,
    percentage_difference FLOAT NOT NULL,
    differences_by_type JSONB DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(import_id, baseline_id)
);

-- Baseline indexes
CREATE INDEX IF NOT EXISTS idx_baselines_name ON baselines(name);
CREATE INDEX IF NOT EXISTS idx_baselines_created ON baselines(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_baselines_source ON baselines(source_import_id);
CREATE INDEX IF NOT EXISTS idx_baselines_system ON baselines(is_system_baseline) WHERE is_system_baseline = TRUE;
CREATE INDEX IF NOT EXISTS idx_baselines_tags ON baselines USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_baseline_comparisons_import ON baseline_comparisons(import_id);
CREATE INDEX IF NOT EXISTS idx_baseline_comparisons_baseline ON baseline_comparisons(baseline_id);

-- Phase 8A-005: Module attribution indexes
CREATE INDEX IF NOT EXISTS idx_nodes_module_type
    ON nodes(import_id, module_type) WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_nodes_module_attribution
    ON nodes(import_id, module_type, top_level_source, closure_size DESC NULLS LAST)
    WHERE is_top_level = TRUE;

-- Phase 8A-005: Module attribution summary table
CREATE TABLE IF NOT EXISTS module_attribution_summary (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    system_packages_count INT DEFAULT 0,
    programs_count INT DEFAULT 0,
    services_count INT DEFAULT 0,
    other_count INT DEFAULT 0,
    by_source JSONB DEFAULT '{}'::jsonb,
    top_modules JSONB DEFAULT '[]'::jsonb,
    computed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(import_id)
);

CREATE INDEX IF NOT EXISTS idx_module_summary_import ON module_attribution_summary(import_id);
