# Closure Treemap Design Specification

## Overview

The Closure Treemap provides a hierarchical visualization of system closure size attribution, answering the question: "Which packages contribute most to my system's closure size, and how?"

This visualization complements the System Health Dashboard by enabling deep exploration into closure composition, showing the relative size contribution of each package and its dependencies.

## Design Goals

1. **Size attribution**: Clearly show which packages contribute most closure size
2. **Hierarchy exploration**: Enable drill-down from top-level applications to transitive dependencies
3. **Pattern recognition**: Use color coding to identify package type clusters
4. **Actionable insights**: Click-through to node details for further investigation
5. **Performance**: Handle 50k+ node graphs with client-side aggregation limits
6. **Consistent**: Follows existing Vizzy UI patterns (Tailwind CSS, HTMX, D3.js)

## User Questions Answered

- "What's taking up the most space in my closure?"
- "Why is my system configuration so large?"
- "Which application brings in the most dependencies?"
- "What percentage of my closure is development tools vs runtime libraries?"

## Layout Structure

### Main View

```
+-----------------------------------------------------------------------+
|                           Navigation Bar                                |
|  [Vizzy]                    [Search...]                     [? Help]    |
+-----------------------------------------------------------------------+
|                                                                         |
|  [Breadcrumb: Home > hostname-config > Treemap]                         |
|                                                                         |
|  +-------------------------------------------------------------------+ |
|  | View: [By Application v]    Filter: [All Types v]    [Back/Reset] | |
|  +-------------------------------------------------------------------+ |
|  |                                                                     | |
|  | +------ Breadcrumb Trail: System > firefox > gtk-3 ---------------+| |
|  |                                                                     | |
|  | +---------------------------------------------------------------+ | |
|  | |                                                               | | |
|  | |  +-------------+  +----------+  +--------+  +-------+         | | |
|  | |  |             |  |          |  |        |  |       |         | | |
|  | |  |   firefox   |  | libre-   |  | gnome- |  | rust  |         | | |
|  | |  |   2,340     |  | office   |  | shell  |  |       |         | | |
|  | |  |             |  | 1,890    |  | 1,567  |  | 980   |         | | |
|  | |  |             |  |          |  |        |  |       |         | | |
|  | |  +-------------+  +----------+  +--------+  +-------+         | | |
|  | |  +---------+  +--------+  +-------+  +------+  +-----+        | | |
|  | |  | nodejs  |  | python |  | gcc   |  | cmake| | perl |        | | |
|  | |  | 654     |  | 756    |  | 432   |  | 321  | | 210  |        | | |
|  | |  +---------+  +--------+  +-------+  +------+  +-----+        | | |
|  | |                                                               | | |
|  | +---------------------------------------------------------------+ | |
|  |                                                                     | |
|  +---------------------------------------------------------------------+ |
|                                                                         |
|  +-------------------------------------------------------------------+ |
|  | Legend:  [library] [application] [development] [service] [other]  | |
|  +-------------------------------------------------------------------+ |
|                                                                         |
+-----------------------------------------------------------------------+
```

### Zoomed View (After Click)

```
+-----------------------------------------------------------------------+
|  [<- Back to System]   firefox (2,340 derivations)                      |
+-----------------------------------------------------------------------+
|                                                                         |
|  +-------------------------------------------------------------------+ |
|  | +------ Breadcrumb: System > firefox ----------------------------+| |
|  |                                                                     | |
|  | +---------------------------------------------------------------+ | |
|  | |                                                               | | |
|  | |  +------------------+  +--------------+  +------------+       | | |
|  | |  |                  |  |              |  |            |       | | |
|  | |  |   gtk-3          |  |   glib       |  |  nss       |       | | |
|  | |  |   456            |  |   389        |  |   312      |       | | |
|  | |  |                  |  |              |  |            |       | | |
|  | |  +------------------+  +--------------+  +------------+       | | |
|  | |  +-----------+  +----------+  +--------+  +--------+          | | |
|  | |  | pango     |  | cairo    |  | dbus   |  | libpng |          | | |
|  | |  | 234       |  | 198      |  | 167    |  | 145    |          | | |
|  | |  +-----------+  +----------+  +--------+  +--------+          | | |
|  | |                                                               | | |
|  | +---------------------------------------------------------------+ | |
|  |                                                                     | |
|  +---------------------------------------------------------------------+ |
+-----------------------------------------------------------------------+
```

