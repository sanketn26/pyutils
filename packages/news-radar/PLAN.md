# news-radar — Implementation Plan

Personal, local-first OSINT / news radar. Monitors RSS + simple web sources, enriches
each item (dedup, semantic embedding, LLM summary/insight via Ollama), then runs a
background **analysis** pass across the accumulated store (story clustering across
sources, novelty/trend detection over time, an entity co-occurrence graph, and an
LLM causal-linking pass). A separate, cheap **brief** step queries the enriched +
analyzed store against user-defined interests (keywords + semantic similarity) to
build the JSON a static single-page app renders. Local-first now; the `output/` folder
is designed to be pushed to GitHub Pages later with no pipeline changes.

Package only is initialized so far (`packages/news-radar`, standard scaffold), plus a
first draft of the core `domain/interfaces.py` abstractions. No ingest/enrich/analysis/
brief code yet — this plan is the spec for building it.

---

## 1. Architecture: gather → analyze → brief

Three decoupled stages, not one monolithic pipeline:

- **Gather** — expensive, runs on a schedule (network + per-item LLM calls). Pulls raw
  items from sources, enriches each one independently (dedup, embed, summarize), and
  writes flat enriched records to SQLite. It does **not** know about interests, other
  articles, or cross-item context — enrichment only ever adds data to a single item.
