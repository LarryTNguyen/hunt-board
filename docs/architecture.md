# Hunt Board Architecture through Milestone 3

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

Application status transitions and manual events share one ordered timeline. A status transition stores both old and new status slugs so history remains understandable if status display names later change.

Real ingestion creates notifications synchronously in the source transaction. Stable dedupe keys prevent repeated `new_match`, `reposted_job`, and tracked-job `job_updated` notifications. Dry-run ingestion never calls the persistence path and therefore cannot create notifications or CRM state.

## Local topology

Docker Compose runs PostgreSQL and the FastAPI backend. Backend startup applies Alembic migrations and runs the idempotent seed command before serving requests. Secrets and environment-specific values are read from environment variables; the YAML source registry contains no credentials.

## Deliberate boundaries

The system remains single-user. The Milestone 3 frontend is served as same-origin static HTML/CSS/JavaScript from FastAPI. There is no login/session layer, resume analysis, email or push delivery, scheduled notification worker, full-text search service, task queue, or new ATS adapter. Search uses indexed/normalized relational fields and SQL substring matching.
