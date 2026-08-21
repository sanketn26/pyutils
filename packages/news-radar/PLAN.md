# news-radar — Implementation Plan

Personal, local-first OSINT / news radar. Monitors RSS + simple web sources, filters
against user-defined interests (keywords + semantic similarity), asks a local LLM
(Ollama) for a summary + "so what" insight, and writes structured JSON that a static
single-page app renders. Local-first now; the `output/` folder is designed to be
pushed to GitHub Pages later with no pipeline changes.

Package only is initialized so far (`packages/news-radar`, standard scaffold). No
pipeline code yet — this plan is the spec for building it.

---

## 1. Final project structure

```
packages/news-radar/
├── pyproject.toml
├── README.md
├── PLAN.md                          # this file
├── config/
│   ├── sources.yaml                 # RSS feeds + optional simple web pages
│   └── interests.yaml               # named interests: keywords, priority, semantic seed text
├── src/news_radar/
│   ├── __init__.py
│   ├── __main__.py                  # CLI: run / daemon / serve
│   ├── config.py                    # load + validate sources.yaml / interests.yaml (pydantic)
│   ├── models.py                    # dataclasses/pydantic models: Article, Interest, BriefItem, Brief
│   ├── db.py                        # SQLite schema + connection helper (seen articles, dedup, cache)
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── rss.py                   # feedparser-based RSS/Atom ingestion
│   │   └── webpage.py               # trivial readability-style single-page fetch (optional sources)
│   ├── dedup.py                     # URL-hash + near-duplicate title/content dedup
│   ├── filter/
│   │   ├── __init__.py
│   │   ├── keywords.py              # keyword/phrase matching against interests
│   │   └── semantic.py              # embeddings (Ollama embedding model) + local vector store, cosine rank
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── ollama_client.py         # thin wrapper over Ollama HTTP API (generate + embeddings)
│   │   └── insight.py               # prompt templates + parsing for summary/insight/novelty/entities
│   ├── pipeline.py                  # orchestrates ingest → dedup → filter/rank → LLM → assemble Brief
│   ├── writer.py                    # writes output/briefs/<timestamp>.json + updates output/latest.json
│   ├── daemon.py                    # scheduler loop (run pipeline every N minutes) + signal handling
│   └── logging_conf.py              # stdlib logging setup, one place
├── frontend/
│   ├── index.html                   # SPA shell
│   ├── app.js                       # fetch latest.json, render grouped-by-interest cards
│   └── styles.css                   # mobile-first, dark/light aware
├── output/                          # generated; gitignored except .gitkeep
│   ├── latest.json
│   └── briefs/
│       └── <ISO-timestamp>.json
├── data/                            # generated; gitignored
│   └── news_radar.db                # SQLite: seen items, embeddings cache
└── tests/
    ├── test_smoke.py
    ├── test_dedup.py
    ├── test_filter_keywords.py
    ├── test_pipeline_assembly.py    # pipeline wired with fake ingest + fake LLM
    └── fixtures/
        └── sample_feed.xml
```

Design notes:
- `frontend/` is plain static HTML/JS/CSS — no build step, no framework. It only ever
  fetches a JSON file by relative path, so `output/` (JSON) + `frontend/` (SPA) can be
  copied as-is into a GitHub Pages branch/folder later. For local-first use, `output/`
  and `frontend/` are served side-by-side by one dev server (Phase 4).
- `config/` is YAML, hand-edited by the user; `data/` and `output/` are generated and
  gitignored (add `packages/news-radar/data/` and `packages/news-radar/output/*` minus
  `.gitkeep`/`latest.json` sample to root `.gitignore`).
- Everything routes through `pipeline.py` — `daemon.py` just calls it on a timer,
  `__main__.py run` calls it once. No duplicated orchestration logic.

---

## 2. JSON schema (confirmed)

Top-level brief, written to `output/briefs/<ISO-timestamp>.json` and copied verbatim to
`output/latest.json`:

```json
{
  "generated_at": "2026-08-21T14:03:00Z",
  "interests": [
    {
      "name": "Interest name",
      "priority": "high",
      "items": [
        {
          "id": "sha256-or-uuid",
          "title": "Article title",
          "summary": "2-3 sentence factual summary",
          "insight": "So-what / novelty / implications, 1-3 sentences",
          "url": "https://...",
          "source": "feed or site name",
          "published_at": "2026-08-21T09:15:00Z",
          "relevance_score": 0.83,
          "novelty": "new",
          "entities": ["Entity A", "Entity B"]
        }
      ]
    }
  ],
  "meta": {
    "total_items_considered": 0,
    "items_after_filter": 0,
    "model": "llama3.1:8b"
  }
}
```

Field notes / constraints:
- `priority`: enum `high | medium | low`, from `interests.yaml`.
- `id`: stable hash of canonical URL (sha256 hex, truncated) — used for dedup across
  runs, not random per-run.
