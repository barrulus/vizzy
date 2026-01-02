# Phase 8: Question-Driven Visualizations - Agent Instructions

## Overview

This phase adds question-driven visualizations that transform Vizzy from showing "what exists" to answering "why does this exist and what should I do about it?"

**Phase 6 (Base) - Already Complete:**
- ✅ Impact analysis (transitive closure breakdown)
- ✅ Visual explorer (vis.js interactive graph)
- ✅ Defined packages view
- ✅ Module packages view

**Phase 8 Sections:**
- 8A: Data Model Enhancements (foundation for new viz)
- 8B: System Health Dashboard
- 8C: Closure Size Treemap
- 8D: Variant Matrix (enhanced duplicates)
- 8E: Why Chain (attribution explorer)
- 8F: Enhanced Comparison (extends Phase 5)
- 8G: Visual Explorer Improvements
- 8H: UX Polish

---

# Section 8A: Data Model Enhancements

These foundational changes enable the new visualizations.

---

## Task 8A-001: Add Build-time vs Runtime Edge Classification

### Objective
Distinguish build-time dependencies from runtime dependencies.

### Context
Currently all edges are treated identically. Build-time deps (gcc, cargo) vs runtime deps (shared libs) have different implications for closure analysis.

### Implementation Steps

1. **Update database schema**
   ```sql
   -- scripts/migrations/010_edge_classification.sql
   ALTER TABLE edges ADD COLUMN IF NOT EXISTS 
       dependency_type TEXT CHECK (dependency_type IN ('build', 'runtime', 'unknown'));
   ```

2. **Define classification patterns**
   ```python
   # src/vizzy/services/importer.py
   
   BUILD_TIME_PATTERNS = [
       r"^gcc-\d", r"^clang-\d", r"^cmake-", r"^cargo-", r"^rustc-",
       r"^meson-", r"^ninja-", r"^make-", r"-hook$", r"^stdenv-",
       r"^bootstrap-", r"-wrapper$", r"^binutils-", r"^pkg-config-",
   ]
   
   def classify_edge_type(source_name: str, target_name: str) -> str:
       """
       Classify edge as build-time or runtime.
       
       Heuristics:
       - Source matches build tool patterns → build
       - Target is -dev package → build  
       - Otherwise → runtime
       """
       import re
       
       for pattern in BUILD_TIME_PATTERNS:
           if re.search(pattern, source_name, re.IGNORECASE):
               return 'build'
       
       if source_name.endswith('-dev'):
           return 'build'
       
       return 'runtime'
   ```

3. **Update importer**
   ```python
   # In parse_dot_file(), update edge parsing:
   yield ("edge", {
       "source_hash": source_hash,
       "target_hash": target_hash,
       "edge_color": color,
       "dependency_type": classify_edge_type(source_name, target_name),
   })
   ```

4. **Update Edge model**
   ```python
   # src/vizzy/models.py
   class Edge(BaseModel):
       id: int
       import_id: int
       source_id: int
       target_id: int
       edge_color: str | None
       is_redundant: bool
       dependency_type: str | None  # 'build', 'runtime', 'unknown'
   ```

### Acceptance Criteria
- [ ] Schema updated
- [ ] Classification logic implemented
- [ ] New imports have classified edges
- [ ] Existing imports can be reclassified

### Output Files
- `scripts/migrations/010_edge_classification.sql`
- `src/vizzy/services/importer.py`
- `src/vizzy/models.py`

---

## Task 8A-002: Implement Top-Level Package Identification

### Objective
Mark packages that are "user-facing" (explicitly requested) vs transitive dependencies.

### Implementation Steps

1. **Update schema**
   ```sql
   ALTER TABLE nodes ADD COLUMN IF NOT EXISTS is_top_level BOOLEAN DEFAULT FALSE;
   ALTER TABLE nodes ADD COLUMN IF NOT EXISTS top_level_source TEXT;
   ```

2. **Enhance nix integration**
   ```python
   # src/vizzy/services/nix.py
   
   def get_top_level_packages_extended(host: str) -> dict[str, str]:
       """
       Get top-level packages with their source.
       
       Returns: {package_name: source}
       """
       result = {}
       
       # 1. environment.systemPackages
       system_pkgs = get_system_packages(host)
       for pkg in system_pkgs:
           result[pkg] = 'systemPackages'
       
       # 2. programs.*.enable (if accessible)
       # This would require additional nix eval calls
       
       return result
   ```

