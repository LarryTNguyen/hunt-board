# Codex prompt: Hunt Board Milestone 3 - live frontend MVP

You are working in the Hunt Board repository. Milestone 2 is considered complete. Implement Milestone 3 as a live, demo-ready frontend that is based on the existing static mockups and consumes the existing FastAPI backend APIs.

## One-sentence goal

Turn the static screens in `mock-designs/` into a live single-user Hunt Board frontend, served by the FastAPI app, with real API reads/writes for job discovery, saved jobs, applications, notifications, preferences, and duplicate review.

## Sources of truth to inspect first

Read these files before editing code:

- `AGENTS.md`
- `README.md`
- `docs/milestone-2.md`
- `mock-designs/index.html`
- `mock-designs/job-discovery.html`
- `mock-designs/job-detail.html`
- `mock-designs/saved-jobs.html`
- `mock-designs/application-tracker.html`
- `mock-designs/notifications.html`
- `mock-designs/preferences.html`
- `mock-designs/duplicate-review.html`
- `mock-designs/app.css`
- `mock-designs/app.js`
- `.superdesign/design-system.md`, if present
- `src/hunt_board/main.py`
- `src/hunt_board/api/schemas.py`
- `src/hunt_board/api/jobs.py`
- `src/hunt_board/tracking/api.py`
- `src/hunt_board/notifications/api.py`
- `src/hunt_board/admin/api.py`

The mockups are the visual and interaction reference. The backend schemas are the data contract.

## Preferred implementation approach

Use a lightweight frontend that matches the repo's current architecture:

- Use plain HTML, CSS, and vanilla JavaScript ES modules.
- Do not introduce React, Vite, Tailwind, shadcn, npm, Playwright, or a frontend build step for this milestone.
- Serve the frontend from the existing FastAPI application using Starlette/FastAPI static file support.
- Preserve the existing JSON API routes and do not break legacy `/api/...` compatibility routes.
- Keep `mock-designs/` as the archived static design reference. Do not mutate it heavily. Create the live app in a new location.

Recommended file layout:

```text
src/hunt_board/web/static/
  index.html
  job-discovery.html
  job-detail.html
  saved-jobs.html
  application-tracker.html
  notifications.html
  preferences.html
  duplicate-review.html
  assets/
    app.css
    api.js
    format.js
    navigation.js
    ui.js
    pages/
      discovery.js
      job-detail.js
      saved-jobs.js
      applications.js
      notifications.js
      preferences.js
      duplicate-review.js
```

Mount the live frontend at `/app`:

- `/app/` or `/app/index.html`
- `/app/job-discovery.html`
- `/app/job-detail.html?id=<job_id>`
- `/app/saved-jobs.html`
- `/app/application-tracker.html`
- `/app/notifications.html`
- `/app/preferences.html`
- `/app/duplicate-review.html`

If a different static directory is easier, keep the same route behavior and document the choice.

## Visual requirements

Use `mock-designs/app.css` as the starting point for the live app stylesheet. Preserve the product identity:

- Paper/map surface: `#f2ebd9`
- Elevated paper: `#fbf8ef`
- Forest ink: `#163d34`
- Graphite: `#252821`
- Signal orange: `#e4572e`
- Grid olive: `#8b9274`
- Sun yellow: `#f2c14e`
- Display face: `Barlow Condensed` with fallbacks
- Body face: `Manrope` with fallbacks
- Data face: `IBM Plex Mono` with fallbacks

Keep the safari field-desk concept from the mockups: route plotting, observation sheets, sightings ledger, wanted-board saved jobs, film-roll application tracker, dispatch-style notifications, field-kit preferences, and duplicate-review comparison sheets.

Accessibility requirements:

- Keep semantic landmarks: `header`, `main`, `nav`, `section`, `article`, `aside`.
- Keep skip links and visible focus states.
- Controls must have labels or `aria-label` values.
- Loading, empty, error, and success states must be communicated in text, not just color.
- Respect existing responsive behavior in the mockups.
- Do not inject unsanitized `description_html` from ATS data. Prefer `description_text`. If rendering HTML is needed, implement a tiny allowlist sanitizer or keep plain text.

