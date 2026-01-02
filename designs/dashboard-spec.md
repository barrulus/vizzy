# System Health Dashboard Design Specification

## Overview

The System Health Dashboard provides an at-a-glance view of NixOS configuration health metrics, answering the question: "How healthy is my system closure?"

This dashboard replaces the basic cluster overview with actionable metrics and navigation to deeper analysis tools.

## Design Goals

1. **Immediate insight**: Key metrics visible without scrolling
2. **Actionable**: Clear paths to address issues (duplicates, bloat)
3. **Comparative**: Context through baseline comparisons where available
4. **Navigation hub**: Gateway to detailed analysis tools
5. **Consistent**: Follows existing Vizzy UI patterns (Tailwind CSS, HTMX)

## Layout Structure

```
+-----------------------------------------------------------------------+
|                           Navigation Bar                                |
|  [Vizzy]                    [Search...]                     [? Help]    |
+-----------------------------------------------------------------------+
|                                                                         |
|  [Breadcrumb: Home > hostname-config > Dashboard]                       |
|                                                                         |
|  +------------------+ +------------------+ +------------------+ +------+|
|  |     45,234       | |      12.3%       | |    67% Runtime   | | 4.2  ||
|  |   derivations    | |    redundancy    | |    dependencies  | | avg  ||
|  |  +23% vs minimal | |   (high)         | |                  | |depth ||
|  +------------------+ +------------------+ +------------------+ +------+|
|                                                                         |
|  +-----------------------------------+ +-------------------------------+|
|  | Top Contributors                  | | By Package Type               ||
|  | --------------------------------- | | ----------------------------- ||
|  | firefox     [======= ] 2,340      | |                               ||
|  | libreoffice [=====   ] 1,890      | |    [Donut/Pie Chart]          ||
|  | gnome-shell [====    ] 1,567      | |                               ||
|  | vscode      [====    ] 1,234      | |    library: 45%               ||
|  | chromium    [===     ] 1,100      | |    application: 25%           ||
|  |                                   | |    development: 15%           ||
|  | [View Treemap ->]                 | |    other: 15%                 ||
|  +-----------------------------------+ +-------------------------------+|
|                                                                         |
|  +---------------------------------------------------------------------+|
|  | Quick Actions                                                        ||
|  | [Find Duplicates] [View Treemap] [Why Chain] [Compare Hosts]        ||
|  +---------------------------------------------------------------------+|
|                                                                         |
+-----------------------------------------------------------------------+
```

## Component Specifications

### 1. Metric Cards (Top Row)

Four horizontal cards displaying key health indicators.

#### Card 1: Total Derivations
- **Primary Value**: Total node count (formatted with commas)
- **Label**: "derivations"
- **Context** (optional): Percentage comparison to baseline/minimal config
- **Visual**: Large bold number, muted label
- **Color**: Neutral (slate-700)

#### Card 2: Redundancy Score
- **Primary Value**: Percentage of redundant edges
- **Label**: "redundancy"
- **Warning Threshold**: > 10% shows amber warning badge
- **Context**: Health indicator (low/medium/high)
- **Color**:
  - < 5%: green-500
  - 5-10%: slate-700
  - > 10%: amber-500 with warning icon

#### Card 3: Runtime Ratio
- **Primary Value**: Percentage of runtime (vs build-time) dependencies
- **Label**: "runtime dependencies"
- **Visual**: Mini progress bar under the percentage
- **Context**: Helps understand build vs runtime footprint
- **Color**: Blue-600 progress bar

#### Card 4: Depth Metrics
- **Primary Value**: Average dependency depth
- **Label**: "avg depth"
- **Secondary**: Max depth in smaller text
- **Color**: Neutral (slate-700)

### 2. Top Contributors Panel (Left Column)

Bar chart showing packages contributing most to closure size.

#### Elements
- **Header**: "Largest Contributors" with count
- **Bars**: Horizontal bar chart, max 10 items
  - Package name (truncated with tooltip)
  - Visual bar (proportional to closure_size)
  - Numeric value (formatted)
