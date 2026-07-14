# Hunt Board Milestone 1 Architecture

Hunt Board uses a conventional Python `src/` layout. The FastAPI application is assembled in `hunt_board.main`, while database, ingestion, matching, job-domain, API, and admin concerns remain in separate packages.

## Runtime boundaries

- `core`: environment-backed settings.
- `db`: SQLAlchemy models, sessions, migrations, and idempotent seed data.
- `ingestion`: YAML registry loading, source synchronization, ATS adapters, and orchestration.
- `jobs`: conservative deduplication and URL/text normalization.
- `matching`: title-only eligibility and weighted ranking.
- `api`: health, job reads, and the backward-compatible ingestion route.
- `admin`: source registry, ingestion, scrape metrics, and duplicate review endpoints.
- `tracking` and `notifications`: domain boundaries reserved by the schema without asynchronous delivery infrastructure in Milestone 1.

PostgreSQL is the source of truth. A posting stores its latest normalized fields, latest raw ATS payload, raw-payload expiry date, description hash, visibility score, lifecycle state, and source identity. `job_versions` retains each distinct description payload. Normalized records are never deleted by ingestion.

The single-user MVP still models users, preferences, matches, saved jobs, applications, application statuses/events, and notifications separately. This avoids coupling job discovery to application tracking and leaves room for later product milestones without introducing multi-user UI or auth complexity now.

## Local topology

Docker Compose runs PostgreSQL and the FastAPI backend. Backend startup applies Alembic migrations and runs the idempotent seed command before serving requests. Secrets and environment-specific values are read from environment variables; the YAML source registry contains no credentials.
