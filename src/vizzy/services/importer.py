"""DOT file parser and database importer"""

import json
import re
from pathlib import Path
from typing import Generator

import psycopg

from vizzy.database import get_db
from vizzy.services import nix


# Regex patterns for parsing DOT files
NODE_PATTERN = re.compile(
    r'^"([^"]+)"\s*\[label\s*=\s*"([^"]+)".*?\]',
    re.MULTILINE
)
EDGE_PATTERN = re.compile(
    r'^"([^"]+)"\s*->\s*"([^"]+)"(?:\s*\[color\s*=\s*"([^"]+)"\])?',
    re.MULTILINE
)

# Build-time dependency patterns
# These are packages that are typically only needed at build time
BUILD_TIME_PATTERNS = [
    r"^gcc-\d",           # GCC compiler
    r"^clang-\d",         # Clang compiler
    r"^cmake-",           # CMake build system
    r"^cargo-",           # Cargo package manager
    r"^rustc-",           # Rust compiler
    r"^meson-",           # Meson build system
    r"^ninja-",           # Ninja build tool
    r"^make-\d",          # GNU Make
    r"^gnumake-",         # GNU Make alternate
    r"-hook$",            # Build hooks (e.g., autoPatchelfHook)
    r"^stdenv-",          # Standard environment
    r"^bootstrap-",       # Bootstrap toolchain
    r"-wrapper$",         # Compiler wrappers
    r"^binutils-",        # Binary utilities
    r"^pkg-config-",      # Package configuration tool
    r"^autoconf-",        # Autoconf
    r"^automake-",        # Automake
    r"^libtool-",         # Libtool
    r"^m4-",              # M4 macro processor
    r"^perl-.*-for-build$",  # Perl build deps
    r"^python.*-for-build$", # Python build deps
    r"-dev$",             # Development packages
    r"-headers$",         # Header files
]


def classify_edge_type(source_name: str, target_name: str) -> str:
    """
    Classify edge as build-time or runtime dependency.

    Heuristics:
    - Source matches build tool patterns -> build
    - Source ends with -dev -> build
    - Otherwise -> runtime

    Args:
        source_name: The name of the source node (dependency)
        target_name: The name of the target node (dependent)

    Returns:
        'build', 'runtime', or 'unknown'
    """
    source_lower = source_name.lower()

    # Check if source is a build-time dependency
    for pattern in BUILD_TIME_PATTERNS:
        if re.search(pattern, source_lower, re.IGNORECASE):
            return 'build'

    # Dev packages are build-time deps
    if source_lower.endswith('-dev') or source_lower.endswith('-dev.drv'):
        return 'build'

    # Headers are build-time deps
    if '-headers' in source_lower or 'include' in source_lower:
        return 'build'

    # Default to runtime
    return 'runtime'


# Package type classification patterns
TYPE_PATTERNS = [
    (r"^linux-\d", "kernel"),
    (r"-modules\.drv$", "kernel"),
    (r"^firmware", "firmware"),
    (r"^systemd-", "service"),
    (r"-service\.drv$", "service"),
    (r"-unit\.drv$", "service"),
    (r"^python\d+\.\d+-", "python-package"),
    (r"^perl\d+\.\d+-", "perl-package"),
    (r"-lib\.drv$", "library"),
    (r"^glibc-", "library"),
    (r"^openssl-", "library"),
    (r"^zlib-", "library"),
    (r"^libffi-", "library"),
    (r"^gcc-", "development"),
    (r"^clang-", "development"),
    (r"^binutils-", "development"),
    (r"^cmake-", "development"),
    (r"^meson-", "development"),
    (r"-dev\.drv$", "development"),
    (r"^bootstrap-", "bootstrap"),
    (r"^stdenv-", "bootstrap"),
    (r"\.json\.drv$", "configuration"),
    (r"\.conf\.drv$", "configuration"),
    (r"\.sh\.drv$", "configuration"),
    (r"-config\.drv$", "configuration"),
    (r"^etc\.drv$", "configuration"),
    (r"-doc\.drv$", "documentation"),
    (r"-man\.drv$", "documentation"),
    (r"-info\.drv$", "documentation"),
    (r"font", "font"),
    (r"nerd-fonts", "font"),
]