- **Analyze** — a background pass over the accumulated store, not per-item. Runs after
  gather (or on its own timer over whatever's accumulated since it last ran) and
  computes cross-article structure: which articles are the same story from different
  sources, whether a story is genuinely new or a rehash, which entities co-occur, and
  what plausibly caused what. It reads/writes derived tables — it doesn't touch the
  raw enriched articles gather wrote. Still doesn't know about interests.
- **Brief** — cheap, pure local computation. Reads enriched articles + analysis output
  + `interests.yaml`, scores/ranks per interest (keyword + semantic cosine, boosted by
  cluster/trend/causal context from analysis), groups into the `Brief` JSON shape, and
  writes `output/latest.json`. No network or LLM calls — a fast local query/render step,
  re-runnable any time without re-gathering or re-analyzing.

Why split analyze out from gather instead of folding it into another `Filter`: every
`Filter` in the gather `Pipeline` (§4) transforms one item in isolation as it streams
through — clustering, trend detection, entity graphs, and causal links are inherently
cross-item and need the *whole accumulated store* (or at least a recent window of it),
not a single article. Trying to do that inside a streaming per-item filter would mean
re-querying the whole store on every single article, which is wasteful; a dedicated
batch pass that runs once per accumulated window is the natural shape.

Why split brief out from analyze: analysis is corpus-wide and interest-agnostic (the
same clusters/trends/causal links serve every interest); brief is comparatively free
and re-run-on-demand (e.g. right after editing `interests.yaml`). Coupling them would
mean re-clustering and re-running the LLM causality pass every time someone tweaks an
interest definition.

The gather stage is built on the domain abstractions already drafted in
`domain/interfaces.py`:

- `Pipe.produce(conf) -> Generator[Any]` — yields raw items from a source.
- `Filter.filter(data) -> Any` — enriches (or drops, e.g. dedup) one item.
- `Sink.consume(data) -> None` — persists one item.
- `Pipeline` — wires one `Pipe`, an ordered list of `Filter`s, and a `Sink`; `run()`
  streams `produce → filter chain → consume`.

Known fix needed in the current draft: `Pipeline.__init__`'s `filters: list[Filter] =
[]` default is a mutable default argument (shared across instances) — switch to
`filters: list[Filter] | None = None` + `self.filters = filters or []`. Also worth
deciding whether a `Filter` can return `None` to drop an item (needed for dedup) and
having `Pipeline.run()` skip `None` before calling `Sink.consume()`.

The analyze stage needs a *different* abstraction since it's batch/cross-item rather
than streaming/per-item — not yet drafted. Proposed addition to `domain/interfaces.py`:

```python
class Analyzer(ABC):
    '''Reads a window of the store and writes derived, cross-article data.'''
    @abstractmethod
    def analyze(self, window: Any) -> None:
        pass

class AnalysisPipeline:
    '''Runs a list of Analyzers, in order, over one window of accumulated data.'''
    def __init__(self, analyzers: list[Analyzer]) -> None:
        self.analyzers = analyzers

    def run(self, window: Any) -> None:
        for analyzer in self.analyzers:
            analyzer.analyze(window)
```

Each `Analyzer.analyze` reads what it needs from the store (via `db.py` query
functions) and writes its derived table(s) directly — there's no shared "data" object
threaded through the chain like there is in the gather `Pipeline`, because each
analyzer produces a different kind of derived data (clusters vs. entity edges vs.
causal links) rather than progressively enriching one record.

---

## 2. Final project structure

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
│   ├── __main__.py                  # CLI: gather / analyze / brief / daemon / serve
│   ├── config.py                    # load + validate sources.yaml / interests.yaml (pydantic)
│   ├── models.py                    # Article, StoryCluster, EntityEdge, CausalLink, Interest, BriefItem, Brief
│   ├── db.py                        # SQLite schema + connection helper (all tables, one place)
│   ├── domain/
│   │   ├── __init__.py
│   │   └── interfaces.py            # Filter / Pipe / Sink / Pipeline (drafted) + Analyzer / AnalysisPipeline (to add)
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── rss.py                   # RssPipe(Pipe): feedparser-based RSS/Atom → Article stream
│   │   └── webpage.py               # WebpagePipe(Pipe): trivial readability-style single-page fetch
│   ├── enrich/
│   │   ├── __init__.py
│   │   ├── dedup.py                 # DedupFilter(Filter): URL-hash seen-check against SQLite, drops seen
│   │   ├── semantic.py              # EmbedFilter(Filter): Ollama embedding, attaches vector, caches in SQLite
│   │   └── insight.py               # InsightFilter(Filter): Ollama generate, attaches summary/insight/entities
│   ├── sinks/
│   │   ├── __init__.py
│   │   └── sqlite_sink.py           # SqliteSink(Sink): persists one enriched Article (flat, no interest grouping)
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── clustering.py            # ClusterAnalyzer: groups same-story articles across sources
│   │   ├── novelty.py               # NoveltyAnalyzer: trend/velocity + new-vs-rehash scoring over time
│   │   ├── entities.py              # EntityGraphAnalyzer: builds/updates entity co-occurrence graph
│   │   └── causality.py             # CausalityAnalyzer: LLM pass inferring cause/effect links between stories
│   ├── llm/
│   │   ├── __init__.py
│   │   └── ollama_client.py         # thin wrapper over Ollama HTTP API (generate + embeddings)
│   ├── gather.py                    # builds Pipeline(pipe, filters, sink) from config, runs it once
│   ├── analyze.py                   # builds AnalysisPipeline(analyzers) from config, runs it once over the current window
│   ├── brief.py                     # reads enriched articles + analysis output + interests.yaml → ranks/groups → Brief
│   ├── writer.py                    # validates + atomically writes output/briefs/<ts>.json + latest.json
│   ├── daemon.py                    # scheduler loop (gather / analyze / brief each on their own interval) + signal handling
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
│   └── news_radar.db                # SQLite: articles, embeddings cache, story_clusters, entity graph, causal_links
└── tests/
    ├── test_smoke.py
    ├── test_dedup_filter.py
    ├── test_pipeline.py             # Pipe/Filter/Sink chain wired with fakes
    ├── test_clustering.py
    ├── test_novelty.py
    ├── test_entity_graph.py
    ├── test_causality.py            # fake LLM client, no live Ollama
    ├── test_brief.py                # ranking/grouping against fixture articles + analysis output + interests
    └── fixtures/
        └── sample_feed.xml
```

Design notes:
- `frontend/` is plain static HTML/JS/CSS — no build step, no framework. It only ever
  fetches a JSON file by relative path, so `output/` (JSON) + `frontend/` (SPA) can be
  copied as-is into a GitHub Pages branch/folder later. For local-first use, `output/`
  and `frontend/` are served side-by-side by one dev server (Phase 9).
- `config/` is YAML, hand-edited by the user; `data/` and `output/` are generated and
  gitignored (add `packages/news-radar/data/` and `packages/news-radar/output/*` minus
  `.gitkeep`/`latest.json` sample to root `.gitignore`).
- `gather.py` owns the enrichment `Pipeline`; `analyze.py` owns the cross-article
  `AnalysisPipeline`; `brief.py` owns interest ranking. None duplicates another's job —
  `daemon.py` just calls all three on their own timers, `__main__.py gather` /
  `analyze` / `brief` call them once each.

---

## 3. JSON schema (confirmed)

This is the output of the **brief** stage — the visualization data contract, written
to `output/briefs/<ISO-timestamp>.json` and copied verbatim to `output/latest.json`.
Brief now operates at the **story level** (a cluster of same-story articles from one or
more sources), not the raw-article level, since clustering happens upstream in
analyze:

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
          "entities": ["Entity A", "Entity B"],
          "sources_count": 3,
          "trend_velocity": 0.42,
          "causal_context": [
            {
              "relation": "effect_of",
              "related_title": "Earlier story title",
              "related_url": "https://...",
              "explanation": "1-sentence LLM-generated causal explanation",
              "confidence": 0.6
            }
          ]
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
- `id`: id of the cluster's representative article (stable hash of its canonical URL,
  sha256 hex, truncated) — matches the id gather assigned when it first persisted that
  article.