- **Interaction**: Click package name to navigate to node detail
- **Footer Link**: "View Treemap ->" to full treemap view

#### Data Source
```sql
SELECT label, closure_size, package_type
FROM nodes
WHERE import_id = ? AND is_top_level = TRUE
ORDER BY closure_size DESC NULLS LAST
LIMIT 10
```

### 3. Package Type Distribution (Right Column)

Visual breakdown of packages by type.

#### Elements
- **Header**: "By Package Type"
- **Chart**: Donut chart or segmented bar
  - Segments colored by package type
  - Legend with counts/percentages
- **Interaction**: Click segment to filter/navigate

#### Color Scheme (consistent with treemap)
```css
library:       #74c0fc (blue-300)
application:   #22d3ee (cyan-400)
service:       #69db7c (green-400)
development:   #b197fc (violet-400)
configuration: #ffd43b (yellow-400)
unknown:       #e2e8f0 (slate-200)
```

### 4. Quick Actions Bar (Bottom)

Navigation buttons to common analysis tasks.

#### Buttons
| Action | Label | Icon | Link |
|--------|-------|------|------|
| Find duplicates | "Find Duplicates" | magnifying glass | /analyze/duplicates/{id} |
| View treemap | "View Treemap" | tree icon | /treemap/{id} |
| Why chain | "Why Chain" | question mark | /why-chain/{id} (select mode) |
| Compare hosts | "Compare" | arrows | /compare?left={id} |

#### Styling
- Background: slate-100
- Border radius: rounded
- Hover: slate-200
- Icon + text layout

## Responsive Design

### Desktop (>= 1024px)
- 4 metric cards in single row
- 2-column layout for panels
- Full quick actions bar

### Tablet (768px - 1023px)
- 2x2 grid for metric cards
- 2-column layout for panels
- Quick actions wrap to 2 rows

### Mobile (< 768px)
- Single column for metric cards (stacked)
- Single column for panels
- Quick actions as vertical list

## HTMX Integration

### Dynamic Loading
```html
<!-- Metric cards can load independently -->
<div id="metric-derivations"
     hx-get="/api/dashboard/{id}/metrics/derivations"
     hx-trigger="load">
    <div class="animate-pulse bg-slate-200 h-20 rounded"></div>
</div>

<!-- Contributors load separately -->
<div id="contributors"
     hx-get="/api/dashboard/{id}/top-contributors"
     hx-trigger="load"
     hx-swap="innerHTML">
    Loading...
</div>
```

### Partial Updates
- Metrics can refresh without full page reload
- Chart updates via HTMX swap

## Accessibility

### Requirements
- All metrics have descriptive labels (aria-label)
- Chart has text alternatives (hidden table or sr-only description)
- Focus states visible on all interactive elements
- Color not sole indicator (icons/text accompany colors)
- Keyboard navigation through all actions

### Implementation
```html
<div class="metric-card" role="group" aria-labelledby="metric-derivations-label">
    <div id="metric-derivations-label" class="sr-only">Total derivations count</div>
    <div class="text-3xl font-bold" aria-describedby="metric-derivations-label">45,234</div>
    <div class="text-sm text-slate-500">derivations</div>
</div>
```

## URL Structure

**Dashboard URL**: `/dashboard/{import_id}`

Alternative: Could be accessed from `/explore/{import_id}` with a tab switch, but dedicated URL preferred for bookmarking.

## API Endpoints Required (Task 8B-002)

| Endpoint | Method | Response |
|----------|--------|----------|
| `/api/dashboard/{id}/summary` | GET | DashboardSummary object |
| `/api/dashboard/{id}/top-contributors` | GET | List of contributor objects |
| `/api/dashboard/{id}/type-distribution` | GET | Type distribution data |

### Response Schemas