## Existing API contract to use

Use same-origin relative URLs. Do not hardcode `localhost`.

### Jobs

- `GET /jobs`
- `GET /jobs/{job_id}`

Useful `GET /jobs` query params:

- `active=true|false`
- `company=<text>`
- `source_slug=<slug>`
- `ats=<greenhouse|lever|ashby>`
- `location=<text>`
- `workplace_type=<text>`
- `duplicate_status=<status>`
- `include_duplicates=true|false`
- `min_score=<0-100>`
- `search=<text>`
- `title=<text>`
- `saved=true|false`
- `discarded=true|false`
- `application_status=<slug-or-name>`
- `remote_only=true|false`
- `sort_by=ranking_score|first_seen_at|last_seen_at|posted_at|company_name|title`
- `sort_order=asc|desc`
- `limit=<1-200>`
- `offset=<0+>`

Important fields in job responses:

- `id`
- `title`
- `company_name`
- `location`
- `department`
- `employment_type`
- `workplace_type`
- `posting_url`
- `apply_url`
- `description_text`
- `active`
- `duplicate_status`
- `is_duplicate`
- `is_reposted`
- `ranking_score`
- `ranking_reasons`
- `first_seen_at`
- `last_seen_at`
- `posted_at`
- `source_slug`
- `source`
- `is_saved`
- `saved_job_id`
- `is_discarded`
- `discarded_job_id`
- `has_application`
- `application_id`
- `application_status`

### Saved jobs

- `GET /saved-jobs`
- `POST /jobs/{job_id}/save` with optional body `{"notes":"..."}`
- `DELETE /jobs/{job_id}/save`
- `PATCH /saved-jobs/{saved_job_id}` with body `{"notes":"..."}`

### Discard pile

- `GET /discarded-jobs`
- `POST /jobs/{job_id}/discard`
- `DELETE /jobs/{job_id}/discard`

Use discard as the frontend's "hide from route" action. Do not delete job postings.

### Applications and timeline events

- `GET /application-statuses`
- `GET /applications`
- `POST /jobs/{job_id}/applications` with optional body `{"status":"applied","notes":"..."}`
- `GET /applications/{application_id}`
- `PATCH /applications/{application_id}` with body containing any of `status`, `notes`, `status_note`
- `GET /applications/{application_id}/events`
- `POST /applications/{application_id}/events` with body containing `event_type`, optional `notes`, optional `occurred_at`

Manual event types currently accepted by the backend:

- `note`
- `follow_up`
- `online_assessment`
- `interview`
- `recruiter_contact`
- `rejection`
- `offer`

Status slugs are seeded by the backend. Fetch them from `/application-statuses` and use the slug values instead of hardcoding only mockup labels.

### Notifications

- `GET /notifications`
- `GET /notifications?unread=true`
- `PATCH /notifications/{notification_id}/read`
- `POST /notifications/read-all`

Notification rows include:

- `id`
- `kind`
- `job_posting_id`
- `scrape_run_id`
- `payload_json`
- `read_at`
- `created_at`

Render a sensible title and body from `payload_json`; provide fallbacks for unknown payload shapes.

### Preferences

- `GET /me/preferences`
- `PATCH /me/preferences`
- `POST /me/preferences/rescore`

Preference fields:

- `include_keywords`
- `exclude_keywords`
- `role_groups`
- `preferred_levels`
- `preferred_locations`
- `home_location`
- `radius_miles`
- `country`
- `remote_allowed`
- `minimum_score_threshold`

Use backend-supported values. Role groups currently include names like `software_engineering`, `backend`, `machine_learning`, `data_science`, `full_stack`, `fullstack`, and `data`. Supported level values include `intern`, `entry`, `junior`, `mid`, `senior`, `staff`, `principal`, `lead`, `manager`, and `director`.

### Duplicate review