- `title` / `summary` / `insight` / `entities`: copied from the cluster's
  representative article's enriched record — brief doesn't call the LLM, it only reads
  what gather/analyze already produced. (Choice of "representative article" per
  cluster — e.g. earliest or most-detailed — is a `ClusterAnalyzer` concern, §5.)
- `relevance_score`: float 0.0–1.0, combined keyword + semantic score against this
  interest, computed by the brief stage at render time (not stored).
- `novelty`: enum `new | update | background`, produced by `NoveltyAnalyzer` (§5), not
  the per-article LLM insight pass — it needs cross-article/historical context that a
  single-article `Filter` doesn't have. Defaults to `new` if analysis hasn't run yet.
- `sources_count`: number of distinct sources in this story's cluster — from
  `ClusterAnalyzer`. Omitted/absent, not required, until Phase 4 is built.
- `trend_velocity`: float, relative rate of new same-story articles appearing — from
  `NoveltyAnalyzer`. Optional field, absent until Phase 5 is built.
- `causal_context`: list (possibly empty) of related earlier/later stories this one is
  plausibly caused by or causes, LLM-generated — from `CausalityAnalyzer`. Optional
  field, absent until Phase 7 is built.
- An interest with zero matching items after ranking is **omitted** from `interests`
  (not included as an empty-items entry) — keeps the frontend simple.
