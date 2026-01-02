# Phase 5: Host Comparison - Agent Instructions

## Overview

This phase enables comparative analysis between hosts and configurations. Users can answer: **"How does my system differ from X?"**

**PRD Requirements:**
- Full diff between two hosts
- Scoped diff (by package type/subsystem)
- Package trace comparison
- Comparison UI

---

## Task 5-001: Design Host Comparison Data Structures

### Objective
Define data structures for representing differences between two imports.

### Design Requirements

```python
# Core comparison structures

from dataclasses import dataclass
from enum import Enum

class DiffType(Enum):
    ONLY_LEFT = "only_left"         # Only in left import
    ONLY_RIGHT = "only_right"       # Only in right import
    DIFFERENT_HASH = "different"    # Same label, different derivation
    SAME = "same"                   # Identical in both

@dataclass
class NodeDiff:
    """Represents a node's difference between two imports."""
    label: str
    package_type: str | None
    left_node: Node | None   # Present in left import
    right_node: Node | None  # Present in right import
    diff_type: DiffType

@dataclass
class ImportComparison:
    """Complete comparison between two imports."""
    left_import: ImportInfo
    right_import: ImportInfo
    
    # Summary metrics
    left_only_count: int
    right_only_count: int
    different_count: int
    same_count: int
    
    # Grouped diffs
    diffs_by_type: dict[str, list[NodeDiff]]  # Grouped by package_type
    diffs_by_status: dict[DiffType, list[NodeDiff]]

@dataclass
class ClosureComparison:
    """Comparison of closure sizes and composition."""
    left_total: int
    right_total: int
    difference: int
    percentage_diff: float
    largest_additions: list[NodeDiff]
    largest_removals: list[NodeDiff]
```

### Matching Strategy

```python
def match_nodes(left_nodes: list[Node], right_nodes: list[Node]) -> list[NodeDiff]:
    """
    Match nodes between two imports.
    
    Algorithm:
    1. Build hash → node maps for both sides
    2. Build label → nodes maps for both sides  
    3. For each left node:
       - If hash in right → SAME
       - Elif label in right with different hash → DIFFERENT_HASH
       - Else → ONLY_LEFT
    4. Remaining right nodes → ONLY_RIGHT
    """
    pass
```

### Acceptance Criteria
- [ ] All diff types covered
- [ ] Matching handles duplicates (same label, different hash)
- [ ] Pydantic models created for API responses


### Output Files to Create
- `src/vizzy/models.py` (add comparison models)
- `docs/comparison-data-model.md`

---

## Task 5-002: Implement Cross-Import Diff Algorithm

### Objective
Create efficient algorithm to diff two imports.

### Implementation Steps

1. **Create comparison service**
   ```python
   # src/vizzy/services/comparison.py
   
   from vizzy.database import get_db
   from vizzy.models import Node, NodeDiff, DiffType, ImportComparison
   
   def compare_imports(
       left_import_id: int,
       right_import_id: int
   ) -> ImportComparison:
       """
       Compare two imports and return detailed diff.
       """
       with get_db() as conn:
           with conn.cursor() as cur:
               # Get all nodes from both imports using FULL OUTER JOIN
               cur.execute("""
                   SELECT 
                       COALESCE(l.label, r.label) as label,
                       l.id as left_id,
                       l.drv_hash as left_hash,
                       l.package_type as left_type,
                       l.closure_size as left_closure,
                       r.id as right_id,
                       r.drv_hash as right_hash,
                       r.package_type as right_type,
                       r.closure_size as right_closure
                   FROM nodes l
                   FULL OUTER JOIN nodes r 
                       ON l.label = r.label 
                       AND r.import_id = %s
                   WHERE l.import_id = %s OR r.import_id = %s
                   ORDER BY COALESCE(l.label, r.label)
               """, (right_import_id, left_import_id, right_import_id))
               
               rows = cur.fetchall()
       
       # Process into diffs
       diffs = []
       for row in rows:
           diff_type = classify_diff(
               row['left_hash'], 
               row['right_hash']
           )
           
           diffs.append(NodeDiff(
               label=row['label'],
               package_type=row['left_type'] or row['right_type'],
               left_node=build_node(row, 'left') if row['left_id'] else None,
               right_node=build_node(row, 'right') if row['right_id'] else None,
               diff_type=diff_type,
           ))
       
       return build_comparison_result(left_import_id, right_import_id, diffs)
   
   
   def classify_diff(left_hash: str | None, right_hash: str | None) -> DiffType:
       """Classify the type of difference."""
       if left_hash and right_hash:
           if left_hash == right_hash:
               return DiffType.SAME
           else:
               return DiffType.DIFFERENT_HASH
       elif left_hash:
           return DiffType.ONLY_LEFT
       else:
           return DiffType.ONLY_RIGHT
   ```

