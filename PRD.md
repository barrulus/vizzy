# Vizzy - NixOS Derivation Graph Explorer

## Product Requirements Document

### Overview

Vizzy is an interactive, server-based visualization tool for exploring NixOS derivation dependency graphs. It addresses the problem that full derivation graphs (100k+ nodes) are too computationally heavy for browser-based rendering by offloading graph computation and rendering to the server.

### Problem Statement

NixOS system configurations produce massive dependency graphs. The `nix-store -q --graph` output for a typical system contains 100,000+ lines representing tens of thousands of derivations. Existing tools either:
- Crash browsers trying to render everything client-side
- Provide static images with no interactivity
- Require specialized graph databases with complex setup

Vizzy solves this by providing progressive, server-rendered exploration with PostgreSQL as the storage backend.

### Goals

1. **Interactive exploration** of derivation graphs without browser performance issues
2. **Multi-level navigation** from high-level overview to individual package details
3. **Dependency analysis** including path finding, loop detection, and redundant link identification
4. **NixOS integration** to explore flakes, hosts, and modules directly from configuration directories

### Non-Goals

- Enterprise features (auth, multi-tenancy, high availability)
- Mock data or fallback modes (hard failures for debugging)
- Support for non-NixOS derivation formats
- Real-time collaboration

---

## Technical Architecture

### Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Database | PostgreSQL | Already available on target system; excellent for graph traversal via recursive CTEs |
| Backend | Python 3.13 + FastAPI | Best-in-class graphviz bindings, easy nix subprocess integration, async support |
| Frontend | HTMX + Jinja2 | No build step, server-rendered paradigm aligns with Graphviz approach, minimal JS |
| Rendering | Graphviz (dot) | Industry standard for directed graphs, subprocess-based on-demand rendering |
| Styling | Tailwind CSS (CDN) | Rapid UI development without build tooling |

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Browser                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────────────┐  │
│  │  Navigation   │  │  Graph View   │  │   Detail Panel      │  │
│  │  - Host select│  │  - SVG render │  │   - Node metadata   │  │
│  │  - Search     │  │  - Click nodes│  │   - Dependencies    │  │
│  │  - Breadcrumb │  │  - Pan/zoom   │  │   - Analysis tools  │  │
│  └───────────────┘  └───────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ HTMX (HTML over the wire)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                         │
│                                                                  │
│  Routes:                                                         │
│  ├── GET  /                     Landing, imports list, host picker│
│  ├── GET  /explore/{import_id}  Cluster overview for an import   │
│  ├── GET  /graph/cluster/{id}/{type}  Nodes within a cluster     │
│  ├── GET  /graph/node/{id}      Single node with neighbors       │
│  ├── GET  /search               Full-text node search (trigram)  │
│  ├── GET  /defined/{import_id}  Explicitly defined packages      │
│  ├── GET  /module-packages/{id} Packages added by NixOS modules  │
│  ├── GET  /impact/{node_id}     Transitive dependency impact     │
│  ├── GET  /visual/{node_id}     Interactive vis.js explorer      │
│  ├── GET  /api/graph/{node_id}  JSON API for vis.js graph data   │
│  ├── GET  /analyze/duplicates/{id}  Packages with multiple drvs  │
│  ├── GET  /analyze/compare/{id}/{label}  Compare duplicate variants│
│  ├── GET  /analyze/path/{id}    Find path between two nodes      │
│  ├── GET  /analyze/sankey/{id}/{label}  Sankey diagram for variants│
│  ├── GET  /analyze/loops/{id}   Circular dependency detection    │
│  ├── GET  /analyze/redundant/{id}  Redundant link detection      │
│  ├── POST /import/file          Upload DOT file                  │
│  ├── POST /import/existing      Import DOT from filesystem       │
│  ├── POST /import/nix           Import from NixOS host config    │
│  └── POST /import/{id}/delete   Delete an import                 │
│                                                                  │
│  Services:                                                       │
│  ├── graph.py          Query & traverse graph in PostgreSQL      │
│  ├── render.py         Generate Graphviz DOT, render to SVG      │
│  ├── nix.py            Shell out to nix CLI for metadata/export  │
│  ├── analysis.py       Duplicates, path finding, Sankey data     │
│  └── importer.py       Parse DOT files, classify, populate DB    │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   PostgreSQL    │  │   Graphviz      │  │   Nix CLI       │
│                 │  │   (subprocess)  │  │   (subprocess)  │
│   - nodes       │  │                 │  │                 │
│   - edges       │  │   dot -Tsvg    │  │   nix eval      │
│   - analysis    │  │   dot -Tpng    │  │   nix derivation│
│   - imports     │  │                 │  │   nix-store -q  │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Database Schema

