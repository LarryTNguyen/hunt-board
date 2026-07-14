# Hunt Board

Hunt Board is a backend-first job intelligence and personal job-search CRM. Milestone 1 ingests and ranks curated Greenhouse, Lever, and Ashby jobs. Milestone 2 adds richer job browsing, editable matching preferences and rescoring, saved jobs, application tracking and event timelines, an in-app notification inbox, and actionable duplicate review APIs.

## Quick start with Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose starts PostgreSQL on host port `55432` and the API on `http://127.0.0.1:8000`. Backend startup applies migrations and idempotently seeds the admin user, default preferences, application statuses, and YAML sources.

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/db
Invoke-RestMethod http://127.0.0.1:8000/admin/sources
```

## Local Python setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --dev
Copy-Item .env.example .env
docker compose up -d postgres
uv run alembic upgrade head
uv run hunt-board seed
uv run uvicorn hunt_board.main:app --reload
```

## Configuration

- `DATABASE_URL`: SQLAlchemy PostgreSQL URL. The host default uses port `55432`.
- `HUNT_BOARD_SOURCES_PATH`: YAML source registry path; defaults to `data/sources.yaml`.
- `HUNT_BOARD_DEFAULT_USER_EMAIL`: seeded single-user admin email.
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS`: per-request ATS timeout; defaults to `10`.
- `HUNT_BOARD_SOURCE_CONCURRENCY`: maximum ATS sources fetched at once; defaults to `5`.
- `HUNT_BOARD_HTTP_MAX_RETRIES`: retries for timeouts, network failures, HTTP 408/429, and HTTP 5xx responses; defaults to `2`.
- `HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS`: base exponential retry delay; defaults to `0.5`.

The source registry supports the milestone shape (`company_name`, `careers_url`, `ats_type`, `ats_slug`, high/medium/low `priority`, `enabled`, `categories`, and `notes`) and the existing explicit `config` shape. ATS slugs are always manually configured; no scraping-based ATS detection is performed.

## Database and source commands

```powershell
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run hunt-board seed
uv run hunt-board sync-sources
```

## Ingestion commands

Dry run all enabled, due sources without database writes:

```powershell
uv run hunt-board ingest --dry-run
```

Run all enabled, due sources or force one configured source by slug:

```powershell
uv run hunt-board ingest
uv run hunt-board ingest --source discord
```

The equivalent API operations are `POST /admin/ingestion/run` and `POST /admin/ingestion/run-source/{source_id}`. The request body for the first endpoint is `{"source_slugs": ["discord"], "dry_run": true}`.

Source fetches run concurrently, while SQLAlchemy writes remain serial and transaction-isolated. Repeated postings are reported as `unchanged_jobs`; only new or materially changed postings count toward `total_upserted`. Running without `--source` scans only enabled sources that are due. Passing `--source` forces that configured source for local validation.

## API surface

- `GET /health` and `GET /health/db`
- `GET /jobs` and `GET /jobs/{job_id}`
- `GET/PATCH /me/preferences` and `POST /me/preferences/rescore`
- `GET /saved-jobs`, `POST/DELETE /jobs/{job_id}/save`, and `PATCH /saved-jobs/{saved_job_id}`
- `GET /application-statuses`
- `GET /applications`, `POST /jobs/{job_id}/applications`, and `GET/PATCH /applications/{application_id}`
- `GET/POST /applications/{application_id}/events`
- `GET /notifications`, `PATCH /notifications/{notification_id}/read`, and `POST /notifications/read-all`
- `GET /admin/sources`
- `POST /admin/sources/sync-from-yaml`
- `GET /admin/scrape-runs` and `GET /admin/scrape-runs/{run_id}`
- `POST /admin/ingestion/run`
- `POST /admin/ingestion/run-source/{source_id}`
- `GET /admin/duplicates`
- `PATCH /admin/duplicates/{duplicate_review_id}`

Legacy `/api/jobs`, `/api/admin/*`, and `/api/ingest/run` paths remain available.

`GET /jobs` remains a list response for Milestone 1 compatibility and now accepts `limit`/`offset`, filters for source/company/location/workplace/score/saved/application state, duplicate controls, and documented sort fields. Active jobs ranked by score remain the default, with confirmed duplicates excluded.

## Milestone 2 workflow examples

```powershell
# Update canonical preferences, then rescore stored jobs.
Invoke-RestMethod -Method Patch http://127.0.0.1:8000/me/preferences `
  -ContentType application/json `
  -Body '{"include_keywords":["backend engineer","python"],"minimum_score_threshold":65}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/me/preferences/rescore

# Save a job and create an application. Both create operations are idempotent.
Invoke-RestMethod -Method Post http://127.0.0.1:8000/jobs/1/save `
  -ContentType application/json -Body '{"notes":"Review this week"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/jobs/1/applications `
  -ContentType application/json -Body '{"notes":"Submitted through company site"}'

# Advance an application; status changes automatically append a timeline event.
Invoke-RestMethod -Method Patch http://127.0.0.1:8000/applications/1 `
  -ContentType application/json `
  -Body '{"status":"interview-scheduled","status_note":"Recruiter screen booked"}'

# Read the in-app inbox and mark it read.
Invoke-RestMethod 'http://127.0.0.1:8000/notifications?unread=true'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/notifications/read-all
```

## Tests

Tests are offline and use saved ATS JSON fixtures plus an in-memory SQLite database:

```powershell
uv run pytest
```

See [architecture](docs/architecture.md), [Milestone 2 workflows](docs/milestone-2.md), and [ingestion pipeline](docs/ingestion-pipeline.md) for design details.
