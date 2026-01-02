# Agent Instructions

## Overview

This phase refines existing visualizations, improves UX, and integrates all components into a cohesive experience.

**Dependencies**: All P0 tasks from Phases 1-4 should be complete.

---

## Task P-001: Implement Semantic Zoom for Graph Explorer

### Objective
Replace the current vis.js explorer with a multi-level semantic zoom system that aggregates nodes at different zoom levels.

### Context
The current visual explorer becomes unusable past ~50 nodes. Semantic zoom shows different levels of detail based on zoom:
- Zoomed out: Package type clusters only
- Medium: Top packages per type
- Zoomed in: Individual nodes

### Implementation Steps

1. **Define zoom levels**
   ```javascript
   const ZOOM_LEVELS = {
       SYSTEM: { scale: 0.3, maxNodes: 10 },      // Show type clusters
       CATEGORY: { scale: 0.6, maxNodes: 50 },    // Show top packages
       PACKAGE: { scale: 1.0, maxNodes: 100 },    // Show package + deps
       DETAIL: { scale: 1.5, maxNodes: 200 }      // Show full neighborhood
   };
   
   function getZoomLevel(scale) {
       if (scale < 0.4) return 'SYSTEM';
       if (scale < 0.8) return 'CATEGORY';
       if (scale < 1.2) return 'PACKAGE';
       return 'DETAIL';
   }
   ```

2. **Create aggregation API**
   ```python
   @router.get("/api/graph/aggregate/{import_id}")
   async def aggregated_graph(
       import_id: int,
       level: str = "category",  # system, category, package
       center_node_id: int | None = None
   ) -> AggregatedGraphData:
       """
       Return aggregated graph data for the specified zoom level.
       """
       if level == "system":
           return get_type_clusters(import_id)
       elif level == "category":
           return get_top_by_type(import_id, limit_per_type=10)
       else:
           return get_node_neighborhood(center_node_id)
   ```

3. **Implement dynamic loading**
   ```javascript
   let currentLevel = 'CATEGORY';
   
   network.on('zoom', (params) => {
       const newLevel = getZoomLevel(params.scale);
       if (newLevel !== currentLevel) {
           currentLevel = newLevel;
           loadGraphForLevel(newLevel);
       }
   });
   
   async function loadGraphForLevel(level) {
       const centerNode = network.getSelectedNodes()[0] || null;
       const response = await fetch(
           `/api/graph/aggregate/${importId}?level=${level}&center_node_id=${centerNode}`
       );
       const data = await response.json();
       updateGraph(data);
   }
   ```

4. **Animate transitions**
   ```javascript
   function updateGraph(newData) {
       // Fade out nodes being removed
       const removing = currentNodes.filter(n => !newData.nodes.includes(n.id));
       removing.forEach(n => {
           nodesDataset.update({ id: n.id, opacity: 0 });
       });
       
       // After animation, update dataset
       setTimeout(() => {
           nodesDataset.clear();
           edgesDataset.clear();
           nodesDataset.add(newData.nodes);
           edgesDataset.add(newData.edges);
       }, 300);
   }
   ```

### Acceptance Criteria
- [ ] Zoom levels change smoothly
- [ ] Node count stays manageable at each level
- [ ] Aggregated nodes are clickable to expand
- [ ] Performance is good (60fps)
- [ ] Transitions are animated

### Output Files to Create/Modify
- `static/js/visual-explorer.js`
- `src/vizzy/routes/api.py`
- `src/vizzy/services/graph.py`
- `src/vizzy/templates/visual.html`

---

## Task P-002: Add Level-of-Detail Node Aggregation

### Objective
Create aggregate "super-nodes" that represent multiple nodes at low zoom levels.

### Implementation Steps

