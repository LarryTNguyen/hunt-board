# Hunt Board

Hunt Board is a backend-first job intelligence system. Milestone 1 ingests curated Greenhouse, Lever, and Ashby boards, stores normalized jobs plus source payloads, detects duplicates and reposts conservatively, ranks titles against a single user's preferences, and exposes operational metrics through FastAPI.

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
- `HUNT_BOARD_HTTP_TIMEOUT_SECONDS`: ATS HTTP timeout.

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

## API surface

- `GET /health` and `GET /health/db`
- `GET /jobs` and `GET /jobs/{job_id}`
- `GET /admin/sources`
- `POST /admin/sources/sync-from-yaml`
- `GET /admin/scrape-runs` and `GET /admin/scrape-runs/{run_id}`
- `POST /admin/ingestion/run`
- `POST /admin/ingestion/run-source/{source_id}`
- `GET /admin/duplicates`
- `PATCH /admin/duplicates/{duplicate_review_id}`

Legacy `/api/jobs`, `/api/admin/*`, and `/api/ingest/run` paths remain available.

## Tests

Tests are offline and use saved ATS JSON fixtures plus an in-memory SQLite database:

```powershell
uv run pytest
```

See [architecture](docs/architecture.md) and [ingestion pipeline](docs/ingestion-pipeline.md) for design details.