def classify_package(name: str) -> str:
    """Classify a package by its name"""
    name_lower = name.lower()
    for pattern, pkg_type in TYPE_PATTERNS:
        if re.search(pattern, name_lower):
            return pkg_type
    return "application"


def parse_dot_file(path: Path) -> Generator[tuple[str, dict], None, None]:
    """
    Parse a DOT file and yield nodes and edges.

    Yields tuples of (type, data) where type is 'node' or 'edge'.
    """
    content = path.read_text()

    # Parse nodes
    for match in NODE_PATTERN.finditer(content):
        full_name = match.group(1)
        label = match.group(2)

        # Extract hash from full name (first 32 chars before the dash)
        parts = full_name.split("-", 1)
        if len(parts) == 2 and len(parts[0]) == 32:
            drv_hash = parts[0]
            drv_name = parts[1]
        else:
            drv_hash = full_name[:32] if len(full_name) >= 32 else full_name
            drv_name = full_name

        yield ("node", {
            "drv_hash": drv_hash,
            "drv_name": drv_name,
            "label": label.replace(".drv", ""),
            "package_type": classify_package(drv_name),
        })

    # Parse edges
    for match in EDGE_PATTERN.finditer(content):
        source_full = match.group(1)
        target_full = match.group(2)
        color = match.group(3) if match.group(3) else None

        # Extract hashes and names
        source_parts = source_full.split("-", 1)
        target_parts = target_full.split("-", 1)

        source_hash = source_parts[0] if len(source_parts[0]) == 32 else source_full[:32]
        target_hash = target_parts[0] if len(target_parts[0]) == 32 else target_full[:32]

        # Get names for classification
        source_name = source_parts[1] if len(source_parts) > 1 else source_full
        target_name = target_parts[1] if len(target_parts) > 1 else target_full

        # Classify edge type
        dependency_type = classify_edge_type(source_name, target_name)

        yield ("edge", {
            "source_hash": source_hash,
            "target_hash": target_hash,
            "edge_color": color,
            "dependency_type": dependency_type,
        })


def import_dot_file(
    path: Path,
    name: str,
    config_path: str,
    drv_path: str,
    fetch_metadata_on_import: bool = False,
    metadata_max_nodes: int | None = 1000,
    mark_top_level: bool = True,
) -> int:
    """
    Import a DOT file into the database.

    Args:
        path: Path to the DOT file
        name: Name for the import (typically the host name)
        config_path: Path to the nix configuration
        drv_path: Path to the derivation
        fetch_metadata_on_import: Whether to eagerly fetch metadata
        metadata_max_nodes: Maximum nodes to fetch metadata for
        mark_top_level: Whether to mark top-level packages (default True)

    Returns the import ID.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # First pass: collect all nodes and edges
    for item_type, data in parse_dot_file(path):
        if item_type == "node":
            nodes[data["drv_hash"]] = data
        else:
            edges.append(data)

    with get_db() as conn:
        with conn.cursor() as cur:
            # Create import record
            cur.execute(
                """
                INSERT INTO imports (name, config_path, drv_path, node_count, edge_count)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, config_path, drv_path, len(nodes), len(edges))
            )
            import_id = cur.fetchone()["id"]

            # Insert nodes using batch execute for better performance
            # Prepare node data for bulk insert
            node_values = [
                (
                    import_id,
                    drv_hash,
                    node_data["drv_name"],
                    node_data["label"],
                    node_data["package_type"],
                )
                for drv_hash, node_data in nodes.items()
            ]

            # Use executemany for batch insert
            cur.executemany(
                """
                INSERT INTO nodes (import_id, drv_hash, drv_name, label, package_type)
                VALUES (%s, %s, %s, %s, %s)
                """,
                node_values
            )

            # Build hash -> id map with a single query
            cur.execute(
                """
                SELECT drv_hash, id FROM nodes WHERE import_id = %s
                """,
                (import_id,)
            )
            node_id_map = {row['drv_hash']: row['id'] for row in cur.fetchall()}

            # Prepare edge data for bulk insert, filtering valid edges
            edge_values = [
                (
                    import_id,
                    node_id_map[edge_data["source_hash"]],
                    node_id_map[edge_data["target_hash"]],
                    edge_data["edge_color"],
                    edge_data.get("dependency_type", "unknown"),
                )
                for edge_data in edges
                if edge_data["source_hash"] in node_id_map and edge_data["target_hash"] in node_id_map
            ]

            # Use executemany for batch edge insert
            if edge_values:
                cur.executemany(
                    """
                    INSERT INTO edges (import_id, source_id, target_id, edge_color, dependency_type)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (import_id, source_id, target_id) DO NOTHING
                    """,
                    edge_values
                )

            conn.commit()

    # Compute depths and closure sizes after import
    compute_depths(import_id)
    compute_closure_sizes(import_id)

    # Optionally fetch metadata eagerly
    if fetch_metadata_on_import:
        fetch_metadata(import_id, max_nodes=metadata_max_nodes)

    # Mark top-level packages if enabled
    if mark_top_level:
        mark_top_level_nodes(import_id, host=name)

    return import_id


