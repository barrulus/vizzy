# Vizzy

Interactive visualization tool for exploring NixOS derivation dependency graphs.

Vizzy solves the problem that full NixOS derivation graphs (100k+ nodes) are too computationally heavy for browser-based rendering. It offloads graph computation to a PostgreSQL-backed server with server-side Graphviz rendering, delivering pre-rendered SVG to the browser.

## Features

- Multi-level graph visualization (clusters → nodes → details)
- Server-side SVG rendering via Graphviz
- Fuzzy search with PostgreSQL trigram matching
- Duplicate package detection and comparison
- Dependency path finding
- Package impact analysis (transitive closure)
- Interactive vis.js graph explorer
- Direct NixOS flake integration

## Prerequisites

- Python 3.13+
- PostgreSQL 13+ (with pg_trgm extension)
- Graphviz
- Nix (for NixOS integration features)

## Quick Start

### 1. Clone and enter development shell

```bash
git clone <repo-url>
cd vizzy
nix develop  # Provides Python 3.13, Graphviz, and activates a venv
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Database Setup

Requires PostgreSQL to be running on your system. Create the database and initialize the schema:

```bash
createdb vizzy
psql vizzy < scripts/init_db.sql
```

The schema creates:
- `imports` - Tracks loaded configurations
- `nodes` - Derivations with metadata (hash, name, type, depth, closure size)
- `edges` - Dependencies between nodes
- `analysis` - Cached analysis results
- Trigram index for fuzzy search

### 4. Environment Configuration

Copy the example environment file and configure:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Required: PostgreSQL connection
VIZZY_DATABASE_URL=postgresql://username:password@localhost/vizzy

# Required: Path to your NixOS flake (for host discovery)
VIZZY_NIX_CONFIG_PATH=/path/to/your/nixos-config

# Optional: Server settings
VIZZY_HOST=127.0.0.1
VIZZY_PORT=8000
VIZZY_DEBUG=true
```

### 5. Run

```bash
uvicorn vizzy.main:app --reload
```

Visit http://127.0.0.1:8000

## Importing Graphs

### From NixOS Flake

If your `VIZZY_NIX_CONFIG_PATH` points to a valid flake with `nixosConfigurations`, you can import directly from the home page by selecting a host.

### From DOT File

You can upload a pre-generated DOT file or import one from the filesystem.

Generate a DOT file from your NixOS flake:

```bash
nix eval .#nixosConfigurations.<hostname>.config.system.build.toplevel.drvPath --raw \
  | xargs nix-store -q --graph \
  | sed 's|/nix/store/[a-z0-9]\{32\}-||g' \
  > graph.dot
```

The `sed` command strips the `/nix/store/<hash>-` prefix from node names for readability.

## Pages

### Home (`/`)

Landing page displaying:
- List of imported configurations with node/edge counts
- Import options: upload DOT file, import from filesystem, or select a NixOS host
- Host selector (if flake is configured)

### Explore (`/explore/{import_id}`)

Main exploration view showing:
- Cluster overview: packages grouped by type (kernel, library, service, etc.) as a high-level graph
- Click any cluster to drill down into its nodes
- Summary statistics for the import

### Cluster View (`/graph/cluster/{import_id}/{package_type}`)

Focused view of a single package type cluster:
- All nodes of the selected type (limited to 100 for performance)
- Subgraph showing dependencies between nodes in this cluster
- Click any node to see its details

### Node Detail (`/graph/node/{node_id}`)

Detailed view of a single derivation:
- Node metadata (hash, name, type, depth, closure size)
- Direct dependencies (what this node depends on)
- Direct dependents (what depends on this node)
- Graph visualization centered on this node
- Links to impact analysis and visual explorer

### Search (`/search?import_id=X&q=query`)

Fuzzy search across all nodes in an import using PostgreSQL trigram matching. Results link directly to node detail pages.

### Defined Packages (`/defined/{import_id}`)

Shows explicitly defined system packages from your NixOS configuration:
- Matched packages (found in the derivation graph)
- Unmatched packages (defined but not found - may indicate naming differences)
- Useful for understanding what you've explicitly installed vs. dependencies

### Module Packages (`/module-packages/{import_id}`)

Shows packages added by NixOS modules (not explicitly defined by user):
- Packages in system-path that aren't in your explicit package list
- Helps identify what modules are pulling in
- Grouped by package type

### Package Impact (`/impact/{node_id}`)

Transitive dependency analysis for a single package:
- Total count of all dependencies (direct and transitive)
- Dependencies grouped by package type
- Direct vs. transitive breakdown
- Shows the "cost" of including this package

### Visual Explorer (`/visual/{node_id}`)

Interactive graph using vis.js:
- Drag and zoom the graph
- Click nodes to navigate
- Expand/collapse neighbors
- Useful for exploring local graph structure interactively

### Analysis: Duplicates (`/analyze/duplicates/{import_id}`)

Finds packages that have multiple derivations in your system:
- Lists packages with more than one derivation
- Shows count of variants for each
- Common with packages built with different flags or dependencies
- Links to comparison view

### Analysis: Compare (`/analyze/compare/{import_id}/{label}`)

Side-by-side comparison of duplicate package variants:
- Shows all derivations with the same base name
- Highlights differences in dependencies
- Helps understand why multiple versions exist

### Analysis: Path Finder (`/analyze/path/{import_id}`)

Find the shortest dependency path between two nodes:
- Select source and target nodes
- Shows the chain of dependencies connecting them
- Useful for understanding "why does X depend on Y?"

### Analysis: Sankey (`/analyze/sankey/{import_id}/{label}`)

Sankey flow diagram for package variants:
- Visualizes which applications depend on which variants
- Shows dependency flow from dependents through variants
- Uses Plotly for interactive visualization

## Architecture

```
Browser (HTMX + SVG)
    ↓ HTML over the wire
FastAPI Application
    ↓
Service Layer
    ↓
PostgreSQL + Graphviz + Nix CLI
```

- **HTMX**: Server-rendered HTML with dynamic updates, no JavaScript framework
- **Graphviz**: Server-side graph rendering to SVG
- **PostgreSQL**: Graph storage with trigram search and recursive CTE queries
- **Jinja2**: Server-side templating

## Development

```bash
# Run tests
pytest

# Run single test
pytest tests/test_file.py::test_name -v

# Run with coverage
pytest --cov=vizzy
```

## License

MIT