- `GET /admin/duplicates?status=open`
- `GET /admin/duplicates?status=<status>`
- `PATCH /admin/duplicates/{duplicate_review_id}` with body `{"status":"merged|not_duplicate|dismissed|open","resolution_notes":"..."}`

Map duplicate review UI buttons as follows:

- `Merge records` -> `merged`
- `Keep separate` -> `not_duplicate`
- `Defer` -> `dismissed`, unless you provide a clearer `Leave open` action that maps to `open`

## Required frontend behavior by page

### 1. `/app/index.html` - live landing and entry

Use the existing `mock-designs/index.html` as the visual source. It can remain mostly static, but update links so they point to the live `/app/...` pages. The page should clearly invite the user to open the live product workspace.

Acceptance criteria:

- Loads at `/app/` and `/app/index.html`.
- Main navigation points to live pages.
- Does not claim live customer data or live listing counts.

### 2. `/app/job-discovery.html` - daily sightings ledger

Use `GET /jobs` as the source of truth.

Required behavior:

- Render active, non-duplicate, non-discarded jobs by default.
- Search box calls `GET /jobs?search=<term>` after debounce, or filters the currently loaded data if simpler.
- Tabs:
  - `All`: default visible jobs.
  - `New`: jobs that are not saved and do not have an application.
  - `Saved`: use `saved=true` or client-side `is_saved`.
  - `Top matches`: score greater than or equal to 90, or the user's `minimum_score_threshold` if higher.
- Location filter maps to `location` or `remote_only`.
- Sort dropdown maps to `sort_by` and `sort_order`.
- Selecting a row opens the observation drawer with the selected job's live data.
- Drawer actions:
  - `View full dossier` links to `/app/job-detail.html?id=<job_id>`.
  - `Save` calls `POST /jobs/{job_id}/save` and updates row state.
  - `Hide` or `Discard` calls `POST /jobs/{job_id}/discard` and removes the row from the default list.
  - `Add to tracker` calls `POST /jobs/{job_id}/applications`.
- Show loading, empty, and error states.

### 3. `/app/job-detail.html?id=<job_id>` - job dossier

Use `GET /jobs/{job_id}`.

Required behavior:

- Render title, company, location, workplace type, source, active state, score, score reasons, first/last seen dates, official posting/apply link, and description text.
- Show tags for saved, applied, duplicate, reposted, active/closed.
- Save/unsave uses saved job endpoints.
- Notes:
  - If the job is saved, update notes with `PATCH /saved-jobs/{saved_job_id}`.
  - If the job is not saved and the user saves notes, first call save with the notes.
- `Add to tracker` calls `POST /jobs/{job_id}/applications` and then links to or shows the new application state.
- `Open official posting` uses `apply_url` first, then `posting_url` as fallback.
- Never use `innerHTML` with raw ATS HTML unless sanitized.

### 4. `/app/saved-jobs.html` - saved field board

Use `GET /saved-jobs`.

Required behavior:

- Render saved jobs as wanted-board cards using live data.
- Search/filter cards by title/company/location/source.
- Sort by recently saved by default; optionally support highest match and oldest saved client-side.
- `Open dossier` links to `/app/job-detail.html?id=<job_id>`.
- `Remove` calls `DELETE /jobs/{job_id}/save` and removes the card.
- Inline note editing calls `PATCH /saved-jobs/{saved_job_id}`.
- Display application status when `application_status` is present.

### 5. `/app/application-tracker.html` - applications in motion

Use `GET /applications` and `GET /application-statuses`.

Required behavior:

- Render applications as the film-roll tracker from the mockup.
- Search by job/company.
- Status/stage filter uses backend status slugs and terminal state.
- Date filter can be client-side using `created_at`/`updated_at`.
- Updating an application's stage calls `PATCH /applications/{application_id}` with `status` and optional `status_note`.
- Editing notes calls `PATCH /applications/{application_id}` with `notes`.
- Show timeline/events for the selected application using `GET /applications/{id}/events`.
- Allow adding a manual event using `POST /applications/{id}/events`.
- The `+ Add application` action should either:
  - open a small job search dialog backed by `GET /jobs?search=...`, then create an application with `POST /jobs/{job_id}/applications`; or
  - link to discovery with a toast explaining that applications start from a job record.

