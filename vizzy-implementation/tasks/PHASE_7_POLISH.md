# Phase 7: Polish - Agent Instructions

## Overview

Phase 7 focuses on UX polish, performance optimization, and accessibility improvements as defined in the original PRD.

**Status**: Not started

---

## Task 7-001: Implement Pan/Zoom for Large Graphviz Graphs

### Objective
Add smooth pan and zoom capabilities to the Graphviz SVG renderings for better navigation of large graphs.

### Context
Currently, large graphs render as static SVGs that overflow their containers. Users need to:
- Pan (drag to move around)
- Zoom (scroll to zoom in/out)
- Reset view (button to fit graph)

### Input Files to Review
- `static/js/app.js` - Existing pan implementation (basic)
- `src/vizzy/templates/base.html` - Graph container styling
- `static/css/app.css` - Graph container CSS

### Implementation Steps

1. **Enhance pan/zoom JavaScript**
   ```javascript
   // static/js/graph-navigation.js
   
   class GraphNavigator {
       constructor(container) {
           this.container = container;
           this.svg = container.querySelector('svg');
           if (!this.svg) return;
           
           this.scale = 1;
           this.translateX = 0;
           this.translateY = 0;
           this.isPanning = false;
           this.startX = 0;
           this.startY = 0;
           
           this.init();
       }
       
       init() {
           // Wrap SVG content in a group for transformations
           const content = this.svg.innerHTML;
           this.svg.innerHTML = `<g class="pan-zoom-group">${content}</g>`;
           this.group = this.svg.querySelector('.pan-zoom-group');
           
           // Set up event listeners
           this.container.addEventListener('wheel', this.handleZoom.bind(this));
           this.container.addEventListener('mousedown', this.startPan.bind(this));
           this.container.addEventListener('mousemove', this.doPan.bind(this));
           this.container.addEventListener('mouseup', this.endPan.bind(this));
           this.container.addEventListener('mouseleave', this.endPan.bind(this));
           
           // Touch support
           this.container.addEventListener('touchstart', this.handleTouchStart.bind(this));
           this.container.addEventListener('touchmove', this.handleTouchMove.bind(this));
           this.container.addEventListener('touchend', this.endPan.bind(this));
           
           // Add controls
           this.addControls();
       }
       
       handleZoom(e) {
           e.preventDefault();
           
           const rect = this.container.getBoundingClientRect();
           const mouseX = e.clientX - rect.left;
           const mouseY = e.clientY - rect.top;
           
           const delta = e.deltaY > 0 ? 0.9 : 1.1;
           const newScale = Math.max(0.1, Math.min(5, this.scale * delta));
           
           // Zoom toward mouse position
           this.translateX -= (mouseX - this.translateX) * (newScale / this.scale - 1);
           this.translateY -= (mouseY - this.translateY) * (newScale / this.scale - 1);
           this.scale = newScale;
           
           this.applyTransform();
       }
       
       startPan(e) {
           if (e.target.closest('a')) return; // Don't pan when clicking links
           
           this.isPanning = true;
           this.startX = e.clientX - this.translateX;
           this.startY = e.clientY - this.translateY;
           this.container.style.cursor = 'grabbing';
       }
       
       doPan(e) {
           if (!this.isPanning) return;
           
           this.translateX = e.clientX - this.startX;
           this.translateY = e.clientY - this.startY;
           this.applyTransform();
       }
       
       endPan() {
           this.isPanning = false;
           this.container.style.cursor = 'grab';
       }
       
       applyTransform() {
           this.group.setAttribute('transform', 
               `translate(${this.translateX}, ${this.translateY}) scale(${this.scale})`
           );
       }
       
       reset() {
           this.scale = 1;
           this.translateX = 0;
           this.translateY = 0;
           this.applyTransform();
           this.fitToContainer();
       }
       
       fitToContainer() {
           const svgRect = this.svg.getBoundingClientRect();
           const groupRect = this.group.getBBox();
           
           const scaleX = svgRect.width / groupRect.width;
           const scaleY = svgRect.height / groupRect.height;
           this.scale = Math.min(scaleX, scaleY, 1) * 0.9;
           
           this.translateX = (svgRect.width - groupRect.width * this.scale) / 2;
           this.translateY = (svgRect.height - groupRect.height * this.scale) / 2;
           
           this.applyTransform();
       }
       
       addControls() {
           const controls = document.createElement('div');
           controls.className = 'graph-controls';
           controls.innerHTML = `
               <button class="zoom-in" title="Zoom In">+</button>
               <button class="zoom-out" title="Zoom Out">−</button>
               <button class="zoom-reset" title="Reset View">⟲</button>
           `;
           
           controls.querySelector('.zoom-in').addEventListener('click', () => {
               this.scale = Math.min(5, this.scale * 1.2);
               this.applyTransform();
           });
           
           controls.querySelector('.zoom-out').addEventListener('click', () => {
               this.scale = Math.max(0.1, this.scale / 1.2);
               this.applyTransform();
           });
           
           controls.querySelector('.zoom-reset').addEventListener('click', () => {
               this.reset();
           });
           
           this.container.style.position = 'relative';
           this.container.appendChild(controls);
       }
   }
   
   // Initialize on all graph containers
   document.addEventListener('DOMContentLoaded', () => {
       document.querySelectorAll('.graph-container').forEach(container => {
           new GraphNavigator(container);
       });
   });
   ```

