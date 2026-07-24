# Milestone 4: Self-refreshing discovery and operations

Milestone 4 turns the existing single-user live product into a continuously operable job-discovery system. It preserves all Milestones 1–3.5 contracts and does not add Workday, browser automation, a task queue, or a frontend build system.

## Delivered product contracts

- `GET /jobs` remains the backward-compatible list response. `GET /jobs/feed` adds a typed envelope with `items`, `total`, `limit`, `offset`, `has_more`, `generated_at`, and server-derived facets.
- Feed filters cover search, active state, company, source, ATS, location, country, workplace type, salary availability, saved/discarded state, application status/state, remote-only, score, posting age, sort, pagination, and duplicate inclusion.
- Facets for ATS, source, country, workplace type, and salary availability are self-excluding: each facet applies every active filter except its own selection.
- PostgreSQL uses `websearch_to_tsquery('english', ...)` against a stored generated `tsvector`. Title and company receive the highest weight, location and department a medium weight, and normalized description text a lower weight. SQLite tests use deterministic weighted substring matching over the same logical fields.
- `/app/job-discovery.html` uses server pagination and facets. Search, filters, sort, page offset, view tab, and selected job are URL state. Refresh and browser back/forward restore the feed and observation drawer; direct `job=<id>` links fetch jobs outside the current page.
- Discovery shows ingestion freshness from `GET /health/ingestion` without blocking the feed when health data is unavailable.
- `hunt-board scheduler` is a separate, signal-aware process. It invokes the existing due-source ingestion service at a validated interval, uses the Milestone 3.5 lock, skips lock contention, and continues after failed ticks.
- `GET /admin/operations` aggregates ingestion state, source counts and safe source health fields, job counts, and a ten-run history window. Raw payloads and source configuration JSON are excluded.
- `/app/operations.html` shows system status, source policy/health, recent run metrics, due-source actions, per-source dry/real actions, and YAML sync. Real runs require confirmation and `409` lock conflicts are shown in plain language.
- `GET /health/live` is process liveness. `GET /health/ready` verifies database connectivity and required tables. Existing health routes remain unchanged.

## Database migration

Revision `202607220009` follows the Milestone 3.5 head. PostgreSQL receives a generated `job_postings.search_vector` and GIN index `ix_job_postings_search_vector_gin`. Generated storage automatically reflects updates to title, company, location, department, and description.

The migration also adds focused indexes for the default feed path, source joins/due selection, and recent-run operations reads:

- `ix_job_postings_feed_default(active, duplicate_status, ranking_score, id)`
- `ix_job_postings_source_id(source_id)`
- `ix_sources_enabled_next_due(enabled, next_due_at)`
- `ix_scrape_runs_started_status(started_at, status)`

## Runtime topology

```text
web process        -> FastAPI/uvicorn; owns Compose migration + idempotent seed startup
scheduler process  -> hunt-board scheduler; exactly one intended replica
postgres           -> source of truth and advisory-lock owner
platform cron      -> optional production alternative invoking hunt-board ingest
```

The scheduler never starts inside FastAPI. The optional Compose profile waits for the migrated, ready backend before starting, so only the backend owns startup migrations. The advisory lock remains mandatory even with one intended scheduler replica because manual/API/cron runs share the same write path.

## Configuration and commands

```powershell
uv run alembic upgrade head
uv run hunt-board seed
uv run hunt-board ingest
uv run hunt-board scheduler
docker compose --profile scheduler up --build
```

Scheduler variables are `HUNT_BOARD_SCHEDULER_ENABLED` (default `true`), `HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS` (default `300`, minimum `10`), and `HUNT_BOARD_SCHEDULER_RUN_ON_STARTUP` (default `true`). Production platforms should prefer cron invoking the one-shot `hunt-board ingest` command when they already provide reliable scheduling.

## Verification

The offline suite covers feed defaults, counts, pagination, structured and application filters, posting age, self-excluding facets, description search, fallback relevance, legacy compatibility, operations aggregates, scheduler failure/lock/shutdown behavior, health routes, and static page contracts.

Optional PostgreSQL verification is marked `postgres` and requires an explicit test database:

```powershell
$env:HUNT_BOARD_TEST_POSTGRES_URL='postgresql+psycopg://hunt_board:hunt_board@localhost:55432/hunt_board'
uv run pytest -m postgres tests/test_milestone_four_postgres.py
```

That check applies Alembic head, verifies the GIN index, title/description matching, relevance order, a combined structured filter, and advisory-lock exclusion across two connections.

## Deliberate boundaries

Milestone 4 remains single-user and supports Greenhouse, Lever, and Ashby only. It uses offset pagination rather than cursor pagination. It does not add Workday, OAuth/RBAC, resume or generative features, external notifications, Celery/Redis, OpenSearch/Elasticsearch, or React/npm tooling.

## Milestone 4.1 handoff

Workday should be a focused adapter milestone using explicit board host/tenant/site/locale configuration, multi-board fixture recordings, list/detail pagination, request throttling and partial-failure behavior, multi-location/date normalization, offline tests, and a monitored feature-flagged rollout. Browser automation and host guessing remain out of scope.