1. **Define aggregation strategy**
   ```python
   @dataclass
   class AggregatedNode:
       id: str  # e.g., "type:library"
       label: str  # e.g., "Libraries (8,234)"
       node_count: int
       representative_nodes: list[int]  # Top 3 node IDs
       total_closure: int
       package_type: str | None
       is_aggregate: bool = True
   
   def aggregate_by_type(import_id: int) -> list[AggregatedNode]:
       """Create one aggregate node per package type."""
       pass
   
   def aggregate_by_closure(
       nodes: list[Node],
       max_nodes: int = 50
   ) -> list[AggregatedNode | Node]:
       """
       Keep top N by closure, aggregate the rest.
       """
       sorted_nodes = sorted(nodes, key=lambda n: n.closure_size or 0, reverse=True)
       
       top = sorted_nodes[:max_nodes]
       rest = sorted_nodes[max_nodes:]
       
       if rest:
           aggregate = AggregatedNode(
               id=f"other:{len(rest)}",
               label=f"Other ({len(rest)} packages)",
               node_count=len(rest),
               ...
           )
           return top + [aggregate]
       return top
   ```

2. **Create aggregate edges**
   ```python
   def aggregate_edges(
       original_edges: list[Edge],
       node_mapping: dict[int, str]  # original_id -> aggregate_id
   ) -> list[AggregatedEdge]:
       """
       Combine edges between aggregated nodes.
       
       If nodes A, B, C are aggregated into X,
       and D, E are aggregated into Y,
       then all edges A→D, A→E, B→D, etc. become X→Y with weight.
       """
       pass
   ```

3. **Update graph API response**
   ```python
   class AggregatedGraphData(BaseModel):
       nodes: list[AggregatedNode | Node]
       edges: list[AggregatedEdge | Edge]
       aggregation_level: str
       expansion_available: dict[str, int]  # aggregate_id -> expand count
   ```

4. **Handle aggregate expansion**
   ```javascript
   function handleNodeClick(nodeId) {
       const node = nodesDataset.get(nodeId);
       if (node.is_aggregate) {
           expandAggregate(nodeId);
       } else {
           navigateToNode(nodeId);
       }
   }
   
   async function expandAggregate(aggregateId) {
       const response = await fetch(`/api/graph/expand/${aggregateId}`);
       const expandedNodes = await response.json();
       
       // Replace aggregate with its contents
       nodesDataset.remove(aggregateId);
       nodesDataset.add(expandedNodes.nodes);
       edgesDataset.add(expandedNodes.edges);
   }
   ```

### Acceptance Criteria
- [ ] Aggregation reduces visual complexity
- [ ] Aggregate labels are informative
- [ ] Click to expand works
- [ ] Edge weights reflect connection strength
- [ ] Back to aggregate is possible

### Output Files to Create/Modify
- `src/vizzy/services/graph.py`
- `src/vizzy/routes/api.py`
- `static/js/visual-explorer.js`

---

## Task P-003: Redesign Sankey with Correct Flow Direction

### Objective
Fix the Sankey diagram to flow from cause (user packages) to effect (variants).

### Context
Current Sankey flows: variants → dependents
Should flow: user packages → intermediate → variants

### Implementation Steps

1. **Reverse data generation**
   ```python
   def build_sankey_data(import_id: int, label: str) -> dict:
       """
       Build Sankey with CORRECT flow direction:
       [User Packages] → [Intermediate] → [Variants]
       
       Read as: "Firefox needs curl, which needs openssl (variant 1)"
       """
       variants = get_variants_for_label(import_id, label)
       
       # For each variant, trace BACK to user packages
       all_links = []
       all_nodes = set()
       
       for variant in variants:
           paths = find_paths_to_node(variant.id)
           
           for path in paths:
               # path is: [top_level, ..., intermediate, variant]
               # Create links for each step
               for i in range(len(path) - 1):
                   all_links.append({
                       "source": path[i],
                       "target": path[i + 1],
                       "value": 1
                   })
                   all_nodes.add(path[i])
                   all_nodes.add(path[i + 1])
       
       # Deduplicate and aggregate links
       return format_for_plotly(all_nodes, all_links)
   ```

2. **Add layer positioning**
   ```python
   def assign_layers(nodes: set[int], links: list) -> dict[int, int]:
       """
       Assign each node to a layer (x position) in the Sankey.
       
       Layer 0: User packages (sources)
       Layer N: Variants (targets)
       Intermediate: Based on distance from source
       """
       # BFS from sources to assign layers
       pass
   ```

