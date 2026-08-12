# Owner UI checklist — Milestone 6.0

## Prerequisites

- Run `uv run alembic upgrade head` and `uv run hunt-board seed`.
- Start the API at the origin configured in Supabase.
- Complete `docs/auth-setup.md`.
- Prepare three exact-email accounts:
  - `owner`: active Hunt Board profile with role `admin`
  - `member-a`: pending invitation, intended role `user`
  - `member-b`: pending invitation, intended role `user`
- Prepare one email with no invitation.
- Open browser developer tools with Preserve log enabled in Network and Console.

For every failed request, record the `X-Request-ID` response header. Search that
exact value in the server's structured log output; the matching record must
show route, method, status, and timing without email, token, cookie, body, or
notes.

## 1. Uninvited identity

1. Open `/app/sign-in.html`.
2. Sign in with the uninvited email using any configured method.

Expected: the page shows `An active invitation is required` (or the equivalent
account-denied state), redirects no private data into view, and protected API
requests return `403`.

## 2. Invited identity with all providers

From the owner Operations page, create an invitation for `member-a` using the
exact normalized email. Test Google, password, and email link in separate
browser profiles where Supabase linking supports the same auth identity.

Expected: each method returns to `/app/sign-in.html`, activation accepts the
exact invitation once, and the dashboard opens. A provider returning a
different email is denied.

## 3. Password verification

Create a new email/password identity for an invited address but do not click
the confirmation email. Attempt to enter.

Expected: visible text says `Verify your email before activating Hunt Board`;
the protected response is `403`. Confirm the email and repeat; activation then
succeeds.

## 4. Signed-out public boundary

Sign out, then open:

- `/app/`
- `/app/job-discovery.html`
- a job detail URL
- `/jobs` in Network or a REST client

Expected: normalized limited catalog content remains readable. No saved,
dismissed, application, notification, raw JSON, or owner information appears.
Private pages redirect to `/app/sign-in.html`.

## 5. Protected route redirect

While signed out, directly enter `/app/dashboard.html`.

Expected: a clean sign-in screen appears with `Sign in to open that route`.
After signing in, the browser returns to the dashboard.

## 6. User A versus User B

As `member-a`, create a saved search, save and dismiss jobs, create two
applications for one job, add an event/note, and leave a notification unread.
Copy the numeric saved-search/application/event URLs or IDs from Network.
Sign in as `member-b`, paste those URLs, and try changing IDs in Network replay
or the console.

Expected: list endpoints show only B's records. A's IDs return `404`; attempts
to reassign `user_id`, owner UUID, role, or status are ignored/rejected. No A
notes or notification payloads appear.

## 7. Standard user admin denial

As `member-a`, open `/app/operations.html` and
`/app/duplicate-review.html`. Request `/admin/operations`,
`/admin/invitations`, and `/admin/metrics` directly.

Expected: static guards return to the dashboard with `admin-required`; APIs
return `403`. Operations and Duplicate review are absent from desktop/mobile
navigation.

## 8. Admin operations and invitations

As `owner`, open `/app/operations.html`.

Expected: Operations and Duplicate review are visible. The Invitations panel
lists status and timestamps. Creating an exact email shows `Invitation
created`; revoking a pending invitation shows `Invitation revoked`. Accepted
invitations cannot be revoked.

## 9. Deactivation

While `member-a` has an active session, deactivate that profile using the
admin API/control. Refresh or make another API request.

Expected: the next request returns `403` with `This profile is not active`.
Refreshing the provider token does not restore Hunt Board access.

## 10. Account menus and sign out

At desktop width, open the upper-right field-pass menu and choose `Sign out`.
At mobile width, open the navigation and use its account section.

Expected: both clear the local Supabase session, show the signed-out message,
hide private/admin navigation, and make the next protected request return
`401`.

## 11. Browser secret inspection

Search page source, loaded JavaScript, Network request/response bodies, storage,
and Console for `service_role`, database credentials, another user's data,
magic-link URLs, or raw job JSON.

Expected: none are present. A current user's access/refresh session may exist in
Supabase-managed browser storage; no service-role key may appear anywhere in
the browser.

## 12. Request ID correlation

Cause a safe error, such as requesting a nonexistent application ID. In
Network, copy `X-Request-ID`.

Expected: the response includes the ID. One sanitized server log/trace record
has the same ID and route template, with no query string, email, token, cookie,
body, or application note.

## Failure capture

Capture:

- route and visible text
- expected versus actual result
- HTTP method/status
- `X-Request-ID`
- timestamp and browser
- a redacted screenshot

Never paste access/refresh tokens, cookies, service keys, magic links, or
application notes into an issue.
