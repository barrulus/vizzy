# Variant Matrix Design Specification

## Overview

The Variant Matrix provides an enhanced duplicate visualization showing which applications use which variants of duplicated packages, answering the question: "Which of my applications are using which versions of this duplicated package?"

This visualization builds upon the existing duplicate detection (`find_duplicates`) and comparison (`compare_duplicates`) functionality, presenting the data in a matrix format that makes cross-cutting concerns immediately visible.

## Design Goals

1. **Clear variant mapping**: Show at a glance which applications depend on which package variants
2. **Actionable insights**: Highlight consolidation opportunities and potential conflicts
3. **Scalable**: Handle packages with up to 20 variants without layout degradation
4. **Integration**: Accessible from the existing duplicates analysis page
5. **Consistent**: Follows existing Vizzy UI patterns (Tailwind CSS, HTMX)
6. **Performance**: Load matrix data efficiently even for packages with many dependents

## User Questions Answered

- "Which of my applications are using which openssl variant?"
- "Can I consolidate these duplicate packages?"
- "Why do I have multiple versions of the same library?"
- "Which variant is used by the most applications?"
- "Are there applications that use multiple variants of the same package?"

## Layout Structure

### Main Matrix View

```
+-----------------------------------------------------------------------+
|                           Navigation Bar                                |
|  [Vizzy]                    [Search...]                     [? Help]    |
+-----------------------------------------------------------------------+
|                                                                         |
|  [Breadcrumb: Home > hostname-config > Duplicates > openssl]            |
|                                                                         |
|  +-------------------------------------------------------------------+ |
|  | openssl (3 variants)                    [Sort: Dependents v] [<>]  | |
|  +-------------------------------------------------------------------+ |
|  |                                                                     | |
|  |                 | 3.0.12      | 3.0.12      | 1.1.1w      |        | |
|  |                 | (abc123...)  | (def456...)  | (ghi789...)  |        | |
|  |                 | runtime     | static      | legacy      |        | |
|  | ----------------+-------------+-------------+-------------+        | |
|  | firefox         |      *      |             |             |        | |
|  | curl            |      *      |             |             |        | |
|  | thunderbird     |      *      |             |             |        | |
|  | rustc           |             |      *      |             |        | |
|  | cargo           |             |      *      |             |        | |
|  | python-crypto   |             |             |      *      |        | |
|  | ----------------+-------------+-------------+-------------+        | |
|  | Dependents:     |     12      |      5      |      3      |        | |
|  | Closure size:   |   2,340     |   1,890     |   1,567     |        | |
|  +-------------------------------------------------------------------+ |
|                                                                         |
|  +-------------------------------------------------------------------+ |
|  | Legend                                                              | |
|  | * Direct dependency    + Transitive dependency    - Not used       | |
|  +-------------------------------------------------------------------+ |
|  |                                                                     | |
|  | [View Sankey] [Compare Variants] [Why Chain]                        | |
|  +-------------------------------------------------------------------+ |
+-----------------------------------------------------------------------+
```

### Compact Matrix View (for narrow screens or many variants)

```
+-----------------------------------------------------------------------+
| openssl Variant Matrix                                                  |
+-----------------------------------------------------------------------+
|        | v1    | v2    | v3    | v4    | v5    | ...   | v20   |       |
| -------+-------+-------+-------+-------+-------+-------+-------+       |
| app1   |   *   |       |       |       |       |       |       |       |
| app2   |   *   |   *   |       |       |       |       |       |       |
| app3   |       |   *   |       |       |       |       |       |       |
| ...    |       |       |   *   |       |       |       |       |       |
| -------+-------+-------+-------+-------+-------+-------+-------+       |
| Count  |  12   |   8   |   5   |   3   |   2   |   1   |   1   |       |
+-----------------------------------------------------------------------+
```

## Component Specifications

### 1. Header Section

Contains package information and controls.

#### Elements
- **Package Label**: Bold package name with variant count badge
- **Sort Dropdown**: Control column ordering
  - By dependents (descending) - default
  - By closure size (descending)
  - By hash (alphabetical)
- **Expand/Collapse Toggle**: Switch between full and compact views

#### Implementation
```html
<div class="flex items-center justify-between mb-4">
    <div class="flex items-center gap-3">
        <h1 class="text-2xl font-bold">{{ label }}</h1>
        <span class="px-2 py-0.5 bg-slate-200 rounded text-sm">
            {{ variants | length }} variants
        </span>
    </div>
    <div class="flex items-center gap-3">
        <select id="sort" class="border rounded p-2 text-sm">
            <option value="dependents">Sort: Dependents</option>
            <option value="closure">Sort: Closure Size</option>
            <option value="hash">Sort: Hash</option>
        </select>
        <button id="toggle-view" class="p-2 border rounded hover:bg-slate-100">
            <svg>...</svg>
        </button>
    </div>
</div>
```

