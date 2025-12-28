"""HTML page routes"""

from pathlib import Path

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from vizzy.config import settings
from vizzy.services import graph as graph_service
from vizzy.services import importer
from vizzy.services import nix as nix_service
from vizzy.services import render as render_service

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page with import list and config browser"""
    imports = graph_service.get_imports()

    # Discover flakes in config path
    flake_path = settings.nix_config_path / "flake.nix"
    has_flake = flake_path.exists()

    # List hosts if flake exists
    hosts = []
    if has_flake:
        hosts_dir = settings.nix_config_path / "hosts"
        if hosts_dir.exists():
            hosts = [d.name for d in hosts_dir.iterdir() if d.is_dir()]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "imports": imports,
            "config_path": str(settings.nix_config_path),
            "has_flake": has_flake,
            "hosts": hosts,
        },
    )


@router.get("/explore/{import_id}", response_class=HTMLResponse)
async def explore(request: Request, import_id: int):
    """Main exploration view for an import"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    clusters = graph_service.get_clusters(import_id)
    svg = render_service.render_clusters(clusters, import_id)

    return templates.TemplateResponse(
        "explore.html",
        {
            "request": request,
            "import_info": import_info,
            "clusters": clusters,
            "svg": svg,
        },
    )


@router.get("/graph/cluster/{import_id}/{package_type}", response_class=HTMLResponse)
async def cluster_view(request: Request, import_id: int, package_type: str):
    """View nodes within a package type cluster"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    nodes = graph_service.get_nodes_by_type(import_id, package_type, limit=100)
    subgraph = graph_service.get_subgraph(import_id, package_type=package_type, max_nodes=100)
    svg = render_service.render_graph(subgraph)

    return templates.TemplateResponse(
        "cluster.html",
        {
            "request": request,
            "import_info": import_info,
            "package_type": package_type,
            "nodes": nodes,
            "svg": svg,
        },
    )


@router.get("/graph/node/{node_id}", response_class=HTMLResponse)
async def node_view(request: Request, node_id: int):
    """Detail view for a single node"""
    node_data = graph_service.get_node_with_neighbors(node_id)
    if not node_data:
        return HTMLResponse("Node not found", status_code=404)

    import_info = graph_service.get_import(node_data.node.import_id)

    svg = render_service.render_node_detail(
        node_data.node,
        node_data.dependencies,
        node_data.dependents,
    )

    return templates.TemplateResponse(
        "node.html",
        {
            "request": request,
            "import_info": import_info,
            "node": node_data.node,
            "dependencies": node_data.dependencies,
            "dependents": node_data.dependents,
            "svg": svg,
        },
    )


@router.get("/defined/{import_id}", response_class=HTMLResponse)
async def defined_packages(request: Request, import_id: int):
    """Show explicitly defined system packages"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    # Get the list of defined packages from nix config
    defined = nix_service.get_system_packages(import_info.name)

    # Match them to nodes in our graph
    matched = []
    unmatched = []

    for pkg_name in defined:
        # Search for this package in our nodes
        # Strip version for matching (e.g., "git-2.43" -> "git")
        nodes = graph_service.search_nodes(import_id, pkg_name.split("-")[0], limit=5)

        # Find best match
        best_match = None
        for node in nodes:
            if node.label == pkg_name or node.label.startswith(pkg_name + "-") or pkg_name.startswith(node.label.split("-")[0]):
                best_match = node
                break

        if best_match:
            matched.append({"name": pkg_name, "node": best_match})
        else:
            unmatched.append(pkg_name)

    return templates.TemplateResponse(
        "defined.html",
        {
            "request": request,
            "import_info": import_info,
            "matched": matched,
            "unmatched": unmatched,
            "total": len(defined),
        },
    )


@router.get("/module-packages/{import_id}", response_class=HTMLResponse)
async def module_packages(request: Request, import_id: int):
    """Show packages added by NixOS modules (not explicit user packages)"""
    from vizzy.database import get_db

    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    # Get explicitly defined packages
    defined = set(nix_service.get_system_packages(import_info.name))
    defined_base = {p.split("-")[0] for p in defined}  # Base names without version

    # Find packages directly in system-path that aren't explicitly defined
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find system-path node
            cur.execute(
                "SELECT id FROM nodes WHERE import_id = %s AND label = 'system-path'",
                (import_id,)
            )
            row = cur.fetchone()
            if not row:
                return templates.TemplateResponse(
                    "module_packages.html",
                    {
                        "request": request,
                        "import_info": import_info,
                        "packages": [],
                        "error": "Could not find system-path node",
                    },
                )

            system_path_id = row['id']

            # Get all direct children of system-path
            cur.execute(
                """
                SELECT n.id, n.label, n.package_type
                FROM edges e
                JOIN nodes n ON e.source_id = n.id
                WHERE e.target_id = %s
                ORDER BY n.label
                """,
                (system_path_id,)
            )

            all_system_packages = cur.fetchall()

    # Categorize packages
    module_packages = []
    for pkg in all_system_packages:
        label = pkg['label']
        base_name = label.split("-")[0]

        # Check if this is explicitly defined
        is_explicit = label in defined or base_name in defined_base

        if not is_explicit:
            module_packages.append({
                "id": pkg['id'],
                "label": label,
                "package_type": pkg['package_type'],
            })

    return templates.TemplateResponse(
        "module_packages.html",
        {
            "request": request,
            "import_info": import_info,
            "packages": module_packages,
            "total_system": len(all_system_packages),
            "error": None,
        },
    )