2. **Add control styles**
   ```css
   /* static/css/graph-controls.css */
   
   .graph-controls {
       position: absolute;
       top: 0.5rem;
       right: 0.5rem;
       display: flex;
       gap: 0.25rem;
       z-index: 10;
   }
   
   .graph-controls button {
       width: 2rem;
       height: 2rem;
       border: 1px solid #e2e8f0;
       background: white;
       border-radius: 0.25rem;
       cursor: pointer;
       font-size: 1.2rem;
       display: flex;
       align-items: center;
       justify-content: center;
   }
   
   .graph-controls button:hover {
       background: #f1f5f9;
   }
   
   .graph-container {
       cursor: grab;
       overflow: hidden;
   }
   
   .graph-container svg {
       width: 100%;
       height: 100%;
   }
   ```

3. **Include new scripts in templates**
   ```html
   <!-- In base.html -->
   <link rel="stylesheet" href="/static/css/graph-controls.css">
   <script src="/static/js/graph-navigation.js"></script>
   ```

### Acceptance Criteria
- [ ] Scroll to zoom works smoothly
- [ ] Pan by dragging works
- [ ] Clicking nodes/links still works
- [ ] Reset button fits graph to container
- [ ] Touch support works on mobile
- [ ] Zoom has min/max limits

### Output Files to Create/Modify
- `static/js/graph-navigation.js`
- `static/css/graph-controls.css`
- `src/vizzy/templates/base.html`

---

## Task 7-002: Add Keyboard Navigation

### Objective
Implement keyboard shortcuts for power users to navigate the application efficiently.

### Implementation Steps

1. **Define shortcuts**
   ```javascript
   // static/js/keyboard.js
   
   const VIZZY_SHORTCUTS = {
       // Navigation
       '/': { action: 'focusSearch', desc: 'Focus search' },
       'Escape': { action: 'escape', desc: 'Close/blur/back' },
       'g h': { action: 'goHome', desc: 'Go to home' },
       'g e': { action: 'goExplore', desc: 'Go to explore' },
       
       // Graph navigation
       'j': { action: 'nextNode', desc: 'Next node in list' },
       'k': { action: 'prevNode', desc: 'Previous node in list' },
       'Enter': { action: 'selectNode', desc: 'Open selected node' },
       'o': { action: 'openInNewTab', desc: 'Open in new tab' },
       
       // Views
       'd': { action: 'viewDuplicates', desc: 'View duplicates' },
       'p': { action: 'viewPath', desc: 'Open path finder' },
       'i': { action: 'viewImpact', desc: 'View impact' },
       
       // Help
       '?': { action: 'showHelp', desc: 'Show shortcuts' },
   };
   ```