### 2. Variant Column Headers

Each column represents one variant of the duplicated package.

#### Elements
- **Short Hash**: First 8 characters of derivation hash
- **Version Label**: Extracted version if parseable, or classification
- **Classification Badge**: runtime/build-time/static/legacy indicator
- **Click Action**: Navigate to node detail page

#### Data Extraction
```python
def extract_variant_info(node: Node) -> dict:
    """Extract display information for a variant."""
    import re

    # Try to extract version from label
    version_match = re.search(r'-(\d+\.\d+(?:\.\d+)?)', node.label)
    version = version_match.group(1) if version_match else None

    # Classify based on dependencies (from compare_duplicates)
    classification = "runtime"  # default
    if node.metadata and node.metadata.get("is_build_time"):
        classification = "build-time"

    return {
        "node_id": node.id,
        "hash": node.drv_hash[:8],
        "full_hash": node.drv_hash,
        "version": version,
        "classification": classification,
        "closure_size": node.closure_size or 0,
    }
```

### 3. Application Rows

Each row represents an application (or direct dependent) that uses one or more variants.

#### Elements
- **Application Name**: Package label (truncated with tooltip if needed)
- **Dependency Cells**: Indicator for each variant column
  - `*` or filled circle: Direct dependency
  - `+` or hollow circle: Transitive dependency (optional)
  - Empty: No dependency
- **Row Hover**: Highlight entire row for clarity
- **Click Action**: Navigate to application node detail

#### Row Filtering
By default, show only:
1. Top-level packages (is_top_level = TRUE)
2. Applications (package_type = 'application')
3. Direct dependents of any variant

Option to expand to show all dependents (may be large).

### 4. Summary Row

Aggregate statistics at the bottom of the matrix.

#### Elements
| Metric | Description | Display |
|--------|-------------|---------|
| Dependents | Count of direct dependents | Integer |
| Closure Size | Closure size of this variant | Formatted number |
| Top-level Users | Count of top-level packages using this variant | Integer |

### 5. Legend

Explains the matrix symbols.

#### Symbols
| Symbol | Meaning | Color |
|--------|---------|-------|
| `*` or filled circle | Direct dependency | green-500 |
| `+` or hollow circle | Transitive dependency | blue-400 |
| Empty | Not a dependency | - |

### 6. Action Buttons

Navigation to related views.

#### Buttons
| Action | Label | Link |
|--------|-------|------|
| View Sankey | "View Sankey" | /analyze/sankey/{import_id}/{label} |
| Compare Variants | "Compare Variants" | /analyze/compare/{import_id}/{label} |
| Why Chain | "Why Chain" | /why-chain?node={first_variant_id} |

## Data Model

### API Endpoint

**URL**: `GET /api/matrix/{import_id}/{label}`

**Response Schema**:
```json
{
    "label": "openssl",
    "variant_count": 3,
    "variants": [
        {
            "node_id": 123,
            "hash": "abc12345",
            "full_hash": "abc12345678901234567890123456789012",
            "version": "3.0.12",
            "classification": "runtime",
            "closure_size": 2340,
            "dependent_count": 12
        }
    ],
    "applications": [
        {
            "node_id": 456,
            "label": "firefox",
            "package_type": "application",
            "is_top_level": true,
            "uses_variants": [123],
            "dependency_type": {
                "123": "direct"
            }
        }
    ],
    "summary": {
        "total_applications": 20,
        "multi_variant_apps": 2,
        "consolidation_potential": "high"
    }
}
```

### Service Implementation