- `relevance_score`: float 0.0–1.0, combined keyword + semantic score (Phase 2).
- `novelty`: enum `new | update | background`, LLM-assigned (Phase 3), defaults to
  `new` if the LLM step is skipped/fails.
- `entities`: list of strings, LLM-extracted, may be empty `[]`.
- An interest with zero matching items after filtering is **omitted** from `interests`
  (not included as an empty-items entry) — keeps the frontend simple.
- `meta.model` is the Ollama model tag actually used for that run (traceability if the
  model changes over time).

This is a `Brief` in `models.py`; `BriefInterest` and `BriefItem` are its nested
shapes. Pydantic models double as the JSON schema and the writer's validation step —
`writer.py` should refuse to write a `Brief` that doesn't validate.

---

## 3. Python pipeline structure (modules + responsibilities)

| Module | Responsibility |
|---|---|
| `config.py` | Load and validate `sources.yaml` + `interests.yaml` into typed objects. Fail fast with a clear error on malformed config. |
| `models.py` | All shared data shapes: `Source`, `Interest`, `Article` (raw ingested), `BriefItem`, `BriefInterest`, `Brief`. |
| `db.py` | SQLite connection + schema (`seen_articles`, `embeddings_cache` tables). One function per query — no ORM. |
| `ingest/rss.py` | Given a `Source`, fetch + parse feed (via `feedparser`), return `list[Article]` with title/url/published_at/source/raw_content populated. |
| `ingest/webpage.py` | Given a plain-page `Source`, fetch HTML, extract main text (basic heuristic, e.g. `trafilatura`), return a single `Article`. |
| `dedup.py` | Given `list[Article]` + the SQLite "seen" table, drop already-seen URLs (by id hash) and near-duplicate titles within the same run. Marks new ones as seen. |
| `filter/keywords.py` | Score an `Article` against an `Interest`'s keyword list (simple substring/regex match on title+content), return a keyword score 0–1. |
| `filter/semantic.py` | Embed article text + interest seed text via Ollama embeddings, cosine-similarity score, cache embeddings in SQLite keyed by article id. |
| `llm/ollama_client.py` | `generate(prompt, model) -> str` and `embed(text, model) -> list[float]`, talking to local Ollama HTTP API (`localhost:11434`). Timeouts + retries only — no fallback provider (local-first, single-provider by design). |
| `llm/insight.py` | Build the summary/insight prompt for a matched `(Article, Interest)` pair, call `ollama_client.generate`, parse the response into `summary`, `insight`, `novelty`, `entities`. |
| `pipeline.py` | `run_once(config) -> Brief`: ingest all sources → dedup → for each interest, keyword+semantic filter+rank, take top-N → LLM insight pass on survivors → assemble `Brief`. This is the one place that knows the end-to-end order. |
| `writer.py` | Validate + serialize a `Brief` to `output/briefs/<ts>.json`, then write/overwrite `output/latest.json` (same content, stable filename). Atomic write (write to temp, rename). |
| `daemon.py` | Loop: call `pipeline.run_once` + `writer.write`, sleep until next interval (config-driven, e.g. every N minutes), handle SIGTERM/SIGINT for clean shutdown. |
| `__main__.py` | CLI subcommands: `run` (single pass), `daemon` (loop), `serve` (serve `output/` + `frontend/` on localhost for local viewing). |

Pipeline call order (`pipeline.run_once`):

```
sources.yaml → ingest.rss / ingest.webpage → [Article]
             → dedup (SQLite seen-check)     → [Article] (new only)
             → for each Interest:
                   filter.keywords + filter.semantic → ranked [Article]
                   → take top N by combined score
                   → llm.insight.generate       → [BriefItem]
             → assemble Brief (skip empty interests)
             → writer.write  → output/briefs/<ts>.json + output/latest.json
```

---

## 4. Frontend approach (spec, no code yet)

- `frontend/index.html` + `app.js` + `styles.css`, no build tooling, no framework.
- On load, `app.js` fetches `../output/latest.json` (relative path, so it works
  identically served locally or from GitHub Pages once `output/` and `frontend/` sit
  side by side in the published folder).
- Renders one section per interest (ordered by `priority`: high → medium → low), each
  a heading + list of item cards: title (linked to `url`), summary, insight, source +
  published_at, relevance_score as a small badge.
- Mobile-first CSS: single column, cards stack; a simple `@media (min-width: 768px)`
  bump to a 2-column grid on desktop. System dark/light via `prefers-color-scheme`.
- No routing, no state library — a `<select>` or set of tabs to switch between
  historical briefs (listing `output/briefs/*.json`) is a nice-to-have, deferred to
  Phase 5+; v1 only reads `latest.json`.

---

## 5. Phased build plan

### Phase 0 — Package scaffold (done)
- [x] `make new NAME=news-radar DESC="..."` → `packages/news-radar` created, synced
      into the uv workspace, builds cleanly.
- Deliverable: empty package that imports and runs (`make run PKG=news-radar`).