2. **Handle duplicate labels**
   ```python
   def compare_with_duplicates(
       left_import_id: int,
       right_import_id: int
   ) -> ImportComparison:
       """
       Handle case where label appears multiple times in one import.
       
       Strategy:
       - Group by label first
       - For each label group, match by hash
       - Report unmatched as additions/removals
       """
       with get_db() as conn:
           with conn.cursor() as cur:
               # Get nodes grouped by label
               cur.execute("""
                   SELECT label, 
                          array_agg(DISTINCT drv_hash) FILTER (WHERE import_id = %s) as left_hashes,
                          array_agg(DISTINCT drv_hash) FILTER (WHERE import_id = %s) as right_hashes
                   FROM nodes
                   WHERE import_id IN (%s, %s)
                   GROUP BY label
               """, (left_import_id, right_import_id, left_import_id, right_import_id))
               
               # Process grouped results
               # ...
   ```

3. **Add comparison caching**
   ```python
   def get_cached_comparison(left_id: int, right_id: int) -> ImportComparison | None:
       """Get cached comparison if exists and still valid."""
       cache_key = f"{min(left_id, right_id)}:{max(left_id, right_id)}"
       
       with get_db() as conn:
           with conn.cursor() as cur:
               cur.execute("""
                   SELECT result
                   FROM analysis
                   WHERE analysis_type = 'comparison'
                     AND result->>'cache_key' = %s
               """, (cache_key,))
               row = cur.fetchone()
               return ImportComparison(**row['result']) if row else None
   ```

### Acceptance Criteria
- [ ] Diff is accurate (verified manually)
- [ ] Handles duplicates correctly
- [ ] Performance <10s for 50k node imports
- [ ] Caching works

### Output Files to Create/Modify
- `src/vizzy/services/comparison.py`


---

## Task 5-003: Build Diff Categorization Service

### Objective
Categorize diffs into meaningful groups for user consumption.

### Implementation Steps

1. **Define category groups**
   ```python
   class DiffCategory(Enum):
       """High-level diff categories for UI."""
       DESKTOP_ENV = "Desktop Environment"
       SYSTEM_SERVICES = "System Services"
       DEVELOPMENT = "Development Tools"
       NETWORKING = "Networking"
       MULTIMEDIA = "Multimedia"
       LIBRARIES = "Core Libraries"
       OTHER = "Other"
   
   CATEGORY_PATTERNS = {
       DiffCategory.DESKTOP_ENV: [
           r"^gnome-", r"^kde-", r"^plasma-", r"^gtk[234]", r"^wayland",
           r"^xorg-", r"^mutter", r"^kwin"
       ],
       DiffCategory.SYSTEM_SERVICES: [
           r"^systemd-", r"-service$", r"^dbus", r"^polkit", r"^udev"
       ],
       DiffCategory.DEVELOPMENT: [
           r"^gcc-", r"^clang-", r"^rustc", r"^cargo", r"^python\d",
           r"^nodejs", r"^go-", r"-dev$"
       ],
       DiffCategory.NETWORKING: [
           r"^networkmanager", r"^wpa_supplicant", r"^iwd",
           r"^curl", r"^wget", r"^openssh"
       ],
       DiffCategory.MULTIMEDIA: [
           r"^pulseaudio", r"^pipewire", r"^alsa-", r"^ffmpeg",
           r"^gstreamer", r"^vlc"
       ],
       DiffCategory.LIBRARIES: [
           r"^glibc", r"^openssl", r"^zlib", r"^libffi", r"^ncurses"
       ],
   }
   ```

