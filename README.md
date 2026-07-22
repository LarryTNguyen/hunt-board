# Hunt Board

Hunt Board is a backend-first job intelligence and personal job-search CRM. Milestone 1 ingests and ranks curated Greenhouse, Lever, and Ashby jobs. Milestone 2 adds the single-user workflow APIs. Milestone 3 serves a live, responsive field-desk frontend from FastAPI for discovery, saved jobs, application tracking, notifications, preferences, and duplicate review.

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

### Live frontend

Start the API, then open `http://127.0.0.1:8000/app/`. The live frontend is served by
FastAPI from `src/hunt_board/web/static/`, uses same-origin API requests, and has no npm
dependencies or frontend build step.

The files in `mock-designs/` are the archived static visual reference. Their sample rows and
preview interactions do not persist. The pages under `/app/` are the live product and read or
write the database through the existing FastAPI routes.

The normal seed command intentionally creates only the single-user defaults, statuses, and
configured sources. To populate job data, run fixture-backed tests for development or ingest
configured ATS sources with `uv run hunt-board ingest`; Milestone 3 does not silently insert
demo records.

## Configuration

- `DATABASE_URL`: SQLAlchemy PostgreSQL URL. The host default uses port `55432`.
- `HUNT_BOARD_SOURCES_PATH`: YAML source registry path; defaults to `data/sources.yaml`.
- `HUNT_BOARD_DEFAULT_USER_EMAIL`: seeded single-user admin email.
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS`: per-request ATS timeout; defaults to `10`.
- `HUNT_BOARD_SOURCE_CONCURRENCY`: maximum ATS sources fetched at once; defaults to `5`.
- `HUNT_BOARD_HTTP_MAX_RETRIES`: retries for timeouts, network failures, HTTP 408/429, and HTTP 5xx responses; defaults to `2`.
- `HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS`: base exponential retry delay; defaults to `0.5`.

The source registry supports the milestone shape (`company_name`, `company_logo_url`, `careers_url`, `ats_type`, `ats_slug`, high/medium/low `priority`, `enabled`, `categories`, and `notes`) and the existing explicit `config` shape. `company_logo_url` is the authoritative logo; the frontend falls back to company initials if it is absent or fails to load. ATS slugs are always manually configured; no scraping-based ATS detection is performed.

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
- `GET /discarded-jobs` and `POST/DELETE /jobs/{job_id}/discard`
- `GET /application-statuses`
- `GET /applications`, `POST /jobs/{job_id}/applications`, and `GET/PATCH /applications/{application_id}`
- `DELETE /applications/{application_id}` to remove an accidentally tracked application and its events
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

`GET /jobs` remains a list response for Milestone 1 compatibility and now accepts `limit`/`offset`, filters for source/company/location/country/workplace/salary availability/score/saved/discarded/application state, duplicate controls, and documented sort fields. Use `country=US` (ISO alpha-2) or `country=United States`, and `salary_known=true|false`, for the normalized filters. Active jobs ranked by score remain the default, with confirmed duplicates and discarded jobs excluded. Use `discarded=true` or `GET /discarded-jobs` to review the discard pile; deleting the per-user discard record restores the job without deleting its normalized posting.

Job responses expose `location_country_code`, `location_country`, `salary_min`, `salary_max`, `salary_currency`, `salary_interval`, and `company_logo_url`. Country values come from explicit ATS fields first, then conservative location parsing. Salary values are normalized only from explicit ATS compensation structures; Hunt Board does not infer pay from prose.

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

## Static product mockups

The responsive, backend-free product concept lives in `mock-designs/`. Open
`mock-designs/index.html` in a browser, then use **Open product mockups** to enter the
cross-linked discovery, job detail, saved jobs, application tracker, notifications,
preferences, and duplicate-review pages. The controls use sample data and lightweight local
JavaScript only; they do not call the API or persist changes.

## Milestone 3 manual QA

After the quick-start commands and at least one ingestion run:

1. Open `/app/` and follow the live navigation on both desktop and a narrow viewport.
2. In Discover, search and filter jobs (including country); verify logos, resolved countries, and available salary ranges; save, hide, restore, and add a job to the tracker.
3. Open a job dossier; verify notes, save/unsave, official links, and application creation.
4. Edit a saved-job note and remove a saved card.
5. Change an application stage, edit notes, add a manual timeline event, and remove an accidental tracker entry.
6. Mark one inbox dispatch read, then mark all read and confirm the navigation badge changes.
7. Save preferences, run a rescore, and review the result summary.
8. Resolve an open duplicate review and confirm the next case is selected.

All live pages provide loading, empty, and API error states. ATS descriptions are rendered as
plain text; raw `description_html` is never injected into the document.

## Tests

Tests are offline and use saved ATS JSON fixtures plus an in-memory SQLite database:

```powershell
uv run pytest
```

See [architecture](docs/architecture.md), [Milestone 2 workflows](docs/milestone-2.md), [Milestone 3 frontend](docs/milestone-3.md), and [ingestion pipeline](docs/ingestion-pipeline.md) for design details.
