# Hunt Board

Hunt Board is a backend-first job intelligence and personal job-search CRM. It ingests curated Greenhouse, Lever, Ashby, and explicitly configured public Workday boards. Milestone 6 adds an invite-only multi-user foundation with Supabase Auth, trusted roles, PostgreSQL RLS, and protected private state without changing the safety-bounded Workday ingestion contract.

## Quick start with Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose starts PostgreSQL on host port `55432` and the API on `http://127.0.0.1:8000`. Backend startup applies migrations and idempotently seeds the admin user, default preferences, application statuses, and YAML sources.

To also run the separate scheduler process locally:

```powershell
docker compose --profile scheduler up --build
```

The scheduler profile is opt-in. The backend remains the only Compose process that applies migrations and seed data; the scheduler waits for backend readiness before starting.

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/db
Invoke-RestMethod http://127.0.0.1:8000/health/ingestion
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
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

The normal seed command creates one deterministic local admin profile, accepted local invitation,
defaults, statuses, and configured sources. It refuses to create an admin in production. To populate job data, run fixture-backed tests for development or ingest
configured ATS sources with `uv run hunt-board ingest`; Milestone 3 does not silently insert
demo records.

The daily starting point is `/app/dashboard.html`. It combines ingestion freshness, recent-job totals, new saved-route matches, the application pipeline, and follow-up candidates. `/app/saved-searches.html` creates and manages reusable discovery routes. A route's `last_viewed_at` is advanced only by **Mark reviewed**; jobs with `first_seen_at` after that timestamp count as new. A never-reviewed route treats all current matches as new.

The live discovery desk at `/app/job-discovery.html` browses the complete server-paginated feed. Its search, source/ATS/country/location/workplace/salary/age/score filters, sort, page offset, view tab, and selected job are represented in the URL, so refresh and browser back/forward preserve the route. Use **Save this route** to persist the current filters. The operations desk at `/app/operations.html` shows ingestion status, source health/policy, recent run metrics, and confirmed manual actions.

### Saved searches and Daily Hunt API

- `GET/POST /saved-searches` lists or creates routes.
- `GET/PATCH/DELETE /saved-searches/{id}` reads, updates, or removes a route.
- `GET /saved-searches/{id}/matches` returns the feed-shaped matches; `new_only=true` restricts results to jobs first seen after review.
- `POST /saved-searches/{id}/mark-reviewed` advances the review timestamp.
- `GET /dashboard/daily` returns the read-only Daily Hunt aggregate.

Seed creates one idempotent default route named `Daily Hunt` using the user's minimum score threshold. Notifications remain in-app only. Milestone 5 does not add resume analysis, AI matching, or email/push delivery.

## Configuration

- `DATABASE_URL`: SQLAlchemy PostgreSQL URL. The host default uses port `55432`.
- `HUNT_BOARD_SOURCES_PATH`: YAML source registry path; defaults to `data/sources.yaml`.
- `HUNT_BOARD_DEFAULT_USER_EMAIL`: deterministic local development admin profile email.
- `HUNT_BOARD_ENVIRONMENT`: `development` by default; production disables automatic admin creation.
- `SUPABASE_URL`: public Supabase project URL used for JWKS and browser auth bootstrap.
- `SUPABASE_ANON_KEY`: public anonymous client key; never substitute a service-role key.
- `SUPABASE_JWT_AUDIENCE`: access-token audience; defaults to `authenticated`.
- `SUPABASE_JWT_ISSUER`: optional issuer override; defaults to `SUPABASE_URL/auth/v1`.
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS`: per-request ATS timeout; defaults to `10`.
- `HUNT_BOARD_SOURCE_CONCURRENCY`: maximum ATS sources fetched at once; defaults to `5`.
- `HUNT_BOARD_HTTP_MAX_RETRIES`: retries for timeouts, network failures, HTTP 408/429, and HTTP 5xx responses; defaults to `2`.
- `HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS`: base exponential retry delay; defaults to `0.5`.
- `HUNT_BOARD_SCHEDULER_ENABLED`: enables the separate scheduler command; defaults to `true`.
- `HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS`: seconds between scheduler ticks; defaults to `300`, minimum `10`.
- `HUNT_BOARD_SCHEDULER_RUN_ON_STARTUP`: run one due-source tick immediately; defaults to `true`.

The source registry supports the milestone shape (`company_name`, `company_logo_url`, `careers_url`, `ats_type`, `ats_slug`, high/medium/low `priority`, `enabled`, `categories`, and `notes`) and the existing explicit `config` shape. `company_logo_url` is the authoritative logo; the frontend falls back to company initials if it is absent or fails to load. ATS slugs are always manually configured; no scraping-based ATS detection is performed.

### Workday source configuration

Workday uses the public Candidate Experience JSON surface, which is separate from Workday's authenticated tenant APIs and may change without notice. Host, tenant, and site are always explicit; Hunt Board never guesses or discovers them. Only HTTPS subdomains of `myworkdayjobs.com` and `myworkdaysite.com` are accepted.

Add an owner-selected source disabled first:

```yaml
  - slug: example-workday
    name: Example Workday
    ats: workday
    company_name: Example Company
    careers_url: https://example.invalid.myworkdayjobs.com/en-US/External
    enabled: false
    priority: 1
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

