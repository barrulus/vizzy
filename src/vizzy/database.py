"""PostgreSQL database connection management with connection pooling.

This module provides database connections using psycopg's connection pool
for better performance in multi-threaded/async environments.
"""

from contextlib import contextmanager
from typing import Generator
from pathlib import Path
import logging

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from vizzy.config import settings

logger = logging.getLogger("vizzy.database")

# Global connection pool - initialized lazily
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """Get or create the connection pool.

    Pool is created lazily on first access to avoid issues during import.
    """
    global _pool
    if _pool is None:
        logger.info("Initializing database connection pool")
        _pool = ConnectionPool(
            settings.database_url,
            min_size=2,          # Minimum connections to keep open
            max_size=10,         # Maximum connections allowed
            max_waiting=5,       # Max requests waiting for a connection
            timeout=30.0,        # Timeout for getting a connection
            max_idle=300.0,      # Close idle connections after 5 minutes
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_connection() -> psycopg.Connection:
    """Create a new database connection (bypasses pool for special cases)."""
    return psycopg.connect(settings.database_url, row_factory=dict_row)


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    """Context manager for database connections using the pool.

    Automatically returns the connection to the pool when done.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def close_pool() -> None:
    """Close the connection pool. Call this on application shutdown."""
    global _pool
    if _pool is not None:
        logger.info("Closing database connection pool")
        _pool.close()
        _pool = None


def pool_stats() -> dict:
    """Return connection pool statistics for monitoring."""
    pool = _get_pool()
    return {
        "pool_size": pool.get_stats().get("pool_size", 0),
        "pool_available": pool.get_stats().get("pool_available", 0),
        "requests_waiting": pool.get_stats().get("requests_waiting", 0),
        "requests_num": pool.get_stats().get("requests_num", 0),
    }


def init_db() -> None:
    """Initialize database schema"""
    schema_path = settings.nix_config_path.parent / "vizzy2" / "scripts" / "init_db.sql"
    if not schema_path.exists():
        schema_path = Path(__file__).parent.parent.parent.parent / "scripts" / "init_db.sql"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text())
