"""Postgres connection helper (psycopg2).

Schema is owned by alembic migrations (see alembic/versions/); this module only
hands out connections. The DSN comes from the NEWS_RADAR_DSN env var, defaulting
to the local docker-compose Postgres.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import connection as PgConnection

DEFAULT_DSN = "postgresql://news_radar:news_radar@localhost:5432/news_radar"


def get_dsn() -> str:
    return os.environ.get("NEWS_RADAR_DSN", DEFAULT_DSN)


@contextmanager
def get_connection(dsn: str | None = None) -> Generator[PgConnection, None, None]:
    """Yield a connection; commit on clean exit, roll back on exception."""
    conn = psycopg2.connect(dsn or get_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