3. **Match to nodes**
   ```python
   def mark_top_level_nodes(import_id: int, host: str) -> int:
       """
       Mark nodes that match top-level packages.
       Returns count of nodes marked.
       """
       top_level = get_top_level_packages_extended(host)
       
       with get_db() as conn:
           with conn.cursor() as cur:
               marked = 0
               for pkg_name, source in top_level.items():
                   # Try exact match first
                   cur.execute("""
                       UPDATE nodes 
                       SET is_top_level = TRUE, top_level_source = %s
                       WHERE import_id = %s 
                         AND (label = %s OR label LIKE %s)
                       RETURNING id
                   """, (source, import_id, pkg_name, f"{pkg_name}-%"))
                   marked += cur.rowcount
               
               conn.commit()
               return marked
   ```

### Acceptance Criteria
- [ ] Schema updated
- [ ] Top-level identification works
- [ ] Source tracked correctly

---

## Task 8A-003: Add Closure Contribution Calculation

### Objective
Calculate each package's marginal contribution to total closure.

### Implementation Steps

1. **Update schema**
   ```sql
   ALTER TABLE nodes ADD COLUMN IF NOT EXISTS unique_contribution INT;
   ALTER TABLE nodes ADD COLUMN IF NOT EXISTS shared_contribution INT;
   ```

2. **Implement calculation**
   ```python
   def compute_contributions(import_id: int) -> None:
       """
       Compute unique vs shared contribution for top-level packages.
       
       unique_contribution = deps only reachable via this package
       shared_contribution = deps also reachable via other top-level packages
       """
       with get_db() as conn:
           with conn.cursor() as cur:
               # Get all top-level nodes
               cur.execute("""
                   SELECT id FROM nodes 
                   WHERE import_id = %s AND is_top_level = TRUE
               """, (import_id,))
               top_level_ids = [r['id'] for r in cur.fetchall()]
               
               if not top_level_ids:
                   return
               
               # For each top-level, compute its closure
               closures = {}
               for tl_id in top_level_ids:
                   cur.execute("""
                       WITH RECURSIVE closure AS (
                           SELECT source_id as dep_id
                           FROM edges WHERE target_id = %s
                           UNION
                           SELECT e.source_id
                           FROM closure c
                           JOIN edges e ON e.target_id = c.dep_id
                       )
                       SELECT DISTINCT dep_id FROM closure
                   """, (tl_id,))
                   closures[tl_id] = set(r['dep_id'] for r in cur.fetchall())
               
               # Compute unique vs shared
               all_deps = set().union(*closures.values())
               
               for tl_id, deps in closures.items():
                   other_deps = set().union(*(
                       c for tid, c in closures.items() if tid != tl_id
                   ))
                   unique = deps - other_deps
                   shared = deps & other_deps
                   
                   cur.execute("""
                       UPDATE nodes 
                       SET unique_contribution = %s, shared_contribution = %s
                       WHERE id = %s
                   """, (len(unique), len(shared), tl_id))
               
               conn.commit()
   ```

### Acceptance Criteria
- [ ] Contribution calculated correctly
- [ ] Performance acceptable (<60s for 50k nodes)

---

## Task 8A-004: Create Baseline Closure Reference System

### Objective
Store reference configurations for comparative context.

### Implementation Steps

1. **Create baseline table**
   ```sql
   CREATE TABLE IF NOT EXISTS baselines (
       id SERIAL PRIMARY KEY,
       name TEXT NOT NULL,
       description TEXT,
       node_count INT NOT NULL,
       edge_count INT NOT NULL,
       closure_by_type JSONB,
       created_at TIMESTAMP DEFAULT NOW()
   );
   ```

2. **Implement baseline operations**
   ```python
   def create_baseline_from_import(
       import_id: int, 
       name: str, 
       description: str
   ) -> int:
       """Export an import as a baseline."""
       pass
   
   def compare_to_baseline(import_id: int, baseline_id: int) -> dict:
       """Compare import against baseline."""
       pass
   ```

### Acceptance Criteria
- [ ] Baselines can be created
- [ ] Comparison returns useful metrics

---

## Task 8A-005: Enhance Module Attribution from Nix CLI

### Objective
Trace packages to the NixOS modules that add them.

### Implementation
See PHASE_4_COMPLETION.md Task 4-003 for related metadata fetching. This task adds module-specific attribution.

### Acceptance Criteria
- [ ] Module attribution data available
- [ ] Pattern-based fallback works