### Phase 1 — Config, models, ingest, dedup (no LLM yet)
- Add deps: `feedparser`, `pyyaml`, `pydantic`, `trafilatura` (webpage extraction).
- `config.py` + `config/sources.yaml` + `config/interests.yaml` (2-3 sample entries
  each) — load and validate.
- `models.py` — `Source`, `Interest`, `Article` only (Brief models come in Phase 3).
- `db.py` — SQLite schema for `seen_articles`.
- `ingest/rss.py` — parse a feed URL into `list[Article]`.
- `dedup.py` — hash-based seen-check against SQLite.
- `__main__.py ingest` subcommand — runs ingest+dedup, prints count of new articles.
- Tests: `test_dedup.py`, a fixture RSS XML file, ingest→dedup round-trip.
- Deliverable: `news-radar ingest` against real feeds prints new-article counts,
  re-running immediately after shows 0 new (dedup works).

### Phase 2 — Filtering & ranking against interests
- `filter/keywords.py` — keyword scoring.
- `filter/semantic.py` — Ollama embeddings + cosine similarity, embeddings cached in
  SQLite (`embeddings_cache` table) so re-runs don't re-embed unchanged articles.
- Combined score = weighted sum (config-driven weight, sane default e.g. 0.4 keyword +
  0.6 semantic), top-N per interest (config-driven, default 10).
- `__main__.py filter` subcommand — prints ranked matches per interest, no LLM calls.
- Tests: `test_filter_keywords.py`, a semantic test with a stubbed embedding function
  (no live Ollama dependency in CI).
- Deliverable: ranked, relevant articles per interest, entirely local, no LLM cost yet.

### Phase 3 — LLM insight generation + Brief assembly + JSON output
- `llm/ollama_client.py` — `generate` + `embed` against local Ollama.
- `llm/insight.py` — prompt template producing summary/insight/novelty/entities as
  parseable (JSON-mode or structured-prompt) output; graceful fallback if parsing
  fails (log + skip item rather than crash the run).
- `models.py` — add `BriefItem`, `BriefInterest`, `Brief` (pydantic, matching the
  schema in §2).
- `pipeline.py` — wire ingest → dedup → filter → insight → `Brief`.
- `writer.py` — validated, atomic write of `output/briefs/<ts>.json` + `latest.json`.
- `__main__.py run` subcommand — full single pass end to end.
- Tests: `test_pipeline_assembly.py` with a fake LLM client (no live Ollama needed).
- Deliverable: `news-radar run` produces a schema-correct `output/latest.json` from
  real feeds through a local Ollama model.

### Phase 4 — Frontend + local serving
- `frontend/index.html`, `app.js`, `styles.css` per §4.
- `__main__.py serve` subcommand — trivial local HTTP server (stdlib
  `http.server.ThreadingHTTPServer`, no extra dep) rooted so both `frontend/` and
  `output/` are reachable, opens to `index.html`.
- Manual check: load in a desktop browser and a phone (or responsive dev tools),
  confirm grouping/readability at both widths.
- Deliverable: `news-radar serve` → open `localhost:PORT` → see the current brief.

### Phase 5 — Daemon mode
- `daemon.py` — interval loop (config-driven `poll_interval_minutes`), calls
  `pipeline.run_once` + `writer.write` each tick, structured logging via
  `logging_conf.py`, clean SIGTERM/SIGINT shutdown.
- `__main__.py daemon` subcommand.
- Optional: a short systemd user-unit example in `README.md` for "run on laptop
  startup / on a schedule" (documentation only, not shipped as a file, since it's
  machine-specific).
- Deliverable: `news-radar daemon` runs indefinitely, refreshing `output/latest.json`
  on schedule, `news-radar serve` in parallel always shows current data.

### Phase 6 — GitHub Pages readiness (no pipeline changes)
- Confirm `frontend/` uses only relative fetches (`./latest.json`, `./briefs/...`) —
  no absolute localhost URLs anywhere.
- Document (README) the publish step: copy/symlink `output/*.json` next to
  `frontend/*` into a `gh-pages` branch or `/docs` folder; this is a file-copy step,
  not a code change.
- Optional nicety: a `news-radar publish --to <dir>` helper that copies
  `frontend/` + `output/` into a target directory — deferred unless actually wanted,
  since `cp -r` already satisfies the requirement.
- Deliverable: one documented command (or manual `cp -r`) turns the local `output/` +
  `frontend/` into a deployable static site.

---

## Explicitly out of scope for v1 (avoid over-engineering)
- No multi-user auth, no server-side rendering, no database beyond SQLite.
- No pluggable LLM providers — Ollama only, matching the local-first constraint.
- No feed-discovery/crawling beyond configured sources.
- No historical-brief browsing UI beyond `latest.json` (deferred nicety in Phase 4 notes).
- No retries/backoff frameworks — simple try/except + log/skip is enough at personal-tool scale.
