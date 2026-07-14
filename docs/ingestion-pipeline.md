# Ingestion Pipeline

An ingestion run follows these stages:

1. Load and validate `data/sources.yaml`. Both the milestone field names (`ats_type`, `ats_slug`, and high/medium/low priority) and the original project field names remain accepted.
2. Select an explicitly requested source, or all enabled sources whose `next_due_at` has passed.
3. Create `scrape_runs` and per-source `scrape_source_runs` records for a real run. Dry runs create no records.
4. Fetch through the shared adapter interface with a global concurrency bound. Requests use configurable timeouts and retry transient network, timeout, rate-limit, and server failures with exponential backoff.
5. Normalize ATS fields into `NormalizedJob`, including posting/apply URLs, HTML/plain descriptions, timestamps, and raw JSON.
6. Apply title-only include, role-group, exclude, level, freshness, location/work-type, and source-priority scoring.
7. Deduplicate in layers: source plus external ID, canonical apply URL, then the uncertain company/title/location signal. Uncertain matches remain separate and create an open duplicate review.
8. Compare normalized fields for a stable-identity match. Insert new jobs, update materially changed jobs, and count unchanged jobs without rerunning version, match, duplicate-review, or notification writes. Unchanged jobs update only observation metadata such as `last_seen_at`. A changed description hash creates a `job_versions` row, raw JSON receives a 60-day retention timestamp, and the user's `job_matches` row is refreshed.
9. Reset the miss counter for observed postings. Unseen postings increment their counter and become inactive only after 12 consecutive successful source runs. Reappearing inactive postings are reactivated and stamped as reposted.
10. Finalize source health/due state and aggregate fetched, inserted, updated, unchanged, closed, duplicate, error, and duration metrics.

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
```

The repository’s default registry contains one public example for each supported ATS. Tests never call those boards; they use `tests/fixtures/*.json` and adapter overrides.

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
```

The CLI prints a JSON summary with per-source and aggregate fetched, inserted, updated, unchanged, closed, duplicate, error, and duration values. The same operations are available at `POST /admin/ingestion/run` and `POST /admin/ingestion/run-source/{source_id}`. Historical data is available from `GET /admin/scrape-runs` and `GET /admin/scrape-runs/{run_id}/sources`.

## Environment variables

- `DATABASE_URL`
- `HUNT_BOARD_SOURCES_PATH`
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS` (default `10`)
- `HUNT_BOARD_SOURCE_CONCURRENCY` (default `5`)
- `HUNT_BOARD_HTTP_MAX_RETRIES` (default `2`)
- `HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS` (default `0.5`)

This project uses PostgreSQL and Alembic, not Supabase. Schema changes are applied with `uv run alembic upgrade head`.