def compute_depths(import_id: int) -> None:
    """Compute depth from root for all nodes in an import"""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find root node (node with most incoming edges, typically the system)
            cur.execute(
                """
                SELECT n.id
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id
                WHERE n.import_id = %s
                GROUP BY n.id
                ORDER BY COUNT(e.id) DESC
                LIMIT 1
                """,
                (import_id,)
            )
            root = cur.fetchone()
            if not root:
                return

            root_id = root["id"]

            # BFS to compute depths
            cur.execute(
                """
                WITH RECURSIVE depths AS (
                    SELECT id, 0 as depth
                    FROM nodes
                    WHERE id = %s

                    UNION ALL

                    SELECT e.source_id, d.depth + 1
                    FROM edges e
                    JOIN depths d ON e.target_id = d.id
                    WHERE e.import_id = %s
                )
                UPDATE nodes n
                SET depth = d.min_depth
                FROM (
                    SELECT id, MIN(depth) as min_depth
                    FROM depths
                    GROUP BY id
                ) d
                WHERE n.id = d.id
                """,
                (root_id, import_id)
            )

            conn.commit()


def compute_closure_sizes(import_id: int) -> None:
    """Compute closure size (transitive dependency count) for all nodes"""
    with get_db() as conn:
        with conn.cursor() as cur:
            # For each node, count all transitive dependencies
            cur.execute(
                """
                WITH RECURSIVE closure AS (
                    SELECT target_id as node_id, source_id as dep_id
                    FROM edges
                    WHERE import_id = %s

                    UNION

                    SELECT c.node_id, e.source_id
                    FROM closure c
                    JOIN edges e ON e.target_id = c.dep_id
                    WHERE e.import_id = %s
                )
                UPDATE nodes n
                SET closure_size = c.cnt
                FROM (
                    SELECT node_id, COUNT(DISTINCT dep_id) as cnt
                    FROM closure
                    GROUP BY node_id
                ) c
                WHERE n.id = c.node_id
                """,
                (import_id, import_id)
            )

            conn.commit()


