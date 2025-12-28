"""Pydantic models for Vizzy"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ImportInfo(BaseModel):
    """Information about an imported configuration"""

    id: int
    name: str
    config_path: str
    drv_path: str
    imported_at: datetime
    node_count: int | None
    edge_count: int | None


class Node(BaseModel):
    """A derivation node in the graph"""

    id: int
    import_id: int
    drv_hash: str
    drv_name: str
    label: str
    package_type: str | None
    depth: int | None
    closure_size: int | None
    metadata: dict[str, Any] | None


class Edge(BaseModel):
    """A dependency edge in the graph"""

    id: int
    import_id: int
    source_id: int
    target_id: int
    edge_color: str | None
    is_redundant: bool


class NodeWithNeighbors(BaseModel):
    """A node with its dependencies and dependents"""

    node: Node
    dependencies: list[Node]
    dependents: list[Node]


class GraphData(BaseModel):
    """Graph data for rendering"""

    nodes: list[Node]
    edges: list[Edge]


class ClusterInfo(BaseModel):
    """Information about a package type cluster"""

    package_type: str
    node_count: int
    total_closure_size: int


class SearchResult(BaseModel):
    """Search result item"""

    node: Node
    similarity: float


class PathResult(BaseModel):
    """Result of path finding between two nodes"""

    source: Node
    target: Node
    path: list[Node]
    length: int


class AnalysisResult(BaseModel):
    """Cached analysis result"""

    id: int
    import_id: int
    analysis_type: str
    result: dict[str, Any]
    computed_at: datetime