---

## Task 8A-006: Add Database Migrations for New Fields

### Objective
Create consolidated migration for all 6A changes.

### Implementation

```sql
-- scripts/migrations/010_phase6_foundation.sql
BEGIN;

-- Edge classification
ALTER TABLE edges ADD COLUMN IF NOT EXISTS 
    dependency_type TEXT CHECK (dependency_type IN ('build', 'runtime', 'unknown'));

-- Top-level identification  
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS is_top_level BOOLEAN DEFAULT FALSE;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS top_level_source TEXT;

-- Contribution metrics
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS unique_contribution INT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS shared_contribution INT;

-- Baselines table
CREATE TABLE IF NOT EXISTS baselines (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    node_count INT NOT NULL,
    edge_count INT NOT NULL,
    closure_by_type JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_nodes_top_level ON nodes(import_id) WHERE is_top_level = TRUE;
CREATE INDEX IF NOT EXISTS idx_edges_dep_type ON edges(import_id, dependency_type);

COMMIT;
```

### Acceptance Criteria
- [ ] Migration runs without error
- [ ] Idempotent (can run multiple times)

---

# Section 8B: System Health Dashboard

Replaces the cluster overview with actionable metrics.

---

## Task 8B-001: Design System Health Dashboard Layout

### Objective
Design dashboard answering "How healthy is my system closure?"

### Layout Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                     System Health Dashboard                          │
├─────────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│ │   45,234    │  │   12.3%     │  │  ████░░ 67% │  │   depth 4   │ │
│ │ derivations │  │ redundancy  │  │  runtime    │  │   average   │ │
│ │ +23% vs min │  │  ⚠ high     │  │             │  │             │ │
│ └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│ Top Contributors                    │  By Package Type             │
│ ───────────────────────────────────│  ────────────────────────────│
│ firefox        ████████ 2,340      │  [Donut chart showing         │
│ libreoffice    ██████   1,890      │   distribution by type]       │
│ gnome-shell    █████    1,567      │                               │
│ vscode         ████     1,234      │  Click segment to drill down  │
│ [View Treemap →]                   │                               │
├─────────────────────────────────────────────────────────────────────┤
│ [🔍 Duplicates]  [🌳 Treemap]  [❓ Why Chain]  [🔄 Compare]        │
└─────────────────────────────────────────────────────────────────────┘
```

### Deliverables
- `designs/dashboard-spec.md`

---

## Task 8B-002: Implement Dashboard Metrics API Endpoints

### Objective
Create API endpoints for dashboard data.

### Implementation

```python
# src/vizzy/services/dashboard.py

@dataclass
class DashboardSummary:
    total_nodes: int
    total_edges: int
    redundancy_score: float
    build_runtime_ratio: float
    depth_stats: dict
    baseline_comparison: dict | None

def get_dashboard_summary(import_id: int) -> DashboardSummary:
    with get_db() as conn:
        with conn.cursor() as cur:
            # Total counts
            cur.execute("""
                SELECT node_count, edge_count FROM imports WHERE id = %s
            """, (import_id,))
            counts = cur.fetchone()
            
            # Redundancy score
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE is_redundant) as redundant,
                    COUNT(*) as total
                FROM edges WHERE import_id = %s
            """, (import_id,))
            edge_stats = cur.fetchone()
            redundancy = edge_stats['redundant'] / edge_stats['total'] if edge_stats['total'] > 0 else 0
            
            # Build/runtime ratio
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE dependency_type = 'runtime') as runtime,
                    COUNT(*) as total
                FROM edges WHERE import_id = %s
            """, (import_id,))
            ratio_stats = cur.fetchone()
            br_ratio = ratio_stats['runtime'] / ratio_stats['total'] if ratio_stats['total'] > 0 else 0
            
            # Depth stats
            cur.execute("""
                SELECT 
                    MAX(depth) as max_depth,
                    AVG(depth) as avg_depth,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY depth) as median_depth
                FROM nodes WHERE import_id = %s AND depth IS NOT NULL
            """, (import_id,))
            depth = cur.fetchone()
            
            return DashboardSummary(
                total_nodes=counts['node_count'] or 0,
                total_edges=counts['edge_count'] or 0,
                redundancy_score=redundancy,
                build_runtime_ratio=br_ratio,
                depth_stats={
                    "max": depth['max_depth'],
                    "avg": float(depth['avg_depth'] or 0),
                    "median": float(depth['median_depth'] or 0),
                },
                baseline_comparison=None,  # TODO: implement
            )