2. **Implement categorization**
   ```python
   def categorize_diffs(diffs: list[NodeDiff]) -> dict[DiffCategory, list[NodeDiff]]:
       """Group diffs by semantic category."""
       import re
       
       categorized = {cat: [] for cat in DiffCategory}
       
       for diff in diffs:
           category = DiffCategory.OTHER
           
           for cat, patterns in CATEGORY_PATTERNS.items():
               for pattern in patterns:
                   if re.search(pattern, diff.label, re.IGNORECASE):
                       category = cat
                       break
               if category != DiffCategory.OTHER:
                   break
           
           categorized[category].append(diff)
       
       # Remove empty categories
       return {k: v for k, v in categorized.items() if v}
   ```

3. **Add importance scoring**
   ```python
   def score_diff_importance(diff: NodeDiff) -> float:
       """
       Score how "important" a diff is to the user.
       
       High importance:
       - Top-level packages (is_top_level)
       - Large closure impact
       - User-facing applications
       
       Low importance:
       - Libraries
       - Build-time only
       - Small closure
       """
       score = 0.0
       
       # Check if top-level (requires is_top_level field from Phase 6)
       node = diff.left_node or diff.right_node
       if node and getattr(node, 'is_top_level', False):
           score += 10
       
       if diff.package_type == 'application':
           score += 5
       elif diff.package_type == 'service':
           score += 4
       elif diff.package_type == 'library':
           score -= 2
       
       # Closure impact
       left_closure = diff.left_node.closure_size if diff.left_node else 0
       right_closure = diff.right_node.closure_size if diff.right_node else 0
       closure_impact = abs((left_closure or 0) - (right_closure or 0))
       score += min(closure_impact / 100, 5)  # Cap at 5
       
       return score
   
   
   def sort_diffs_by_importance(diffs: list[NodeDiff]) -> list[NodeDiff]:
       """Sort diffs with most important first."""
       return sorted(diffs, key=score_diff_importance, reverse=True)
   ```

4. **Create summary generator**
   ```python
   def generate_diff_summary(comparison: ImportComparison) -> str:
       """
       Generate human-readable summary.
       
       Example:
       "hostname2 has 7,132 more packages than hostname1.
        Main additions: GNOME Desktop (+2,340), LibreOffice (+1,890).
        Main removals: KDE Plasma (-1,234)."
       """
       diff = comparison.right_import.node_count - comparison.left_import.node_count
       direction = "more" if diff > 0 else "fewer"
       
       # Find largest category changes
       categorized = categorize_diffs(comparison.diffs_by_status[DiffType.ONLY_RIGHT])
       top_additions = sorted(
           [(cat.value, len(diffs)) for cat, diffs in categorized.items()],
           key=lambda x: x[1],
           reverse=True
       )[:3]
       
       summary = f"{comparison.right_import.name} has {abs(diff):,} {direction} packages than {comparison.left_import.name}."
       
       if top_additions:
           additions_str = ", ".join(f"{cat} (+{count})" for cat, count in top_additions)
           summary += f" Main additions: {additions_str}."
       
       return summary
   ```

### Acceptance Criteria
- [ ] Categories are intuitive
- [ ] Important diffs surface first
- [ ] Summary is helpful
- [ ] Handles all edge cases

### Output Files to Create/Modify
- `src/vizzy/services/comparison.py`


---

## Task 5-004: Design Comparison UI Layout

### Objective
Design the user interface for host/import comparison.

### Design Requirements

1. **Comparison Header**
   ```
   ┌─────────────────────────────────────────────────────────────────────┐
   │ Compare Configurations                                              │
   ├─────────────────────────────────────────────────────────────────────┤
   │ ┌─────────────────────┐     VS     ┌─────────────────────┐         │
   │ │ hostname1           │            │ hostname2           │         │
   │ │ 38,102 packages     │            │ 45,234 packages     │         │
   │ │ Imported 2024-01-15 │            │ Imported 2024-01-16 │         │
   │ └─────────────────────┘            └─────────────────────┘         │
   │                                                                     │
   │ Summary: hostname2 has +7,132 packages (+18.7%)                    │
   └─────────────────────────────────────────────────────────────────────┘
   ```