3. **Update Plotly configuration**
   ```javascript
   const layout = {
       font: { size: 12 },
       // Left = user packages, Right = variants
       annotations: [
           { x: 0, y: 1.05, text: "Your Packages", showarrow: false },
           { x: 1, y: 1.05, text: "Variants", showarrow: false }
       ]
   };
   ```

4. **Add interactive path highlighting**
   ```javascript
   // Highlight path on hover
   plotly_chart.on('plotly_hover', (data) => {
       const point = data.points[0];
       highlightPath(point.source, point.target);
   });
   ```

### Acceptance Criteria
- [ ] Flow direction is intuitive (left = user, right = variants)
- [ ] Paths are traceable
- [ ] Hover highlights related flows
- [ ] Legend explains the visualization

### Output Files to Create/Modify
- `src/vizzy/services/analysis.py`
- `src/vizzy/templates/analyze/sankey.html`

---

## Task P-004: Add Application-Filtered Sankey View

### Objective
Allow filtering the Sankey to show only paths from a specific application.

### Implementation Steps

1. **Add filter control**
   ```html
   <div class="sankey-filters">
       <label>
           Filter by application:
           <select id="app-filter" onchange="updateSankey()">
               <option value="">All applications</option>
               {% for app in top_level_packages %}
               <option value="{{ app.id }}">{{ app.label }}</option>
               {% endfor %}
           </select>
       </label>
   </div>
   ```

2. **Update API endpoint**
   ```python
   @router.get("/api/sankey/{import_id}/{label}")
   async def sankey_data(
       import_id: int,
       label: str,
       filter_app_id: int | None = None
   ) -> dict:
       """
       Get Sankey data, optionally filtered to paths from one app.
       """
       if filter_app_id:
           paths = find_paths_between(filter_app_id, target_label=label)
       else:
           paths = find_all_paths_to_label(import_id, label)
       
       return build_sankey_from_paths(paths)
   ```

3. **Implement client-side filtering**
   ```javascript
   async function updateSankey() {
       const appId = document.getElementById('app-filter').value;
       const url = `/api/sankey/${importId}/${label}` +
           (appId ? `?filter_app_id=${appId}` : '');
       
       const response = await fetch(url);
       const data = await response.json();
       
       Plotly.react('sankey-diagram', [createSankeyTrace(data)], layout);
   }
   ```

### Acceptance Criteria
- [ ] Filter dropdown populated with applications
- [ ] Filtering updates diagram
- [ ] "All applications" shows complete view
- [ ] Filtered view is clearer

### Output Files to Create/Modify
- `src/vizzy/templates/analyze/sankey.html`
- `src/vizzy/routes/api.py`

---

## Task P-005: Create Unified Navigation System

### Objective
Implement consistent navigation across all views with breadcrumbs, sidebar, and cross-links.

### Dependencies
- V-003 (Dashboard) complete
- A-006 (Why Chain) complete
- C-006 (Comparison) complete

### Implementation Steps

1. **Create navigation partial**
   ```html
   <!-- src/vizzy/templates/partials/navigation.html -->
   <nav class="main-nav">
       <div class="nav-primary">
           <a href="/" class="logo">Vizzy</a>
           
           {% if current_import %}
           <div class="import-context">
               <span>{{ current_import.name }}</span>
               <a href="/explore/{{ current_import.id }}">Dashboard</a>
           </div>
           {% endif %}
       </div>
       
       <div class="nav-search">
           <input type="search" 
                  placeholder="Search packages..."
                  hx-get="/search"
                  hx-trigger="keyup changed delay:300ms"
                  hx-target="#search-results"
                  name="q">
           <div id="search-results" class="search-dropdown"></div>
       </div>
       
       <div class="nav-actions">
           {% if current_import %}
           <a href="/compare?left={{ current_import.id }}">Compare</a>
           <a href="/why-chain/select?import={{ current_import.id }}">Why Chain</a>
           {% endif %}
           <a href="/imports">Manage Imports</a>
       </div>
   </nav>
   ```