def get_top_contributors(import_id: int, limit: int = 10) -> list[dict]:
    """Get top-level packages by closure contribution."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, label, closure_size, unique_contribution, package_type
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                ORDER BY COALESCE(closure_size, 0) DESC
                LIMIT %s
            """, (import_id, limit))
            
            return [dict(row) for row in cur.fetchall()]
```

### API Endpoints

```python
# src/vizzy/routes/api.py

@router.get("/api/dashboard/{import_id}/summary")
async def dashboard_summary(import_id: int):
    return get_dashboard_summary(import_id)

@router.get("/api/dashboard/{import_id}/top-contributors")
async def top_contributors(import_id: int, limit: int = 10):
    return get_top_contributors(import_id, limit)

@router.get("/api/dashboard/{import_id}/type-distribution")
async def type_distribution(import_id: int):
    return get_type_distribution(import_id)
```

### Acceptance Criteria
- [ ] All endpoints return correct data
- [ ] Response times <500ms

---

## Task 8B-003: Build Dashboard Frontend Component

### Objective
Implement dashboard UI replacing the cluster overview.

### Implementation

```html
<!-- src/vizzy/templates/dashboard.html -->
{% extends "base.html" %}

{% block title %}{{ import_info.name }} - Dashboard{% endblock %}

{% block content %}
<div class="dashboard">
    <!-- Metrics Row -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div class="metric-card bg-white rounded-lg shadow p-4">
            <div class="text-3xl font-bold">{{ summary.total_nodes | number_format }}</div>
            <div class="text-sm text-slate-500">Total Derivations</div>
            {% if summary.baseline_comparison %}
            <div class="text-xs mt-1 {{ 'text-red-500' if summary.baseline_comparison.difference > 0 else 'text-green-500' }}">
                {{ summary.baseline_comparison.percentage }}
            </div>
            {% endif %}
        </div>
        
        <div class="metric-card bg-white rounded-lg shadow p-4">
            <div class="text-3xl font-bold">{{ "%.1f" | format(summary.redundancy_score * 100) }}%</div>
            <div class="text-sm text-slate-500">Redundancy</div>
            {% if summary.redundancy_score > 0.1 %}
            <div class="text-xs text-amber-500">⚠ High</div>
            {% endif %}
        </div>
        
        <div class="metric-card bg-white rounded-lg shadow p-4">
            <div class="text-3xl font-bold">{{ "%.0f" | format(summary.build_runtime_ratio * 100) }}%</div>
            <div class="text-sm text-slate-500">Runtime Deps</div>
        </div>
        
        <div class="metric-card bg-white rounded-lg shadow p-4">
            <div class="text-3xl font-bold">{{ summary.depth_stats.avg | round(1) }}</div>
            <div class="text-sm text-slate-500">Avg Depth</div>
        </div>
    </div>
    
    <!-- Main Content -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Top Contributors -->
        <div class="bg-white rounded-lg shadow p-4">
            <h2 class="font-semibold mb-4">Largest Contributors</h2>
            <div id="contributors" 
                 hx-get="/api/dashboard/{{ import_info.id }}/top-contributors"
                 hx-trigger="load"
                 hx-swap="innerHTML">
                Loading...
            </div>
            <a href="/treemap/{{ import_info.id }}" class="text-blue-600 text-sm mt-4 block">
                View Treemap →
            </a>
        </div>
        
        <!-- Type Distribution -->
        <div class="bg-white rounded-lg shadow p-4">
            <h2 class="font-semibold mb-4">Package Types</h2>
            <canvas id="type-chart"></canvas>
        </div>
    </div>
    
    <!-- Quick Actions -->
    <div class="flex flex-wrap gap-4 mt-6">
        <a href="/analyze/duplicates/{{ import_info.id }}" 
           class="px-4 py-2 bg-slate-100 rounded hover:bg-slate-200">
            🔍 Find Duplicates
        </a>
        <a href="/treemap/{{ import_info.id }}"
           class="px-4 py-2 bg-slate-100 rounded hover:bg-slate-200">
            🌳 View Treemap
        </a>
        <a href="/compare?left={{ import_info.id }}"
           class="px-4 py-2 bg-slate-100 rounded hover:bg-slate-200">
            🔄 Compare
        </a>
    </div>
