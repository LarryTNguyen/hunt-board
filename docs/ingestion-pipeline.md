# Ingestion Pipeline

An ingestion run follows these stages:

1. Load and validate `data/sources.yaml`. Both the milestone field names (`ats_type`, `ats_slug`, and high/medium/low priority) and the original project field names remain accepted.
2. Select an explicitly requested source, or all enabled sources whose `next_due_at` has passed.
3. For a real run, atomically acquire the ingestion lock, recover stale run records, and create `scrape_runs`. Dry runs take no lock and create no records.
4. Fetch through adapters registered in the central adapter registry with a global concurrency bound. Requests use configurable timeouts and retry transient network, timeout, rate-limit, and server failures with exponential backoff. Workday additionally establishes a complete stable listing before its bounded detail phase.
5. Normalize ATS fields into `NormalizedJob`, including the ATS-provided publication timestamp when available, sanitize external HTML with a conservative allowlist, derive safe plain text, and retain the unchanged original payload in `raw_json`. `posted_at` is never synthesized from Hunt Board's `first_seen_at`; Greenhouse uses `first_published`, Lever uses `createdAt` when present, Ashby uses `publishedAt`, and Workday uses its exact `startDate` or bounded public relative posting label.
6. Apply title-only include, role-group, exclude, level, freshness, location/work-type, and source-priority scoring.
7. Deduplicate in layers: source plus external ID, canonical apply URL, then the uncertain company/title/location signal. Uncertain matches remain separate and create an open duplicate review.
8. Compare normalized fields and the stored description hash for a stable-identity match. Insert new jobs, update materially changed jobs, and count unchanged jobs without rerunning version, match, duplicate-review, notification, or raw-payload writes. Unchanged jobs update only observation metadata such as `last_seen_at`. A changed description hash creates a normalized `job_versions` row, the posting raw JSON receives a seven-day retention timestamp, and the user's `job_matches` row is refreshed.
9. Reset the miss counter for observed postings. Unseen postings increment their counter and become inactive only after the source's effective `close_after_missed_runs` successful observations. Reappearing inactive postings are reactivated and stamped as reposted. Failed scans never advance misses.
10. Finalize source health/due state using its effective `poll_interval_minutes` and aggregate fetched, inserted, updated, unchanged, closed, duplicate, error, and duration metrics. Unexpected failures finalize the run as `failed`; startup recovery marks stale rows `abandoned`.

Dry-run mode executes fetch, normalization, database-aware dedupe checks, and ranking but does not mutate sources, jobs, matches, reviews, or scrape metrics.

Failures are isolated to one source through a database savepoint. Other configured sources continue, and unhealthy sources retain `last_checked_at`, `last_error`, and a delayed next attempt. A successful scan clears the prior error and records `last_successful_at`.

## Adapter and source configuration

Every adapter implements `fetch_jobs(source) -> list[NormalizedJob]`. Stable ATS job IDs are the primary identity. Add sources to `data/sources.yaml` with one of these identifiers:

```yaml
sources:
  - slug: example-greenhouse
    name: Example Greenhouse
    ats: greenhouse
    company_name: Example Company
    poll_interval_minutes: 60
    close_after_missed_runs: 12
    config:
      board_token: company-board-token

  - slug: example-lever
    name: Example Lever
    ats: lever
    company_name: Example Company
    config:
      site: company-lever-slug

  - slug: example-ashby
    name: Example Ashby
    ats: ashby
    company_name: Example Company
    config:
      organization: company-ashby-slug

  - slug: example-workday
    name: Example Workday
    ats: workday
    company_name: Example Company
    careers_url: https://example.invalid.myworkdayjobs.com/en-US/External
    enabled: false
    poll_interval_minutes: 360
    close_after_missed_runs: 12
    config:
      host: example.invalid.myworkdayjobs.com
      tenant: example
      site: External
      locale: en-US
      page_size: 20
      detail_concurrency: 3
      request_interval_ms: 200
      max_jobs: 5000
```

The repository's default registry keeps the owner's three existing enabled sources unchanged and does not invent a live Workday employer. Workday examples remain disabled placeholders in documentation. Tests never call live boards; they use `tests/fixtures/*.json`, route-aware transports, and adapter overrides.

Both policy fields are optional. Omitted closure policy defaults to 12 successful misses. Omitted cadence preserves the prior priority mapping exactly: priority 5 is 360 minutes, priority 3-4 is 720 minutes, and priority 0-2 is 1440 minutes. Effective values are persisted on `sources` and returned by the admin API.

### Workday complete-scan boundary