2. **Create breadcrumb component**
   ```html
   <!-- src/vizzy/templates/partials/breadcrumb.html -->
   <nav class="breadcrumb" aria-label="Breadcrumb">
       <ol>
           <li><a href="/">Home</a></li>
           {% for crumb in breadcrumbs %}
           <li>
               {% if crumb.url %}
               <a href="{{ crumb.url }}">{{ crumb.label }}</a>
               {% else %}
               <span>{{ crumb.label }}</span>
               {% endif %}
           </li>
           {% endfor %}
       </ol>
   </nav>
   ```

3. **Create sidebar for context**
   ```html
   <!-- src/vizzy/templates/partials/sidebar.html -->
   <aside class="context-sidebar">
       {% if current_node %}
       <section class="current-node">
           <h3>{{ current_node.label }}</h3>
           <dl>
               <dt>Type</dt>
               <dd>{{ current_node.package_type }}</dd>
               <dt>Closure</dt>
               <dd>{{ current_node.closure_size }}</dd>
           </dl>
           <nav class="node-actions">
               <a href="/why-chain/{{ current_node.id }}">Why Chain</a>
               <a href="/impact/{{ current_node.id }}">Impact</a>
               <a href="/visual/{{ current_node.id }}">Explorer</a>
           </nav>
       </section>
       {% endif %}
       
       <section class="quick-nav">
           <h4>Quick Navigation</h4>
           <ul>
               <li><a href="/explore/{{ import_id }}">Dashboard</a></li>
               <li><a href="/analyze/duplicates/{{ import_id }}">Duplicates</a></li>
               <li><a href="/treemap/{{ import_id }}">Treemap</a></li>
           </ul>
       </section>
   </aside>
   ```

4. **Update base template**
   ```html
   <!-- src/vizzy/templates/base.html -->
   <!DOCTYPE html>
   <html lang="en">
   <head>
       <meta charset="UTF-8">
       <meta name="viewport" content="width=device-width, initial-scale=1.0">
       <title>{% block title %}Vizzy{% endblock %}</title>
       <link rel="stylesheet" href="/static/css/main.css">
       <script src="https://unpkg.com/htmx.org@2.0.4"></script>
   </head>
   <body>
       {% include "partials/navigation.html" %}
       
       <div class="app-layout">
           {% if show_sidebar %}
           {% include "partials/sidebar.html" %}
           {% endif %}
           
           <main class="main-content">
               {% include "partials/breadcrumb.html" %}
               {% block content %}{% endblock %}
           </main>
       </div>
       
       {% block scripts %}{% endblock %}
   </body>
   </html>
   ```

5. **Add breadcrumb generation helper**
   ```python
   def generate_breadcrumbs(request: Request, **context) -> list[dict]:
       """
       Generate breadcrumbs based on current URL and context.
       """
       path = request.url.path
       breadcrumbs = []
       
       if '/explore/' in path:
           breadcrumbs.append({
               "label": context.get('import_name', 'Import'),
               "url": f"/explore/{context.get('import_id')}"
           })
       
       if '/graph/node/' in path:
           breadcrumbs.append({
               "label": context.get('node_label', 'Node'),
               "url": None
           })
       
       # ... more patterns
       
       return breadcrumbs
   ```

### Acceptance Criteria
- [ ] Navigation is consistent across all pages
- [ ] Breadcrumbs show current location
- [ ] Sidebar provides context actions
- [ ] Search is globally accessible
- [ ] Mobile navigation works

### Output Files to Create/Modify
- `src/vizzy/templates/base.html`
- `src/vizzy/templates/partials/navigation.html`
- `src/vizzy/templates/partials/breadcrumb.html`
- `src/vizzy/templates/partials/sidebar.html`
- `static/css/navigation.css`

---

## Task P-006: Implement Cross-View State Coordination

### Objective
Maintain state when navigating between views (e.g., selected node, filters).

### Implementation Steps

