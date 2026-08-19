# Hunt Board Architecture through Milestone 6.2

Hunt Board uses a conventional Python `src/` layout. The FastAPI application is assembled in `hunt_board.main`, while database, ingestion, matching, job-domain, API, and admin concerns remain in separate packages.

Milestone 6.1 keeps `jobs/query.py` as the one SQL filter/sort/facet path for discovery, saved searches, and dashboard selection. `jobs/classification.py` owns the fixed taxonomy/rules; adapters only normalize source data. Ingestion preserves admin overrides. `jobs/relaxation.py` changes a `JobQueryFilters` value and re-executes the canonical path, preventing strict and relaxed semantics from drifting.

`UserPreference` remains canonical and saved-search JSON remains portable. Shared `job_postings` are separate from RLS-protected `manual_jobs`, applications, saved state, and discarded state. Custom stages map to six standard reporting categories.

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
- `searches`: saved-search validation, discovery-filter conversion, matching counts, review state, and CRUD routes.
- `dashboard`: an authenticated per-profile aggregate for the daily start page.

PostgreSQL is the source of truth. A posting stores its latest normalized fields, including an ISO country code, a source-independent structured location collection, and structured compensation range when the ATS provides them, plus the latest raw ATS payload, raw-payload expiry date, description hash, visibility score, lifecycle state, and source identity. Company logo URLs belong to the normalized source record rather than being copied into every posting. `job_versions` retains each distinct description payload. Normalized records are never deleted by ingestion.

The multi-user foundation models profiles, invitations, preferences, matches, per-user job state, applications, application statuses/events, and notifications separately. The existing `users` table is the profile table: its integer key remains an internal foreign-key compatibility detail while `auth_user_id` is the unique verified Supabase UUID boundary. `user_preferences` is canonical; `users.preferences_json` is updated only as a compatibility snapshot. `applications.status_id` is canonical; the legacy `applications.status` string is kept synchronized as a display/compatibility slug.

Milestone 5 stores portable saved-search filters in `saved_searches.filters_json`. Source selection uses `source_slug`, never database `source_id`. The typed filter schema rejects extra fields and converts directly into `JobQueryFilters`, so saved-route matches, counts, previews, facets, and deterministic sorting use the same SQL path as discovery. `last_viewed_at` is explicit review state: a job is new when its ingestion-owned `first_seen_at` is later than the review timestamp; all matches are new when the timestamp is null.

`GET /dashboard/daily` composes source freshness, CRM totals, saved-route summaries, deduplicated new route matches, application pipeline counts, and seven-day follow-up candidates for the authenticated profile. It is deliberately computed on read for the small beta. The response uses normalized job/source fields only and excludes raw ATS payloads and source configuration.

Authenticated job reads outer-join the resolved profile's saved/dismissed and most-recent application state. Anonymous reads receive no private state. Confirmed duplicates are excluded by default, while callers can explicitly include or filter them. List pagination remains `limit`/`offset` and the response remains a JSON list to preserve the Milestone 1 contract.

Milestone 4 centralizes those joins and filters in `jobs.query`. The legacy list and the discovery feed use the same builder, while the feed adds a count independent of pagination and self-excluding ATS/source/country/workplace/salary facets. Feed ordering always ends with `job_postings.id` for deterministic offsets. PostgreSQL search uses an English generated weighted `tsvector` and a GIN index; SQLite uses a deterministic weighted substring fallback only for offline tests.

Application status transitions and manual events share one ordered timeline. A status transition stores both old and new status slugs so history remains understandable if status display names later change.

Real ingestion creates notifications synchronously in the source transaction. Stable dedupe keys prevent repeated `new_match`, `reposted_job`, and tracked-job `job_updated` notifications. Dry-run ingestion never calls the persistence path and therefore cannot create notifications or CRM state.

The adapter registry in `ingestion/adapters/registry.py` is the only owner of supported ATS keys and factories. YAML validation reads those registered keys, and ingestion asks the registry to construct adapters; source-slug overrides remain available for offline tests. Sanitization is a separate ingestion-boundary service built on `lxml`, so stored posting and version HTML share the same conservative allowlist while `raw_json` remains untouched.

