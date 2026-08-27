"""Placeholder repository for the flat `articles` table (PLAN.md §4).

All methods are stubs until Phase 1; each documents the query it will own so the
gather-stage filters/sinks can be written against this interface now.
"""

from typing import Any

from psycopg2.extensions import connection as PgConnection


class ArticleRepository:
    """Reads/writes the `articles` table. One method per query — no ORM."""

    def __init__(self, conn: PgConnection) -> None:
        self.conn = conn

    def exists(self, article_id: str) -> bool:
        """Seen-check by id hash — backs DedupFilter."""
        raise NotImplementedError("Phase 1: SELECT 1 FROM articles WHERE id = %s")

    def upsert(self, article: Any) -> None:
        """Persist one enriched Article — backs PostgresSink."""
        raise NotImplementedError("Phase 1: INSERT ... ON CONFLICT (id) DO UPDATE")

    def fetch_since(self, since: Any) -> list[Any]:
        """Articles gathered after `since` — backs the analyze-stage window query."""
        raise NotImplementedError("Phase 4: SELECT ... WHERE gathered_at > %s")