1. **Define shared state**
   ```javascript
   // static/js/state.js
   
   const VizzyState = {
       currentImportId: null,
       selectedNodeId: null,
       filters: {
           packageType: null,
           buildTime: true,
           runtime: true
       },
       
       save() {
           const params = new URLSearchParams();
           if (this.selectedNodeId) params.set('node', this.selectedNodeId);
           if (this.filters.packageType) params.set('type', this.filters.packageType);
           
           const newUrl = `${window.location.pathname}?${params}`;
           history.replaceState(this, '', newUrl);
       },
       
       load() {
           const params = new URLSearchParams(window.location.search);
           this.selectedNodeId = params.get('node');
           this.filters.packageType = params.get('type');
       }
   };
   ```

2. **Sync state with HTMX**
   ```javascript
   document.body.addEventListener('htmx:afterSwap', (event) => {
       // After HTMX swaps content, restore state
       if (VizzyState.selectedNodeId) {
           highlightNode(VizzyState.selectedNodeId);
       }
   });
   
   document.body.addEventListener('htmx:beforeRequest', (event) => {
       // Before HTMX request, save current state
       VizzyState.save();
       
       // Add state to request parameters
       const url = new URL(event.detail.requestConfig.path, window.location.origin);
       if (VizzyState.selectedNodeId) {
           url.searchParams.set('context_node', VizzyState.selectedNodeId);
       }
       event.detail.requestConfig.path = url.pathname + url.search;
   });
   ```

3. **Server-side state handling**
   ```python
   def get_view_context(request: Request) -> dict:
       """Extract state from request for view context."""
       return {
           "selected_node_id": request.query_params.get("context_node"),
           "package_type_filter": request.query_params.get("type"),
           "from_view": request.query_params.get("from"),
       }
   ```

4. **Highlight carried state in views**
   ```html
   {% if context_node %}
   <script>
       document.addEventListener('DOMContentLoaded', () => {
           highlightNode({{ context_node }});
           scrollToNode({{ context_node }});
       });
   </script>
   {% endif %}
   ```

### Acceptance Criteria
- [ ] Selected node persists across views
- [ ] Filters persist when navigating
- [ ] URL reflects current state
- [ ] Back button works correctly
- [ ] State is cleared when changing imports

### Output Files to Create/Modify
- `static/js/state.js`
- `src/vizzy/routes/pages.py`
- `src/vizzy/templates/base.html`

---

## Task P-007: Add Keyboard Navigation Shortcuts

### Objective
Implement keyboard shortcuts for power users.

### Implementation Steps

1. **Define shortcuts**
   ```javascript
   const SHORTCUTS = {
       '/': { action: 'focusSearch', description: 'Focus search' },
       'Escape': { action: 'closeModal', description: 'Close modal / go back' },
       'g h': { action: 'goHome', description: 'Go to home' },
       'g d': { action: 'goDashboard', description: 'Go to dashboard' },
       'g c': { action: 'goCompare', description: 'Go to compare' },
       '?': { action: 'showHelp', description: 'Show keyboard shortcuts' },
       'j': { action: 'nextItem', description: 'Next item in list' },
       'k': { action: 'prevItem', description: 'Previous item in list' },
       'Enter': { action: 'selectItem', description: 'Select/activate item' },
   };
   ```

2. **Implement shortcut handler**
   ```javascript
   // static/js/keyboard.js
   
   class KeyboardHandler {
       constructor() {
           this.buffer = '';
           this.bufferTimeout = null;
           
           document.addEventListener('keydown', this.handleKeydown.bind(this));
       }
       
       handleKeydown(event) {
           // Ignore if in input field
           if (event.target.matches('input, textarea, select')) {
               if (event.key === 'Escape') {
                   event.target.blur();
               }
               return;
           }
           
           // Single key shortcuts
           if (SHORTCUTS[event.key]) {
               event.preventDefault();
               this.executeAction(SHORTCUTS[event.key].action);
               return;
           }
           
           // Multi-key shortcuts (e.g., 'g h')
           this.buffer += event.key + ' ';
           clearTimeout(this.bufferTimeout);
           
           const combo = this.buffer.trim();
           if (SHORTCUTS[combo]) {
               event.preventDefault();
               this.executeAction(SHORTCUTS[combo].action);
               this.buffer = '';
           } else {
               this.bufferTimeout = setTimeout(() => {
                   this.buffer = '';
               }, 500);
           }
       }
       
       executeAction(action) {
           switch (action) {
               case 'focusSearch':
                   document.querySelector('input[type="search"]')?.focus();
                   break;
               case 'goHome':
                   window.location.href = '/';
                   break;
               case 'goDashboard':
                   window.location.href = `/explore/${VizzyState.currentImportId}`;
                   break;
               case 'showHelp':
                   showShortcutsModal();
                   break;
               // ... more actions
           }
       }
   }
   
   new KeyboardHandler();
   ```

