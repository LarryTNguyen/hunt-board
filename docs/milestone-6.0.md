# Milestone 6.0 — Multi-user foundation

Milestone 6 replaces implicit first-user resolution with verified Supabase
identity mapping and adds invite-only profiles, two roles, PostgreSQL RLS,
protected API boundaries, a static-frontend authentication shell, and
provider-neutral observability.

## Decisions

- The existing `users` table remains the Hunt Board profile table. Its integer
  ID is an internal compatibility key; `users.auth_user_id` is the unique
  Supabase UUID authorization boundary. Caller-provided user IDs are never
  trusted.
- `role` has exactly `admin` and `user`. The retained `is_admin` column is a
  Milestone 1 compatibility field and must agree with `role`; authorization
  requires both until a later cleanup migration removes it.
- Existing local private rows are assigned to a deterministic UUID derived
  from the normalized seed email. A development-only activation may replace
  that placeholder with the real invited Supabase UUID. Production does not
  auto-seed an admin.
- An accepted, non-revoked invitation is checked on every protected request in
  addition to profile active state.
- Existing saved/discarded rows are backfilled into canonical
  `user_job_states`. The legacy tables remain temporarily mapped for Milestone
  1–5 compatibility; all receive the same owner RLS. A later cleanup can move
  remaining compatibility reads and drop them after a measured release.
- Multiple applications for the same user/job are allowed only through the
  explicit `POST /jobs/{job_id}/applications` action with
  `{"create_new": true}`. The default remains idempotent for Milestone 1–5
  clients. Catalog summaries select the newest application deterministically.
- Public job routes expose normalized catalog response models only. Raw JSON,
  provider payloads, application notes, and private state never appear.
- RLS policies map each private row's internal `user_id` through
  `users.auth_user_id = auth.uid()`. Application events use an indirect
  ownership `EXISTS` check. Ownership cannot be changed to another profile
  because update `WITH CHECK` repeats the owner predicate.
- Admin browser visibility is only a convenience. Every admin API and the
  parallel ingestion mutation require the trusted admin dependency.

## Route boundaries

Public:

- Health endpoints
- `GET /auth/config`
- `POST /auth/activate` with a valid provider bearer token
- Limited read-only catalog routes
- Landing, discovery/detail, and sign-in static pages

Authenticated:

- `GET /auth/me`
- Preferences, saved searches, Daily Hunt, notifications
- Saved/dismissed state, applications, and events
- Personalized fields on catalog reads

Admin:

- All `/admin/*` operations and duplicate-review APIs
- Invitation creation/list/revocation
- Profile deactivation/reactivation
- Metrics
- `/api/ingest/run`

## Observability

Request middleware accepts safe request/trace IDs or generates them, returns
both headers, records route templates rather than raw URLs, and emits structured
JSON-compatible events. Token verification and profile resolution have timed
trace events. The admin metrics endpoint exposes bounded route/status/auth
labels plus profile, invitation, authorization-denial, and database-error
counters.

Logs and metric labels must not contain names, email addresses, request bodies,
notes, cookies, access/refresh tokens, magic links, or provider/service keys.

## Manual provider work

The owner must configure:

- Supabase project URL and public anonymous key
- Email confirmation and passwordless templates
- Google OAuth client and Supabase callback
- Exact local/deployed redirect allow-list
- Initial real owner invitation/profile bootstrap

See `docs/auth-setup.md`.

## Known limitations

- Static HTML navigation requests cannot carry a bearer token. Client guards
  promptly redirect signed-out/non-admin users, while API authorization and RLS
  are the hard security boundary. A production reverse proxy may add
  cookie-based route redirects if serving the admin HTML bytes themselves must
  be denied.
- The JWKS verifier requires asymmetric Supabase signing keys (ES256, RS256, or
  EdDSA). Legacy HS256 projects should rotate to supported asymmetric keys
  rather than distribute a JWT secret.
- PostgreSQL RLS integration tests require
  `HUNT_BOARD_TEST_POSTGRES_URL`; the default suite remains fully offline on
  SQLite and proves API/service isolation with two identities.
- Provider identity linking behavior is ultimately controlled by Supabase. Hunt
  Board protects against two unrelated auth UUIDs claiming one normalized
  profile email.
- Profile deletion scheduling fields are present, but a destructive purge
  workflow is intentionally deferred until its retention policy is specified.

## Commands

```powershell
uv run alembic upgrade head
uv run hunt-board seed
uv run pytest
```

Run the owner checklist after provider setup.