```python
# src/vizzy/services/variant_matrix.py

from dataclasses import dataclass
from vizzy.database import get_db
from vizzy.models import Node

@dataclass
class VariantInfo:
    node_id: int
    hash: str
    full_hash: str
    version: str | None
    classification: str
    closure_size: int
    dependent_count: int

@dataclass
class ApplicationRow:
    node_id: int
    label: str
    package_type: str | None
    is_top_level: bool
    uses_variants: list[int]  # List of variant node_ids
    dependency_types: dict[int, str]  # node_id -> "direct" or "transitive"

@dataclass
class VariantMatrix:
    label: str
    variants: list[VariantInfo]
    applications: list[ApplicationRow]
    summary: dict

def build_variant_matrix(
    import_id: int,
    label: str,
    max_applications: int = 50,
    include_transitive: bool = False
) -> VariantMatrix:
    """Build matrix data for a duplicated package."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all variants
            cur.execute("""
                SELECT id, drv_hash, label, package_type, closure_size, metadata
                FROM nodes
                WHERE import_id = %s AND label = %s
                ORDER BY closure_size DESC NULLS LAST
            """, (import_id, label))
            variants_raw = cur.fetchall()

            if not variants_raw:
                return VariantMatrix(
                    label=label,
                    variants=[],
                    applications=[],
                    summary={}
                )

            # Build variant info
            variants = []
            variant_ids = []
            for row in variants_raw:
                variant_ids.append(row['id'])

                # Get dependent count
                cur.execute("""
                    SELECT COUNT(DISTINCT target_id)
                    FROM edges
                    WHERE source_id = %s
                """, (row['id'],))
                dep_count = cur.fetchone()[0]

                variants.append(VariantInfo(
                    node_id=row['id'],
                    hash=row['drv_hash'][:8],
                    full_hash=row['drv_hash'],
                    version=_extract_version(row['label']),
                    classification=_classify_variant(row),
                    closure_size=row['closure_size'] or 0,
                    dependent_count=dep_count,
                ))

            # Get applications that use these variants
            cur.execute("""
                SELECT DISTINCT n.id, n.label, n.package_type, n.is_top_level,
                       e.source_id as variant_id
                FROM edges e
                JOIN nodes n ON e.target_id = n.id
                WHERE e.source_id = ANY(%s)
                ORDER BY n.is_top_level DESC, n.label
                LIMIT %s
            """, (variant_ids, max_applications))

            app_map: dict[int, ApplicationRow] = {}
            for row in cur.fetchall():
                app_id = row['id']
                variant_id = row['variant_id']

                if app_id not in app_map:
                    app_map[app_id] = ApplicationRow(
                        node_id=app_id,
                        label=row['label'],
                        package_type=row['package_type'],
                        is_top_level=row['is_top_level'] or False,
                        uses_variants=[],
                        dependency_types={},
                    )

                app_map[app_id].uses_variants.append(variant_id)
                app_map[app_id].dependency_types[variant_id] = "direct"

            applications = list(app_map.values())

            # Sort applications: top-level first, then by name
            applications.sort(key=lambda a: (not a.is_top_level, a.label))

            # Build summary
            multi_variant = sum(1 for a in applications if len(a.uses_variants) > 1)
            summary = {
                "total_applications": len(applications),
                "multi_variant_apps": multi_variant,
                "consolidation_potential": _assess_consolidation(variants, applications),
            }

            return VariantMatrix(
                label=label,
                variants=variants,
                applications=applications,
                summary=summary,
            )


def _extract_version(label: str) -> str | None:
    """Extract version number from package label."""
    import re
    match = re.search(r'-(\d+\.\d+(?:\.\d+)?(?:[.-]\w+)?)', label)
    return match.group(1) if match else None


def _classify_variant(row: dict) -> str:
    """Classify variant as runtime, build-time, static, etc."""
    metadata = row.get('metadata') or {}

    if metadata.get('is_build_time'):
        return 'build-time'
    if 'static' in row['drv_hash'] or '-static' in (row['label'] or ''):
        return 'static'

    return 'runtime'


def _assess_consolidation(variants: list[VariantInfo], apps: list[ApplicationRow]) -> str:
    """Assess potential for variant consolidation."""
    if len(variants) <= 1:
        return "none"

    # If most apps use the same variant, high consolidation potential
    variant_usage = {v.node_id: 0 for v in variants}
    for app in apps:
        for vid in app.uses_variants:
            variant_usage[vid] = variant_usage.get(vid, 0) + 1

    max_usage = max(variant_usage.values()) if variant_usage else 0
    total_apps = len(apps)

    if total_apps == 0:
        return "unknown"

    ratio = max_usage / total_apps

    if ratio > 0.8:
        return "high"
    elif ratio > 0.5:
        return "medium"
    else:
        return "low"
```

## Responsive Design

### Desktop (>= 1024px)
- Full matrix with all columns visible
- Horizontal scrolling if >10 variants
- Sticky first column (application names)
- Full action button bar

### Tablet (768px - 1023px)
- Compact matrix headers (hash only, tooltip for full info)
- Horizontal scrolling with shadow indicators
- Sticky first column
- Buttons wrap to 2 rows

### Mobile (< 768px)
- Switch to card-based view per variant
- Each card shows: variant hash, version, list of applications
- Swipe between variants
- Alternative: Vertical matrix with transposed layout

