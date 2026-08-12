# Owner UI and operations verification — Milestone 6.2

Run this in staging first with a synthetic invited admin. Keep browser Network
tools open, preserve response status/headers, and save screenshots or exported
JSON using names such as `6.2-03-third-trigger.png`. Never save tokens, cookies,
emails, notes, descriptions, raw payloads, or source configuration in evidence.

## Before opening the UI

```bash
uv run alembic upgrade head
uv run pytest
docker compose config
docker build --build-arg HUNT_BOARD_RELEASE=6.2-check -t hunt-board:6.2-check .
docker compose up --build
```

For staging set `HUNT_BOARD_ENVIRONMENT=staging`, a real release identifier,
the separate staging database/Supabase values, and
`HUNT_BOARD_SOURCES_PATH=data/sources.staging.yaml`. Sign in as the synthetic
admin and open `/app/operations.html`.

## 1. Deployment and health identity

Expected UI: the top ribbon says `STAGING`, the expected release/deploy ID, and
`Web healthy · DB healthy`. System status is Idle unless a scan is running.

Failure: missing/unsafe staging variables must stop startup with `Unsafe staging
configuration`; a database/schema failure makes `/health/ready` return 503.

Evidence: ribbon screenshot, `/health/live`, `/health/ready`, and response
`X-Request-ID`/`X-Trace-ID` with authorization headers hidden.

## 2. Start one active scan

Choose **Run due sources**, confirm the dialog, and refresh while it runs. If no
source is due, choose **Run source** on the staging board.

Expected UI: queue Active shows `Run #<id>`, Pending shows Empty; Recent runs
shows running status, live persisted counters as source boundaries complete,
and a request/trace ID. Another browser/session can observe active state.

Evidence: active queue screenshot plus run/request/trace IDs.

## 3. Queue exactly one pending scan

While step 2 remains active, trigger the same real scan from a second signed-in
admin tab or run `uv run hunt-board ingest`.

Expected UI/API: one Pending run appears with status `pending`; Active remains
unchanged. There is never a second running row.

Evidence: active and pending IDs in one screenshot and the second command JSON.

## 4. Coalesce the third trigger

While both slots are occupied, trigger a third real scan.

Expected message: `Run due sources: Coalesced.` The queue keeps the same pending
ID and **Joined requests** increments. No third pending/running row is created.

## 5. Retry and isolation on one source timeout

Run `uv run pytest tests/test_milestone_six_point_two.py -k retry_timeout`.

Expected: three total attempts (two retries), increasing jittered backoff,
timeout/retry counts in source detail, the source eventually failed, and other
companies completed. The whole run ends `completed_with_errors`.

## 6. Prove failures do not close jobs

Before and after the failed scan, compare active count and missed counters with
an admin-safe database query.

Expected: affected jobs remain active; `consecutive_missed_runs` is unchanged;
closed count is zero. Failed/quarantined/non-authoritative scans are not closure
evidence. Save aggregate evidence without private job/user fields.

## 7. Retry failed companies only

Select the failed/degraded run and choose **Retry failed**.

Expected: a new run requests only failed/abandoned source slugs. Successful
companies are not repeated. If none failed, the UI shows `This run has no failed
companies to retry` (409).

## 8. Trigger anomaly quarantine

Run `uv run pytest tests/test_milestone_six_point_two.py -k quarantine` against
the offline mature-baseline fixture.

Expected UI: source becomes Quarantined; the review card shows only counts,
ratios, and reason; run status is `completed_with_errors`. Zero jobs deactivate
and no miss counter advances.

## 9. Approve and reject quarantines

Choose **Approve and rescan** for a verified-real staging change. Create another
synthetic anomaly and choose **Reject result**.

Expected: approval records admin/time/note and performs a fresh one-use
authorized scan. Rejection applies no lifecycle evidence. A second decision
returns `Quarantine was already decided` (409).

## 10. Cancel and recover stuck work

Choose **Cancel** on an active test run. Cancellation is cooperative and becomes
`cancelled` after the fetch boundary. A pending run cancels immediately. For a
fixture row older than `HUNT_BOARD_STALE_RUN_MINUTES`, choose **Recover stale
run**.

Expected: stale active/source rows become `abandoned` with finish/duration.
Completed runs cannot be cancelled and return a 409 explanation.

## 11. Read the operational signals

Confirm release/environment, active/pending/joined state, last success/next due,
source freshness/failures, job counts, runs/failures, retries, timeouts, duration,
fetched/new/updated/reactivated/closed counts, and quarantines are understandable.
Metric dimensions must be bounded and never use user/job/title/email/raw URL.

## 12. Follow a request into logs and traces

Paste a displayed request or trace ID into **Find operational evidence**.

Expected: matching run metadata only. Search the provider for the exact ID and
follow `run_id`/controlled `source_slug` through run, source fetch span, retry,
timeout, quarantine, lock, queue, and completion events. Save sanitized evidence.

## 13. Audit redaction

Search logs for a representative token prefix, invited email, unique test note,
description fragment, and source secret.

Expected: no matches. Emails, bearer values, secret query values, source config,
payloads, descriptions, notes, tokens, cookies, magic links, and keys are absent
or redacted. Any match is a security incident and blocks launch.

## 14. Compare staging and production boundaries

Open both provider URLs in separate browser profiles.

Expected: different environment ribbons, URLs, deployment IDs, Supabase issuer,
invited identities, source coverage, rows, and logs. Staging uses synthetic users
and `data/sources.staging.yaml`; production rows are never copied to it.

## 15. Rehearse the 14-day production launch gate

With invitations/sign-up disabled in a new empty production project:

```bash
uv run alembic upgrade head
uv run hunt-board sync-sources
uv run hunt-board backfill --days 14
uv run hunt-board coverage-report
```

Validate source/active/family counts, duplicate reviews, classification error or
`other` rate, failed source rows, and quarantines. Unknown posting dates may
remain; known older dates are excluded. Verify `hunt-board seed` refuses
production. Do not enable invitations until the gate passes.

## 16. Rehearse rollback and restore outside production

Follow `docs/runbooks/rollback.md` and `backup-restore.md` in an isolated project.
Deploy the last stable tag, smoke it, restore a daily backup into new
nonproduction, verify revision/counts/RLS/auth, and dry scan. Never overwrite
staging or expose restored personal data to staging users.

## Sign-off

Record pass/fail for all steps, environment/release/deployment IDs, Alembic
revision, run/source/quarantine IDs, evidence filenames, unresolved risks, and
owner/date. Invitations remain disabled until every launch gate passes or has a
documented accepted risk.