2. **Three-Column Layout**
   ```
   ┌───────────────────┬─────────────────────┬───────────────────────┐
   │ Only in hostname1 │   Shared (37,344)   │  Only in hostname2    │
   │ (758 packages)    │                     │  (7,890 packages)     │
   ├───────────────────┼─────────────────────┼───────────────────────┤
   │                   │ [Collapsed default] │                       │
   │ Desktop Env       │                     │ Desktop Environment   │
   │ ├─ kde-plasma     │                     │ ├─ gnome-shell        │
   │ ├─ kwin           │                     │ ├─ mutter             │
   │ └─ ...            │                     │ └─ ...                │
   │                   │                     │                       │
   │ Development       │                     │ Office                │
   │ ├─ qtcreator      │                     │ ├─ libreoffice        │
   │ └─ ...            │                     │ └─ ...                │
   └───────────────────┴─────────────────────┴───────────────────────┘
   ```

3. **Interactions**
   - Click package → Navigate to node detail (in relevant import)
   - Click category → Expand/collapse
   - Click "Show all" → Modal with full list
   - Swap button → Switch left/right

### Deliverables
- `designs/comparison-ui-spec.md`

### Acceptance Criteria
- [ ] Layout handles large diffs
- [ ] Information hierarchy is clear
- [ ] Mobile-responsive
- [ ] Accessibility considered

### Output Files to Create
- `designs/comparison-ui-spec.md`

---

## Task 5-005: Implement Comparison API Endpoints

### Objective
Create API endpoints for the comparison UI.

### Implementation Steps

1. **Main comparison endpoint**
   ```python
   # src/vizzy/routes/compare.py
   
   from fastapi import APIRouter, Request
   from fastapi.responses import HTMLResponse
   
   router = APIRouter(prefix="/compare")
   
   @router.get("/api/{left_id}/{right_id}")
   async def compare_imports_api(
       left_id: int,
       right_id: int,
       category: str | None = None,
   ):
       """Get comparison data between two imports."""
       comparison = compare_imports(left_id, right_id)
       
       if category:
           # Filter to specific category
           categorized = categorize_diffs(comparison.all_diffs)
           cat_enum = DiffCategory(category)
           return {"diffs": categorized.get(cat_enum, [])}
       
       return comparison
   ```

2. **Category detail endpoint**
   ```python
   @router.get("/api/{left_id}/{right_id}/category/{category}")
   async def compare_category(
       left_id: int,
       right_id: int,
       category: str,
       page: int = 1,
       limit: int = 50
   ):
       """Get paginated diffs for a specific category."""
       comparison = compare_imports(left_id, right_id)
       categorized = categorize_diffs(comparison.all_diffs)
       
       cat_enum = DiffCategory(category)
       diffs = categorized.get(cat_enum, [])
       
       # Paginate
       start = (page - 1) * limit
       end = start + limit
       
       return {
           "diffs": diffs[start:end],
           "total": len(diffs),
           "page": page,
           "pages": (len(diffs) + limit - 1) // limit
       }
   ```

3. **HTMX partial endpoints**
   ```python
   @router.get("/partials/category/{left_id}/{right_id}/{category}")
   async def compare_category_partial(
       request: Request,
       left_id: int,
       right_id: int,
       category: str,
       side: str = "both"  # left, right, both
   ):
       """Return category HTML for HTMX swap."""
       comparison = compare_imports(left_id, right_id)
       categorized = categorize_diffs(comparison.all_diffs)
       
       cat_enum = DiffCategory(category)
       diffs = categorized.get(cat_enum, [])
       
       if side == "left":
           diffs = [d for d in diffs if d.diff_type == DiffType.ONLY_LEFT]
       elif side == "right":
           diffs = [d for d in diffs if d.diff_type == DiffType.ONLY_RIGHT]
       
       return templates.TemplateResponse(
           "partials/compare-category.html",
           {"request": request, "diffs": diffs, "category": category}
       )
   ```