</div>
{% endblock %}
```

### Acceptance Criteria
- [ ] Dashboard renders correctly
- [ ] Metrics update dynamically
- [ ] Chart is interactive
- [ ] Quick actions work

---

# Section 8C: Closure Treemap

Interactive visualization showing size attribution.

---

## Task 8C-001: Design Closure Treemap Component

### Objective
Design zoomable treemap showing closure contribution by package.

### Design
- Hierarchy: Applications → Direct deps → Transitive deps
- Area = closure contribution
- Color = package type
- Click to zoom, breadcrumb navigation

### Deliverables
- `designs/treemap-spec.md`

---

## Task 8C-002: Implement Treemap Data Aggregation Service

### Objective
Generate hierarchical data for D3.js treemap.

### Implementation

```python
# src/vizzy/services/treemap.py

@dataclass
class TreemapNode:
    name: str
    node_id: int | None
    contribution: int
    package_type: str | None
    children: list["TreemapNode"]

def build_treemap_data(
    import_id: int,
    mode: str = "application",  # application, type, depth
    max_depth: int = 3,
) -> dict:
    """Build hierarchical data for treemap."""
    
    if mode == "application":
        return _build_by_application(import_id, max_depth)
    elif mode == "type":
        return _build_by_type(import_id)
    else:
        return _build_by_depth(import_id, max_depth)

