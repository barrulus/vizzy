# Comparison Data Model

This document describes the data structures used for comparing two imported NixOS configurations in Vizzy.

## Overview

The comparison system enables users to understand how two NixOS configurations differ. It answers questions like:
- What packages are unique to each configuration?
- Which packages have different versions/derivations?
- What is the closure size impact of the differences?

## Core Types

### DiffType Enum

Represents the relationship between a node in two imports:

```python
class DiffType(str, Enum):
    ONLY_LEFT = "only_left"      # Node exists only in the left import
    ONLY_RIGHT = "only_right"    # Node exists only in the right import
    DIFFERENT_HASH = "different" # Same label, different derivation hash
    SAME = "same"                # Identical in both imports (same hash)
```

### NodeDiff

Represents a single node's comparison result between two imports:

```python
class NodeDiff(BaseModel):
    label: str                    # Package label (e.g., "openssl-3.0.12")
    package_type: str | None      # Classification (app, lib, service, etc.)
    left_node: Node | None        # Node from left import (None if ONLY_RIGHT)
    right_node: Node | None       # Node from right import (None if ONLY_LEFT)
    diff_type: DiffType           # Type of difference

    @computed_field
    def closure_impact(self) -> int:
        """Returns right_closure - left_closure (positive means growth)"""
```

### ImportComparison

Complete comparison result between two imports:

```python
class ImportComparison(BaseModel):
    left_import: ImportInfo       # Metadata about left import
    right_import: ImportInfo      # Metadata about right import

    # Summary metrics
    left_only_count: int          # Nodes unique to left
    right_only_count: int         # Nodes unique to right
    different_count: int          # Nodes with same label but different hash
    same_count: int               # Identical nodes

    # Full diff list
    all_diffs: list[NodeDiff]     # All comparison results

    @computed_field
    def total_nodes_compared(self) -> int:
        """Total unique labels compared"""

    @computed_field
    def net_package_change(self) -> int:
        """right_only - left_only (positive means right has more)"""

    def get_diffs_by_type(self, diff_type: DiffType) -> list[NodeDiff]:
        """Filter diffs by their type"""

    def get_diffs_by_package_type(self, package_type: str) -> list[NodeDiff]:
        """Filter diffs by package classification"""
```

### ClosureComparison

Analyzes closure size differences between imports:

```python
class ClosureComparison(BaseModel):
    left_total: int               # Total closure size of left import
    right_total: int              # Total closure size of right import

    @computed_field
    def difference(self) -> int:
        """right_total - left_total"""

    @computed_field
    def percentage_diff(self) -> float:
        """Percentage change relative to left"""

    largest_additions: list[NodeDiff]  # Biggest new packages (by closure)
    largest_removals: list[NodeDiff]   # Biggest removed packages (by closure)
```

## Matching Algorithm

The comparison system uses a two-phase matching algorithm:

### Phase 1: Hash-Based Matching
Nodes are first matched by their derivation hash (`drv_hash`). If two nodes have the same hash, they are identical derivations and marked as `SAME`.

### Phase 2: Label-Based Matching
For nodes not matched by hash, the system matches by label. If nodes share a label but have different hashes, they represent the same package with different versions/builds and are marked as `DIFFERENT_HASH`.

### Handling Duplicates

When the same label appears multiple times within a single import (e.g., multiple versions of a library), the `compare_with_duplicates()` function groups nodes by label and compares hash sets:

- If all hashes match: `SAME`
- If some hashes differ: `DIFFERENT_HASH`
- If no overlap in hashes: `ONLY_LEFT` / `ONLY_RIGHT`

## Database Query

The primary comparison uses a PostgreSQL `FULL OUTER JOIN`:

```sql
SELECT
    COALESCE(l.label, r.label) as label,
    l.id as left_id,
    l.drv_hash as left_hash,
    -- ... other columns
    r.id as right_id,
    r.drv_hash as right_hash,
    -- ... other columns
FROM nodes l
FULL OUTER JOIN nodes r
    ON l.label = r.label
    AND r.import_id = <right_id>
WHERE (l.import_id = <left_id> OR l.import_id IS NULL)
  AND (r.import_id = <right_id> OR r.import_id IS NULL)
ORDER BY COALESCE(l.label, r.label)
```

This efficiently matches all nodes by label while handling the case where a node exists in only one import.

## API Usage

### Compare Two Imports

```python
from vizzy.services.comparison import compare_imports, generate_diff_summary

# Get full comparison
comparison = compare_imports(left_import_id=1, right_import_id=2)

# Access summary metrics
print(f"Left only: {comparison.left_only_count}")
print(f"Right only: {comparison.right_only_count}")
print(f"Different: {comparison.different_count}")
print(f"Same: {comparison.same_count}")

# Filter by type
only_left = comparison.get_diffs_by_type(DiffType.ONLY_LEFT)

# Generate human-readable summary
summary = generate_diff_summary(comparison)
```

### Get Closure Analysis

```python
from vizzy.services.comparison import get_closure_comparison

closure = get_closure_comparison(left_import_id=1, right_import_id=2, limit=10)

print(f"Left total: {closure.left_total}")
print(f"Right total: {closure.right_total}")
print(f"Change: {closure.difference} ({closure.percentage_diff:.1f}%)")

# Show biggest additions
for diff in closure.largest_additions[:5]:
    print(f"  + {diff.label}: {diff.right_node.closure_size}")
```

### Match Pre-Loaded Nodes

```python
from vizzy.services.comparison import match_nodes

# Useful for testing or when nodes are already loaded
diffs = match_nodes(left_nodes, right_nodes)
```

## Caching

Comparison results can be cached using the analysis table:

```python
from vizzy.services.comparison import get_cached_comparison, cache_comparison

# Check for cached result
cached = get_cached_comparison(left_id, right_id)
if cached:
    return cached

# Compute and cache
comparison = compare_imports(left_id, right_id)
cache_comparison(comparison)
```

The cache key is normalized so that `compare(A, B)` and `compare(B, A)` share the same cache entry.

## See Also

- `src/vizzy/models.py` - Model definitions
- `src/vizzy/services/comparison.py` - Service implementation