@router.get("/impact/{node_id}", response_class=HTMLResponse)
async def package_impact(request: Request, node_id: int):
    """Show what dependencies a package pulls into your system"""
    from vizzy.database import get_db

    node = graph_service.get_node(node_id)
    if not node:
        return HTMLResponse("Node not found", status_code=404)

    import_info = graph_service.get_import(node.import_id)

    # Get all transitive dependencies of this package
    with get_db() as conn:
        with conn.cursor() as cur:
            # Recursive CTE to find all dependencies
            cur.execute(
                """
                WITH RECURSIVE deps AS (
                    -- Direct dependencies
                    SELECT n.id, n.label, n.package_type, 1 as depth
                    FROM edges e
                    JOIN nodes n ON e.source_id = n.id
                    WHERE e.target_id = %s

                    UNION

                    -- Transitive dependencies
                    SELECT n.id, n.label, n.package_type, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.target_id = d.id
                    JOIN nodes n ON e.source_id = n.id
                    WHERE d.depth < 20
                )
                SELECT DISTINCT id, label, package_type, MIN(depth) as min_depth
                FROM deps
                GROUP BY id, label, package_type
                ORDER BY min_depth, label
                """,
                (node_id,)
            )

            all_deps = [dict(row) for row in cur.fetchall()]

            # Group by package type
            by_type = {}
            for dep in all_deps:
                pkg_type = dep['package_type'] or 'other'
                if pkg_type not in by_type:
                    by_type[pkg_type] = []
                by_type[pkg_type].append(dep)

            # Get direct dependencies (depth 1) separately
            direct_deps = [d for d in all_deps if d['min_depth'] == 1]

    return templates.TemplateResponse(
        "impact.html",
        {
            "request": request,
            "import_info": import_info,
            "node": node,
            "all_deps": all_deps,
            "direct_deps": direct_deps,
            "by_type": dict(sorted(by_type.items(), key=lambda x: -len(x[1]))),
            "total_count": len(all_deps),
        },
    )


@router.get("/visual/{node_id}", response_class=HTMLResponse)
async def visual_explorer(request: Request, node_id: int):
    """Interactive visual graph explorer"""
    node = graph_service.get_node(node_id)
    if not node:
        return HTMLResponse("Node not found", status_code=404)

    import_info = graph_service.get_import(node.import_id)

    return templates.TemplateResponse(
        "visual.html",
        {
            "request": request,
            "import_info": import_info,
            "start_node": node,
        },
    )


@router.get("/api/graph/{node_id}")
async def api_graph_neighbors(node_id: int, depth: int = 1):
    """API endpoint to get node neighbors for visual explorer"""
    from vizzy.database import get_db

    node = graph_service.get_node(node_id)
    if not node:
        return {"error": "Node not found"}

    with get_db() as conn:
        with conn.cursor() as cur:
            # Get neighbors up to specified depth
            if depth == 1:
                # Just direct neighbors
                cur.execute(
                    """
                    SELECT DISTINCT n.id, n.label, n.package_type, 'dependency' as relation
                    FROM edges e
                    JOIN nodes n ON e.source_id = n.id
                    WHERE e.target_id = %s
                    UNION
                    SELECT DISTINCT n.id, n.label, n.package_type, 'dependent' as relation
                    FROM edges e
                    JOIN nodes n ON e.target_id = n.id
                    WHERE e.source_id = %s
                    """,
                    (node_id, node_id)
                )
            else:
                # Multi-level (limit to avoid explosion)
                cur.execute(
                    """
                    WITH RECURSIVE neighbors AS (
                        SELECT n.id, n.label, n.package_type, 1 as depth
                        FROM edges e
                        JOIN nodes n ON e.source_id = n.id
                        WHERE e.target_id = %s
                        UNION
                        SELECT n.id, n.label, n.package_type, 1 as depth
                        FROM edges e
                        JOIN nodes n ON e.target_id = n.id
                        WHERE e.source_id = %s
                        UNION
                        SELECT n.id, n.label, n.package_type, nb.depth + 1
                        FROM neighbors nb
                        JOIN edges e ON e.target_id = nb.id OR e.source_id = nb.id
                        JOIN nodes n ON (e.source_id = n.id OR e.target_id = n.id) AND n.id != nb.id
                        WHERE nb.depth < %s
                    )
                    SELECT DISTINCT id, label, package_type
                    FROM neighbors
                    LIMIT 100
                    """,
                    (node_id, node_id, depth)
                )

            neighbor_rows = cur.fetchall()
            neighbor_ids = [row['id'] for row in neighbor_rows]
            all_ids = [node_id] + neighbor_ids

            # Get edges between all these nodes
            cur.execute(
                """
                SELECT source_id, target_id
                FROM edges
                WHERE source_id = ANY(%s) AND target_id = ANY(%s)
                """,
                (all_ids, all_ids)
            )
            edge_rows = cur.fetchall()

    # Build vis.js compatible data
    nodes = [
        {
            "id": node.id,
            "label": node.label[:30] + ("..." if len(node.label) > 30 else ""),
            "title": node.label,
            "color": get_node_color(node.package_type),
            "font": {"size": 14, "face": "sans-serif"},
            "shape": "box",
            "borderWidth": 3,
        }
    ]

    for row in neighbor_rows:
        nodes.append({
            "id": row['id'],
            "label": row['label'][:25] + ("..." if len(row['label']) > 25 else ""),
            "title": row['label'],
            "color": get_node_color(row['package_type']),
            "font": {"size": 12, "face": "sans-serif"},
            "shape": "box",
        })

    edges = [
        {"from": row['source_id'], "to": row['target_id'], "arrows": "to"}
        for row in edge_rows
    ]

    return {"nodes": nodes, "edges": edges, "center": node_id}