def _build_by_application(import_id: int, max_depth: int) -> dict:
    """Build hierarchy: top-level apps → dependencies."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get top-level packages
            cur.execute("""
                SELECT id, label, package_type, closure_size
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                ORDER BY closure_size DESC NULLS LAST
                LIMIT 20
            """, (import_id,))
            top_level = cur.fetchall()
            
            children = []
            for tl in top_level:
                # Get direct dependencies
                cur.execute("""
                    SELECT n.id, n.label, n.package_type, n.closure_size
                    FROM edges e
                    JOIN nodes n ON e.source_id = n.id
                    WHERE e.target_id = %s
                    ORDER BY n.closure_size DESC NULLS LAST
                    LIMIT 10
                """, (tl['id'],))
                deps = cur.fetchall()
                
                children.append({
                    "name": tl['label'],
                    "node_id": tl['id'],
                    "package_type": tl['package_type'],
                    "children": [
                        {
                            "name": d['label'],
                            "node_id": d['id'],
                            "value": d['closure_size'] or 1,
                            "package_type": d['package_type'],
                        }
                        for d in deps
                    ] or [{"name": "(no deps)", "value": 1}]
                })
            
            return {
                "name": "System",
                "children": children
            }
```

### API Endpoint

```python
@router.get("/api/treemap/{import_id}")
async def treemap_data(
    import_id: int,
    mode: str = "application",
    root_node_id: int | None = None
):
    return build_treemap_data(import_id, mode)
```

### Acceptance Criteria
- [ ] Hierarchical data generated correctly
- [ ] Multiple modes work
- [ ] Response time <2s

---

## Task 8C-003: Build Interactive Treemap with D3.js

### Objective
Implement zoomable treemap visualization.

### Implementation

```html
<!-- src/vizzy/templates/treemap.html -->
{% extends "base.html" %}

{% block head_extra %}
<script src="https://d3js.org/d3.v7.min.js"></script>
{% endblock %}

{% block content %}
<div class="treemap-container">
    <div class="controls mb-4 flex gap-4">
        <select id="mode" onchange="loadTreemap()" class="border rounded p-2">
            <option value="application">By Application</option>
            <option value="type">By Type</option>
        </select>
        <button id="zoom-out" onclick="zoomOut()" class="px-4 py-2 bg-slate-200 rounded">
            ← Back
        </button>
    </div>
    
    <nav id="breadcrumb" class="text-sm text-slate-500 mb-2"></nav>
    
    <div id="treemap" style="width: 100%; height: 600px;"></div>
</div>

<script>
const importId = {{ import_id }};
let currentRoot = null;

async function loadTreemap(mode = 'application') {
    const response = await fetch(`/api/treemap/${importId}?mode=${mode}`);
    const data = await response.json();
    renderTreemap(data);
}

function renderTreemap(data) {
    const container = document.getElementById('treemap');
    const width = container.clientWidth;
    const height = 600;
    
    d3.select('#treemap').selectAll('*').remove();
    
    const svg = d3.select('#treemap')
        .append('svg')
        .attr('width', width)
        .attr('height', height);
    
    const root = d3.hierarchy(data)
        .sum(d => d.value || 0)
        .sort((a, b) => b.value - a.value);
    
    d3.treemap()
        .size([width, height])
        .padding(2)
        .round(true)(root);
    
    const cells = svg.selectAll('g')
        .data(root.leaves())
        .join('g')
        .attr('transform', d => `translate(${d.x0},${d.y0})`);
    
    cells.append('rect')
        .attr('width', d => d.x1 - d.x0)
        .attr('height', d => d.y1 - d.y0)
        .attr('fill', d => getColor(d.data.package_type))
        .attr('stroke', '#fff')
        .style('cursor', 'pointer')
        .on('click', (event, d) => handleClick(d));
    
    cells.append('text')
        .attr('x', 4)
        .attr('y', 14)
        .text(d => d.data.name)
        .attr('font-size', '11px')
        .attr('fill', '#333');
}

function getColor(type) {
    const colors = {
        'library': '#74c0fc',
        'application': '#22d3ee',
        'service': '#69db7c',
        'development': '#b197fc',
        'configuration': '#ffd43b',
    };
    return colors[type] || '#e2e8f0';
}

function handleClick(d) {
    if (d.data.node_id) {
        window.location.href = `/graph/node/${d.data.node_id}`;
    }
}

loadTreemap();
</script>
{% endblock %}
```

### Acceptance Criteria
- [ ] Treemap renders
- [ ] Colors by type
- [ ] Click navigates to node

---

## Task 8C-004: Add Treemap Zoom and Filter Interactions

### Objective
Add zoom transitions, filtering, and keyboard navigation.

### Implementation
- Smooth zoom transitions
- Filter by build/runtime
- Keyboard navigation (arrow keys, Enter, Escape)

### Acceptance Criteria
- [ ] Zoom animations smooth
- [ ] Filters work
- [ ] Keyboard navigation works

---

# Section 8D: Variant Matrix

Enhanced duplicate visualization.

---

## Task 8D-001: Design Variant Matrix Layout

### Objective
Design matrix showing which apps use which package variants.

### Layout

```
                │ openssl-3.0   │ openssl-3.0   │ openssl-1.1
                │ (runtime)     │ (static)      │ (legacy)
────────────────┼───────────────┼───────────────┼─────────────
firefox         │      ●        │               │
curl            │      ●        │               │
rustc           │               │      ●        │
python-crypto   │               │               │      ●
────────────────┼───────────────┼───────────────┼─────────────
Dependents      │      12       │       5       │       3
```

### Acceptance Criteria
- [ ] Layout documented
- [ ] Handles up to 20 variants

---

## Task 8D-002: Implement Variant Matrix Data Service

### Implementation

```python
# src/vizzy/services/variant_matrix.py

def build_variant_matrix(import_id: int, label: str) -> dict:
    """Build matrix data for a package with variants."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants
            cur.execute("""
                SELECT id, drv_hash, label
                FROM nodes
                WHERE import_id = %s AND label = %s
            """, (import_id, label))
            variants = cur.fetchall()
            
            # For each variant, get dependents
            matrix_data = {
                "label": label,
                "variants": [],
                "applications": [],
            }
            
            all_apps = set()
            variant_deps = {}
            
            for v in variants:
                cur.execute("""
                    SELECT n.id, n.label
                    FROM edges e
                    JOIN nodes n ON e.target_id = n.id
                    WHERE e.source_id = %s
                """, (v['id'],))
                deps = cur.fetchall()
                
                variant_deps[v['id']] = {d['id'] for d in deps}
                all_apps.update(d['label'] for d in deps)
                
                matrix_data['variants'].append({
                    "node_id": v['id'],
                    "hash": v['drv_hash'][:12],
                    "dependent_count": len(deps),
                })
            
            # Build application rows
            for app in sorted(all_apps):
                row = {"label": app, "cells": {}}
                for v in variants:
                    has_dep = app in [d['label'] for d in variant_deps.get(v['id'], [])]
                    row["cells"][v['id']] = has_dep
                matrix_data['applications'].append(row)
            
            return matrix_data
```

---

## Task 8D-003: Build Variant Matrix Frontend Component

### Implementation

```html
<!-- src/vizzy/templates/analyze/matrix.html -->
{% extends "base.html" %}

