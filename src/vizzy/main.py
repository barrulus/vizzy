"""Vizzy - NixOS Derivation Graph Explorer"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware

from vizzy.routes import pages, analyze, compare, api, baseline
from vizzy.middleware import TimingMiddleware
from vizzy.services.cache import cache
from vizzy.database import close_pool, pool_stats

app = FastAPI(
    title="Vizzy",
    description="NixOS Derivation Graph Explorer",
    version="0.1.0",
)

# Add performance middleware
# GZip compression for responses larger than 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Request timing and slow request logging
app.add_middleware(
    TimingMiddleware,
    slow_request_threshold=1.0,  # Log requests taking > 1 second
    log_all_requests=False,      # Set to True for debugging
)

# Mount static files
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(pages.router)
app.include_router(analyze.router)
app.include_router(compare.router)
app.include_router(api.router)
app.include_router(baseline.router)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


@app.get("/api/cache/stats")
async def cache_stats():
    """Return cache statistics for monitoring."""
    return cache.stats()


@app.get("/api/pool/stats")
async def db_pool_stats():
    """Return database connection pool statistics for monitoring."""
    return pool_stats()


@app.post("/api/cache/clear")
async def clear_cache():
    """Clear all cache entries. Use with caution."""
    count = cache.invalidate()
    return {"cleared": count}


@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    # Clean up any expired cache entries periodically
    # In a production app, you might use a background task scheduler
    pass


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    # Clear cache on shutdown
    cache.invalidate()
    # Close database connection pool
    close_pool()