```sql
-- Imports tracking (which configurations have been loaded)
CREATE TABLE imports (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,                    -- e.g., "hostname1", "hostname2"
    config_path TEXT NOT NULL,             -- e.g., "/home/user/hostname1"
    drv_path TEXT NOT NULL,                -- full derivation path evaluated
    imported_at TIMESTAMP DEFAULT NOW(),
    node_count INT,
    edge_count INT
);

-- Nodes (derivations)
CREATE TABLE nodes (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    drv_hash TEXT NOT NULL,                -- 32-char nix hash
    drv_name TEXT NOT NULL,                -- human-readable name (e.g., "glibc-2.40-66.drv")
    label TEXT NOT NULL,                   -- display label (name without .drv)
    package_type TEXT,                     -- classified type (library, app, service, etc.)
    depth INT,                             -- distance from root
    closure_size INT,                      -- count of transitive dependencies
    metadata JSONB,                        -- cached nix metadata
    UNIQUE(import_id, drv_hash)
);

-- Edges (dependencies)
CREATE TABLE edges (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    source_id INT REFERENCES nodes(id) ON DELETE CASCADE,
    target_id INT REFERENCES nodes(id) ON DELETE CASCADE,
    edge_color TEXT,                       -- original color from DOT (informational)
    is_redundant BOOLEAN DEFAULT FALSE,    -- can be removed without changing closure
    UNIQUE(import_id, source_id, target_id)
);

-- Analysis results cache
CREATE TABLE analysis (
    id SERIAL PRIMARY KEY,
    import_id INT REFERENCES imports(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL,           -- 'loops', 'redundant', 'clusters'
    result JSONB NOT NULL,
    computed_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_nodes_import ON nodes(import_id);
CREATE INDEX idx_nodes_type ON nodes(import_id, package_type);
CREATE INDEX idx_nodes_name ON nodes(import_id, drv_name);
CREATE INDEX idx_nodes_label_trgm ON nodes USING gin(label gin_trgm_ops);  -- for fuzzy search
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_import ON edges(import_id);
```

---

## Features

### 1. Implemented Visualizations

#### Cluster Overview (`/explore/{import_id}`)
Server-rendered SVG via Graphviz showing packages grouped by `package_type`:
- Each cluster node displays: type name, package count
- Color-coded by package type
- Click any cluster to drill down to its nodes
- Layout: hierarchical top-to-bottom

#### Cluster View (`/graph/cluster/{import_id}/{package_type}`)
Focused view of nodes within a single package type:
- Shows up to 100 nodes of the selected type
- Subgraph rendered with internal dependencies
- Click any node to see its details
- Layout: force-directed

#### Node Detail (`/graph/node/{node_id}`)
Single-node centered Graphviz visualization:
- Target node prominently displayed in center
- Direct dependencies shown below (outgoing edges)
- Direct dependents shown above (incoming edges)
- Metadata panel with depth, closure size, package type
- Links to impact analysis and visual explorer

#### Visual Explorer (`/visual/{node_id}`)
Interactive client-side graph using vis.js:
- Drag nodes to rearrange layout
- Pan and zoom the viewport
- Click nodes to navigate to their detail pages
- Force-directed physics simulation
- Configurable neighbor depth (1-3 levels)
- Limited to 100 nodes for performance

#### Sankey Diagram (`/analyze/sankey/{import_id}/{label}`)
Flow visualization for duplicate package variants using Plotly:
- Shows which applications depend on which variant
- Left side: dependent packages
- Center: package variants (same name, different hashes)
- Flow width indicates number of dependency paths
- Interactive hover for details

#### Impact Visualization (`/impact/{node_id}`)
Transitive dependency breakdown (data view):
- Total count of all dependencies (direct + transitive)
- Dependencies grouped by package type with counts
- Direct dependencies listed separately
- Sorted by type frequency (largest groups first)
- Recursive CTE limited to depth 20

#### Path Visualization (`/analyze/path/{import_id}`)
Shortest dependency path between two nodes:
- Node selector for source and target
- Renders path as ordered list of nodes
- Shows path length (hop count)
- Uses PostgreSQL recursive CTE for BFS