def fetch_metadata(import_id: int, batch_size: int = 50, max_nodes: int | None = None) -> int:
    """Fetch metadata for nodes in an import using nix derivation show.

    This is called eagerly at import time to avoid latency during exploration.

    Args:
        import_id: The import to fetch metadata for
        batch_size: Number of derivations to fetch per batch (default 50)
        max_nodes: Maximum number of nodes to fetch metadata for (None = all)

    Returns:
        Number of nodes with metadata fetched
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get nodes without metadata
            limit_clause = f"LIMIT {max_nodes}" if max_nodes else ""
            cur.execute(
                f"""
                SELECT id, drv_hash, drv_name
                FROM nodes
                WHERE import_id = %s AND metadata IS NULL
                ORDER BY depth ASC NULLS LAST
                {limit_clause}
                """,
                (import_id,)
            )
            nodes = cur.fetchall()

            if not nodes:
                return 0

            fetched_count = 0

            # Process in batches
            for i in range(0, len(nodes), batch_size):
                batch = nodes[i:i + batch_size]

                # Reconstruct drv paths
                drv_paths = []
                node_id_by_path = {}
                for node in batch:
                    drv_path = f"/nix/store/{node['drv_hash']}-{node['drv_name']}"
                    drv_paths.append(drv_path)
                    node_id_by_path[drv_path] = node['id']

                # Fetch metadata for batch
                try:
                    batch_metadata = nix.get_batch_derivation_metadata(drv_paths)
                except Exception:
                    # If batch fails, try individual fetches
                    batch_metadata = {}
                    for drv_path in drv_paths:
                        try:
                            meta = nix.get_derivation_metadata(drv_path)
                            if meta:
                                batch_metadata[drv_path] = meta
                        except Exception:
                            continue

                # Update nodes with metadata
                for drv_path, full_metadata in batch_metadata.items():
                    node_id = node_id_by_path.get(drv_path)
                    if node_id and full_metadata:
                        # Extract summary for storage
                        summary = nix.extract_metadata_summary(full_metadata)
                        if summary:
                            cur.execute(
                                """
                                UPDATE nodes SET metadata = %s WHERE id = %s
                                """,
                                (json.dumps(summary), node_id)
                            )
                            fetched_count += 1

                conn.commit()

            return fetched_count


def reclassify_edges(import_id: int) -> int:
    """Reclassify edge dependency types for an existing import.

    This can be used to update edge classifications after the classification
    logic has been improved, without needing to re-import the entire graph.

    Args:
        import_id: The import to reclassify edges for

    Returns:
        Number of edges reclassified
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all edges with their source node names
            cur.execute(
                """
                SELECT e.id, n_src.drv_name as source_name, n_tgt.drv_name as target_name
                FROM edges e
                JOIN nodes n_src ON e.source_id = n_src.id
                JOIN nodes n_tgt ON e.target_id = n_tgt.id
                WHERE e.import_id = %s
                """,
                (import_id,)
            )
            edges = cur.fetchall()

            if not edges:
                return 0

            # Reclassify each edge
            updates = []
            for edge in edges:
                new_type = classify_edge_type(edge['source_name'], edge['target_name'])
                updates.append((new_type, edge['id']))

            # Batch update
            cur.executemany(
                """
                UPDATE edges SET dependency_type = %s WHERE id = %s
                """,
                updates
            )

            conn.commit()
            return len(updates)


def _classify_module_type(source: str) -> str:
    """Classify a top_level_source into a module type.

    Args:
        source: The top_level_source value (e.g., 'systemPackages', 'programs.git.enable')

    Returns:
        Module type: 'systemPackages', 'programs', 'services', or 'other'
    """
    if source == 'systemPackages':
        return 'systemPackages'
    elif source.startswith('programs.'):
        return 'programs'
    elif source.startswith('services.'):
        return 'services'
    else:
        return 'other'


def mark_top_level_nodes(import_id: int, host: str | None = None) -> int:
    """Mark nodes that match top-level packages.

    Identifies nodes that correspond to explicitly-requested packages
    (e.g., environment.systemPackages, programs.*.enable, services.*.enable)
    and marks them as is_top_level=TRUE with their source module.

    This enables the "Why Chain" feature to trace dependencies back to
    user-facing packages and understand which NixOS modules added them.

    Args:
        import_id: The import to mark nodes for
        host: The host name (used to extract top-level package list)

    Returns:
        Count of nodes marked as top-level
    """
    if not host:
        # Try to extract host from import name
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM imports WHERE id = %s",
                    (import_id,)
                )
                row = cur.fetchone()
                if row:
                    host = row['name']

    if not host:
        return 0

    # Get top-level packages with their sources (enhanced with programs/services)
    try:
        top_level = nix.get_top_level_packages_extended(host)
    except Exception:
        # If we can't get top-level packages, return 0
        return 0

    if not top_level:
        return 0

    with get_db() as conn:
        with conn.cursor() as cur:
            marked = 0

            for pkg_name, source in top_level.items():
                # Classify the module type for easier querying
                module_type = _classify_module_type(source)

                # Try exact match first, then prefix match
                # This handles versioned package names (e.g., "firefox-120.0")
                cur.execute("""
                    UPDATE nodes
                    SET is_top_level = TRUE,
                        top_level_source = %s,
                        module_type = %s
                    WHERE import_id = %s
                      AND (label = %s OR label LIKE %s || '-%%')
                      AND is_top_level = FALSE
                    RETURNING id
                """, (source, module_type, import_id, pkg_name, pkg_name))
                marked += cur.rowcount

            conn.commit()
            return marked


