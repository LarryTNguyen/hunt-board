# Milestone 6.0 pre-implementation audit

Date: 2026-07-29

This audit is the required first Milestone 6.0 artifact. It records the
single-user assumptions and security boundaries present after Milestone 5,
before functional Milestone 6 changes.

## Baseline and compatibility constraints

- The repository contains in-progress, uncommitted Milestone 5 changes. They
  are the baseline for this work and must not be reset or overwritten.
- `users.id` is the integer owner key used by all existing private tables.
  Milestone 6 will retain it as an internal compatibility key and add a unique
  Supabase auth UUID to `users`. Authentication and authorization must resolve
  the UUID from a verified token to this internal ID; caller-provided integer
  IDs are never an authorization input.
- The existing `users` row is the application profile record. Extending this
  table is safer than renaming it while uncommitted Milestone 5 work depends on
  its foreign keys. Documentation and API copy call it a profile.
- Existing tests construct users directly and use SQLite. A clearly isolated
  test-auth dependency override is required; production may not fall back to
  the seeded first user.
- PostgreSQL RLS is versioned in Alembic. SQLite remains the offline unit-test
  database, so policy verification needs optional PostgreSQL integration tests
  in addition to service/API isolation tests.

## Single-user assumptions by module

| Area | Current assumption | Required boundary |
| --- | --- | --- |
| `auth/single_user.py` | Selects the first active integer user. Missing seed returns 503. | Replace route usage with verified bearer-token identity, invitation/profile resolution, `require_user`, and `require_admin`. Retain only an explicit test helper if needed. |
| `api/preferences.py` | All three `/me/preferences` routes call `get_single_user`. | Authenticated profile only; rescore for that owner. |
| `tracking/api.py` | Saved, discarded, applications, and events all use the first user. | Authenticated profile only. Every object lookup must include owner, including event access through its application. |
| `searches/api.py` | Saved-search CRUD, matches, and reviewed state use the first user. | Authenticated profile only; continue to call the central discovery query path with the resolved internal profile ID. |
| `dashboard/api.py` | Daily dashboard counts and saved-search cards use the first user. | Authenticated profile only. `first_seen_at` remains the review/newness boundary. |
| `notifications/api.py` | Notification list/read actions use the first user. | Authenticated profile only; discarded filtering must use the same owner. |
| `api/jobs.py` | Public list/feed/detail optionally personalize against whichever active user is seeded. | Split limited public catalog responses from authenticated personalized responses. Public requests must not inherit a user or expose raw/private fields. |
| `admin/api.py` | Reads and mutations have no authentication. | Every admin endpoint requires an admin. Mutation events must be audited. |
| `api/ingest.py` | `/api/ingest/run` is an unauthenticated mutation outside the admin router. | Require admin or remove the parallel unsafe route. |
| `ingestion/service.py` | Ranking/notification paths select the first or first active user. | Ingestion may operate over all active profiles where user-specific output is required; no implicit first-user selection. |
| `matching/service.py` | Accepts a `User`, but callers commonly obtain it from the shim. | Keep explicit profile argument and ensure callers use trusted identity or deliberate ingestion iteration. |
| `db/seed.py` | Seeds the configured email as active admin in every environment. | Deterministic local auth UUID, normalized email, idempotent profile/preferences/searches. Refuse automatic admin seeding outside local/test/development. |
| `main.py` | Mounts every HTML page below an unguarded static directory and has no request correlation. | Add public auth/config routes, request IDs/traces, sanitized structured logs/metrics, and client route guards. API authorization remains the hard boundary. |
| `web/static/assets/api.js` | Sends anonymous fetches and has no session-expiry behavior. | Bootstrap/refresh Supabase session, attach bearer token, and redirect cleanly on 401. |
| `web/static/assets/navigation.js` | Always renders Operations and Duplicate review. | Render private navigation only after session bootstrap and admin items only after trusted `/auth/me` role resolution; add desktop/mobile account controls. |
| All private HTML pages | Assume APIs are available anonymously. | Guard on session bootstrap. Sign-in and the limited public catalog remain public. |

## Private data inventory

| Table/domain | Existing ownership | Migration/RLS action |
| --- | --- | --- |
| `user_preferences` | Direct `user_id` | RLS through `users.auth_user_id`; ownership immutable. |
| `saved_searches` | Direct `user_id` | RLS through profile mapping; ownership immutable. |
| `saved_jobs` and `discarded_jobs` | Separate direct-owner tables | Consolidate into `user_job_states`, preserving saved notes and saved/discarded timestamps. |
| `job_matches` | Direct `user_id` | RLS through profile mapping; ownership immutable. |
| `applications` | Direct `user_id`; unique user/job constraint | Direct-owner RLS. Remove the uniqueness constraint so a deliberate API action can create multiple applications for the same user/job. |
| `application_events` | Owner is indirect through `applications` | RLS using an `EXISTS` owner check. API lookup must also join/check the application owner. |
| `notifications` | Direct `user_id`; globally unique dedupe key | Direct-owner RLS. Preserve server-generated payloads; browser cannot reassign ownership. |
| Future manual jobs, feedback, analytics, deleted items | Not present | Must use the same auth UUID-to-profile owner pattern when added; out of scope to create empty feature tables. |