## Component Specifications

### 1. View Mode Selector

Dropdown to switch between different hierarchical organization modes.

#### Options
| Mode | Description | Hierarchy |
|------|-------------|-----------|
| By Application | Top-level apps as root, deps as children | App > Direct Deps > Transitive |
| By Type | Package type as root, packages as children | Type > Package > Deps |
| By Depth | Dependency depth as root | Depth 1 > Depth 2 > Depth 3... |
| Flat | No hierarchy, all packages at same level | Package (sized by closure) |

#### Default: "By Application"

### 2. Filter Controls

Filter which packages appear in the treemap.

#### Filter Options
- **All Types** (default)
- **Runtime Only** (exclude build-time dependencies)
- **Build-time Only** (exclude runtime dependencies)
- **By Package Type**: library, application, development, service, etc.

#### Implementation
```html
<select id="treemap-filter" class="border rounded p-2">
    <option value="all">All Types</option>
    <option value="runtime">Runtime Only</option>
    <option value="build">Build-time Only</option>
    <optgroup label="Package Types">
        <option value="type:library">Libraries</option>
        <option value="type:application">Applications</option>
        <option value="type:development">Development</option>
        <option value="type:service">Services</option>
    </optgroup>
</select>
```

### 3. Breadcrumb Trail

Shows current zoom level and enables navigation back through hierarchy.

#### Elements
- Click any segment to zoom to that level
- "System" is always the root
- Current level is highlighted (non-clickable)
- Separator: ">" character

#### Example
```
System > firefox > gtk-3 > glib
```

### 4. Treemap Container

The main D3.js treemap visualization.

#### Specifications
- **Width**: 100% of container (responsive)
- **Height**: Fixed at 500px (configurable via URL param)
- **Padding**: 2px between cells
- **Border**: 1px white stroke between cells
- **Border Radius**: 2px for leaf nodes

#### Cell Content
- **Large cells (>100px wide)**: Package name + closure count
- **Medium cells (50-100px wide)**: Package name only (truncated)
- **Small cells (<50px wide)**: No text, tooltip on hover

#### Sizing Algorithm
Area is proportional to `closure_size` (or `unique_contribution` when available).

### 5. Color Scheme

Consistent with dashboard and existing Vizzy patterns.

#### Package Type Colors
```css
library:       #74c0fc  /* blue-300 */
application:   #22d3ee  /* cyan-400 */
service:       #69db7c  /* green-400 */
development:   #b197fc  /* violet-400 */
configuration: #ffd43b  /* yellow-400 */
kernel:        #ff8787  /* red-300 */
python-package:#38d9a9  /* teal-400 */
font:          #f783ac  /* pink-400 */
unknown:       #e2e8f0  /* slate-200 */
```

#### Interaction States
- **Hover**: Darken by 10%, show tooltip
- **Selected**: 2px solid blue-600 outline
- **Zoomed parent**: Semi-transparent overlay

### 6. Tooltip

Detailed information on hover.

#### Content
```
+--------------------------------+
| firefox                        |
| -------------------------      |
| Closure size: 2,340            |
| Unique contribution: 1,200     |
| Type: application              |
| Direct deps: 47                |
| Click to zoom in               |
+--------------------------------+
```

#### Styling
- Background: slate-800
- Text: white
- Border radius: 4px
- Shadow: medium
- Max width: 250px

### 7. Legend

Color key for package types.

#### Layout
- Horizontal at bottom of treemap
- Only show types present in current view
- Click to filter by type

#### Implementation
```html
<div class="legend flex flex-wrap gap-3 mt-4 text-sm">
    <button class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-slate-100"
            onclick="filterByType('library')">
        <span class="w-3 h-3 rounded" style="background: #74c0fc"></span>
        library (12,450)
    </button>
    <!-- ... more types ... -->
</div>
```

### 8. Back/Reset Button

Navigation control for zoom state.

#### States
- **At root**: Disabled (grayed out)
- **Zoomed in**: Enabled, shows "Back to [parent]"
- **Alt text**: "Reset to System view"

## Interaction Patterns

### Click Behaviors

| Target | Action |
|--------|--------|
| Leaf node | Navigate to node detail page |
| Parent node | Zoom into that node |
| Breadcrumb segment | Zoom to that level |
| Back button | Go up one level |
| Legend item | Toggle filter for that type |

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `Tab` | Move focus between cells |
| `Enter` | Zoom into focused cell or navigate to detail |
| `Escape` | Zoom out one level |
| `Home` | Reset to root view |
| `?` | Show keyboard help |