def update_module_attribution_summary(import_id: int) -> None:
    """Compute and store module attribution summary for an import.

    Calculates aggregated statistics about which modules contribute
    to the closure and stores them for quick dashboard access.

    Args:
        import_id: The import to compute summary for
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Count packages by module type
            cur.execute("""
                SELECT module_type, COUNT(*) as count
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                GROUP BY module_type
            """, (import_id,))

            counts = {row['module_type']: row['count'] for row in cur.fetchall()}

            # Get breakdown by source
            cur.execute("""
                SELECT top_level_source, COUNT(*) as count
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                GROUP BY top_level_source
            """, (import_id,))

            by_source = {row['top_level_source']: row['count'] for row in cur.fetchall()}

            # Get top modules by closure size impact
            cur.execute("""
                SELECT
                    top_level_source as source,
                    array_agg(label ORDER BY closure_size DESC NULLS LAST) as packages,
                    SUM(closure_size) as total_closure
                FROM nodes
                WHERE import_id = %s AND is_top_level = TRUE
                GROUP BY top_level_source
                ORDER BY total_closure DESC NULLS LAST
                LIMIT 10
            """, (import_id,))

            top_modules = [
                {
                    'source': row['source'],
                    'packages': row['packages'][:5],  # Top 5 packages per module
                    'closure_size': row['total_closure'],
                }
                for row in cur.fetchall()
            ]

            # Insert or update the summary
            cur.execute("""
                INSERT INTO module_attribution_summary (
                    import_id,
                    system_packages_count,
                    programs_count,
                    services_count,
                    other_count,
                    by_source,
                    top_modules,
                    computed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (import_id) DO UPDATE SET
                    system_packages_count = EXCLUDED.system_packages_count,
                    programs_count = EXCLUDED.programs_count,
                    services_count = EXCLUDED.services_count,
                    other_count = EXCLUDED.other_count,
                    by_source = EXCLUDED.by_source,
                    top_modules = EXCLUDED.top_modules,
                    computed_at = NOW()
            """, (
                import_id,
                counts.get('systemPackages', 0),
                counts.get('programs', 0),
                counts.get('services', 0),
                counts.get('other', 0),
                json.dumps(by_source),
                json.dumps(top_modules),
            ))

            conn.commit()


def fetch_single_node_metadata(node_id: int) -> dict | None:
    """Fetch metadata for a single node on-demand.

    Used when metadata wasn't fetched at import time.

    Returns:
        The metadata dict if successful, None otherwise
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT drv_hash, drv_name, metadata
                FROM nodes
                WHERE id = %s
                """,
                (node_id,)
            )
            row = cur.fetchone()

            if not row:
                return None

            # If already have metadata, return it
            if row['metadata']:
                return row['metadata']

            # Fetch from nix
            drv_path = f"/nix/store/{row['drv_hash']}-{row['drv_name']}"
            try:
                full_metadata = nix.get_derivation_metadata(drv_path)
                if not full_metadata:
                    return None

                summary = nix.extract_metadata_summary(full_metadata)
                if summary:
                    # Cache it
                    cur.execute(
                        """
                        UPDATE nodes SET metadata = %s WHERE id = %s
                        """,
                        (json.dumps(summary), node_id)
                    )
                    conn.commit()
                    return summary
            except Exception:
                return None

    return None
