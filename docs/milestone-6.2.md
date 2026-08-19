# Milestone 6.2 — Production deployment and operations

Milestone 6.2 makes Hunt Board deployable without changing its core topology:
one FastAPI/static web service, Supabase Auth/PostgreSQL, and a separate
one-shot private-beta source-group scan every twelve hours. Render is the isolated reference host and GitHub
Actions is the reference cron; Docker and application commands are portable.

Real triggers now share PostgreSQL advisory locking plus a persisted queue with
one active and one pending run. Extra triggers coalesce into the pending row.
The lock holder drains pending work. Runs support cooperative cancellation and
stale recovery; failed companies can be retried independently. Requests use a
30-second default, three total attempts, exponential backoff with jitter, and a
60-minute run deadline.

Lifecycle policy is now three successful misses, explicit source closure,
admin-confirmed dead apply URL, or one-year age. Reappearance reactivates the
same stable row and lifecycle events retain the transition history. Failed,
non-authoritative, and quarantined source results never advance closure
evidence.

Source results are quarantined before mutation when a mature baseline suddenly
returns zero, changes volume dramatically, changes many titles/locations, or
would deactivate a large share. Only sanitized counts and stable external IDs
are retained. Admin approval records an audit decision and performs a fresh,
authorized source scan; rejection applies no lifecycle evidence.

Operations now exposes release/environment/health, queue state, bounded 24-hour
metrics, run/source correlation IDs, retry/cancel/recovery actions, and
quarantine review. JSON logs add environment/release/process context and redact
sensitive keys, emails, bearer values, and secret query parameters. Lightweight
span events are OpenTelemetry-compatible call sites without forcing a paid
collector.

Deployment, launch/backfill, alert retention, backup/restore, rollback, scan
failure, incident debugging, and the step-by-step owner exercise are documented
in `docs/deployment.md`, `docs/runbooks/`, and
`docs/owner-ui-checklist-6.2.md`.
