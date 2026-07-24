# Milestone 3.5: Ingestion hardening and adapter-readiness bridge

Milestone 3.5 is a focused hardening pass over the existing Milestones 1-3 implementation. It does not add Workday or replace the current ingestion pipeline, models, run tables, source registry, APIs, or vanilla-JavaScript frontend.

## Goal and implemented contracts

- One adapter registry owns the Greenhouse, Lever, and Ashby keys and factories. YAML source validation uses those keys, source-slug test overrides remain supported, and each adapter raises `AdapterError` for missing required configuration before making a request.
- External ATS HTML is sanitized at normalization and again at the ingestion boundary using an `lxml` allowlist. Formatting tags and safe `http`, `https`, and `mailto` links remain; active elements, unsafe schemes, event attributes, and embedded content are removed. Normalized postings and versions receive identical safe descriptions, while original payloads remain unchanged in `raw_json`.
- Real ingestion is mutually exclusive. PostgreSQL uses a session advisory lock on a dedicated connection; SQLite uses an injectable local/fake lock. Contention creates no `scrape_runs` row or domain writes, produces API `409`, and exits the CLI nonzero. Dry runs do not lock.
- Unexpected exceptions finalize the persisted run as `failed` with `error_message`, `finished_at`, and duration. After acquiring the lock, startup recovery changes stale `running` run/source-run rows to `abandoned`. The threshold is configured with `HUNT_BOARD_STALE_RUN_MINUTES`.
- Sources accept optional `poll_interval_minutes` and `close_after_missed_runs`. Existing YAML preserves the exact priority cadence (6/12/24 hours) and a 12-successful-miss closure default. Successful empty boards advance misses; failed boards never do.
- `purge-expired-raw` reports and replaces expired posting/version payloads with `{}`, clears expiration markers, preserves normalized and CRM data, supports dry run, and is idempotent.
- `GET /jobs?search=` trims whitespace and searches title, company, location, and normalized description text while preserving the list response, sorting, limit, and offset contracts. The frontend continues rendering descriptions as text and validates external URL schemes.
- `GET /health/ingestion` returns HTTP 200 with `ok`, `degraded`, or `stale`, active-run state, last-run summary, last successful completion, and aggregate due/unhealthy/stale counts without exposing configuration or payloads.

## Persistent changes

Migration `202607220008` adds `sources.poll_interval_minutes`, `sources.close_after_missed_runs`, and `scrape_runs.error_message`. Existing sources are backfilled using the priority cadence, closure defaults to 12, and downgrade removes only these fields.

## Operational commands

```powershell
uv run alembic upgrade head
uv run hunt-board sync-sources
uv run hunt-board ingest --dry-run
uv run hunt-board ingest
uv run hunt-board purge-expired-raw --dry-run
uv run hunt-board purge-expired-raw
uv run pytest
```

## Deliberate exclusions

This bridge does not add Workday, rendered-page scraping, an internal scheduler, Celery/Redis or another queue, full-text search, a new pagination envelope, a frontend redesign, multi-user authentication, resume/AI features, external notifications, or deployment automation.

## Workday-readiness gate

A future adapter can be added with one registry entry, opaque per-source configuration, clear config errors, multiple requests behind the existing `fetch_jobs` contract, source-specific policy, centralized sanitization, production locking/recovery, and fixture-injected tests. No Workday network contract is implemented here.
