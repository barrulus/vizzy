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