### Acceptance Criteria
- [ ] All endpoints implemented
- [ ] Pagination works
- [ ] Category filtering works
- [ ] HTMX partials work
- [ ] Response time <2s

### Output Files to Create/Modify
- `src/vizzy/routes/compare.py`
- `src/vizzy/main.py` (register router)

---

## Task 5-006: Build Comparison Frontend Component

### Objective
Implement the comparison UI using HTMX and Jinja2.

### Implementation Steps

1. **Create comparison select page**
   ```html
   <!-- src/vizzy/templates/compare-select.html -->
   {% extends "base.html" %}
   
   {% block title %}Compare Configurations - Vizzy{% endblock %}
   
   {% block content %}
   <div class="max-w-2xl mx-auto">
       <h1 class="text-2xl font-bold mb-6">Compare Configurations</h1>
       
       <form action="/compare" method="GET" class="space-y-6">
           <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
               <div>
                   <label class="block text-sm font-medium mb-2">First configuration:</label>
                   <select name="left" required
                           class="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                       {% for imp in imports %}
                       <option value="{{ imp.id }}">
                           {{ imp.name }} ({{ imp.node_count | default(0) }} packages)
                       </option>
                       {% endfor %}
                   </select>
               </div>
               
               <div>
                   <label class="block text-sm font-medium mb-2">Second configuration:</label>
                   <select name="right" required
                           class="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500">
                       {% for imp in imports %}
                       <option value="{{ imp.id }}" {% if loop.index == 2 %}selected{% endif %}>
                           {{ imp.name }} ({{ imp.node_count | default(0) }} packages)
                       </option>
                       {% endfor %}
                   </select>
               </div>
           </div>
           
           <button type="submit" 
                   class="w-full py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
               Compare
           </button>
       </form>
   </div>
   {% endblock %}
   ```

2. **Create comparison result page**
   ```html
   <!-- src/vizzy/templates/compare.html -->
   {% extends "base.html" %}
   
   {% block title %}{{ left.name }} vs {{ right.name }} - Vizzy{% endblock %}
   
   {% block content %}
   <div class="comparison-container">
       <!-- Header -->
       <header class="flex items-center justify-center gap-8 mb-6">
           <div class="text-center p-4 bg-white rounded-lg shadow">
               <h2 class="font-bold text-lg">{{ left.name }}</h2>
               <p class="text-slate-500">{{ left.node_count | default(0) | number_format }} packages</p>
           </div>
           <span class="text-2xl font-bold text-slate-400">VS</span>
           <div class="text-center p-4 bg-white rounded-lg shadow">
               <h2 class="font-bold text-lg">{{ right.name }}</h2>
               <p class="text-slate-500">{{ right.node_count | default(0) | number_format }} packages</p>
           </div>
       </header>
       
       <p class="text-center text-slate-600 mb-6">{{ summary }}</p>
       
       <!-- Three columns -->
       <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
           <!-- Only Left -->
           <section class="bg-white rounded-lg shadow p-4 border-l-4 border-red-400">
               <h3 class="font-semibold mb-4">
                   Only in {{ left.name }}
                   <span class="text-slate-400 font-normal">({{ left_only_count }})</span>
               </h3>
               <div id="left-categories" class="space-y-2">
                   {% for category, diffs in left_by_category.items() %}
                   <div class="category-group">
                       <button class="w-full flex justify-between items-center p-2 hover:bg-slate-50 rounded"
                               hx-get="/compare/partials/category/{{ left.id }}/{{ right.id }}/{{ category.value }}?side=left"
                               hx-target="#left-{{ category.name }}-content"
                               hx-swap="innerHTML"
                               hx-trigger="click once">
                           <span>{{ category.value }}</span>
                           <span class="text-slate-400">{{ diffs | length }}</span>
                       </button>
                       <div id="left-{{ category.name }}-content"></div>
                   </div>
                   {% endfor %}
               </div>
           </section>
           
           <!-- Shared -->
           <section class="bg-white rounded-lg shadow p-4">
               <h3 class="font-semibold mb-4">
                   Shared
                   <span class="text-slate-400 font-normal">({{ same_count }})</span>
               </h3>
               <div class="text-sm text-slate-500 mb-4">
                   <span class="text-amber-600 font-medium">{{ different_count }}</span> 
                   packages have different versions
               </div>
               <button class="text-blue-600 hover:underline text-sm"
                       hx-get="/compare/partials/versions/{{ left.id }}/{{ right.id }}"
                       hx-target="#version-diffs"
                       hx-swap="innerHTML">
                   Show version differences
               </button>
               <div id="version-diffs" class="mt-4"></div>
           </section>
           
           <!-- Only Right -->
           <section class="bg-white rounded-lg shadow p-4 border-l-4 border-green-400">
               <h3 class="font-semibold mb-4">
                   Only in {{ right.name }}
                   <span class="text-slate-400 font-normal">({{ right_only_count }})</span>
               </h3>
               <div id="right-categories" class="space-y-2">
                   {% for category, diffs in right_by_category.items() %}
                   <div class="category-group">
                       <button class="w-full flex justify-between items-center p-2 hover:bg-slate-50 rounded"
                               hx-get="/compare/partials/category/{{ left.id }}/{{ right.id }}/{{ category.value }}?side=right"
                               hx-target="#right-{{ category.name }}-content"
                               hx-swap="innerHTML"
                               hx-trigger="click once">
                           <span>{{ category.value }}</span>
                           <span class="text-slate-400">{{ diffs | length }}</span>
                       </button>
                       <div id="right-{{ category.name }}-content"></div>
                   </div>
                   {% endfor %}
               </div>
           </section>
       </div>
   </div>
   {% endblock %}
   ```