The Workday adapter is deliberately isolated around the public Candidate Experience JSON contract. It validates an explicitly configured host, tenant, site, locale, and career URL before network access. A scan first enumerates listing pages sequentially and accepts them only when the first-page total exactly matches unique safe `/job/` paths. Later nonempty pages may report Workday's observed `total: 0` sentinel; any other total change or an early empty page remains an integrity failure. It then uses a fixed-size worker pool for detail reads while preserving listing order. A possible mid-scan withdrawal permits one complete listing reconciliation. Individually identified paths that remain listed but have no detail are skipped in an explicit partial result; complete jobs may be upserted, but missed-run and closure reconciliation is suppressed for the entire source. Listing instability, duplicate paths, repeated churn that prevents complete enumeration, and non-withdrawal detail failures still fail the source atomically.

Every real ingestion run acquires one global lock before recovery or writes. PostgreSQL uses a session advisory lock on a dedicated connection held through finalization; SQLite uses an in-process lock for deterministic tests. Lock contention persists at most one `pending` scrape run; later triggers coalesce into it, and the lock holder drains that row after the active run. After lock acquisition, stale `running` run/source-run rows are marked `abandoned`. Cancellation is cooperative at source boundaries. Unexpected exceptions roll back partial work, finalize the already-created run as `failed`, and release the lock in `finally`.

Successful authoritative sources reconcile lifecycle evidence. Three consecutive successful misses, explicit source closure, a confirmed dead apply URL, or maximum age closes a posting; reappearance reactivates the same stable row. Failed, partial/non-authoritative, and quarantined results never increment misses. Mature-source zero, extreme volume, mass title/location, and mass-deactivation changes are quarantined before mutation with a sanitized decision ledger.

Retention cleanup is a server-side bulk CLI service scheduled daily in production. It replaces expired posting/version `raw_json` values with `{}` and clears their expiration markers without transferring payloads to the cleanup worker or removing normalized records, lifecycle history, CRM state, or metrics. Private-beta posting payloads expire after seven days and unchanged observations do not extend that window; new job versions retain normalized descriptions without duplicating raw source payloads.

## Runtime topology

Docker Compose runs PostgreSQL and the FastAPI backend by default. The backend is the single Compose migration/seed owner and becomes ready only after required schema queries succeed. The optional `scheduler` profile starts a separate `hunt-board scheduler` container only after the backend is healthy. It never runs inside FastAPI, keeps no scheduler database, and calls the same due-source ingestion service and advisory lock used by API, CLI, and cron runs.

Production topology has one Render-compatible web process, Supabase PostgreSQL/Auth, and GitHub Actions (or equivalent platform cron) invoking the private-beta source groups every twelve hours plus daily retention cleanup. The web image never seeds or migrates on process startup; migration is a reviewed release step. Development, staging, and production use separate data/auth/provider identities. The lock remains necessary because manual, API, CLI, cron, and the optional local scheduler can coincide.

The operations boundary consists of a typed aggregate read at `GET /admin/operations`, run/source detail, retry/cancel/recovery, quarantine decision, correlation lookup routes, and `/app/operations.html`. It exposes safe deployment/source/queue fields and bounded aggregate metrics, never raw ATS payloads, descriptions, user-private fields, or source configuration JSON. `/health/live` checks only process response; `/health/ready` checks database connectivity and required schema. Ingestion degradation is reported separately and does not make the web process unready.

## Deliberate boundaries

The system supports fewer than ten invite-only beta profiles with exactly `admin` and `user` roles. Supabase verifies identity; Hunt Board owns invitations, activation, active state, roles, and authorization. Private tables have PostgreSQL RLS keyed through the profile's auth UUID. The frontend remains same-origin static HTML/CSS/JavaScript from FastAPI and uses the public Supabase client. Notifications remain in-app only. There is no resume analysis or AI matching, email or push delivery, distributed task queue, external search service, authenticated Workday integration, source discovery, CAPTCHA bypass, proxy service, or browser automation. PostgreSQL-native full-text search remains part of the primary database rather than a separate service.
