# Milestone 2: Single-user job-search CRM

Milestone 2 turns ranked ingestion results into a backend workflow for reviewing jobs and managing a personal search. It remains a single-user FastAPI service; the active seeded user is used for all preference, saved-job, application, and notification state.

## Job browsing

`GET /jobs` preserves the Milestone 1 list response and accepts:

- lifecycle filters: `active`, `duplicate_status`, `include_duplicates`;
- source filters: `source_id`, `source_slug`, `ats`;
- text/state filters: `company`, `location`, `workplace_type`, `search`, `title`, `remote_only`, `saved`, `application_status`;
- ranking and page controls: `min_score`, `sort_by`, `sort_order`, `limit`, `offset`.

Sort fields are `ranking_score`, `first_seen_at`, `last_seen_at`, `posted_at`, `company_name`, and `title`. Confirmed duplicates are hidden by default. Each list/detail item includes source metadata, score reasons, saved state, application state, lifecycle state, and duplicate/repost indicators.

## Preferences and rescoring

`GET /me/preferences` reads the canonical `user_preferences` row. `PATCH /me/preferences` supports include/exclude keywords, role groups, preferred levels/locations, home location, radius, country, remote preference, and `minimum_score_threshold`.

Updates trim and case-insensitively deduplicate list values. Empty strings, unknown role groups/levels, out-of-range radii, and score thresholds outside 0-100 are rejected. The compatibility `users.preferences_json` snapshot is synchronized after successful changes.

`PATCH /me/preferences` persists the canonical preferences and compatibility snapshot without rescoring, so the save request remains fast as the catalog grows. `POST /me/preferences/rescore` is a separate explicit operation that recomputes each stored job's ranking fields and the user's `job_matches` row without creating or deleting job postings. Its response reports considered/rescored and visible/low-ranked counts plus timing.

## Saved jobs

- `GET /saved-jobs`
- `POST /jobs/{job_id}/save`
- `DELETE /jobs/{job_id}/save`
- `PATCH /saved-jobs/{saved_job_id}`

Save and unsave are idempotent. Repeating a save returns the existing saved record and does not overwrite its note; use the patch endpoint to make note changes. Repeating an unsave returns `removed: false`.

## Discard pile

- `GET /discarded-jobs`
- `POST /jobs/{job_id}/discard`
- `DELETE /jobs/{job_id}/discard`

Discarding is a per-user, idempotent state change: it hides a job from the default discovery list and hides any related notification from the inbox. It does not delete the normalized job posting, so a user can review the discard pile later and restore a job with the delete endpoint. `GET /jobs?discarded=true` is also available for filtered browsing.

## Applications and timelines

- `GET /application-statuses`
- `GET /applications`
- `POST /jobs/{job_id}/applications`
- `GET/PATCH /applications/{application_id}`
- `GET/POST /applications/{application_id}/events`

There is at most one application per user/job. Creation defaults to `Applied`, creates the initial status event, and returns the existing application on an idempotent retry. `status_id` is canonical; the legacy string field is a synchronized status slug.

Changing status through the application patch endpoint automatically appends an event containing the old status, new status, optional status note, and timestamp. Manual event types are `note`, `follow_up`, `online_assessment`, `interview`, `recruiter_contact`, `rejection`, and `offer`.

Application lists can filter by status, terminal state, company, active-job state, and saved-job state.

## In-app notifications

- `GET /notifications` with optional `unread=true|false`
- `PATCH /notifications/{notification_id}/read`
- `POST /notifications/read-all`

Real ingestion can create `new_match`, `reposted_job`, and `job_updated` rows. A new/reposted job must match preferences and meet `minimum_score_threshold`. `job_updated` applies when a saved or applied job gets a new description version. Each event has a stable unique dedupe key, so repeated source runs do not spam the inbox. Dry runs create no notifications.

Notifications are database records only: there is no email, browser push, polling worker, or scheduler.

## Duplicate review

`GET /admin/duplicates` and its patch response include complete candidate and existing-job summaries. Resolution behavior is:

- `merged`: mark the candidate `duplicate` and link it to the canonical job;
- `not_duplicate`: mark the candidate `unique` and clear the canonical link;
- `dismissed`: close the review without changing candidate duplicate state;
- `open`: reopen the review without changing candidate state.

Confirmed duplicates are excluded from default `GET /jobs` results.

## Local verification

```powershell
uv sync --dev
docker compose up -d postgres
uv run alembic upgrade head
uv run hunt-board seed
uv run pytest
uv run uvicorn hunt_board.main:app
```

The test suite remains offline: ATS behavior uses fixture JSON or in-process fake adapters.

## Out of scope

Milestone 2 does not add frontend code, demo mode, multi-user authentication/RBAC, resume parsing, email or browser delivery, background workers/queues, full-text search infrastructure, deployment automation, or new ATS adapters.
