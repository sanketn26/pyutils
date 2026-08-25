"""create articles table (placeholder)

Placeholder for the Phase 1 schema (PLAN.md §4). Columns below are a first
sketch of the flat enriched Article record; refine when gather is implemented.
Later phases add embeddings_cache (Phase 2), story_clusters (Phase 4),
entity_mentions / entity_cooccurrence (Phase 5), causal_links (Phase 7) as
separate migrations.

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id           TEXT PRIMARY KEY,          -- sha256 of canonical URL, truncated
            title        TEXT NOT NULL,
            url          TEXT NOT NULL,
            source       TEXT NOT NULL,
            published_at TIMESTAMPTZ,
            gathered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_content  TEXT,
            summary      TEXT,                      -- InsightFilter output
            insight      TEXT,                      -- InsightFilter output
            entities     JSONB,                     -- InsightFilter output
            model        TEXT                       -- Ollama model tag used for enrichment
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS articles")