Avoid adding new database columns for next action/deadline/contact unless absolutely necessary. For this milestone, store those details in `notes` or application events.

### 6. `/app/notifications.html` - incoming signals inbox

Use `GET /notifications`.

Required behavior:

- Render notifications as dispatch items.
- Show unread state using `read_at === null`.
- Nav badge should show count from `GET /notifications?unread=true`.
- Tabs filter by `kind`, with an `All` tab.
- `Mark read` calls `PATCH /notifications/{notification_id}/read`.
- `Mark all read` calls `POST /notifications/read-all`.
- If `job_posting_id` exists, provide `Open sighting` link to `/app/job-detail.html?id=<job_posting_id>`.
- Provide robust fallback copy for unknown notification kinds.

### 7. `/app/preferences.html` - field kit settings

Use `GET /me/preferences`, `PATCH /me/preferences`, and `POST /me/preferences/rescore`.

Required behavior:

- Load current preferences on page open.
- Include/exclude keywords should be editable as one phrase per line.
- Role groups should use supported backend keys, with user-friendly labels.
- Preferred levels should map to backend-supported values.
- Preferred locations should be editable as one phrase per line or comma-separated input.
- Include home location, radius, country, remote allowed, and minimum score threshold controls.
- `Save changes` calls `PATCH /me/preferences`.
- After saving, ask for confirmation or provide a second button to run `POST /me/preferences/rescore`.
- Show the rescore response summary: considered, rescored, visible, hidden/low-ranked, duration.
- Render validation errors from the backend in the page.

### 8. `/app/duplicate-review.html` - admin duplicate review

Use `GET /admin/duplicates?status=open` and `PATCH /admin/duplicates/{id}`.

Required behavior:

- Render queue of open duplicate review cases.
- Selecting a queue item renders candidate and existing job comparison.
- Show reason, status, confidence/signals from `signals_json`, company/title/location/source/apply URL, first/last seen, active state, and current duplicate status.
- Actions:
  - Merge records -> `merged`
  - Keep separate -> `not_duplicate`
  - Defer -> `dismissed`
- After a decision, remove the case from the open queue and select the next case.
- Include an empty state when there are no open reviews.

## Shared frontend modules

Create a small shared API client in `assets/api.js`:

- `request(path, options)` with JSON serialization, error handling, and same-origin URLs.
- Throw readable errors that include status code and response detail.
- Helpers for each endpoint group are encouraged, but keep it simple.

Create shared UI utilities in `assets/ui.js`:

- `makeToast(message, type)`
- `setBusy(element, isBusy)`
- `renderEmpty(target, title, body, action?)`
- `renderError(target, error, retry?)`
- `debounce(fn, ms)`

Create shared format helpers in `assets/format.js`:

- relative date formatting
- absolute date formatting
- score formatting
- text truncation
- safe URL handling
- fallback label helpers for statuses/kinds

Create shared navigation in `assets/navigation.js`:

- Render the wordmark and nav from the mockup.
- Highlight the current page.
- Fetch unread notification count and render the badge.
- Keep mobile menu behavior.

## Optional but strongly recommended: explicit demo seed

The live frontend is hard to evaluate against an empty database. Add an explicit, idempotent demo seed command without changing default seed behavior.

Preferred command:

```powershell
uv run hunt-board seed-demo
```

or:

```powershell
uv run hunt-board seed --demo
```

Requirements:

- Do not make demo data appear from the normal `hunt-board seed` command unless a `--demo` flag is supplied.
- Seed a small dataset that mirrors the mockups: Roblox, Poshmark, Unwrap.ai, Northstar, Fathom, and Altom-style job rows.
- Include at least:
  - 6 job postings across Greenhouse, Lever, and Ashby sources
  - 2 saved jobs with notes
  - 2 applications in different statuses
  - 3 notifications with different `kind` values
  - 1 open duplicate review case
