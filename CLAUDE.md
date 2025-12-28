# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vizzy is an interactive visualization tool for exploring NixOS derivation dependency graphs. It solves the problem that full derivation graphs (100k+ nodes) are too heavy for browser rendering by offloading graph computation to a PostgreSQL-backed server with server-side Graphviz rendering.

## Development Commands

```bash
# Enter Nix dev shell (provides Python 3.13, graphviz, postgresql)
nix develop

# Install package in editable mode
pip install -e ".[dev]"

# Run development server
uvicorn vizzy.main:app --reload

# Run tests
pytest

# Run single test
pytest tests/test_file.py::test_name -v

# Database setup
createdb vizzy
psql vizzy < scripts/init_db.sql
```

## Architecture

```
Browser (HTMX + SVG)
    ↓ (HTML over the wire)
FastAPI Application (routes/, templates/)
    ↓
Service Layer (services/)
    ↓
PostgreSQL + Graphviz + Nix CLI
```

**Key design decisions:**
- Server-rendered SVG via Graphviz subprocess (not browser-side rendering)
- HTMX for interactivity without JavaScript framework
- PostgreSQL trigram extension for fuzzy search
- Recursive CTEs for graph traversal (depth, closure size, path finding)
- Package type classification at import time for clustering

## Code Structure

**Services** (`src/vizzy/services/`):
- `graph.py` - Graph queries: get_node_with_neighbors, get_subgraph, search_nodes
- `importer.py` - DOT file parsing, package classification, bulk import
- `render.py` - Graphviz DOT generation and SVG rendering
- `analysis.py` - Duplicates, path finding, Sankey data
- `nix.py` - Nix CLI integration (drv paths, graph export, metadata)

**Routes** (`src/vizzy/routes/`):
- `pages.py` - Main HTML routes (explore, node detail, search, import)
- `analyze.py` - Analysis routes (duplicates, path, sankey)

**Database** (`scripts/init_db.sql`):
- `imports` - Loaded configurations
- `nodes` - Derivations with hash, name, package_type, depth, closure_size
- `edges` - Dependencies (source → target)
- `analysis` - Cached analysis results

## Configuration

Uses pydantic-settings with `VIZZY_` prefix. Required env vars in `.env`:
- `VIZZY_DATABASE_URL` - PostgreSQL connection string
- `VIZZY_NIX_CONFIG_PATH` - Path to NixOS flake for host discovery
