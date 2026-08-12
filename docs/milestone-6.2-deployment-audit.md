# Milestone 6.2 pre-implementation deployment audit

Date: 2026-08-04

This audit records the runtime and operations boundary before Milestone 6.2
changes. It is intentionally written before runtime behavior is changed.

## Current topology and runtime

- FastAPI serves the API and static application from one Uvicorn process.
- PostgreSQL is the durable store. Docker Compose starts PostgreSQL, then the
  web container applies migrations and runs the development seed before
  Uvicorn. This startup command is not safe for production because seeding is
  mixed with web startup.
- `hunt-board ingest` is the canonical one-shot scan. `hunt-board scheduler`
  is a separate, signal-aware process and is never started inside FastAPI.
- The optional Compose scheduler wakes every five minutes by default, while
  source cadence defaults to hours. No provider-neutral two-hour cron artifact
  exists.
- The image runs as root, has no OCI release labels, and has no image-level
  health check. `/health/live` and `/health/ready` already separate process and
  database health correctly.

## Scan length, concurrency, locking, and restart behavior

| Area | Existing behavior | Milestone 6.2 gap |
| --- | --- | --- |
| Request timeout | One `httpx.AsyncClient` timeout, normally 10–20 seconds. | Production default should be about 30 seconds and explicitly configurable. |
| Retry | Adapter HTTP requests make three total attempts with exponential backoff. | Add jitter, bounded retry/timeout metrics, and source-run counters. |
| Concurrency | Sources fetch concurrently behind an asyncio semaphore; reconciliation is serialized in one database session. | Preserve this shape and add a configurable whole-run deadline. |
| Lock | Real runs use one PostgreSQL session advisory lock; SQLite tests use a process-local lock. Dry runs do not lock or write. | Lock contention is currently a 409/skip only. Persist at most one pending request and coalesce any further request. |
| Restart | After acquiring the lock, running rows older than the stale threshold are marked abandoned. | Expose secure cancel/recover operations and cancellation state; recover source rows consistently. |
| Trigger paths | API, CLI, scheduler, and admin routes instantiate the same `IngestionService`. | Preserve the shared path and attach trigger/request/trace metadata everywhere. |

## Lifecycle and dedupe safety

- Reconciliation only runs when `lifecycle_authoritative` is true. Fetch,
  parse, and bounded Workday safety failures therefore do not advance missed
  counters or close jobs. This is the critical Milestone 4.1 boundary.
- Present jobs reset `consecutive_missed_runs`; absent active jobs increment it
  and close at the per-source threshold. Reappearing jobs reuse the same row,
  clear closure state, and set `reposted_at`.
- The configured/default missed-run threshold is currently 12, not the agreed
  production policy of three. There is no explicit-closed flag, confirmed dead
  URL action, maximum-age closure, or durable lifecycle event ledger.
- Same source/external ID and canonical apply URL are strong dedupe signals.
  Company/title/location matches remain separate and create
  `duplicate_reviews`. Preserve this conservative boundary.
- No anomaly baseline or quarantine exists. A successful but broken zero/mass
  change could be treated as authoritative and eventually close many jobs.

## Environment and secret safety

- `.env.example` contains placeholders and the production seed function refuses
  to create an admin in `production`, but settings accept arbitrary environment
  names and do not fail fast when a deployed environment is missing database or
  Supabase settings.
- Development, staging, and production do not have documented configuration
  contracts. The Compose web command always invokes seed.
- Supabase anon keys are browser-safe; service-role keys are not used by the
  application and must remain absent. Logs must never include either tokens or
  source `config_json`.

## Operations, logs, traces, and metrics

- `/admin/operations`, run/source history routes, `/metrics`, request IDs, JSON
  formatting, redaction, and lightweight timing spans provide a useful base.
- Structured records do not consistently include environment, release,
  process, run/source IDs, start/end status, or retry/quarantine/lock events.
- Metrics cover HTTP/auth/search/classification concerns but not the complete
  scan queue, retry, timeout, quarantine, freshness, or lifecycle inventory.
- `/app/operations.html` shows health, source policy, recent runs, invitations,
  and manual scan actions. It has no deployment identity banner, pending state,
  cancellation/recovery, retry-failed-only action, quarantine review, live
  counters, or request/trace lookup hints.
- OpenTelemetry is not installed. The safe portable approach is an
  OpenTelemetry-compatible span adapter that emits structured span records now
  and can be replaced/exported without changing call sites.

## Deployment decision

Use Render as the documented reference host because it supports a normal
Python web service and isolated provider configuration, while retaining Docker
and generic commands for Railway/Fly or another worker-friendly host. Use one
Render web service and a GitHub Actions two-hour one-shot scan against Supabase
PostgreSQL. This avoids paying for a continuously running worker. Production
uses a paid low-cost web instance when availability matters; staging can be
manually activated or use a free/sleeping instance. Supabase remains the auth
and PostgreSQL provider.

Provider-specific files stay isolated in `render.yaml` and
`.github/workflows/ingestion-cron.yml`. FastAPI and scans are not converted to
Vercel functions.

## Planned changes and invariants

1. Validate environment identity and production/staging secrets at startup;
   keep seed commands development/test-only.
2. Add release/process metadata and a production-ready non-root container.
3. Extend scrape records with queue, cancellation, correlation, retry, timeout,
   and quarantine fields plus durable quarantine/lifecycle ledgers.
4. Keep the advisory lock authoritative, with one persisted pending row and
   coalescing beyond it. The lock holder drains that pending row.
5. Add three-successful-miss, explicit closure, one-year closure, reactivation,
   and auditable lifecycle transitions. Never reconcile a failed or quarantined
   source result.
6. Detect suspicious source deltas before mutation, store only sanitized counts
   and stable identifiers, and require an admin decision before destructive
   reconciliation.
7. Extend the existing admin API and operations page; do not expose raw ATS
   payloads, descriptions, user-private data, or source secrets.
8. Add provider-neutral deploy/cron commands, release and smoke checks, launch,
   backup, rollback, scan-failure, and incident-debugging runbooks.

## Explicit non-goals

No in-FastAPI scheduler, task queue, automatic source discovery, authenticated
Workday API, browser automation, external search system, resume analysis,
multi-user auth redesign, or mandatory notification vendor is introduced.