Replace every placeholder with values copied from the selected public career site. `host`, `tenant`, `site`, and an HTTPS `careers_url` on the same host are required. The optional bounds are: page size 1-100, detail concurrency 1-8, request interval 0-10,000 ms, and max jobs 1-10,000. Exceeding `max_jobs` fails rather than truncating.

Synchronize and stage rollout with two dry runs:

```powershell
uv run hunt-board sync-sources
uv run hunt-board ingest --source example-workday --dry-run
uv run hunt-board ingest --source example-workday --dry-run
uv run hunt-board ingest --source example-workday
```

Compare listing counts and sample public URLs before setting `enabled: true`. Use a conservative cadence because each scan performs sequential listing-page requests plus one bounded detail request per job. Persistent access denial, unsupported response contracts, or bot protection fail clearly; Hunt Board does not bypass them with cookies, proxies, or browser automation.

If a completely enumerated Workday listing contains an individual path whose detail remains unavailable after one reconciliation, Hunt Board records a `completed_with_errors` partial result and skips that path. Complete jobs may still be upserted, but missed-run counters and closure reconciliation are suppressed for the source so a partial scan cannot deactivate jobs.

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
uv run hunt-board scheduler
```

The equivalent API operations are `POST /admin/ingestion/run` and `POST /admin/ingestion/run-source/{source_id}`. The request body for the first endpoint is `{"source_slugs": ["discord"], "dry_run": true}`.

Source fetches run concurrently, while SQLAlchemy writes remain serial and transaction-isolated. Repeated postings are reported as `unchanged_jobs`; only new or materially changed postings count toward `total_upserted`. Running without `--source` scans only enabled sources that are due. Passing `--source` forces that configured source for local validation.

Real runs are mutually exclusive. PostgreSQL uses a session advisory lock held on a dedicated connection; lock contention creates no run row and returns HTTP `409` (or a nonzero CLI exit). Dry runs do not take the lock. On startup, a lock-owning run marks older `running` records `abandoned` using `HUNT_BOARD_STALE_RUN_MINUTES` (default `120`). ATS HTML is sanitized before normalized storage while the original payload remains only in `raw_json`. Workday stores a deterministic `{listing, detail}` composite raw payload, and job APIs expose only normalized fields. Multi-location jobs expose an optional typed `locations` collection while existing scalar fields remain compatible.

Inspect or purge expired raw payloads without deleting normalized records:

```powershell
uv run hunt-board purge-expired-raw --dry-run
uv run hunt-board purge-expired-raw
```

`hunt-board ingest` remains the canonical one-shot production unit and is the preferred target for platform cron. Without `--source` it selects enabled due sources, uses the global lock, finalizes metrics, and exits; when no source is due it exits successfully without creating an empty run. `hunt-board scheduler` wraps that same service in a separate signal-aware process. Run exactly one intended scheduler replica. Lock contention is a skipped tick, and later ticks continue after failures.

## API surface

- `GET /health`, `GET /health/db`, `GET /health/live`, `GET /health/ready`, and `GET /health/ingestion`
- `GET /jobs` and `GET /jobs/{job_id}`
- `GET /jobs/feed` for typed discovery items, total, pagination metadata, and self-excluding facets
- `GET/PATCH /me/preferences` and `POST /me/preferences/rescore`
- `GET /saved-jobs`, `POST/DELETE /jobs/{job_id}/save`, and `PATCH /saved-jobs/{saved_job_id}`
- `GET /discarded-jobs` and `POST/DELETE /jobs/{job_id}/discard`
- `GET /application-statuses`
- `GET /applications`, `POST /jobs/{job_id}/applications`, and `GET/PATCH /applications/{application_id}`
- `DELETE /applications/{application_id}` to remove an accidentally tracked application and its events
- `GET/POST /applications/{application_id}/events`
- `GET /notifications`, `PATCH /notifications/{notification_id}/read`, and `POST /notifications/read-all`
- `GET /admin/sources`
- `GET /admin/operations`
- `POST /admin/sources/sync-from-yaml`
- `GET /admin/scrape-runs` and `GET /admin/scrape-runs/{run_id}`
- `POST /admin/ingestion/run`
- `POST /admin/ingestion/run-source/{source_id}`
- `GET /admin/duplicates`
- `PATCH /admin/duplicates/{duplicate_review_id}`

Legacy `/api/jobs`, `/api/admin/*`, and `/api/ingest/run` paths remain available.

`GET /jobs` remains a list response for Milestone 1 compatibility and now accepts `limit`/`offset`, filters for source/company/location/country/workplace/salary availability/score/saved/discarded/application state, duplicate controls, and documented sort fields. Use `country=US` (ISO alpha-2) or `country=United States`, and `salary_known=true|false`, for the normalized filters. Active jobs ranked by score remain the default, with confirmed duplicates and discarded jobs excluded. Use `discarded=true` or `GET /discarded-jobs` to review the discard pile; deleting the per-user discard record restores the job without deleting its normalized posting.

`GET /jobs/feed` keeps those shared filters and adds `q`, `application_state=none|tracked|any`, bounded `posted_within_days`, `relevance` sorting, a default page size of 25 (maximum 100), an independent total, and ATS/source/country/workplace/salary facets. Facets are self-excluding. Production search uses PostgreSQL web-search semantics over a generated weighted vector and GIN index; the offline SQLite suite uses a deterministic weighted substring fallback.

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

## Milestone 4 manual QA

After the quick-start commands and at least one ingestion run:

1. Open `/app/` and follow the live navigation on both desktop and a narrow viewport.
2. In Discover, search and apply source, ATS, country, location, workplace, salary, age, score, and sort controls; verify total counts and server facets.
3. Refresh a filtered URL, paginate, open a drawer, use browser back/forward, and directly load a `job=<id>` URL.
4. Verify the freshness message degrades without blocking job results.
5. Save, hide, restore, and add a job to the tracker; verify discovery explicitly excludes tracked applications.
6. Open `/app/operations.html`, inspect source policy/health and recent source-run metrics, perform a dry run, and confirm a real due-source run.
7. Start the scheduler profile and confirm runs occur outside the web process without overlapping a concurrent manual run.
8. Recheck job dossiers, saved jobs, applications, inbox, preferences, and duplicate review for regressions.

All live pages provide loading, empty, and API error states. ATS descriptions are rendered as
plain text; raw `description_html` is never injected into the document.

## Tests

Tests are offline and use saved ATS JSON fixtures plus an in-memory SQLite database:

```powershell
uv run pytest
```

Optional PostgreSQL verification (use a disposable/test database) applies Alembic head and checks the GIN vector/index, title and description matches, relevance ordering, a combined structured filter, and advisory lock behavior:

```powershell
$env:HUNT_BOARD_TEST_POSTGRES_URL='postgresql+psycopg://hunt_board:hunt_board@localhost:55432/hunt_board'
uv run pytest -m postgres tests/test_milestone_four_postgres.py
```

See [architecture](docs/architecture.md), [Milestone 2 workflows](docs/milestone-2.md), [Milestone 3 frontend](docs/milestone-3.md), [Milestone 3.5](docs/milestone-3.5.md), [Milestone 4](docs/milestone-4.md), [Milestone 4.1](docs/milestone-4.1.md), [Milestone 5](docs/milestone-5.md), [Milestone 6](docs/milestone-6.0.md), [authentication setup](docs/auth-setup.md), and [ingestion pipeline](docs/ingestion-pipeline.md) for design details.
