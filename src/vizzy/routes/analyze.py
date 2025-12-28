"""Analysis routes - duplicates, paths, comparisons"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from vizzy.services import analysis
from vizzy.services import graph as graph_service

router = APIRouter(prefix="/analyze")

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/duplicates/{import_id}", response_class=HTMLResponse)
async def duplicates(request: Request, import_id: int):
    """Show packages with multiple derivations"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    duplicate_groups = analysis.find_duplicates(import_id)

    return templates.TemplateResponse(
        "analyze/duplicates.html",
        {
            "request": request,
            "import_info": import_info,
            "duplicates": duplicate_groups,
        },
    )


@router.get("/compare/{import_id}/{label}", response_class=HTMLResponse)
async def compare_duplicates(request: Request, import_id: int, label: str):
    """Compare different derivations of the same package"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    comparison = analysis.compare_duplicates(import_id, label)

    return templates.TemplateResponse(
        "analyze/compare.html",
        {
            "request": request,
            "import_info": import_info,
            "comparison": comparison,
        },
    )


@router.get("/path/{import_id}", response_class=HTMLResponse)
async def path_finder(request: Request, import_id: int, source: int | None = None, target: int | None = None):
    """Find path between two nodes"""
    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    path_result = None
    if source and target:
        path_result = analysis.find_path(source, target)

    return templates.TemplateResponse(
        "analyze/path.html",
        {
            "request": request,
            "import_info": import_info,
            "source_id": source,
            "target_id": target,
            "path_result": path_result,
        },
    )


@router.get("/sankey/{import_id}/{label}", response_class=HTMLResponse)
async def sankey_view(request: Request, import_id: int, label: str):
    """Sankey diagram showing flow from apps to package variants"""
    import json

    import_info = graph_service.get_import(import_id)
    if not import_info:
        return HTMLResponse("Import not found", status_code=404)

    sankey_data = analysis.build_sankey_data(import_id, label)

    return templates.TemplateResponse(
        "analyze/sankey.html",
        {
            "request": request,
            "import_info": import_info,
            "label": label,
            "sankey_data": json.dumps(sankey_data),
            "variant_count": sankey_data.get("variant_count", 0),
        },
    )
