# Milestone 5: Saved Searches and the Daily Hunt

Milestone 5 turns the discovery feed into a repeatable daily workflow. It adds persisted saved searches, explicit review state, a read-only daily dashboard API, two live frontend pages, and discovery-route capture. It does not change ATS ingestion behavior.

## Saved-search contract

`saved_searches` belongs to the seeded single user and stores a name, optional description, typed filter JSON, deterministic sort, active/default flags, optional in-app notification preference, and `last_viewed_at`. Names are unique per user.

The filter object accepts only discovery-portable keys. `source_slug` is supported; `source_id` is intentionally rejected. Validation trims strings, normalizes ATS/application/sort values, uppercases two-letter country codes, enforces numeric bounds, and rejects unknown fields. Matching converts the validated object into `JobQueryFilters` and reuses `job_row_statement`, `apply_job_filters`, `apply_job_sort`, `count_jobs`, `feed_facets`, and `job_read_payload`.

Routes:

- `GET /saved-searches`
- `POST /saved-searches`
- `GET/PATCH/DELETE /saved-searches/{saved_search_id}`
- `GET /saved-searches/{saved_search_id}/matches`
- `POST /saved-searches/{saved_search_id}/mark-reviewed`

`new_since_review_count` counts matching postings whose `first_seen_at` is later than `last_viewed_at`. ATS `posted_at` is not used because it can be stale or backfilled. A null review timestamp means every current match is new. Changing filters does not reset review state unless PATCH explicitly includes `reset_reviewed=true`.

## Daily dashboard

`GET /dashboard/daily` is the read model for `/app/dashboard.html`. It reports:

- ingestion freshness and source attention;
- recent, saved, discarded, application, inbox, duplicate-review, and route totals;
- active saved routes with counts and three-job previews;
- up to ten new route matches, deduplicated by job ID;
- application pipeline counts;
- non-terminal applications unchanged for at least seven days.

When no active routes exist, top matches fall back to active, non-discarded, untracked jobs above the user's preference threshold that were first seen in the last seven days. The endpoint is calculated on read and exposes neither `raw_json` nor source `config_json`.

## Frontend workflow

`/app/dashboard.html` is the practical daily start page. It supports save, hide, and tracker actions on new matches. `/app/saved-searches.html` supports route creation, editing, deletion, match viewing, `new_only`, review marking, and links back to a serialized discovery URL. Discovery adds **Save this route** without changing URL-driven feed state.

The idempotent seed creates `Daily Hunt` only when the user has no saved searches. It uses the seeded preference threshold and excludes discarded, tracked, and confirmed duplicate jobs.

## Boundaries

Notifications remain database-backed and in-app only. The `notify_on_new_matches` preference is persisted for future ingestion integration, but Milestone 5 does not add external delivery. There is no resume upload/parsing, AI or LLM matching, scheduler inside FastAPI, task queue, multi-user authentication, new ATS adapter, source discovery, or browser automation.

## Validation

```powershell
uv run alembic upgrade head
uv run hunt-board seed
uv run pytest
```

Offline tests cover saved-search validation and CRUD, default selection, matching and review state, dashboard aggregation/deduplication/fallback/privacy, seed idempotency, and static frontend contracts.