2. **Implement keyboard handler**
   ```javascript
   class KeyboardNav {
       constructor() {
           this.buffer = '';
           this.bufferTimeout = null;
           this.selectedIndex = -1;
           
           document.addEventListener('keydown', this.handle.bind(this));
       }
       
       handle(e) {
           // Skip if in input
           if (e.target.matches('input, textarea, select')) {
               if (e.key === 'Escape') e.target.blur();
               return;
           }
           
           // Build buffer for multi-key shortcuts
           const key = e.key;
           this.buffer += key + ' ';
           clearTimeout(this.bufferTimeout);
           
           // Check for match
           const trimmed = this.buffer.trim();
           if (VIZZY_SHORTCUTS[trimmed]) {
               e.preventDefault();
               this.execute(VIZZY_SHORTCUTS[trimmed].action);
               this.buffer = '';
               return;
           }
           
           // Reset buffer after delay
           this.bufferTimeout = setTimeout(() => {
               this.buffer = '';
           }, 500);
       }
       
       execute(action) {
           switch (action) {
               case 'focusSearch':
                   document.querySelector('[name="q"], [type="search"]')?.focus();
                   break;
               case 'escape':
                   this.handleEscape();
                   break;
               case 'goHome':
                   window.location.href = '/';
                   break;
               case 'goExplore':
                   const importId = this.getCurrentImportId();
                   if (importId) window.location.href = `/explore/${importId}`;
                   break;
               case 'showHelp':
                   this.showHelpModal();
                   break;
               case 'nextNode':
                   this.navigateList(1);
                   break;
               case 'prevNode':
                   this.navigateList(-1);
                   break;
               case 'selectNode':
                   this.activateSelected();
                   break;
           }
       }
       
       getCurrentImportId() {
           // Try to extract from URL
           const match = window.location.pathname.match(/\/(explore|graph|analyze)\/(\d+)/);
           return match ? match[2] : null;
       }
       
       handleEscape() {
           const modal = document.querySelector('.modal.visible, .modal:not(.hidden)');
           if (modal) {
               modal.classList.add('hidden');
               return;
           }
           history.back();
       }
       
       navigateList(delta) {
           const items = document.querySelectorAll('.node-list a, .results a, [data-navigable]');
           if (!items.length) return;
           
           this.selectedIndex = Math.max(0, Math.min(items.length - 1, this.selectedIndex + delta));
           
           items.forEach((item, i) => {
               item.classList.toggle('keyboard-selected', i === this.selectedIndex);
           });
           
           items[this.selectedIndex]?.scrollIntoView({ block: 'nearest' });
       }
       
       activateSelected() {
           const selected = document.querySelector('.keyboard-selected');
           if (selected) selected.click();
       }
       
       showHelpModal() {
           let modal = document.getElementById('keyboard-help');
           if (!modal) {
               modal = document.createElement('div');
               modal.id = 'keyboard-help';
               modal.className = 'modal hidden';
               modal.innerHTML = `
                   <div class="modal-content">
                       <h2>Keyboard Shortcuts</h2>
                       <table>
                           <tbody>
                               ${Object.entries(VIZZY_SHORTCUTS).map(([key, {desc}]) => `
                                   <tr>
                                       <td><kbd>${key.replace(/ /g, '</kbd> <kbd>')}</kbd></td>
                                       <td>${desc}</td>
                                   </tr>
                               `).join('')}
                           </tbody>
                       </table>
                       <button onclick="this.closest('.modal').classList.add('hidden')">Close</button>
                   </div>
               `;
               document.body.appendChild(modal);
           }
           modal.classList.toggle('hidden');
       }
   }
   
   new KeyboardNav();
   ```