### Animations

| Transition | Duration | Easing |
|------------|----------|--------|
| Zoom in | 500ms | ease-out |
| Zoom out | 500ms | ease-out |
| Filter change | 300ms | ease-in-out |
| Hover highlight | 150ms | ease |

## Data Requirements

### API Endpoint

**URL**: `GET /api/treemap/{import_id}`

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| mode | string | "application" | Hierarchy mode |
| filter | string | "all" | Type filter |
| root_node_id | int | null | Zoom root (null = system) |
| max_depth | int | 3 | Maximum hierarchy depth |
| limit | int | 50 | Max nodes per level |

### Response Schema

```json
{
  "name": "System",
  "node_id": null,
  "value": 45234,
  "package_type": null,
  "children": [
    {
      "name": "firefox",
      "node_id": 123,
      "value": 2340,
      "package_type": "application",
      "unique_contribution": 1200,
      "children": [
        {
          "name": "gtk-3",
          "node_id": 456,
          "value": 456,
          "package_type": "library",
          "children": []
        }
      ]
    }
  ]
}
```

### Data Aggregation Rules

1. **Limit children per parent**: Max 20 children shown, rest aggregated into "other"
2. **Minimum value threshold**: Nodes with <1% of parent's value grouped into "other"
3. **Max total nodes**: Limit to 500 nodes client-side for performance
4. **Aggregation label**: "X others (Y derivations)"

## Responsive Design

### Desktop (>= 1024px)
- Full layout with side controls
- Treemap height: 500px
- Legend inline at bottom

### Tablet (768px - 1023px)
- Controls move above treemap
- Treemap height: 400px
- Legend wraps to 2 rows

### Mobile (< 768px)
- Stacked layout
- Treemap height: 300px
- Legend as dropdown
- Touch-friendly cell sizes (min 44px)

## URL State Management

The treemap state should be reflected in the URL for bookmarking and sharing.

### URL Pattern
```
/treemap/{import_id}?mode=application&filter=runtime&zoom=123
```

### State Parameters
| Param | Type | Description |
|-------|------|-------------|
| mode | string | View mode |
| filter | string | Active filter |
| zoom | int | Current zoom root node ID |

### History Integration
- Use `history.pushState` for zoom navigation
- Browser back button zooms out
- URL updates without page reload

## Accessibility

### Requirements
- All interactive elements keyboard accessible
- Color not sole indicator (labels + patterns)
- Screen reader announces: node name, size, type
- Focus indicators visible (2px outline)
- Reduced motion: disable zoom animations if `prefers-reduced-motion`

### ARIA Implementation
```html
<div role="tree" aria-label="Closure size treemap">
    <div role="treeitem"
         aria-label="firefox, 2340 derivations, application"
         aria-expanded="false"
         tabindex="0">
        firefox
    </div>
</div>
```

## Performance Considerations

### Client-Side
- Limit rendered nodes to 500 (configurable)
- Use `requestAnimationFrame` for smooth animations
- Debounce resize handlers (150ms)
- Virtualize tooltip content

### Server-Side
- Pre-aggregate hierarchies at import time (optional)
- Cache treemap data (5 minute TTL)
- Limit recursive depth in queries
- Index on `closure_size` for sorting

### Performance Targets
| Metric | Target |
|--------|--------|
| Initial render (500 nodes) | < 500ms |
| Zoom transition | < 200ms |
| Filter update | < 300ms |
| API response time | < 1s |

## Error States

### Empty Data
```
+---------------------------------------+
|                                       |
|   No packages found matching filters. |
|                                       |
|   [Clear Filters]                     |
|                                       |
+---------------------------------------+
```

### Loading State
```
+---------------------------------------+
|                                       |
|   [Skeleton placeholder animation]    |
|                                       |
+---------------------------------------+
```

### API Error
```
+---------------------------------------+
|                                       |
|   Failed to load treemap data.        |
|   [Retry]                             |
|                                       |
+---------------------------------------+
```

## File Deliverables

### This Task (8C-001)
- `designs/treemap-spec.md` (this file)