3. **Create help modal**
   ```html
   <div id="shortcuts-modal" class="modal hidden">
       <div class="modal-content">
           <h2>Keyboard Shortcuts</h2>
           <table>
               <tbody>
                   <tr><td><kbd>/</kbd></td><td>Focus search</td></tr>
                   <tr><td><kbd>Esc</kbd></td><td>Close / Go back</td></tr>
                   <tr><td><kbd>g</kbd> <kbd>h</kbd></td><td>Go home</td></tr>
                   <tr><td><kbd>g</kbd> <kbd>d</kbd></td><td>Go to dashboard</td></tr>
                   <tr><td><kbd>?</kbd></td><td>Show this help</td></tr>
               </tbody>
           </table>
           <button onclick="closeShortcutsModal()">Close</button>
       </div>
   </div>
   ```

### Acceptance Criteria
- [ ] All shortcuts work
- [ ] Shortcuts don't interfere with input fields
- [ ] Help modal shows all shortcuts
- [ ] Multi-key combos work with timing

### Output Files to Create/Modify
- `static/js/keyboard.js`
- `src/vizzy/templates/partials/shortcuts-modal.html`
- `src/vizzy/templates/base.html`
- `static/css/modal.css`

---

## Task P-008: Create Onboarding/Help Overlay System

### Objective
Help new users understand the visualization system.

### Implementation Steps

1. **Create tour system**
   ```javascript
   // static/js/tour.js
   
   const TOUR_STEPS = {
       dashboard: [
           {
               target: '.metrics-panel',
               title: 'System Overview',
               content: 'These metrics summarize your NixOS configuration.',
               position: 'bottom'
           },
           {
               target: '.contributors-panel',
               title: 'Largest Packages',
               content: 'Click any package to see what it pulls in.',
               position: 'right'
           },
           // ... more steps
       ],
       nodeDetail: [
           {
               target: '.why-chain-link',
               title: 'Attribution',
               content: 'Click here to see why this package exists.',
               position: 'left'
           }
       ]
   };
   
   class Tour {
       constructor(steps) {
           this.steps = steps;
           this.currentStep = 0;
       }
       
       start() {
           this.showStep(0);
       }
       
       showStep(index) {
           this.hideCurrentStep();
           
           const step = this.steps[index];
           const target = document.querySelector(step.target);
           
           if (!target) {
               this.next();
               return;
           }
           
           // Create tooltip
           const tooltip = document.createElement('div');
           tooltip.className = 'tour-tooltip';
           tooltip.innerHTML = `
               <h4>${step.title}</h4>
               <p>${step.content}</p>
               <div class="tour-nav">
                   <button onclick="tour.prev()">Back</button>
                   <span>${index + 1} / ${this.steps.length}</span>
                   <button onclick="tour.next()">Next</button>
               </div>
           `;
           
           this.positionTooltip(tooltip, target, step.position);
           document.body.appendChild(tooltip);
           
           // Highlight target
           target.classList.add('tour-highlight');
       }
       
       // ... more methods
   }
   ```

2. **Create contextual help**
   ```html
   <button class="help-trigger" 
           aria-label="Help"
           hx-get="/partials/help/{{ current_view }}"
           hx-target="#help-panel"
           hx-swap="innerHTML">
       ?
   </button>
   
   <aside id="help-panel" class="help-panel hidden">
       <!-- Loaded via HTMX -->
   </aside>
   ```