```json
// DashboardSummary
{
    "total_nodes": 45234,
    "total_edges": 123456,
    "redundancy_score": 0.123,
    "build_runtime_ratio": 0.67,
    "depth_stats": {
        "max": 12,
        "avg": 4.2,
        "median": 4.0
    },
    "baseline_comparison": {
        "baseline_name": "minimal",
        "node_difference": 12000,
        "percentage": 23
    }
}

// TopContributor
{
    "node_id": 123,
    "label": "firefox",
    "closure_size": 2340,
    "package_type": "application",
    "unique_contribution": 1200
}

// TypeDistribution
{
    "types": [
        {"type": "library", "count": 20000, "percentage": 45},
        {"type": "application", "count": 11000, "percentage": 25},
        ...
    ]
}
```

## File Deliverables

### This Task (8B-001)
- `designs/dashboard-spec.md` (this file)
- `src/vizzy/templates/dashboard.html` (HTML template)
- `static/css/dashboard.css` (component-specific styles)

### Subsequent Tasks
- `src/vizzy/services/dashboard.py` (8B-002)
- `src/vizzy/routes/api.py` updates (8B-002)
- Route integration and testing (8B-003)

## Design Decisions

### Why a dedicated dashboard vs enhancing explore.html?
The explore view focuses on graph navigation with cluster overview. The dashboard serves a different purpose: health metrics and triage. Keeping them separate allows focused UX for each use case.

### Why donut chart for type distribution?
- Familiar visualization for proportions
- Works well with 5-7 categories (package types)
- Can be implemented with pure CSS/SVG or lightweight Chart.js

### Why limit contributors to 10?
- Screen real estate constraint
- Top 10 covers majority of closure (usually 80%+)
- Full exploration available via Treemap link

## Mockup

```
+-----------------------------------------------------------------------+
| Vizzy                            [Search...]                    [?]   |
+-----------------------------------------------------------------------+
| Home > workstation-nixos > Dashboard                                   |
|                                                                        |
| +-----------------+ +-----------------+ +-----------------+ +---------+|
| |    45,234       | |     12.3%       | |   67% Runtime   | |  4.2    ||
| |   derivations   | |   redundancy    | |       deps      | |  avg    ||
| |   +23% vs min   | |   [!] high      | |  [=======---]   | | depth   ||
| +-----------------+ +-----------------+ +-----------------+ +---------+|
|                                                                        |
| +-----------------------------------+ +-------------------------------+|
| | Largest Contributors              | | By Package Type               ||
| |-----------------------------------| |-------------------------------||
| | firefox        [========] 2,340   | |          ,-----.              ||
| | libreoffice    [======  ] 1,890   | |        ,'   45%`.   library   ||
| | gnome-shell    [=====   ] 1,567   | |       /    lib   \  --------  ||
| | vscode         [====    ] 1,234   | |      |   25%     |  app       ||
| | chromium       [===     ] 1,100   | |       \   app   /   --------  ||
| | rust           [===     ]   980   | |        `.     ,'    dev       ||
| | python3        [==      ]   756   | |          `---'      --------  ||
| | nodejs         [==      ]   654   | |                     other     ||
| | gcc            [=       ]   432   | |                               ||
| | cmake          [=       ]   321   | |                               ||
| |                                   | |                               ||
| | [View Treemap ->]                 | | Click segment to explore      ||
| +-----------------------------------+ +-------------------------------+|
|                                                                        |
| +---------------------------------------------------------------------+|
| | [Find Duplicates] [View Treemap] [Why Chain] [Compare Hosts]        ||
| +---------------------------------------------------------------------+|
+-----------------------------------------------------------------------+
```

## Acceptance Criteria

- [ ] Design document complete with all sections
- [ ] HTML template created following existing patterns
- [ ] CSS styles defined (can use Tailwind + minimal custom)
- [ ] Layout is responsive (mobile, tablet, desktop)
- [ ] Quick actions link to existing analysis pages
- [ ] Placeholder states for loading/empty data
- [ ] Accessibility considerations documented and implemented