### Implementation
```css
/* Sticky first column */
.matrix-container {
    overflow-x: auto;
}

.matrix-table th:first-child,
.matrix-table td:first-child {
    position: sticky;
    left: 0;
    background: white;
    z-index: 1;
    box-shadow: 2px 0 4px rgba(0,0,0,0.1);
}

/* Scroll shadow indicators */
.matrix-container::after {
    content: '';
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: 20px;
    background: linear-gradient(to left, rgba(0,0,0,0.1), transparent);
    pointer-events: none;
}
```

## HTMX Integration

### Initial Load
```html
<div id="matrix-container"
     hx-get="/api/matrix/{{ import_id }}/{{ label }}"
     hx-trigger="load"
     hx-swap="innerHTML">
    <div class="animate-pulse">
        <!-- Skeleton loader -->
    </div>
</div>
```

### Sort Change
```html
<select hx-get="/api/matrix/{{ import_id }}/{{ label }}"
        hx-include="[name='sort']"
        hx-trigger="change"
        hx-target="#matrix-body"
        hx-swap="innerHTML"
        name="sort">
    <option value="dependents">Sort: Dependents</option>
    <option value="closure">Sort: Closure Size</option>
</select>
```

### Expand Applications
```html
<button hx-get="/api/matrix/{{ import_id }}/{{ label }}?expand=true"
        hx-target="#matrix-body"
        hx-swap="innerHTML">
    Show all applications
</button>
```

## Accessibility

### Requirements
- Table uses proper `<table>`, `<thead>`, `<tbody>` elements
- Column and row headers use `<th>` with `scope` attribute
- Matrix cells have `aria-label` describing the relationship
- Keyboard navigation: Tab through cells, Enter to navigate
- Color is not the sole indicator (icons + text)
- Focus visible on all interactive elements

### Implementation
```html
<table class="variant-matrix" role="grid" aria-label="Variant dependency matrix">
    <thead>
        <tr>
            <th scope="col" class="sr-only">Application</th>
            <th scope="col" aria-label="openssl version 3.0.12, hash abc12345">
                <span aria-hidden="true">abc12345</span>
                <span class="sr-only">openssl 3.0.12</span>
            </th>
            <!-- ... more columns -->
        </tr>
    </thead>
    <tbody>
        <tr>
            <th scope="row">firefox</th>
            <td aria-label="firefox directly depends on openssl abc12345">
                <span class="text-green-500" aria-hidden="true">*</span>
            </td>
            <td aria-label="firefox does not depend on openssl def45678">
                <span class="sr-only">No dependency</span>
            </td>
            <!-- ... more cells -->
        </tr>
    </tbody>
</table>
```

## Keyboard Navigation

| Key | Action |
|-----|--------|
| `Tab` | Move focus between interactive elements |
| `Arrow keys` | Navigate within matrix cells |
| `Enter` | Navigate to focused node detail |
| `Escape` | Return to duplicates list |
| `?` | Show keyboard help |

## Performance Considerations

### Server-Side
- Limit default application list to 50 (configurable)
- Pre-compute variant classifications at import time
- Cache matrix data (5 minute TTL)
- Index on edges(source_id, target_id)

### Client-Side
- Use `content-visibility: auto` for off-screen rows
- Lazy load additional applications on scroll
- Debounce sort changes (300ms)
- Use CSS transforms for hover effects (GPU accelerated)

### Performance Targets
| Metric | Target |
|--------|--------|
| API response (20 variants) | < 500ms |
| Initial render (50 apps) | < 200ms |
| Sort change | < 100ms |
| Memory usage | < 5MB per matrix |

## URL State Management

### URL Pattern
```
/analyze/matrix/{import_id}/{label}?sort=dependents&expand=false
```

### Parameters
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| sort | string | "dependents" | Sort order for columns |
| expand | boolean | false | Show all applications |

### History Integration
- Sort changes update URL without page reload
- Browser back button restores previous sort
- Matrix is bookmarkable/shareable

## Error States

### No Variants Found
```
+---------------------------------------+
|                                       |
|   Package "openssl" not found or      |
|   has no duplicate variants.          |
|                                       |
|   [Back to Duplicates]                |
|                                       |
+---------------------------------------+
```

### API Error
```
+---------------------------------------+
|                                       |
|   Failed to load matrix data.         |
|   [Retry]                             |
|                                       |
+---------------------------------------+
```

### Many Variants (>20)
```
+---------------------------------------+
|                                       |
|   This package has 47 variants.       |
|   Showing top 20 by dependent count.  |
|                                       |
|   [Show All]  [Download CSV]          |
|                                       |
+---------------------------------------+
```