Workday listing requests are read-only JSON POSTs. Pages are fetched sequentially from offset zero, with an authoritative first-page nonnegative total, unique validated `/job/` paths, a derived maximum page count, and no early empty page. A later nonempty page may use Workday's observed `total: 0` sentinel; any other total change is rejected, and completion still requires exactly the first-page total. A possibly churn-related integrity failure retries the entire listing once. A repeated inconsistency or `max_jobs` breach fails without truncation.

Only after the listing is complete does a fixed-size worker pool fetch detail JSON. Request starts honor source pacing, transient errors use the shared retry policy, and valid `Retry-After` values for 429/503 are capped at 30 seconds. Details remain in listing order. A 404, 410, or explicit `posted: false` triggers at most one fresh complete listing. Paths that disappeared are omitted, newly listed paths are fetched, and individually identified paths that remain unavailable are returned as skipped in a non-authoritative partial result.

Complete jobs from either a complete or partial adapter result enter the normal sanitizer, dedupe, and ranking path. A partial result is recorded as `completed_with_errors`, includes its skipped count and warning, marks source health unhealthy, and may upsert complete jobs. It never increments missed-run counters or closes existing jobs. Listing integrity failures, non-withdrawal detail failures, parsing errors, and access denial remain atomic source failures that cannot persist a subset. Every default Workday test uses route-aware local fixtures and no live network.

## Incremental identity and change detection

Identity is evaluated conservatively in this order:

1. Same source plus stable external job ID: update that posting.
2. Same canonical apply URL: reuse the normalized posting and record the duplicate signal.
3. Same company, normalized title, and normalized location: keep a separate posting and open a duplicate review.

After an identity match, the service compares normalized title, location, department, employment/workplace type, URLs, descriptions, ATS timestamps, active state, and ranking output. A stable job with the same values is counted as unchanged. Raw payload differences alone do not force a material update because ATS payloads may contain volatile, non-job fields; the latest raw payload and observation timestamps are still refreshed.

## Running and inspecting scans

Apply the PostgreSQL migration and synchronize YAML sources:

```powershell
uv run alembic upgrade head
uv run hunt-board sync-sources
```

Validate all due sources without writes, run all due sources, or force one source:

```powershell
uv run hunt-board ingest --dry-run
uv run hunt-board ingest
uv run hunt-board ingest --source discord
uv run hunt-board purge-expired-raw --dry-run
uv run hunt-board purge-expired-raw
```

The CLI prints a JSON summary with per-source and aggregate fetched, inserted, updated, unchanged, closed, duplicate, error, and duration values. The same operations are available at `POST /admin/ingestion/run` and `POST /admin/ingestion/run-source/{source_id}`. Historical data is available from `GET /admin/scrape-runs` and `GET /admin/scrape-runs/{run_id}/sources`.

`GET /health/ingestion` returns `ok`, `degraded`, or `stale` plus aggregate run/source state. A degraded body still returns HTTP 200. The endpoint never exposes source configuration or raw payloads.

## Scheduled runs

`uv run hunt-board ingest` remains the canonical one-shot unit of work. Without an explicit source it selects only enabled due sources inside `IngestionService`; when none are due it exits successfully without creating an empty run record. Platform cron should invoke this command directly when available.

`uv run hunt-board scheduler` provides a lightweight separate-process loop for local Docker and simple single-host deployments. It optionally runs one tick at startup, then calls the same one-shot service at `HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS`. It does not maintain alternate due-time state or launch per-source tasks. Advisory-lock contention is logged as a skipped tick, source/run failures do not terminate the loop, and SIGINT/SIGTERM request a clean exit.

The Compose `scheduler` profile waits for the backend readiness check, leaving Alembic migration and idempotent seed ownership with the backend container. Only one scheduler replica is intended; the global lock still protects concurrent API, CLI, cron, and scheduler triggers.

## Environment variables

- `DATABASE_URL`
- `HUNT_BOARD_SOURCES_PATH`
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS` (default `10`)
- `HUNT_BOARD_SOURCE_CONCURRENCY` (default `5`)
- `HUNT_BOARD_HTTP_MAX_RETRIES` (default `2`)
- `HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS` (default `0.5`)
- `HUNT_BOARD_STALE_RUN_MINUTES` (default `120`, minimum `5`)
- `HUNT_BOARD_SCHEDULER_ENABLED` (default `true`)
- `HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS` (default `300`, minimum `10`)
- `HUNT_BOARD_SCHEDULER_RUN_ON_STARTUP` (default `true`)

This project uses PostgreSQL and Alembic, not Supabase. Schema changes are applied with `uv run alembic upgrade head`.