- `meta.model` is the Ollama model tag actually used for that article's enrichment
  (traceability if the model changes over time; the brief stage doesn't call the LLM).

This is a `Brief` in `models.py`; `BriefInterest` and `BriefItem` are its nested
shapes. Pydantic models double as the JSON schema and the writer's validation step —
`writer.py` should refuse to write a `Brief` that doesn't validate. The flat `Article`
record gather writes and the `StoryCluster` / `EntityEdge` / `CausalLink` records
analyze writes are separate, simpler shapes — `brief.py` is what turns all of them into
`BriefItem`s.

---

## 4. Python module structure — gather stage

| Module | Responsibility |
|---|---|
| `domain/interfaces.py` | `Filter`, `Pipe`, `Sink` ABCs + generic `Pipeline` that streams `produce → filter chain → consume`. Source-, enrichment-, and storage-agnostic. |
| `config.py` | Load and validate `sources.yaml` + `interests.yaml` into typed objects. Fail fast with a clear error on malformed config. |
| `models.py` | All shared data shapes: `Source`, `Interest`, `Article` (flat, enriched), `StoryCluster`, `EntityEdge`, `CausalLink`, `BriefItem`, `BriefInterest`, `Brief`. |
| `db.py` | SQLite connection + schema for every table: `articles`, `embeddings_cache`, `story_clusters`, `entity_mentions`, `entity_cooccurrence`, `causal_links`. One function per query — no ORM. |
| `ingest/rss.py` | `RssPipe(Pipe)`: given `Source`s, fetch + parse feeds (via `feedparser`), yield raw `Article`s (title/url/published_at/source/raw_content populated, no enrichment yet). |
| `ingest/webpage.py` | `WebpagePipe(Pipe)`: given plain-page `Source`s, fetch HTML, extract main text (e.g. `trafilatura`), yield a single `Article`. |
| `enrich/dedup.py` | `DedupFilter(Filter)`: drop (return `None`) already-seen URLs (by id hash) against the SQLite `articles` table; new items pass through unchanged. |
| `enrich/semantic.py` | `EmbedFilter(Filter)`: embed article text via Ollama embeddings, attach the vector to the `Article`, cache in SQLite keyed by article id. No cross-article comparison here — just attaches data. |
| `enrich/insight.py` | `InsightFilter(Filter)`: build a summarization prompt from the `Article`, call `ollama_client.generate`, attach `summary`, `insight`, `entities` to the `Article`. (`novelty` moves to analyze — see §5.) |
| `sinks/sqlite_sink.py` | `SqliteSink(Sink)`: persist one fully-enriched `Article` into the flat `articles` table (upsert by id). |
| `llm/ollama_client.py` | `generate(prompt, model) -> str` and `embed(text, model) -> list[float]`, talking to local Ollama HTTP API (`localhost:11434`). Timeouts + retries only — no fallback provider (local-first, single-provider by design). |
| `gather.py` | `run_once(config) -> int` (count of new articles): builds `Pipeline(RssPipe/WebpagePipe, [DedupFilter, EmbedFilter, InsightFilter], SqliteSink)` from config and runs it. |

Gather call order:

```
sources.yaml → RssPipe.produce / WebpagePipe.produce → Article (raw)
             → DedupFilter   (drops already-seen, else pass through)
             → EmbedFilter   (attaches embedding vector, cached)
             → InsightFilter (attaches summary/insight/entities)
             → SqliteSink.consume → data/news_radar.db (flat articles table)
```

## 5. Python module structure — analyze stage

| Module | Responsibility |
|---|---|
| `domain/interfaces.py` | `Analyzer` ABC + `AnalysisPipeline` (to add, §1) — batch/cross-article, run over a window of the store rather than one item at a time. |
| `analysis/clustering.py` | `ClusterAnalyzer`: for articles in the window, group same-story articles across sources by embedding-similarity threshold (cosine over the `EmbedFilter` vectors already cached) + title-similarity as a tiebreaker. Writes/updates `story_clusters` (member article ids, representative article id, centroid embedding). Picks a representative article per cluster (e.g. earliest-published or most-detailed by content length) — brief reads title/summary/insight/entities from that one. |
| `analysis/novelty.py` | `NoveltyAnalyzer`: for each cluster, compare its centroid embedding against recent history (rolling window, not just this batch) to classify `novelty` (`new | update | background`) and compute `trend_velocity` (rate of new member articles joining the cluster over time). Writes onto `story_clusters`. |
| `analysis/entities.py` | `EntityGraphAnalyzer`: read each article's LLM-extracted `entities` list (from `InsightFilter`), update `entity_mentions` (entity ↔ article) and `entity_cooccurrence` (entity ↔ entity, incremented when they co-occur in the same article), decaying/aging old edges optionally deferred to a later phase. |
| `analysis/causality.py` | `CausalityAnalyzer`: for clusters that are new/updated in this window, use the entity graph + recency to shortlist plausibly-related earlier clusters, then one LLM call per candidate pair asking for a cause/effect judgement + 1-sentence explanation + confidence; writes accepted links (above a confidence threshold) to `causal_links`. Most expensive analyzer (LLM per candidate pair) — shortlisting via entity overlap keeps the candidate set small. |
| `analyze.py` | `run_once(config) -> None`: builds `AnalysisPipeline([ClusterAnalyzer, EntityGraphAnalyzer, NoveltyAnalyzer, CausalityAnalyzer])` and runs it over the current window (e.g. "articles gathered since analyze last ran," config-driven). Order matters: clustering first (novelty and causality both operate at cluster level), entity graph before causality (causality's shortlisting uses it). |

Analyze call order:

```
data/news_radar.db (enriched articles, window since last analyze run)
             → ClusterAnalyzer     (group same-story articles → story_clusters)
             → EntityGraphAnalyzer (update entity_mentions / entity_cooccurrence)
             → NoveltyAnalyzer     (classify novelty + trend_velocity per cluster)
             → CausalityAnalyzer   (shortlist via entity graph → LLM judge → causal_links)
             → data/news_radar.db (story_clusters, entity graph, causal_links updated)
```

## 6. Python module structure — brief stage

| Module | Responsibility |
|---|---|
| `brief.py` | `build(config) -> Brief`: load recent `story_clusters` (+ representative `Article`, entity/causal context) + `interests.yaml`, score each cluster per interest (keyword substring/regex + semantic cosine against interest seed embedding, weighted combine), take top-N per interest, assemble `Brief` (skip empty interests). No network/LLM calls — everything it needs was already computed by gather/analyze. |
| `writer.py` | Validate + serialize a `Brief` to `output/briefs/<ts>.json`, then write/overwrite `output/latest.json` (same content, stable filename). Atomic write (write to temp, rename). |
| `daemon.py` | Three interval loops: `gather.run_once` (least frequent, network+LLM heavy), `analyze.run_once` (middle — batch/LLM work but cheaper than per-article gather), `brief.build` + `writer.write` (most frequent — pure local compute). Handles SIGTERM/SIGINT for clean shutdown. |
| `__main__.py` | CLI subcommands: `gather`, `analyze`, `brief` (each a single pass), `daemon` (loop all three), `serve` (serve `output/` + `frontend/` on localhost for local viewing). |

Brief call order:

```
data/news_radar.db (story_clusters + articles + entity/causal context) + interests.yaml
             → for each Interest:
                   keyword score + semantic cosine (cluster centroid vs interest seed embedding)
                   → combined score → rank → take top N
             → assemble Brief (skip empty interests)
             → writer.write → output/briefs/<ts>.json + output/latest.json
```

---

## 7. Frontend approach (spec, no code yet)

- `frontend/index.html` + `app.js` + `styles.css`, no build tooling, no framework.
- On load, `app.js` fetches `../output/latest.json` (relative path, so it works
  identically served locally or from GitHub Pages once `output/` and `frontend/` sit
  side by side in the published folder).
- Renders one section per interest (ordered by `priority`: high → medium → low), each
  a heading + list of item cards: title (linked to `url`), summary, insight, source +
  published_at, relevance_score as a small badge, `sources_count` badge ("3 sources")
  when present, `trend_velocity` indicator when present, and `causal_context` entries
  rendered as small "related" links with their explanation, when present.
- Mobile-first CSS: single column, cards stack; a simple `@media (min-width: 768px)`
  bump to a 2-column grid on desktop. System dark/light via `prefers-color-scheme`.
- No routing, no state library — a `<select>` or set of tabs to switch between
  historical briefs (listing `output/briefs/*.json`) is a nice-to-have, deferred.
- All the analysis-derived fields (`sources_count`, `trend_velocity`,
  `causal_context`) are optional in the schema and phased in gradually (§3) — the
  frontend should render fine with none of them present (Phase 3 checkpoint) and pick
  up each one as its analyzer phase lands.

---

## 8. Phased build plan

### Phase 0 — Package scaffold (done)
- [x] `make new NAME=news-radar DESC="..."` → `packages/news-radar` created, synced
      into the uv workspace, builds cleanly.
- [x] First draft of `domain/interfaces.py` (`Filter`/`Pipe`/`Sink`/`Pipeline`).
- Deliverable: empty package that imports and runs (`make run PKG=news-radar`).

### Phase 1 — Config, models, ingest, dedup (gather stage begins)
- Fix the mutable-default-argument bug in `Pipeline.__init__` (§1) and decide/implement
  the `Filter` "drop via `None`" convention needed by dedup.
- Add deps: `feedparser`, `pyyaml`, `pydantic`, `trafilatura` (webpage extraction).
- `config.py` + `config/sources.yaml` + `config/interests.yaml` (2-3 sample entries
  each) — load and validate. `interests.yaml` isn't consumed until Phase 8, but
  validating it early catches config errors sooner.
- `models.py` — `Source`, `Interest`, `Article` (raw + slots for enrichment fields).
- `db.py` — SQLite schema for the flat `articles` table.
- `ingest/rss.py` — `RssPipe` parsing a feed URL into an `Article` stream.
- `enrich/dedup.py` — `DedupFilter`, hash-based seen-check against SQLite.
- `sinks/sqlite_sink.py` — `SqliteSink` persisting raw (not-yet-enriched-further)
  `Article`s.
- `gather.py` + `__main__.py gather` subcommand — runs `Pipeline(RssPipe, [DedupFilter],
  SqliteSink)`, prints count of new articles.
- Tests: `test_dedup_filter.py`, `test_pipeline.py` (fake `Pipe`/`Sink`), a fixture RSS
  XML file, ingest→dedup round-trip.
- Deliverable: `news-radar gather` against real feeds prints new-article counts,
  re-running immediately after shows 0 new (dedup works).

### Phase 2 — Semantic enrichment
- `enrich/semantic.py` — `EmbedFilter`: Ollama embeddings, attaches vector to
  `Article`, cached in SQLite `embeddings_cache` (keyed by article id) so re-runs don't
  re-embed unchanged articles.
- Add `EmbedFilter` to the gather `Pipeline` filter list.
- Tests: stubbed embedding function (no live Ollama dependency in CI).
- Deliverable: gathered articles carry a cached embedding vector; still no
  cross-article or interest logic anywhere.

### Phase 3 — LLM insight generation
- `llm/ollama_client.py` — `generate` + `embed` against local Ollama.
- `enrich/insight.py` — `InsightFilter`: prompt template producing summary/insight/
  entities as parseable (JSON-mode or structured-prompt) output; graceful fallback if
  parsing fails (log + skip enrichment for that item rather than crash the run —
  dedup/embed still succeed, insight fields stay empty).
- Add `InsightFilter` to the gather `Pipeline` filter list.
- Tests: `test_pipeline.py` extended with a fake LLM client (no live Ollama needed).
- Deliverable: `news-radar gather` produces fully-enriched flat article records in
  `data/news_radar.db` from real feeds through a local Ollama model. Gather stage is
  now complete end to end.

### Phase 4 — Analysis stage begins: story clustering
- Add `Analyzer` + `AnalysisPipeline` to `domain/interfaces.py` (§1).
- `models.py` — add `StoryCluster`.
- `db.py` — `story_clusters` table.
- `analysis/clustering.py` — `ClusterAnalyzer`: embedding-similarity grouping across
  sources, representative-article selection.
- `analyze.py` + `__main__.py analyze` subcommand — runs
  `AnalysisPipeline([ClusterAnalyzer])` over articles gathered since analyze last ran.
- Tests: `test_clustering.py` with fixture articles (near-duplicate titles/embeddings
  from different sources) → expect one cluster.
- Deliverable: `news-radar analyze` groups multi-source coverage of the same story
  into one cluster; single-source stories become one-member clusters.

### Phase 5 — Entity graph
- `models.py` — add `EntityEdge` (or equivalent mention/co-occurrence shapes).
- `db.py` — `entity_mentions`, `entity_cooccurrence` tables.
- `analysis/entities.py` — `EntityGraphAnalyzer`, reading `Article.entities` (already
  populated since Phase 3) and updating the graph incrementally.
- Add `EntityGraphAnalyzer` to the `AnalysisPipeline`, after clustering.
- Tests: `test_entity_graph.py` — repeated co-occurring entities across fixture
  articles produce/strengthen an edge.
- Deliverable: entity co-occurrence graph updates on every `analyze` run; not yet used
  by anything downstream (that's Phase 7).

### Phase 6 — Novelty / trend detection
- `db.py` — novelty/trend columns on `story_clusters` (or a companion table).
- `analysis/novelty.py` — `NoveltyAnalyzer`: classify `new | update | background`
  against rolling history, compute `trend_velocity`.
- Add `NoveltyAnalyzer` to the `AnalysisPipeline`, after clustering (needs clusters,
  not raw articles).
- Tests: `test_novelty.py` — a cluster reappearing across fixture "runs" should
  transition `new → update`; a burst of new members should raise `trend_velocity`.
- Deliverable: `story_clusters` carry novelty + trend data after each `analyze` run.

### Phase 7 — LLM causal linking
- `models.py` — add `CausalLink`.
- `db.py` — `causal_links` table.
- `analysis/causality.py` — `CausalityAnalyzer`: entity-graph-based shortlisting of
  candidate related clusters, one LLM judgement call per candidate pair
  (cause/effect/unrelated + explanation + confidence), persist links above a
  confidence threshold.
- Add `CausalityAnalyzer` to the `AnalysisPipeline`, last (depends on clustering +
  entity graph).
- Tests: `test_causality.py` with a fake LLM client returning canned judgements — no
  live Ollama needed, confidence-threshold filtering covered.
- Deliverable: `news-radar analyze` produces `causal_links` for plausibly related
  clusters. Analysis stage is now complete end to end.

### Phase 8 — Brief stage (interest ranking, consumes gather + analyze output)
- `models.py` — add `BriefItem`, `BriefInterest`, `Brief` (pydantic, matching the
  schema in §3, including the optional `sources_count` / `trend_velocity` /
  `causal_context` fields).
- `brief.py` — load `story_clusters` (+ representative article, entity/causal context)
  + `interests.yaml`, keyword + semantic-cosine score per interest, top-N ranking,
  `Brief` assembly.
- `writer.py` — validated, atomic write of `output/briefs/<ts>.json` + `latest.json`.
- `__main__.py brief` subcommand — single rank/render pass over already-gathered and
  already-analyzed data.
- Tests: `test_brief.py` with fixture clusters (incl. novelty/trend/causal fields) +
  `interests.yaml`, no live Ollama or network needed.
- Deliverable: `news-radar gather` then `news-radar analyze` then `news-radar brief`
  (re-runnable independently, even after editing `interests.yaml`) produces a
  schema-correct `output/latest.json`.

### Phase 9 — Frontend + local serving
- `frontend/index.html`, `app.js`, `styles.css` per §7.
- `__main__.py serve` subcommand — trivial local HTTP server (stdlib
  `http.server.ThreadingHTTPServer`, no extra dep) rooted so both `frontend/` and
  `output/` are reachable, opens to `index.html`.
- Manual check: load in a desktop browser and a phone (or responsive dev tools),
  confirm grouping/readability at both widths, and that analysis-derived badges
  (sources count, trend, causal context) render correctly.
- Deliverable: `news-radar serve` → open `localhost:PORT` → see the current brief.

### Phase 10 — Daemon mode
- `daemon.py` — three interval loops (config-driven `gather_interval_minutes`,
  `analyze_interval_minutes`, `brief_interval_minutes`, in decreasing cost/increasing
  frequency order), calls `gather.run_once` / `analyze.run_once` / `brief.build` +
  `writer.write` on their own ticks, structured logging via `logging_conf.py`, clean
  SIGTERM/SIGINT shutdown.
- `__main__.py daemon` subcommand.
- Optional: a short systemd user-unit example in `README.md` for "run on laptop
  startup / on a schedule" (documentation only, not shipped as a file, since it's
  machine-specific).
- Deliverable: `news-radar daemon` runs indefinitely, refreshing `output/latest.json`
  on its own (cheapest, most frequent) schedule, analyzing on a middle cadence, and
  gathering on the least frequent (most expensive) one; `news-radar serve` in parallel
  always shows current data.

### Phase 11 — GitHub Pages readiness (no pipeline changes)
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
- No historical-brief browsing UI beyond `latest.json` (deferred nicety in Phase 9 notes).
- No retries/backoff frameworks — simple try/except + log/skip is enough at personal-tool scale.
- No interest/relevance logic inside gather or analyze — enrichment filters only ever
  add data to an article, analyzers only ever compute cross-article structure; neither
  knows what the user is interested in. That's the brief stage's job exclusively.
- No entity-graph decay/pruning, no clustering re-merge across old windows, no
  causal-link confidence recalibration over time — v1 analyzers run once per window and
  persist their output; revisiting old conclusions is future work if it turns out to
  matter in practice.
