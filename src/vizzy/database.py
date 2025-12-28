"""PostgreSQL database connection management"""

from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row

from vizzy.config import settings


def get_connection() -> psycopg.Connection:
    """Create a new database connection"""
    return psycopg.connect(settings.database_url, row_factory=dict_row)


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    """Context manager for database connections"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database schema"""
    schema_path = settings.nix_config_path.parent / "vizzy2" / "scripts" / "init_db.sql"
    if not schema_path.exists():
        schema_path = Path(__file__).parent.parent.parent.parent / "scripts" / "init_db.sql"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text())