3. **Create help content partials**
   ```html
   <!-- src/vizzy/templates/help/treemap.html -->
   <div class="help-content">
       <h3>Treemap Guide</h3>
       
       <section>
           <h4>Reading the Treemap</h4>
           <p>Each rectangle represents a package. Larger rectangles have more dependencies.</p>
       </section>
       
       <section>
           <h4>Interactions</h4>
           <ul>
               <li><strong>Click</strong> a rectangle to zoom in</li>
               <li><strong>Right-click</strong> to zoom out</li>
               <li><strong>Hover</strong> for details</li>
           </ul>
       </section>
       
       <section>
           <h4>Colors</h4>
           <ul>
               <li><span class="color-sample library"></span> Libraries</li>
               <li><span class="color-sample application"></span> Applications</li>
               <!-- ... -->
           </ul>
       </section>
   </div>
   ```

4. **Track onboarding state**
   ```javascript
   const Onboarding = {
       hasSeenTour(name) {
           return localStorage.getItem(`tour_${name}`) === 'true';
       },
       
       markTourSeen(name) {
           localStorage.setItem(`tour_${name}`, 'true');
       },
       
       maybeShowTour(name) {
           if (!this.hasSeenTour(name)) {
               setTimeout(() => {
                   if (confirm('Would you like a quick tour of this feature?')) {
                       new Tour(TOUR_STEPS[name]).start();
                   }
                   this.markTourSeen(name);
               }, 1000);
           }
       }
   };
   ```

### Acceptance Criteria
- [ ] Tour highlights key features
- [ ] Contextual help available on each page
- [ ] Tour only shows once per feature
- [ ] Help content is accurate and clear
- [ ] Skip/dismiss works

### Output Files to Create/Modify
- `static/js/tour.js`
- `static/js/onboarding.js`
- `src/vizzy/templates/help/*.html`
- `static/css/tour.css`
- `src/vizzy/routes/pages.py`

---

## Task P-009: Performance Optimization Pass

### Objective
Optimize performance across all views for large imports.

### Implementation Steps

1. **Profile current performance**
   ```python
   # Add timing middleware
   @app.middleware("http")
   async def timing_middleware(request: Request, call_next):
       start = time.perf_counter()
       response = await call_next(request)
       duration = time.perf_counter() - start
       
       logger.info(f"{request.method} {request.url.path} - {duration:.3f}s")
       response.headers["X-Response-Time"] = f"{duration:.3f}"
       
       return response
   ```

2. **Add database query optimization**
   ```python
   # Add indexes for common queries
   # scripts/migrations/010_performance_indexes.sql
   
   CREATE INDEX CONCURRENTLY idx_nodes_closure_desc 
       ON nodes(import_id, closure_size DESC NULLS LAST);
   
   CREATE INDEX CONCURRENTLY idx_edges_composite 
       ON edges(import_id, source_id, target_id);
   
   CREATE INDEX CONCURRENTLY idx_nodes_toplevel 
       ON nodes(import_id) WHERE is_top_level = true;
   ```

3. **Implement query result caching**
   ```python
   from functools import lru_cache
   import hashlib
   
   def cache_key(*args, **kwargs):
       key_str = str(args) + str(sorted(kwargs.items()))
       return hashlib.md5(key_str.encode()).hexdigest()
   
   # Redis-backed cache for expensive queries
   class QueryCache:
       def __init__(self, redis_client):
           self.redis = redis_client
           self.default_ttl = 3600  # 1 hour
       
       def get_or_compute(self, key: str, compute_fn, ttl: int = None):
           cached = self.redis.get(key)
           if cached:
               return json.loads(cached)
           
           result = compute_fn()
           self.redis.setex(key, ttl or self.default_ttl, json.dumps(result))
           return result
   ```

4. **Add pagination everywhere**
   ```python
   class PaginatedResponse(BaseModel, Generic[T]):
       items: list[T]
       total: int
       page: int
       per_page: int
       pages: int
       has_next: bool
       has_prev: bool
   
   def paginate_query(query, page: int, per_page: int = 50):
       total = query.count()
       items = query.offset((page - 1) * per_page).limit(per_page).all()
       
       return PaginatedResponse(
           items=items,
           total=total,
           page=page,
           per_page=per_page,
           pages=(total + per_page - 1) // per_page,
           has_next=page * per_page < total,
           has_prev=page > 1
       )
   ```

