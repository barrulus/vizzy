"""DOT file parser and database importer"""

import re
from pathlib import Path
from typing import Generator

import psycopg

from vizzy.database import get_db


# Regex patterns for parsing DOT files
NODE_PATTERN = re.compile(
    r'^"([^"]+)"\s*\[label\s*=\s*"([^"]+)".*?\]',
    re.MULTILINE
)
EDGE_PATTERN = re.compile(
    r'^"([^"]+)"\s*->\s*"([^"]+)"(?:\s*\[color\s*=\s*"([^"]+)"\])?',
    re.MULTILINE
)

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

        # Extract hashes
        source_parts = source_full.split("-", 1)
        target_parts = target_full.split("-", 1)

        source_hash = source_parts[0] if len(source_parts[0]) == 32 else source_full[:32]
        target_hash = target_parts[0] if len(target_parts[0]) == 32 else target_full[:32]

        yield ("edge", {
            "source_hash": source_hash,
            "target_hash": target_hash,
            "edge_color": color,
        })


def import_dot_file(
    path: Path,
    name: str,
    config_path: str,
    drv_path: str,
) -> int:
    """
    Import a DOT file into the database.

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

            # Insert nodes in batch
            node_id_map: dict[str, int] = {}
            for drv_hash, node_data in nodes.items():
                cur.execute(
                    """
                    INSERT INTO nodes (import_id, drv_hash, drv_name, label, package_type)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        import_id,
                        drv_hash,
                        node_data["drv_name"],
                        node_data["label"],
                        node_data["package_type"],
                    )
                )
                node_id_map[drv_hash] = cur.fetchone()["id"]

            # Insert edges in batch
            for edge_data in edges:
                source_id = node_id_map.get(edge_data["source_hash"])
                target_id = node_id_map.get(edge_data["target_hash"])

                if source_id and target_id:
                    cur.execute(
                        """
                        INSERT INTO edges (import_id, source_id, target_id, edge_color)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (import_id, source_id, target_id) DO NOTHING
                        """,
                        (import_id, source_id, target_id, edge_data["edge_color"])
                    )

            conn.commit()

    # Compute depths after import
    compute_depths(import_id)

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