{% block content %}
<div class="matrix-container overflow-x-auto">
    <h1 class="text-2xl font-bold mb-4">{{ matrix.label }} Variants</h1>
    
    <table class="min-w-full border-collapse">
        <thead>
            <tr>
                <th class="p-2 border"></th>
                {% for v in matrix.variants %}
                <th class="p-2 border text-center">
                    <div class="font-mono text-xs">{{ v.hash }}</div>
                    <div class="text-slate-500">{{ v.dependent_count }} deps</div>
                </th>
                {% endfor %}
            </tr>
        </thead>
        <tbody>
            {% for app in matrix.applications %}
            <tr>
                <td class="p-2 border font-medium">{{ app.label }}</td>
                {% for v in matrix.variants %}
                <td class="p-2 border text-center">
                    {% if app.cells[v.node_id] %}
                    <span class="text-green-500 text-xl">●</span>
                    {% endif %}
                </td>
                {% endfor %}
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

---

## Task 8D-004: Add Matrix Sorting and Filtering

### Objective
Add interactive sorting and filtering to the matrix.

### Acceptance Criteria
- [ ] Sort by dependent count
- [ ] Filter to direct only

---

# Section 8E: Why Chain (Attribution Explorer)

Answer "Why does this package exist in my system?"

---

## Task 8E-001: Design Why Chain Data Model

### Objective
Define structures for attribution paths.

### Implementation

```python
@dataclass
class AttributionPath:
    top_level_node: Node
    path: list[Node]

@dataclass
class AttributionGroup:
    via_node: Node
    top_level_packages: list[Node]
    path_to_target: list[Node]

@dataclass
class WhyChainResult:
    target: Node
    direct_dependents: list[Node]
    attribution_groups: list[AttributionGroup]
    is_essential: bool
```

---

## Task 8E-002: Implement Reverse Path Computation

### Objective
Find all paths FROM top-level packages TO a target node.

### Implementation

```python
def find_paths_to_node(node_id: int, max_depth: int = 10) -> list[list[int]]:
    """Find paths from top-level packages to this node."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH RECURSIVE reverse_paths AS (
                    SELECT 
                        ARRAY[%s] as path,
                        1 as depth
                    
                    UNION ALL
                    
                    SELECT
                        e.target_id || rp.path,
                        rp.depth + 1
                    FROM reverse_paths rp
                    JOIN edges e ON e.source_id = rp.path[1]
                    WHERE rp.depth < %s
                      AND NOT (e.target_id = ANY(rp.path))
                )
                SELECT path
                FROM reverse_paths rp
                JOIN nodes n ON n.id = rp.path[1]
                WHERE n.is_top_level = TRUE
                ORDER BY array_length(path, 1)
                LIMIT 100
            """, (node_id, max_depth))
            
            return [row['path'] for row in cur.fetchall()]
```

---

## Task 8E-003: Build Path Aggregation Algorithm

### Objective
Group paths by common ancestors for cleaner display.

### Implementation

```python
def aggregate_paths(paths: list[list[int]], target_id: int) -> list[AttributionGroup]:
    """Group paths by the node closest to target (common ancestor)."""
    # Build groups by the node just before target in each path
    groups = defaultdict(list)
    
    for path in paths:
        if len(path) >= 2:
            # Node before target
            via_node_id = path[1] if path[0] == target_id else path[-2]
            top_level_id = path[-1] if path[0] == target_id else path[0]
            groups[via_node_id].append(top_level_id)
    
    # Convert to AttributionGroup objects
    result = []
    for via_id, top_level_ids in groups.items():
        via_node = get_node(via_id)
        top_level_nodes = [get_node(tid) for tid in set(top_level_ids)]
        result.append(AttributionGroup(
            via_node=via_node,
            top_level_packages=[n for n in top_level_nodes if n],
            path_to_target=[via_node, get_node(target_id)]
        ))
    
    return sorted(result, key=lambda g: len(g.top_level_packages), reverse=True)
```

---

## Task 8E-004: Design Why Chain UI Component

### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Why is openssl-3.0.12 in my system?                                 │
├─────────────────────────────────────────────────────────────────────┤
│ This package is needed by 19 top-level packages through 3 paths.   │
│                                                                     │
│ 📦 Via curl (12 packages)                                          │
│ ├── firefox, thunderbird, chromium (+9 more)                       │
│ └── Path: [app] → curl → openssl                                   │
│                                                                     │
│ 🐍 Via python-requests (5 packages)                                │
│ ├── home-assistant, calibre (+3 more)                              │
│ └── Path: [app] → python-requests → openssl                        │
│                                                                     │
│ ⚠️ ESSENTIAL: Cannot be removed without breaking 19 packages       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Task 8E-005: Implement Why Chain API Endpoint

