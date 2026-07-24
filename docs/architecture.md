# Hunt Board Architecture through Milestone 4

Hunt Board uses a conventional Python `src/` layout. The FastAPI application is assembled in `hunt_board.main`, while database, ingestion, matching, job-domain, API, and admin concerns remain in separate packages.

## Runtime boundaries

- `core`: environment-backed settings.
- `db`: SQLAlchemy models, sessions, migrations, and idempotent seed data.
- `ingestion`: YAML registry loading, source synchronization, ATS adapters, and orchestration.
- `jobs`: conservative deduplication and URL/text normalization.
- `matching`: title-only eligibility, weighted ranking, canonical preference mapping, and bulk rescoring.
- `api`: health, enriched job reads, preference management, and the backward-compatible ingestion route.
- `admin`: source registry, ingestion, scrape metrics, and duplicate review endpoints.
- `tracking`: saved-job and application/application-event HTTP workflows.
- `notifications`: a synchronous, database-backed in-app inbox with no external delivery infrastructure.

PostgreSQL is the source of truth. A posting stores its latest normalized fields, including an ISO country code and structured compensation range when the ATS provides them, plus the latest raw ATS payload, raw-payload expiry date, description hash, visibility score, lifecycle state, and source identity. Company logo URLs belong to the normalized source record rather than being copied into every posting. `job_versions` retains each distinct description payload. Normalized records are never deleted by ingestion.

The single-user MVP models users, preferences, matches, saved jobs, applications, application statuses/events, and notifications separately. `user_preferences` is canonical; `users.preferences_json` is updated only as a compatibility snapshot. `applications.status_id` is canonical; the legacy `applications.status` string is kept synchronized as a display/compatibility slug.

Job reads outer-join saved and application state for the seeded active user. Confirmed duplicates are excluded by default, while callers can explicitly include or filter them. List pagination remains `limit`/`offset` and the response remains a JSON list to preserve the Milestone 1 contract.

Milestone 4 centralizes those joins and filters in `jobs.query`. The legacy list and the discovery feed use the same builder, while the feed adds a count independent of pagination and self-excluding ATS/source/country/workplace/salary facets. Feed ordering always ends with `job_postings.id` for deterministic offsets. PostgreSQL search uses an English generated weighted `tsvector` and a GIN index; SQLite uses a deterministic weighted substring fallback only for offline tests.

Application status transitions and manual events share one ordered timeline. A status transition stores both old and new status slugs so history remains understandable if status display names later change.

Real ingestion creates notifications synchronously in the source transaction. Stable dedupe keys prevent repeated `new_match`, `reposted_job`, and tracked-job `job_updated` notifications. Dry-run ingestion never calls the persistence path and therefore cannot create notifications or CRM state.

The adapter registry in `ingestion/adapters/registry.py` is the only owner of supported ATS keys and factories. YAML validation reads those registered keys, and ingestion asks the registry to construct adapters; source-slug overrides remain available for offline tests. Sanitization is a separate ingestion-boundary service built on `lxml`, so stored posting and version HTML share the same conservative allowlist while `raw_json` remains untouched.

Every real ingestion run acquires one global lock before recovery or writes. PostgreSQL uses a session advisory lock on a dedicated connection held through finalization; SQLite uses an in-process lock for deterministic tests. After lock acquisition, stale `running` run/source-run rows are marked `abandoned`. Unexpected exceptions roll back partial work, finalize the already-created run as `failed`, and release the lock in `finally`.

Retention cleanup is deliberately an explicit CLI service. It replaces expired posting/version `raw_json` values with `{}` and clears their expiration markers without removing normalized records, lifecycle history, CRM state, or metrics.

## Runtime topology

Docker Compose runs PostgreSQL and the FastAPI backend by default. The backend is the single Compose migration/seed owner and becomes ready only after required schema queries succeed. The optional `scheduler` profile starts a separate `hunt-board scheduler` container only after the backend is healthy. It never runs inside FastAPI, keeps no scheduler database, and calls the same due-source ingestion service and advisory lock used by API, CLI, and cron runs.

Production topology has one web process, PostgreSQL as source of truth, and exactly one intended scheduler process. A platform cron invoking the one-shot `hunt-board ingest` command is the preferred alternative on platforms with reliable scheduling. The lock remains necessary because manual, cron, and scheduler triggers can coincide.

The operations boundary consists of a typed aggregate read at `GET /admin/operations`, existing source/run detail and action routes, and `/app/operations.html`. It exposes safe source policy/health fields and aggregate metrics, never raw ATS payloads or source configuration JSON. `/health/live` checks only process response; `/health/ready` checks database connectivity and required schema. Ingestion degradation is reported separately and does not make the web process unready.

## Deliberate boundaries

The system remains single-user. The frontend is served as same-origin static HTML/CSS/JavaScript from FastAPI. There is no login/session layer, resume analysis, email or push delivery, distributed task queue, external search service, or new ATS adapter. PostgreSQL-native full-text search is deliberately part of the primary database rather than a separate service.
