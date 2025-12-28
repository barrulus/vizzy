"""Vizzy - NixOS Derivation Graph Explorer"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from vizzy.routes import pages, analyze

app = FastAPI(
    title="Vizzy",
    description="NixOS Derivation Graph Explorer",
    version="0.1.0",
)

# Mount static files
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(pages.router)
app.include_router(analyze.router)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}