## Integration Points

### From Duplicates Page
Add "View Matrix" button next to each duplicate group:
```html
<!-- In duplicates.html -->
<div class="mt-3 flex gap-2">
    <a href="/analyze/matrix/{{ import_info.id }}/{{ group.label }}"
       class="text-sm text-blue-600 hover:text-blue-800">
        View Matrix
    </a>
    <a href="/analyze/compare/{{ import_info.id }}/{{ group.label }}"
       class="text-sm text-blue-600 hover:text-blue-800">
        Compare Variants
    </a>
</div>
```

### To Node Detail
Matrix cells link to node detail:
```html
<td>
    <a href="/graph/node/{{ variant.node_id }}"
       class="text-green-500 hover:text-green-700">*</a>
</td>
```

### To Why Chain
"Why Chain" button passes variant node:
```html
<a href="/why-chain/{{ variants[0].node_id }}"
   class="px-4 py-2 bg-slate-100 rounded">
    Why Chain
</a>
```

## File Deliverables

### This Task (8D-001)
- `designs/variant-matrix-spec.md` (this file)

### Subsequent Tasks
- `src/vizzy/services/variant_matrix.py` - Data service (8D-002)
- `src/vizzy/routes/analyze.py` - API endpoint updates (8D-002)
- `src/vizzy/templates/analyze/matrix.html` - HTML template (8D-003)
- `static/css/matrix.css` - Component styles (8D-003)

## Design Decisions

### Why matrix format instead of list?
- Matrix reveals cross-cutting relationships at a glance
- Easier to spot applications using multiple variants
- More compact than listing dependencies per variant

### Why limit to 20 variants by default?
- Wide matrices cause usability issues
- 20 columns fits most screens with horizontal scroll
- Packages with >20 variants are rare edge cases
- Full data available via download

### Why prioritize top-level packages?
- Users care most about their explicitly installed packages
- Transitive dependents are less actionable
- Reduces initial data load

### Why separate from existing Sankey view?
- Different use case: matrix shows categorical relationships, Sankey shows flow
- Matrix better for answering "who uses what"
- Sankey better for answering "how does it flow"
- Complementary visualizations

### Why include consolidation assessment?
- Answers "should I try to reduce these variants?"
- Provides actionable guidance without requiring deep analysis
- Simple heuristic is useful starting point

## Mockups

### Full Matrix View

```
+-----------------------------------------------------------------------+
| Home > workstation > Duplicates > openssl                              |
+-----------------------------------------------------------------------+
| openssl (3 variants)                          [Sort: Dependents v]     |
+-----------------------------------------------------------------------+
|                | 3.0.12        | 3.0.12        | 1.1.1w        |      |
|                | abc12345      | def45678      | ghi78901      |      |
|                | runtime       | static        | legacy        |      |
+----------------+---------------+---------------+---------------+      |
| firefox        |       *       |               |               |      |
| thunderbird    |       *       |               |               |      |
| curl           |       *       |               |               |      |
| wget           |       *       |               |               |      |
| rustc          |               |       *       |               |      |
| cargo          |               |       *       |               |      |
| python-crypto  |               |               |       *       |      |
| openssl-compat |               |               |       *       |      |
+----------------+---------------+---------------+---------------+      |
| Dependents     |      12       |       5       |       3       |      |
| Closure Size   |    2,340      |    1,890      |    1,567      |      |
+-----------------------------------------------------------------------+
| Legend: * Direct dependency                                            |
+-----------------------------------------------------------------------+
| [View Sankey]  [Compare Variants]  [Why Chain]                         |
+-----------------------------------------------------------------------+
```

### Mobile Card View

```
+---------------------------+
| openssl (3 variants)       |
| [< v1] [v2] [v3 >]         |
+---------------------------+
| 3.0.12 (abc12345)          |
| runtime                    |
| --------------------------  |
| 12 dependents              |
| 2,340 closure size         |
| --------------------------  |
| Used by:                   |
| * firefox                  |
| * thunderbird              |
| * curl                     |
| * wget                     |
| + 8 more                   |
+---------------------------+
| [View Sankey] [Compare]    |
+---------------------------+
```

## Acceptance Criteria

- [x] Design document complete with all sections
- [x] Matrix layout handles up to 20 variants
- [x] Application rows prioritize top-level packages
- [x] Responsive design specified for mobile/tablet/desktop
- [x] Integration with existing duplicates page documented
- [x] API endpoint schema defined
- [x] Accessibility requirements documented
- [x] URL state management specified
- [x] Performance targets defined
- [x] Error states designed
- [x] Action buttons link to related views