5. **Optimize frontend rendering**
   ```javascript
   // Use virtual scrolling for long lists
   import { VirtualScroller } from './virtual-scroll.js';
   
   const scroller = new VirtualScroller({
       container: document.getElementById('node-list'),
       itemHeight: 40,
       renderItem: (item) => `<div class="node-item">${item.label}</div>`,
       data: nodes
   });
   ```

6. **Add response compression**
   ```python
   from fastapi.middleware.gzip import GZipMiddleware
   
   app.add_middleware(GZipMiddleware, minimum_size=1000)
   ```

### Acceptance Criteria
- [ ] Dashboard loads in <2s for 50k node imports
- [ ] Treemap loads in <3s
- [ ] Search responds in <500ms
- [ ] No blocking queries >10s
- [ ] Memory usage stays reasonable

### Output Files to Create/Modify
- `scripts/migrations/010_performance_indexes.sql`
- `src/vizzy/services/cache.py`
- `src/vizzy/main.py`
- `static/js/virtual-scroll.js`

---

## Task P-010: Accessibility Audit and Fixes

### Objective
Ensure all visualizations are accessible.

### Implementation Steps

1. **Run accessibility audit**
   ```bash
   # Use axe-core for automated testing
   npm install -g @axe-core/cli
   axe http://localhost:8000/explore/1 --save results.json
   ```

2. **Fix color contrast issues**
   ```css
   /* Ensure all text meets WCAG AA contrast ratio */
   :root {
       --text-primary: #1e293b;     /* 13.5:1 on white */
       --text-secondary: #475569;   /* 7.2:1 on white */
       --text-on-primary: #ffffff;  /* Ensure contrast on colored backgrounds */
   }
   
   /* Check all colored backgrounds */
   .package-type-library { 
       background: #74c0fc;
       color: #1e293b;  /* Dark text on light blue */
   }
   ```

3. **Add ARIA labels**
   ```html
   <nav aria-label="Main navigation">
       <a href="/" aria-current="{{ 'page' if is_home else 'false' }}">Home</a>
   </nav>
   
   <div role="treegrid" aria-label="Package dependency treemap">
       <div role="row" aria-level="1">
           <div role="gridcell" aria-label="firefox, 2340 dependencies">
               firefox (2,340)
           </div>
       </div>
   </div>
   ```

4. **Add keyboard navigation to visualizations**
   ```javascript
   // Treemap keyboard navigation
   treemapContainer.addEventListener('keydown', (e) => {
       switch (e.key) {
           case 'ArrowRight':
               selectNextSibling();
               break;
           case 'ArrowLeft':
               selectPrevSibling();
               break;
           case 'ArrowDown':
               selectFirstChild();
               break;
           case 'ArrowUp':
               selectParent();
               break;
           case 'Enter':
               activateSelected();
               break;
       }
   });
   ```

5. **Add screen reader announcements**
   ```javascript
   const announcer = document.getElementById('sr-announcer');
   
   function announce(message) {
       announcer.textContent = message;
   }
   
   // Usage
   function onNodeSelect(node) {
       announce(`Selected ${node.label}, ${node.closure_size} dependencies`);
   }
   ```

6. **Add skip links**
   ```html
   <a href="#main-content" class="skip-link">Skip to main content</a>
   <a href="#search" class="skip-link">Skip to search</a>
   ```

### Acceptance Criteria
- [ ] No critical axe-core violations
- [ ] All interactive elements keyboard accessible
- [ ] Screen reader can navigate all views
- [ ] Color is not only means of conveying info
- [ ] Focus indicators visible

### Output Files to Create/Modify
- `static/css/accessibility.css`
- All template files (ARIA labels)
- `static/js/*.js` (keyboard handlers)
- `src/vizzy/templates/base.html` (skip links, announcer)

---

## Phase 5 Completion Checklist

Final verification before release:

- [ ] All P-* tasks completed
- [ ] No console errors
- [ ] Performance targets met
- [ ] Accessibility audit passed
- [ ] All views have help content
- [ ] Navigation is consistent
- [ ] State management works
- [ ] Keyboard shortcuts documented