3. **Add styles**
   ```css
   /* static/css/keyboard.css */
   
   .keyboard-selected {
       outline: 2px solid #3b82f6 !important;
       outline-offset: 2px;
   }
   
   kbd {
       display: inline-block;
       padding: 0.2em 0.4em;
       font-size: 0.85em;
       font-family: monospace;
       background: #f1f5f9;
       border: 1px solid #e2e8f0;
       border-radius: 0.25rem;
   }
   
   .modal {
       position: fixed;
       inset: 0;
       background: rgba(0,0,0,0.5);
       display: flex;
       align-items: center;
       justify-content: center;
       z-index: 1000;
   }
   
   .modal.hidden {
       display: none;
   }
   
   .modal-content {
       background: white;
       padding: 2rem;
       border-radius: 0.5rem;
       max-width: 500px;
       max-height: 80vh;
       overflow: auto;
   }
   ```

### Acceptance Criteria
- [ ] All shortcuts work
- [ ] Multi-key shortcuts (g h) work
- [ ] Don't interfere with input fields
- [ ] Help modal shows all shortcuts
- [ ] List navigation (j/k) works

### Output Files to Create/Modify
- `static/js/keyboard.js`
- `static/css/keyboard.css`
- `src/vizzy/templates/base.html`

---

## Task 7-003: Performance Optimization

### Objective
Optimize database queries, add caching, and improve frontend performance.

### Implementation Steps

1. **Add database indexes**
   ```sql
   -- scripts/migrations/020_performance_indexes.sql
   
   -- Optimize common queries
   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_closure_desc 
       ON nodes(import_id, closure_size DESC NULLS LAST);
   
   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_label_pattern
       ON nodes(import_id, label text_pattern_ops);
   
   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nodes_toplevel
       ON nodes(import_id) WHERE is_top_level = true;
   
   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_edges_both
       ON edges(import_id, source_id, target_id);
   ```

2. **Add query result caching**
   ```python
   # src/vizzy/services/cache.py
   
   from functools import lru_cache
   from datetime import datetime, timedelta
   import json
   
   class SimpleCache:
       """Simple in-memory cache with TTL."""
       
       def __init__(self, default_ttl: int = 300):
           self._cache = {}
           self._default_ttl = default_ttl
       
       def get(self, key: str):
           if key not in self._cache:
               return None
           value, expires = self._cache[key]
           if datetime.now() > expires:
               del self._cache[key]
               return None
           return value
       
       def set(self, key: str, value, ttl: int = None):
           ttl = ttl or self._default_ttl
           expires = datetime.now() + timedelta(seconds=ttl)
           self._cache[key] = (value, expires)
       
       def invalidate(self, pattern: str = None):
           if pattern is None:
               self._cache.clear()
           else:
               keys = [k for k in self._cache if pattern in k]
               for k in keys:
                   del self._cache[k]
   
   cache = SimpleCache()
   ```

3. **Cache expensive queries**
   ```python
   # src/vizzy/services/graph.py
   
   from vizzy.services.cache import cache
   
   def get_clusters(import_id: int) -> list[ClusterInfo]:
       cache_key = f"clusters:{import_id}"
       cached = cache.get(cache_key)
       if cached:
           return cached
       
       # ... existing query ...
       
       cache.set(cache_key, result)
       return result
   ```

4. **Add response compression**
   ```python
   # src/vizzy/main.py
   
   from fastapi.middleware.gzip import GZipMiddleware
   
   app.add_middleware(GZipMiddleware, minimum_size=1000)
   ```

5. **Add timing middleware**
   ```python
   # src/vizzy/middleware.py
   
   import time
   from starlette.middleware.base import BaseHTTPMiddleware
   import logging
   
   logger = logging.getLogger("vizzy.performance")
   
   class TimingMiddleware(BaseHTTPMiddleware):
       async def dispatch(self, request, call_next):
           start = time.perf_counter()
           response = await call_next(request)
           duration = time.perf_counter() - start
           
           if duration > 1.0:  # Log slow requests
               logger.warning(f"Slow request: {request.method} {request.url.path} - {duration:.2f}s")
           
           response.headers["X-Response-Time"] = f"{duration:.3f}"
           return response
   
   # In main.py
   app.add_middleware(TimingMiddleware)
   ```