def get_node_color(package_type: str | None) -> str:
    """Get color for node based on package type"""
    colors = {
        "kernel": "#ff6b6b",
        "firmware": "#ffa94d",
        "service": "#69db7c",
        "library": "#74c0fc",
        "development": "#b197fc",
        "bootstrap": "#f783ac",
        "configuration": "#ffd43b",
        "python-package": "#3b82f6",
        "perl-package": "#8b5cf6",
        "font": "#ec4899",
        "documentation": "#94a3b8",
        "application": "#22d3ee",
    }
    return colors.get(package_type, "#e2e8f0")


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, import_id: int, q: str = ""):
    """Search for nodes"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    results = []
    if q:
        results = graph_service.search_nodes(import_id, q)

    return templates.TemplateResponse(
        "partials/search_results.html",
        {
            "request": request,
            "results": results,
            "query": q,
        },
    )


@router.post("/import/file")
async def import_file(
    name: str = Form(...),
    file: UploadFile = File(...),
):
    """Import a DOT file"""
    import tempfile

    # Save uploaded file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".dot", delete=False) as f:
        content = await file.read()
        f.write(content)
        temp_path = Path(f.name)

    try:
        import_id = importer.import_dot_file(
            path=temp_path,
            name=name,
            config_path="uploaded",
            drv_path="uploaded",
        )
        return RedirectResponse(url=f"/explore/{import_id}", status_code=303)
    finally:
        temp_path.unlink()


@router.post("/import/existing")
async def import_existing(name: str = Form(...), dot_path: str = Form(...)):
    """Import an existing DOT file from filesystem"""
    path = Path(dot_path)
    if not path.exists():
        return HTMLResponse(f"File not found: {dot_path}", status_code=400)

    import_id = importer.import_dot_file(
        path=path,
        name=name,
        config_path=str(path.parent),
        drv_path=str(path),
    )
    return RedirectResponse(url=f"/explore/{import_id}", status_code=303)


@router.post("/import/{import_id}/delete")
async def delete_import(import_id: int):
    """Delete an import and all its data"""
    from vizzy.database import get_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM imports WHERE id = %s", (import_id,))
            conn.commit()

    return RedirectResponse(url="/", status_code=303)


@router.post("/import/nix")
async def import_nix(host: str = Form(...)):
    """Import a NixOS host configuration from the configured flake"""
    try:
        # Export graph from nix
        drv_path, dot_path = nix_service.export_host_graph(host)

        try:
            # Import the generated DOT file
            import_id = importer.import_dot_file(
                path=dot_path,
                name=host,
                config_path=str(settings.nix_config_path),
                drv_path=drv_path,
            )
            return RedirectResponse(url=f"/explore/{import_id}", status_code=303)
        finally:
            # Clean up temp file
            dot_path.unlink(missing_ok=True)

    except nix_service.NixError as e:
        return HTMLResponse(
            f"""
            <html>
            <head><title>Import Error</title></head>
            <body style="font-family: sans-serif; padding: 2rem;">
                <h1>Import Failed</h1>
                <p style="color: red;">{e}</p>
                <a href="/">← Back to Home</a>
            </body>
            </html>
            """,
            status_code=500,
        )