- Keep it idempotent by using stable source slugs, external job IDs, apply URLs, and dedupe keys.
- Add tests for idempotence if implemented.

If demo seed would take too long, skip it and document how to get data into the UI through the existing ingestion commands. Do not block the rest of Milestone 3 on demo seed.

## Backend changes allowed

Allowed:

- Mount static frontend files at `/app`.
- Add small test-only/demo seed helpers.
- Add read-only helper endpoints only if the frontend cannot reasonably consume existing APIs. Prefer not to add new endpoints.
- Add CORS only if you introduce a separate origin, but the preferred approach is same-origin static files and no CORS changes.

Not allowed for this milestone:

- Multi-user authentication/RBAC.
- OAuth/login screens.
- Email, browser push, or SMS notifications.
- Resume parsing or AI resume matching.
- New ATS adapters.
- Background queues such as Celery, Redis, RabbitMQ, Kafka.
- OpenSearch or full-text search infrastructure.
- Major backend schema rewrites.
- Replacing the existing backend API contract.

## Tests and verification

Add or update tests where useful.

Minimum backend tests:

- Static frontend index is served from `/app/` or `/app/index.html`.
- At least one frontend asset is served, for example `/app/assets/app.css` or `/app/assets/api.js`.
- Existing API routes still work.
- If demo seed is implemented, test that it is idempotent.

Suggested test file:

```text
tests/test_milestone_three_frontend.py
```

Run:

```powershell
uv sync --dev
docker compose up -d postgres
uv run alembic upgrade head
uv run hunt-board seed
uv run pytest
```

Manual verification:

```powershell
uv run uvicorn hunt_board.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/app/
```

If demo seed is implemented:

```powershell
uv run hunt-board seed-demo
```

Then verify all live pages have data and the actions persist after refresh.

## Documentation updates

Update `README.md` with:

- Live frontend route: `/app/`
- Difference between `mock-designs/` and the live frontend
- Frontend commands, if any
- Demo seed command, if implemented
- Manual QA checklist

Add this implementation spec to:

```text
docs/milestone-3.md
```

Keep `docs/milestone-2.md` intact unless a small clarification is needed.

## Cleanup requirements

Do not commit or depend on generated/private files:

- `.env`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- `.git/`
- local browser screenshots or temporary debug files

If `.gitignore` is missing any of those, update it.

## Milestone 3 definition of done

Milestone 3 is done when all of these are true:

- `/app/` serves a live frontend from FastAPI.
- The frontend preserves the visual identity of the supplied mockups.
- Discovery, detail, saved jobs, applications, notifications, preferences, and duplicate review pages all render live backend data.
- Save/unsave, discard/restore, application creation, application status updates, application event creation, notification read state, preference updates/rescore, and duplicate review decisions work through the API.
- All pages show loading, empty, and error states.
- Navigation unread badge uses live notification data.
- The UI is responsive and keyboard-accessible.
- Existing backend tests pass.
- New Milestone 3 tests pass.
- README documents how to run and verify the frontend.

## Normalized job metadata extension

The live frontend also consumes normalized company and compensation metadata:

- `sources.company_logo_url` is configured in `data/sources.yaml` and returned with source and job reads. The UI removes failed images and keeps the initials fallback visible.
- `job_postings.location_country_code` stores an ISO 3166-1 alpha-2 code, while `location_country` stores the canonical display name. Explicit Lever and Ashby country fields take priority; Greenhouse office/location text and common US state suffixes are conservative fallbacks.
- `salary_min`, `salary_max`, `salary_currency`, and `salary_interval` are populated only from structured ATS fields. Lever uses `salaryRange`; Ashby requests `includeCompensation=true` and selects the salary summary component; Greenhouse normalizes `pay_input_ranges` when that structure is present in a payload.
- `GET /jobs` accepts `country` and `salary_known` filters. Discovery, job dossiers, saved cards, and the application tracker show the normalized values when available.

## Completion report format

When finished, report:

1. What changed.
2. Files created/changed.
3. Commands to run.
4. Test results.
5. Known limitations.
6. Recommended next step.