6. **Lazy load heavy content with HTMX**
   ```html
   <!-- Example: Lazy load node list -->
   <div hx-get="/partials/nodes/{{ import_id }}?type={{ type }}"
        hx-trigger="revealed"
        hx-swap="innerHTML">
       <div class="skeleton-loader">Loading...</div>
   </div>
   ```

### Acceptance Criteria
- [ ] Database indexes created
- [ ] Cache improves repeated query times
- [ ] Slow request logging works
- [ ] Response compression enabled
- [ ] Dashboard loads in <2s for 50k nodes

### Output Files to Create/Modify
- `scripts/migrations/020_performance_indexes.sql`
- `src/vizzy/services/cache.py`
- `src/vizzy/middleware.py`
- `src/vizzy/main.py`
- `src/vizzy/services/graph.py`

---

## Task 7-004: URL State Management Improvements

### Objective
Ensure all view state is reflected in URLs for shareability and back-button support.

### Implementation Steps

1. **Track state in URL**
   ```javascript
   // static/js/url-state.js
   
   class URLState {
       static get(key) {
           const params = new URLSearchParams(window.location.search);
           return params.get(key);
       }
       
       static set(key, value) {
           const params = new URLSearchParams(window.location.search);
           if (value) {
               params.set(key, value);
           } else {
               params.delete(key);
           }
           const newUrl = `${window.location.pathname}?${params}`;
           history.replaceState(null, '', newUrl);
       }
       
       static setMultiple(updates) {
           const params = new URLSearchParams(window.location.search);
           for (const [key, value] of Object.entries(updates)) {
               if (value) {
                   params.set(key, value);
               } else {
                   params.delete(key);
               }
           }
           const newUrl = `${window.location.pathname}?${params}`;
           history.replaceState(null, '', newUrl);
       }
   }
   ```

2. **Restore state on page load**
   ```javascript
   document.addEventListener('DOMContentLoaded', () => {
       // Restore filters
       const typeFilter = URLState.get('type');
       if (typeFilter) {
           document.getElementById('type-filter')?.value = typeFilter;
       }
       
       // Restore search
       const query = URLState.get('q');
       if (query) {
           const search = document.querySelector('[name="q"]');
           if (search) search.value = query;
       }
       
       // Restore selected node highlight
       const nodeId = URLState.get('node');
       if (nodeId) {
           document.querySelector(`[data-node-id="${nodeId}"]`)
               ?.classList.add('selected');
       }
   });
   ```

3. **Sync HTMX requests with URL**
   ```javascript
   document.body.addEventListener('htmx:configRequest', (e) => {
       // Include URL state in HTMX requests
       const params = new URLSearchParams(window.location.search);
       for (const [key, value] of params) {
           e.detail.parameters[key] = value;
       }
   });
   
   document.body.addEventListener('htmx:afterSwap', (e) => {
       // Update URL after content swap
       const target = e.detail.target;
       const state = target.dataset.urlState;
       if (state) {
           URLState.setMultiple(JSON.parse(state));
       }
   });
   ```

### Acceptance Criteria
- [ ] Filter state in URL
- [ ] Search query in URL
- [ ] Selected node in URL
- [ ] Back button restores state
- [ ] URLs are shareable

### Output Files to Create/Modify
- `static/js/url-state.js`
- `src/vizzy/templates/base.html`

---

## Phase 7 Completion Checklist

- [ ] All 7-* tasks completed
- [ ] Pan/zoom works on all graph views
- [ ] Keyboard shortcuts documented
- [ ] Performance acceptable (<2s loads)
- [ ] URL state works for key filters