### 2. Search & Navigation

- **Full-text search**: Find nodes by name with fuzzy matching
- **Breadcrumb trail**: Track navigation path, allow jumping back
- **URL-based state**: Shareable links to specific views
- **Keyboard shortcuts**: `/` to focus search, `Esc` to go back

### 3. Path Finding

- Select two nodes (source and target)
- Find shortest dependency path between them
- Render path as highlighted subgraph
- Show path length and intermediate nodes
- Answer: "Why does X depend on Y?"

### 4. Loop Detection (`/analyze/loops/{import_id}`)

Circular dependency detection using Tarjan's Strongly Connected Components algorithm:
- Implemented in Python using Tarjan's SCC algorithm
- Finds all strongly connected components with more than one node
- Extracts a simple cycle path within each SCC for visualization
- Displays all nodes participating in cycles with links to node details
- Shows cycle count and total affected nodes
- Loops indicate circular dependencies (unusual in Nix but possible with overrides)

### 5. Redundant Link Detection (`/analyze/redundant/{import_id}`)

Transitive reduction analysis to identify inherited dependencies:
- Uses PostgreSQL recursive CTE to find alternative paths
- Identifies edges A→C where a path A→B→...→C exists (depth limit: 5)
- Shows the bypass path that makes each edge redundant
- Provides `mark_redundant_edges()` function to update the `is_redundant` flag in database
- Displays redundancy percentage and links to affected nodes
- Helps understand true vs inherited dependencies

### 6. NixOS Configuration Integration

When pointed at a NixOS configuration directory:

1. **Discovery**:
   - Parse `flake.nix` to find `nixosConfigurations`
   - List available hosts, devShells, packages
   - Show flake inputs and their sources

2. **Selection UI**:
   - Dropdown/list to select what to explore
   - "Explore hostname2", "Explore hostname1", etc.
   - Option to compare two configurations

3. **Import Process**:
   ```bash
   # Evaluate to get derivation path
   nix eval .#nixosConfigurations.{host}.config.system.build.toplevel.drvPath --raw

   # Generate graph
   nix-store -q --graph {drv_path}

   # Parse and import to PostgreSQL
   ```

4. **Module Exploration** (future):
   - Map derivations back to NixOS modules
   - Show which module introduced which package

### 7. Host Comparison

Compare two hosts/configurations side-by-side at multiple levels:

#### Comparison Modes

| Mode | Description | Example |
|------|-------------|---------|
| **Full diff** | Show packages unique to each host, shared packages | "What's different between hostname1 and hostname2?" |
| **Scoped diff** | Compare specific subsystems | "Compare networking between hostname1 and hostname2" |
| **Package trace** | How same package arrives via different paths | "How does ripgrep get added to hostname1 vs hostname2?" |

#### UI for Comparison

```
┌─────────────────────────────────────────────────────────────────────┐
│  Compare: [hostname1 ▼]  ←→  [hostname2 ▼]    Scope: [networking ▼]   │
├─────────────────────────────────┬───────────────────────────────────┤
│        hostname1 only (12)        │        hostname2 only (8)          │
│  • networkmanager-1.48          │  • systemd-networkd               │
│  • wpa_supplicant-2.11          │  • iwd-2.22                       │
│  • ...                          │  • ...                            │
├─────────────────────────────────┴───────────────────────────────────┤
│                        shared (47)                                   │
│  • iptables-1.8  • iproute2-6.11  • dnsmasq-2.90  • ...             │
└─────────────────────────────────────────────────────────────────────┘
```

#### Package Trace Comparison

Show dependency path differences:
```
ripgrep on hostname1:              ripgrep on hostname2:
system-path                      system-path
  └── user-packages                └── home-manager
        └── ripgrep-14.1                 └── ripgrep-14.1
```

### 8. Nix Metadata Integration

Metadata fetching supports both eager (at import time) and on-demand (when viewing a node) modes:

**Eager fetching** (optional at import):
- Enabled via `fetch_metadata_on_import=True` parameter
- Processes nodes in batches of 50 for efficiency
- Limited to configurable `max_nodes` (default 1000) to prevent import timeouts
- Prioritizes nodes by depth (closest to root first)

**On-demand fetching** (default):
- Metadata fetched when viewing a node's detail page
- Cached in database after first fetch
- Transparent to user - metadata appears on node detail page

For each node, fetch rich metadata via:

```bash
nix derivation show /nix/store/{hash}-{name}.drv
```

Display (in Node Detail view):
- System architecture (e.g., `x86_64-linux`)
- Builder path
- Build inputs count (derivations)
- Source inputs count
- Output paths (out, dev, lib, etc.)
- Version and package name (from env)
- Source URL (if available)

Cache results in `nodes.metadata` JSONB column as a summary extracted by `extract_metadata_summary()`.

---

## User Interface

### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  [Logo] Vizzy                    [Search...] 🔍    [Import] [Settings]│
├──────────────────────────────────────────────────────────────────────┤
│ ◀ Overview > Libraries > glibc-2.40                    [Path] [Loops]│
├────────────────────────────────────┬─────────────────────────────────┤
│                                    │                                 │
│                                    │  glibc-2.40-66                  │
│                                    │  ─────────────                  │
│          [Graph SVG]               │  Type: library                  │
│                                    │  Depth: 2                       │
│          (pan/zoom enabled)        │  Closure: 847 packages          │
│                                    │                                 │
│          Click nodes to explore    │  Dependencies (23):             │
│                                    │  • linux-headers-6.16           │
│                                    │  • bootstrap-tools              │
│                                    │  • ...                          │
│                                    │                                 │
│                                    │  Dependents (1,247):            │
│                                    │  • systemd-258                  │
│                                    │  • coreutils-9.8                │
│                                    │  • ...                          │
│                                    │                                 │
└────────────────────────────────────┴─────────────────────────────────┘
```

### Interactions

| Action | Trigger | Result |
|--------|---------|--------|
| Explore node | Click node in graph | Load detail view for that node |
| Go back | Click breadcrumb / press Esc | Return to previous view |
| Search | Type in search box | Show matching nodes, click to navigate |
| Find path | Select "Path" tool, pick two nodes | Render path subgraph |
| Show loops | Click "Loops" button | Highlight all cycles |
| Pan graph | Click and drag | Move viewport |
| Zoom | Scroll wheel | Zoom in/out |

### Responsive Behavior

- Detail panel collapses to bottom sheet on narrow screens
- Graph takes full width on mobile
- Touch-friendly node selection

---

## Package Type Classification

Using Nix metadata (via `nix derivation show`), classify packages:

| Type | Detection Heuristic |
|------|---------------------|
| `library` | Name contains `-lib` or is known library (glibc, openssl, etc.) |
| `application` | Has `bin/` output, not a library |
| `service` | Name contains `systemd-`, `-service`, or is systemd unit |
| `kernel` | Name starts with `linux-` and contains version |
| `firmware` | Name contains `firmware` |
| `development` | Name contains `-dev`, `gcc`, `clang`, build tools |
| `configuration` | Name ends in `.json`, `.conf`, `.sh`, `-config` |
| `python-package` | Name starts with `python3.x-` |
| `perl-package` | Name starts with `perl5.x-` |
| `font` | Name contains `font`, `nerd-fonts`, etc. |
| `documentation` | Name contains `-doc`, `-man`, `-info` |
| `bootstrap` | Name contains `bootstrap` |
| `other` | Default fallback |

Classification runs at import time; results stored in `nodes.package_type`.

---

## File Structure

```
vizzy/
├── README.md                 # Project documentation
├── CLAUDE.md                 # Claude Code guidance
├── PRD.md                    # This document
├── .env                      # Environment configuration
├── .env.example              # Example environment file
├── flake.nix                 # Nix flake for dev environment
├── flake.lock
├── pyproject.toml            # Python project config
├── src/
│   └── vizzy/
│       ├── __init__.py
│       ├── main.py           # FastAPI application entry
│       ├── config.py         # Pydantic settings configuration
│       ├── models.py         # Pydantic models
│       ├── database.py       # PostgreSQL connection (psycopg)
│       ├── services/
│       │   ├── __init__.py
│       │   ├── graph.py      # Graph queries (nodes, edges, search)
│       │   ├── render.py     # Graphviz DOT generation & SVG rendering
│       │   ├── nix.py        # Nix CLI integration (eval, graph export)
│       │   ├── analysis.py   # Duplicates, path finding, Sankey data
│       │   └── importer.py   # DOT parsing, classification, import
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── pages.py      # HTML routes (explore, node, search, import)
│       │   └── analyze.py    # Analysis routes (duplicates, path, sankey)
│       └── templates/
│           ├── base.html
│           ├── index.html          # Landing page
│           ├── explore.html        # Cluster overview
│           ├── cluster.html        # Nodes in cluster
│           ├── node.html           # Node detail
│           ├── defined.html        # Defined packages
│           ├── module_packages.html # Module-added packages
│           ├── impact.html         # Impact analysis
│           ├── visual.html         # vis.js explorer
│           ├── analyze/
│           │   ├── duplicates.html
│           │   ├── compare.html
│           │   ├── path.html
│           │   ├── sankey.html
│           │   ├── loops.html
│           │   └── redundant.html
│           └── partials/
│               └── search_results.html
├── static/
│   ├── css/
│   │   └── app.css
│   └── js/
│       └── app.js
├── tests/
│   └── ...
└── scripts/
    └── init_db.sql           # Database schema initialization
