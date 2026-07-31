# Supabase authentication setup

Hunt Board uses Supabase Auth as the identity provider and keeps authorization,
roles, invitations, and private-record ownership in the Hunt Board database.
The browser receives only the public project URL and anonymous key. Never place
the service-role key in frontend code, screenshots, logs, fixtures, or this
repository.

## Prerequisites

- A Supabase project for the beta environment.
- The Hunt Board API origin, for example `http://localhost:8000`.
- Node.js available for Supabase CLI commands.
- A separate production project/configuration when deployment begins.

## Local project link and database commands

Every Supabase CLI command is intentionally prefixed with `npx`:

```powershell
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
npx supabase migration list
```

Hunt Board's canonical application migrations remain Alembic migrations. Use
`npx supabase db push` only for the linked Supabase workflow after confirming
that its migration directory mirrors the reviewed policy SQL. Do not improvise
policies in the dashboard without adding the equivalent version-controlled
change.

## Server environment

Set:

```dotenv
HUNT_BOARD_ENVIRONMENT=development
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_PUBLIC_ANON_KEY
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ISSUER=https://YOUR_PROJECT_REF.supabase.co/auth/v1
```

`SUPABASE_ANON_KEY` is designed for public clients. Do not add a service-role
key to browser configuration. If later server-side provider administration
needs one, use a server-only secret named separately and scope its use to
invitation, ingestion, migration, purge, or tightly reviewed admin work.

## URL configuration

In Supabase Dashboard → Authentication → URL Configuration:

- Site URL for local work: `http://localhost:8000`
- Additional redirect URL:
  `http://localhost:8000/app/sign-in.html`
- Add the exact deployed HTTPS sign-in URL later; do not use an unrestricted
  wildcard in production.

The frontend uses PKCE and returns OAuth and email-link sign-ins to
`/app/sign-in.html`.

## Email and password

In Authentication → Providers → Email:

1. Enable email/password.
2. Keep email confirmation required.
3. Do not enable automatic Hunt Board access based only on confirmation. The
   server still requires an exact pending invitation.
4. Test that an unverified password account receives `403` from
   `POST /auth/activate`.

Suggested confirmation-template copy:

> Confirm your email to finish provider sign-in. Hunt Board access is granted
> separately to an invited email.

Keep the template's Supabase confirmation variable intact. Do not paste or log
a generated confirmation URL.

## Passwordless email link

Enable Email OTP/magic-link sign-in. The current frontend calls
`signInWithOtp` and uses the configured sign-in redirect. Keep invitation
matching exact after trimming and lowercasing the provider email.

Suggested template subject: `Your Hunt Board sign-in link`.

The link must lead through Supabase verification and return to the configured
redirect. Hunt Board never stores the link or OTP.

## Google OAuth

1. Create a Google OAuth web client.
2. Add the Supabase callback shown on Authentication → Providers → Google to
   the Google client's authorized redirect URIs. It normally has the form
   `https://YOUR_PROJECT_REF.supabase.co/auth/v1/callback`.
3. Add the Google client ID and secret to the Supabase provider settings, not
   Hunt Board JavaScript.
4. Enable Google.
5. Confirm the Google identity returns the exact invited email.

If one human uses multiple methods, Supabase identity linking must map those
methods to the same auth user UUID. Hunt Board deliberately rejects a second
auth UUID attempting to claim an email already bound to a non-local profile.

## Bootstrap the first local admin

For development only:

```powershell
uv run alembic upgrade head
uv run hunt-board seed
```

The seed creates or updates a deterministic local UUID profile and an accepted
local invitation. Automatic admin creation is refused when
`HUNT_BOARD_ENVIRONMENT=production`.

For a real beta project, create the owner invitation/profile through a reviewed
bootstrap procedure using a trusted database or service-role session, then
sign in with the same email. Do not temporarily make the public invitation
policy permissive.

## Verification

```powershell
uv run pytest
```

Then follow `docs/owner-ui-checklist-6.0.md`. In browser developer tools,
confirm requests contain a user access token only and that no service-role key,
refresh token in response bodies, raw job JSON, or another user's state is
present.