Shared catalog/operations tables are `sources`, `job_postings`,
`job_versions`, `application_statuses`, `duplicate_reviews`, `scrape_runs`, and
`scrape_source_runs`. Public catalog access is intentionally read-only and
limited to normalized response fields. Raw JSON, raw HTML, scrape operations,
source configuration, duplicate resolution, and ingestion are never public.

## Route inventory and intended access

Public:

- `GET /health`, `/health/live`, `/health/db`, `/health/ready`
- `GET /auth/config`
- `POST /auth/activate` (requires a valid Supabase bearer token but not an
  existing profile)
- Limited, read-only `GET /jobs`, `/jobs/feed`, and `/jobs/{id}`
- Static sign-in and landing/catalog shell

Authenticated:

- `GET /auth/me`
- `/me/preferences` read/update/rescore
- Saved/discarded state routes
- Applications and application-event routes
- Notifications routes
- Saved-search routes and Daily Hunt dashboard
- Personalized job fields when a valid session is present

Admin:

- All `/admin/*` routes, including read-only operations data
- `/api/ingest/run`
- Invitation list/create/revoke
- Protected metrics
- Profile list/deactivate/reactivate/deletion scheduling and tightly scoped
  purge operations

## Security boundaries

- Only a verified Supabase access token supplies `sub`, email, provider, and
  verification claims. Request bodies, query strings, and URL IDs never supply
  owner or role.
- Role, active state, invitation acceptance, deactivation, and deletion state
  come from the database profile, not JWT metadata.
- A valid Supabase identity is insufficient: protected access requires a
  matching accepted invitation and active profile.
- Activation normalizes email using trim plus case-fold/lowercase and accepts
  only an active, non-revoked invitation for the exact normalized email.
- Email/password activation requires a verified-email claim. OAuth and email
  link providers rely on Supabase's verified identity claims.
- The browser receives only the Supabase URL and public anonymous key. Service
  role credentials stay server-side and are never logged or returned.
- 401 means the request lacks a valid/usable authentication token. 403 means a
  verified identity lacks invitation, activation, active status, or required
  role.
- PostgreSQL policies apply defense in depth for browser/user JWT database
  access. Trusted ingestion/admin work uses the service role or migration
  connection and does not grant permissive browser policies.
- Structured logs prohibit names, emails, tokens, cookies, magic links,
  application notes, raw bodies, and provider/service secrets. Metric labels
  are restricted to bounded route templates, status classes, and decision
  categories.

## Migration risks and mitigations

- **Existing owner rows:** add deterministic seed `auth_user_id`, normalize the
  existing seed email, then make auth UUID and normalized email unique/non-null
  only after backfill.
- **Job-state consolidation:** merge saved/discarded rows by `(user_id,
  job_posting_id)` before dropping legacy tables. A row may retain both saved
  and dismissed timestamps so no state is lost.
- **Multiple applications:** dropping the existing unique constraint changes
  lookup semantics. List and explicit-create APIs must use application IDs;
  job summaries use deterministic most-recent application state.
- **RLS and backend pooling:** request dependencies set transaction-local
  `request.jwt.claim.sub` only for PostgreSQL user-scoped work. Backend
  service-role paths remain separately trusted. Connection-local identity must
  never leak across pooled requests.
- **Alembic downgrade:** recreate legacy saved/discarded data from
  `user_job_states`, remove policies before schema changes, and keep auth
  profile data where practical. Accepted identity metadata cannot be perfectly
  represented in the Milestone 5 schema and will be discarded on downgrade.
- **Static route protection:** bearer tokens cannot accompany a normal HTML
  navigation request. The frontend guard prevents authenticated users from
  remaining on unauthorized pages, while the API is the non-bypassable
  security boundary. Production hosting must also apply route-level redirects
  if zero-byte exposure of static admin markup is required.
- **Provider setup:** Google OAuth, email templates, redirect allow-list, and
  Supabase project keys require manual owner configuration and are documented
  separately.

## Out-of-scope guardrails

This milestone does not add authenticated Workday APIs, automatic board
discovery, browser automation, an in-process scheduler, task queues, external
search, resume analysis, delivery notifications, production deployment, or a
second frontend framework.