### Subsequent Tasks
- `src/vizzy/services/treemap.py` - Data aggregation service (8C-002)
- `src/vizzy/routes/api.py` - API endpoint updates (8C-002)
- `src/vizzy/templates/treemap.html` - HTML template (8C-003)
- `static/css/treemap.css` - Component styles (8C-003)
- `static/js/treemap.js` - D3.js implementation (8C-003)

## Design Decisions

### Why D3.js for treemap?
- Industry standard for hierarchical visualizations
- Excellent treemap layout algorithms (`d3.treemap`)
- Smooth zoom transitions built-in
- No additional dependencies (already planned for Vizzy)

### Why limit to 500 nodes?
- Browser performance degrades with thousands of DOM elements
- 500 nodes covers 95%+ of typical system closure visualization
- Full exploration available via zoom drill-down

### Why "By Application" as default mode?
- Matches user mental model: "My applications and their deps"
- Most actionable view for identifying bloat sources
- Aligns with "question-driven" Phase 8 objectives

### Why separate from vis.js explorer?
- Different visualization goals: size attribution vs graph topology
- Treemap optimized for area comparison, vis.js for relationships
- Complementary tools, not replacements

## Mockups

### Root View (By Application)

```
+-----------------------------------------------------------------------+
| Closure Treemap                                     [By Application v] |
+-----------------------------------------------------------------------+
| Breadcrumb: System (45,234 derivations)                                |
+-----------------------------------------------------------------------+
|                                                                         |
|  +------------------------+  +-----------------+  +---------------+    |
|  |                        |  |                 |  |               |    |
|  |       firefox          |  |   libreoffice   |  |  gnome-shell  |    |
|  |        2,340           |  |      1,890      |  |     1,567     |    |
|  |                        |  |                 |  |               |    |
|  +------------------------+  +-----------------+  +---------------+    |
|  +-------------+  +----------+  +---------+  +--------+  +-------+     |
|  |    vscode   |  | chromium |  |  rust   |  | python |  | nodejs|     |
|  |    1,234    |  |   1,100  |  |   980   |  |   756  |  |  654  |     |
|  +-------------+  +----------+  +---------+  +--------+  +-------+     |
|  +--------+  +-------+  +-------+  +------+  +-----+  +----+  +---+    |
|  |  gcc   |  | cmake |  |  perl |  | ruby |  | go  |  |java|  |...|    |
|  |  432   |  |  321  |  |  210  |  | 189  |  | 167 |  | 145|  |   |    |
|  +--------+  +-------+  +-------+  +------+  +-----+  +----+  +---+    |
|                                                                         |
+-----------------------------------------------------------------------+
| [lib] [app] [dev] [service] [other]        Click cell to zoom in       |
+-----------------------------------------------------------------------+
```

### Zoomed View (firefox)

```
+-----------------------------------------------------------------------+
| [<- Back]   firefox (2,340 derivations)             [By Application v] |
+-----------------------------------------------------------------------+
| Breadcrumb: System > firefox                                           |
+-----------------------------------------------------------------------+
|                                                                         |
|  +---------------------------+  +---------------------+                 |
|  |                           |  |                     |                 |
|  |          gtk-3            |  |        glib         |                 |
|  |           456             |  |         389         |                 |
|  |                           |  |                     |                 |
|  +---------------------------+  +---------------------+                 |
|  +-----------------+  +-------------+  +-----------+  +---------+      |
|  |       nss       |  |    pango    |  |   cairo   |  |  dbus   |      |
|  |       312       |  |     234     |  |    198    |  |   167   |      |
|  +-----------------+  +-------------+  +-----------+  +---------+      |
|  +---------+  +--------+  +-------+  +------+  +-----+  +----+         |
|  | libpng  |  |freetype|  | zlib  |  | pcre |  | xml2|  | ...|         |
|  |   145   |  |   134  |  |  112  |  |  98  |  |  87 |  |    |         |
|  +---------+  +--------+  +-------+  +------+  +-----+  +----+         |
|                                                                         |
+-----------------------------------------------------------------------+
| [lib] [app] [dev]                          Click cell to zoom deeper   |
+-----------------------------------------------------------------------+
```

## Acceptance Criteria

- [x] Design document complete with all sections
- [x] Layout mockups provided (ASCII diagrams)
- [x] Interaction patterns documented
- [x] API endpoint schema defined
- [x] Responsive breakpoints specified
- [x] Accessibility requirements documented
- [x] Performance targets defined
- [x] Color scheme consistent with existing Vizzy patterns
- [x] Error states designed
- [x] URL state management specified