```python
@router.get("/api/why-chain/{node_id}")
async def why_chain(node_id: int):
    node = get_node(node_id)
    if not node:
        return {"error": "Not found"}
    
    paths = find_paths_to_node(node_id)
    groups = aggregate_paths(paths, node_id)
    
    # Get direct dependents
    direct = get_direct_dependents(node_id)
    
    return {
        "target": node,
        "direct_dependents": direct,
        "attribution_groups": groups,
        "is_essential": len(paths) > 0,
    }
```

---

## Task 8E-006: Build Why Chain Frontend Visualization

```html
<!-- src/vizzy/templates/why-chain.html -->
{% extends "base.html" %}

{% block content %}
<div class="why-chain max-w-3xl mx-auto">
    <h1 class="text-2xl font-bold mb-2">
        Why is <span class="text-blue-600">{{ target.label }}</span> in my system?
    </h1>
    
    <p class="text-slate-600 mb-6">
        This package is needed by {{ total_top_level }} top-level packages 
        through {{ groups | length }} paths.
    </p>
    
    <div class="space-y-4">
        {% for group in groups %}
        <div class="bg-white rounded-lg shadow p-4">
            <div class="flex items-center justify-between mb-2">
                <span class="font-semibold">Via {{ group.via_node.label }}</span>
                <span class="text-slate-500">({{ group.top_level_packages | length }} packages)</span>
            </div>
            
            <div class="text-sm text-slate-600 mb-2">
                {{ group.top_level_packages[:3] | map(attribute='label') | join(', ') }}
                {% if group.top_level_packages | length > 3 %}
                (+{{ group.top_level_packages | length - 3 }} more)
                {% endif %}
            </div>
            
            <div class="flex items-center gap-2 text-sm">
                <span class="text-slate-400">Path:</span>
                {% for node in group.path_to_target %}
                <a href="/graph/node/{{ node.id }}" class="px-2 py-1 bg-slate-100 rounded">
                    {{ node.label }}
                </a>
                {% if not loop.last %}<span>→</span>{% endif %}
                {% endfor %}
            </div>
        </div>
        {% endfor %}
    </div>
    
    {% if is_essential %}
    <div class="mt-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
        <strong>⚠️ Essential Package</strong>
        <p class="text-sm">Removing this would break {{ total_top_level }} packages.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
```

---

## Task 8E-007: Add "Essential vs Removable" Classification

### Implementation

```python
def classify_removal_impact(node_id: int) -> str:
    """Classify if removing this node would break user packages."""
    paths = find_paths_to_node(node_id)
    
    if not paths:
        return "orphan"  # No top-level depends on it
    
    # Check if all paths are build-time only
    # ... implementation
    
    return "essential"
```

---

## Task 8E-008: Implement Attribution Caching

### Implementation

```python
def cache_attribution(node_id: int, data: dict) -> None:
    """Cache attribution results."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO analysis (import_id, analysis_type, result)
                SELECT import_id, 'attribution:' || %s, %s
                FROM nodes WHERE id = %s
                ON CONFLICT DO UPDATE SET result = %s, computed_at = NOW()
            """, (node_id, json.dumps(data), node_id, json.dumps(data)))
```

---

## Phase 6 Extension Completion Checklist

### 6A: Data Model
- [ ] 8A-001: Edge classification
- [ ] 8A-002: Top-level identification
- [ ] 8A-003: Contribution calculation
- [ ] 8A-004: Baseline system
- [ ] 8A-005: Module attribution
- [ ] 8A-006: Migrations

### 6B: Dashboard
- [ ] 8B-001: Design
- [ ] 8B-002: API
- [ ] 8B-003: Frontend

### 6C: Treemap
- [ ] 8C-001: Design
- [ ] 8C-002: Data service
- [ ] 8C-003: D3.js implementation
- [ ] 8C-004: Interactions

### 6D: Variant Matrix
- [ ] 8D-001: Design
- [ ] 8D-002: Data service
- [ ] 8D-003: Frontend
- [ ] 8D-004: Sorting/filtering

### 6E: Why Chain
- [ ] 8E-001: Data model
- [ ] 8E-002: Reverse paths
- [ ] 8E-003: Aggregation
- [ ] 8E-004: UI design
- [ ] 8E-005: API
- [ ] 8E-006: Frontend
- [ ] 8E-007: Classification
- [ ] 8E-008: Caching
