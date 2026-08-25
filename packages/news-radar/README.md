# news-radar

Local-first OSINT/news radar: RSS ingest, interest filtering, LLM insights, static JSON+SPA output.

```bash
make test PKG=news-radar
make run PKG=news-radar
make add PKG=news-radar DEP=<library>
```

Not yet implemented — see [PLAN.md](PLAN.md) for the phased build plan (project
structure, JSON schema, module responsibilities, and phases 0–6).

## Database setup

All persistent state lives in Postgres. From `packages/news-radar`:

```bash
docker compose up -d          # local Postgres 17 (user/pass/db: news_radar)
uv run alembic upgrade head   # create/migrate tables
```

The DSN is read from `NEWS_RADAR_DSN` (see `.env.example`), defaulting to the
docker-compose instance. Schema changes are alembic migrations under
`alembic/versions/`; application code talks to Postgres via psycopg2 through
`news_radar.db.get_connection()` and the repositories in
`news_radar/repository/`.