```

---

## Development Setup

### Prerequisites

- PostgreSQL running on localhost
- Nix with flakes enabled
- Python 3.13 (provided by flake devShell)
- Graphviz installed

### Database Setup

```bash
createdb vizzy
psql vizzy < scripts/init_db.sql
```

### Running

```bash
cd vizzy2
nix develop  # or use existing devShell
pip install -e .
uvicorn vizzy.main:app --reload
```

### Environment Variables

Configuration uses pydantic-settings with `VIZZY_` prefix:

```bash
VIZZY_DATABASE_URL=postgresql://username:password@localhost/vizzy
VIZZY_NIX_CONFIG_PATH=/path/to/nixos-config
VIZZY_HOST=127.0.0.1      # optional
VIZZY_PORT=8000           # optional
VIZZY_DEBUG=false         # optional
```

---

## Implementation Phases

### Phase 1: Foundation ✅
- [x] Database schema and connection
- [x] DOT file parser and importer
- [x] Basic FastAPI skeleton
- [x] Simple graph rendering (full graph, no clustering)

### Phase 2: Core Visualization ✅
- [x] Package type classification
- [x] Overview clustering
- [x] Focused view (expand cluster)
- [x] Detail view (single node)
- [x] HTMX navigation

### Phase 3: Search & Analysis ✅
- [x] Full-text search with trigram matching
- [x] Path finding between nodes
- [x] Duplicate package detection
- [x] Sankey visualization for variants
- [x] Loop detection
- [x] Redundant link detection

### Phase 4: NixOS Integration ✅
- [x] Flake discovery and parsing
- [x] Host/module selection UI
- [x] On-demand graph export from nix
- [x] System packages enumeration
- [x] Module-added packages view
- [x] Eager metadata fetching at import

### Phase 5: Host Comparison
- [ ] Full diff between two hosts
- [ ] Scoped diff (by package type/subsystem)
- [ ] Package trace comparison
- [ ] Comparison UI

### Phase 6: Additional Visualizations ✅
- [x] Impact analysis (transitive closure breakdown)
- [x] Visual explorer (vis.js interactive graph)
- [x] Defined packages view
- [x] Module packages view

### Phase 7: Polish
- [ ] Pan/zoom for large Graphviz graphs
- [ ] Keyboard navigation
- [x] URL state management
- [ ] Performance optimization

---

## Success Criteria

1. **Performance**: Overview renders in <2 seconds for 50k+ node graphs
2. **Usability**: Navigate from overview to specific package in <5 clicks
3. **Accuracy**: Path finding returns correct shortest path
4. **Integration**: Can explore any host in the hostname1 configuration

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Server-side rendering | Graphviz subprocess | Handles 100k+ nodes without browser performance issues |
| Interactive graphs | vis.js (client-side) | Complements Graphviz for local exploration; limited to 100 nodes |
| Flow diagrams | Plotly Sankey | Best-in-class flow visualization; used for duplicate variant analysis |
| Duplicate detection | Same label, different hash | Identifies packages built multiple ways (different flags/deps) |
| Metadata fetching | Eager (at import) | One-time operation, data is static, avoids exploration latency |
| Search | PostgreSQL trigram | Fuzzy matching without external search engine |
| Interface | Web UI primary | TUI planned as future feature |

---

## Future Features

These are explicitly out of scope for initial implementation but desired:

1. **TUI Interface**: Terminal-based UI for exploration without browser
2. **Export**: Filtered DOT, JSON, or other formats for external tools
3. **Module Mapping**: Trace packages back to specific NixOS modules that added them
4. **Diff Over Time**: Compare same host across different commits/generations