3. **Add route handler**
   ```python
   # src/vizzy/routes/compare.py
   
   @router.get("", response_class=HTMLResponse)
   async def compare_page(
       request: Request,
       left: int | None = None,
       right: int | None = None
   ):
       """Comparison page - shows selector or results."""
       imports = graph_service.get_imports()
       
       if left and right and left != right:
           left_import = graph_service.get_import(left)
           right_import = graph_service.get_import(right)
           
           if not left_import or not right_import:
               return HTMLResponse("Import not found", status_code=404)
           
           comparison = compare_imports(left, right)
           summary = generate_diff_summary(comparison)
           
           # Group by category for each side
           left_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_LEFT]
           right_diffs = [d for d in comparison.all_diffs if d.diff_type == DiffType.ONLY_RIGHT]
           
           return templates.TemplateResponse("compare.html", {
               "request": request,
               "left": left_import,
               "right": right_import,
               "summary": summary,
               "left_only_count": comparison.left_only_count,
               "right_only_count": comparison.right_only_count,
               "same_count": comparison.same_count,
               "different_count": comparison.different_count,
               "left_by_category": categorize_diffs(left_diffs),
               "right_by_category": categorize_diffs(right_diffs),
           })
       
       return templates.TemplateResponse("compare-select.html", {
           "request": request,
           "imports": imports,
       })
   ```

### Acceptance Criteria
- [ ] Selection page works
- [ ] Comparison renders correctly
- [ ] HTMX expansion works
- [ ] Categories are clickable
- [ ] Responsive layout

### Output Files to Create/Modify
- `src/vizzy/templates/compare-select.html`
- `src/vizzy/templates/compare.html`
- `src/vizzy/templates/partials/compare-category.html`
- `src/vizzy/routes/compare.py`

---

## Task 5-007: Add Semantic Diff Grouping

### Objective
Group diffs by what they represent semantically, not just by package type.

### Implementation
See Task 5-003 for `categorize_diffs()` - this task extends it with better semantic grouping and UI integration.

### Acceptance Criteria
- [ ] Semantic groups are intuitive
- [ ] Net change shown per group
- [ ] UI highlights important changes

---

## Task 5-008: Implement Version Difference Detection

### Objective
Detect when the same package exists in both imports but with different versions.

### Implementation Steps

1. **Parse version from label**
   ```python
   import re
   
   def extract_version(label: str) -> tuple[str, str | None]:
       """
       Extract package name and version from label.
       
       Examples:
       - "openssl-3.0.12" → ("openssl", "3.0.12")
       - "glibc-2.40-66" → ("glibc", "2.40-66")
       - "bootstrap-tools" → ("bootstrap-tools", None)
       """
       match = re.match(r'^(.+?)-(\d+[\d.]*(?:-\d+)?)$', label)
       if match:
           return match.group(1), match.group(2)
       return label, None
   ```

