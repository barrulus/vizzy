# Vizzy

Interactive visualization tool for exploring NixOS derivation dependency graphs.

Vizzy solves the problem that full NixOS derivation graphs (100k+ nodes) are too computationally heavy for browser-based rendering. It offloads graph computation to a PostgreSQL-backed server with server-side Graphviz rendering, delivering pre-rendered SVG to the browser.

## Features

### Core Visualization
- Multi-level graph visualization (clusters → nodes → details)
- Server-side SVG rendering via Graphviz
- Interactive vis.js graph explorer with semantic zoom
- Closure Treemap with D3.js for size attribution
- Pan/zoom for large graphs with keyboard navigation

### Analysis Tools
- Fuzzy search with PostgreSQL trigram matching
- Duplicate package detection and comparison
- Dependency path finding
- Package impact analysis (transitive closure)
- Loop detection (circular dependencies via Tarjan's SCC algorithm)
- Redundant link detection (transitive reduction analysis)
- Variant Matrix showing which apps use which package variants
- Sankey flow diagrams showing why variants exist

### Question-Driven Insights
- **System Health Dashboard** - Key metrics at a glance
- **Why Chain** - "Why is package X in my closure?" with attribution paths
- **Closure Treemap** - "Which packages contribute most to closure size?"
- Essential vs removable package classification
- Module-level attribution (systemPackages, programs.*, services.*)

### Host Comparison
- Side-by-side diff between two NixOS configurations
- Semantic grouping by category (Desktop, Services, Development, etc.)
- Package trace comparison (how a package is reached in each config)
- Version difference detection
- Baseline presets for common comparisons
- Export comparison reports (JSON, CSV, Markdown)

### NixOS Integration
- Direct NixOS flake integration
- Automatic host discovery from flake
- Build-time vs runtime edge classification
- Top-level package identification

## IMPORTANT NOTE

> This is a quick LLM generated project that could be useful to someone, or not.
If you think of a way to make the visualizations make more sense or want something added, please feel free to contribute or submit an issue with a detailed explanation and I will happily burn some tokens to make it a little less generically useless :)

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
- Nix derivation metadata (fetched on-demand via `nix derivation show`):
  - System architecture
  - Builder path
  - Build inputs count
  - Output paths
  - Version and package name
  - Source URL
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

Sankey flow diagram showing why package variants exist:
- **Left side**: Top-level applications (firefox, vscode, etc.)
- **Middle**: Intermediate dependencies (curl, openssl, etc.)
- **Right side**: Package variants (different derivation hashes)
- Filter by specific application to trace its dependency path
- Uses Plotly for interactive visualization

### Analysis: Loops (`/analyze/loops/{import_id}`)

Circular dependency detection using Tarjan's Strongly Connected Components algorithm:
- Finds all cycles in the dependency graph
- Shows nodes participating in each cycle
- Displays the cycle path for visualization
- Circular dependencies are unusual in Nix but can occur with overrides or fixpoints

### Analysis: Redundant Links (`/analyze/redundant/{import_id}`)

Transitive reduction analysis to find redundant edges:
- Identifies edges A → C where a path A → B → ... → C exists
- Shows the bypass path that makes each edge redundant
- Helps understand inherited vs. direct dependencies
- Useful for simplifying dependency understanding

### Analysis: Why Chain (`/analyze/why/{import_id}/{node_id}`)

Attribution analysis answering "Why is this package in my closure?":
- Shows all paths from top-level packages to the target
- Groups paths by intermediate "via" nodes for readability
- Displays essential vs removable classification
- Module-level attribution (which NixOS option added it)
- Export reports in JSON, CSV, or Markdown

### Analysis: Variant Matrix (`/analyze/matrix/{import_id}/{label}`)

Matrix view showing which applications use which package variants:
- Rows: Applications that depend on the package
- Columns: Different derivation variants of the package
- Highlights consolidation opportunities
- Filter by runtime/build-time dependencies
- Sort by dependent count, closure size, or hash

### System Health Dashboard (`/dashboard/{import_id}`)

At-a-glance metrics for your system closure:
- Total derivations and edges
- Redundancy score (percentage of redundant edges)
- Runtime vs build-time dependency ratio
- Depth statistics (max, average, median)
- Top contributors by closure size
- Package type distribution chart
- Baseline comparison (if configured)

### Closure Treemap (`/treemap/{import_id}`)

D3.js treemap visualization showing closure size attribution:
- View modes: By Application, By Type, By Depth, Flat
- Filter by runtime/build-time dependencies
- Click to zoom into subcategories
- Breadcrumb navigation
- Keyboard shortcuts (arrows to navigate, Escape to go back)
- Color-coded by package type

### Host Comparison (`/compare`)

Compare two NixOS configurations side-by-side:
- Select any two imports to compare
- Shows packages unique to each side
- Highlights version/hash differences
- Semantic grouping by category (Desktop, Services, etc.)
- Baseline presets for common comparisons

### Package Trace (`/compare/trace/{left_id}/{right_id}`)

Compare how a package is reached in two configurations:
- Shows dependency paths in both configs
- Highlights different inclusion reasons
- Useful for understanding divergent closures

### Baseline Management (`/baselines`)

Manage closure baselines for comparison:
- Create baselines from any import
- System presets (minimal, desktop, server)
- Use as comparison reference in dashboard
- Track closure growth over time

## Keyboard Shortcuts

Global shortcuts available across views:

| Key | Action |
|-----|--------|
| `/` | Focus search |
| `?` | Show help |
| `Escape` | Close modal / Go back |
| `Home` | Reset to root view |

Treemap-specific:
| Key | Action |
|-----|--------|
| Arrow keys | Navigate between cells |
| Enter/Space | Zoom into cell |
| `r` | Toggle runtime-only filter |
| `b` | Toggle build-time-only filter |
| Backspace | Go back one level |

## Architecture

```
Browser (HTMX + SVG + D3.js)
    ↓ HTML over the wire
FastAPI Application
    ↓
Service Layer
    ↓
PostgreSQL + Graphviz + Nix CLI
```

- **HTMX**: Server-rendered HTML with dynamic updates, minimal JavaScript
- **D3.js**: Client-side treemap visualization
- **vis.js**: Interactive graph explorer
- **Graphviz**: Server-side graph rendering to SVG
- **PostgreSQL**: Graph storage with trigram search and recursive CTE queries
- **Jinja2**: Server-side templating
- **Plotly**: Interactive Sankey diagrams

## License

MIT