2. **Create version diff model**
   ```python
   @dataclass
   class VersionDiff:
       package_name: str
       left_version: str
       right_version: str
       left_node_id: int
       right_node_id: int
       change_type: str  # 'upgrade', 'downgrade', 'rebuild'
   ```

3. **Detect changes**
   ```python
   def detect_version_changes(
       left_import_id: int,
       right_import_id: int
   ) -> list[VersionDiff]:
       """Find packages with different versions."""
       comparison = compare_imports(left_import_id, right_import_id)
       
       version_diffs = []
       for diff in comparison.all_diffs:
           if diff.diff_type == DiffType.DIFFERENT_HASH:
               left_name, left_ver = extract_version(diff.left_node.label)
               right_name, right_ver = extract_version(diff.right_node.label)
               
               if left_ver and right_ver:
                   change = classify_version_change(left_ver, right_ver)
                   version_diffs.append(VersionDiff(
                       package_name=left_name,
                       left_version=left_ver,
                       right_version=right_ver,
                       left_node_id=diff.left_node.id,
                       right_node_id=diff.right_node.id,
                       change_type=change,
                   ))
       
       return version_diffs
   ```

### Acceptance Criteria
- [ ] Version extraction works
- [ ] Change type classification accurate
- [ ] UI shows version changes clearly

---

## Task 5-009: Create Comparison Report Export

### Objective
Allow users to export comparison results.

### Implementation Steps

1. **Markdown export**
   ```python
   def comparison_to_markdown(comparison: ImportComparison) -> str:
       """Generate markdown report."""
       lines = [
           f"# Configuration Comparison",
           f"",
           f"## Summary",
           f"- **{comparison.left_import.name}**: {comparison.left_import.node_count:,} packages",
           f"- **{comparison.right_import.name}**: {comparison.right_import.node_count:,} packages",
           f"",
           f"## Only in {comparison.left_import.name} ({comparison.left_only_count})",
       ]
       # Add categorized diffs...
       return "\n".join(lines)
   ```

2. **Export endpoint**
   ```python
   @router.get("/api/{left_id}/{right_id}/export")
   async def export_comparison(
       left_id: int,
       right_id: int,
       format: str = "markdown"
   ):
       comparison = compare_imports(left_id, right_id)
       
       if format == "markdown":
           content = comparison_to_markdown(comparison)
           return Response(
               content=content,
               media_type="text/markdown",
               headers={"Content-Disposition": "attachment; filename=comparison.md"}
           )
   ```

### Acceptance Criteria
- [ ] Markdown export works
- [ ] JSON export works
- [ ] Download triggers correctly

---

## Task 5-010: Implement Package Trace Comparison

### Objective
Show how the same package arrives via different dependency paths in two configs.

### Implementation

```python
def compare_package_traces(
   left_import_id: int,
   right_import_id: int,
   package_label: str
) -> dict:
   """
   Compare how a package is reached in two configurations.
   
   Returns:
   {
       "package": "ripgrep",
       "left_paths": [
           ["system-path", "user-packages", "ripgrep"]
       ],
       "right_paths": [
           ["system-path", "home-manager", "ripgrep"]
       ]
   }
   """
   pass
```

### Acceptance Criteria
- [ ] Traces show different paths
- [ ] UI displays paths clearly
- [ ] Handles packages in only one config

---

## Phase 5 Completion Checklist

- [ ] 5-001: Data structures defined
- [ ] 5-002: Diff algorithm implemented
- [ ] 5-003: Categorization service built
- [ ] 5-004: UI design documented
- [ ] 5-005: API endpoints created
- [ ] 5-006: Frontend implemented
- [ ] 5-007: Semantic grouping added
- [ ] 5-008: Version detection working
- [ ] 5-009: Export functionality complete
- [ ] 5-010: Package trace comparison implemented
- [ ] Compare link added to navigation
