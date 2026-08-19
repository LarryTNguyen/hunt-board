# Hunt Board deployment and release operations

Milestone 6.2 keeps one FastAPI web service and a separate one-shot ingestion
process. The documented reference is Render for the web service, Supabase for
Auth/PostgreSQL, and GitHub Actions for the two-hour scan. `Dockerfile` and the
commands below remain provider-neutral.

## Environments and budget

| Environment | Database/Auth | Runtime | Data rule |
| --- | --- | --- | --- |
| Development | Local Compose PostgreSQL plus a development Supabase project | Local Docker | Seeded owner and curated/full development sources are allowed. |
| Staging | Separate Supabase project | Manually activated/free web service | Synthetic invited users and `data/sources.staging.yaml`; never a production dump. |
| Production | Separate Supabase project | Render Starter web service | Invited real admin only; invitations stay disabled through launch validation. |

As of the implementation date, the target private-beta assumption is one
low-cost Render web instance (budgeted at about $7/month), Supabase free tier
where its current quotas and backup needs are acceptable, and included GitHub
Actions minutes for the two-hour job. Allow $0–$10/month for an optional email
alert/log add-on. Expected total: $7–$17/month, below $20. Provider prices and
free-tier terms change; verify them before launch. If paid Supabase backups are
required, re-evaluate the ceiling rather than silently dropping backup policy.

Each environment has different `DATABASE_URL`, `SUPABASE_URL`, anon key,
invited identities, provider URL, logs, and deployment ID. Do not copy users,
applications, notes, tokens, or production rows into staging. Never configure
`SUPABASE_SERVICE_ROLE_KEY` in the web, static app, or cron environment.

## Required production variables

Copy names from `.env.example`, not its development values. Production and
staging startup fail unless the environment name is recognized, the database
URL is non-local, Supabase uses HTTPS, an anon key is present, and
`HUNT_BOARD_RELEASE` is a real release identifier.

Required deployment identity:

```text
HUNT_BOARD_ENVIRONMENT=production
HUNT_BOARD_RELEASE=<git-sha-or-v0.6.2>
HUNT_BOARD_DEPLOYMENT_ID=<provider-deploy-id>
HUNT_BOARD_PROCESS=web
HUNT_BOARD_PUBLIC_URL=https://<provider-host>
```

Staging must set `HUNT_BOARD_SOURCES_PATH=data/sources.staging.yaml` and use a
reduced synthetic-safe registry. No `.env` file is committed.

## First production launch

Keep Supabase public sign-ups and Hunt Board invitations disabled until step 8.

1. Create the empty production Supabase project and production Auth URL allow
   list. Create the separate staging project independently.
2. Save an on-demand database backup before any destructive migration. For an
   empty database, save provider project/version evidence.
3. From the exact release image or checkout, migrate the empty schema:

   ```bash
   uv sync --frozen --no-dev
   uv run alembic current
   uv run alembic upgrade head
   uv run alembic current
   ```

4. Do **not** run `hunt-board seed` in production; it is guarded and will fail.
   Create the first Supabase Auth admin through the provider's secure invitation
   flow, then insert/activate the matching Hunt Board profile using a reviewed,
   one-time owner procedure. Never paste a service-role key into the browser.

For a single-instance free Docker web service without shell or pre-deploy
access, the image startup command runs `alembic upgrade head` before Uvicorn.
Migrations must therefore remain compatible with the previous application
release during deployment. Production reference data belongs in reviewed,
idempotent Alembic data migrations; never bypass the production seed guard.
5. Sync the reviewed production source registry:

   ```bash
   uv run hunt-board sync-sources
   uv run hunt-board coverage-report
   ```

6. Run the bounded initial catalog load:

   ```bash
   uv run hunt-board backfill --days 14
   ```

   Jobs with unknown posting dates are retained; known dates older than the
   boundary are excluded. Save the run/source IDs.
7. Validate active counts, all intended job families, source coverage, open
   duplicate reviews, classification `other` rate, errors, and quarantines in
   `/app/operations.html` and `/admin/coverage`. Reject the launch if a required
   source failed, a quarantine is unexplained, or counts are implausible.
8. Run the smoke checks, finish `docs/owner-ui-checklist-6.2.md`, and only then
   enable invited beta users. Public sign-up remains disabled.

## Deploy and migrate

Render reads `render.yaml`; keep automatic deploy disabled for controlled
releases. Build and inspect locally first:

```bash
docker build --build-arg HUNT_BOARD_RELEASE=<git-sha> -t hunt-board:<git-sha> .
docker run --rm hunt-board:<git-sha> hunt-board --help
docker compose config
```

Apply migrations as a separate release command before moving web traffic:

```bash
uv run alembic current
uv run alembic upgrade head
uv run alembic current
```

Start the web command only after migration succeeds:

```bash
uv run uvicorn hunt_board.main:app --host 0.0.0.0 --port 8000
```

The image itself does not migrate or seed on startup. Local Compose remains the
development convenience owner for migration and seed.

## Scheduled scans

`.github/workflows/ingestion-cron.yml` invokes `uv run hunt-board ingest` at
minute 17 every twelve hours. Configure the three production secrets named in the
workflow and protect the GitHub `production` environment. The one-shot command
uses the same PostgreSQL advisory lock and persisted pending state as admin,
API, CLI, and the optional local scheduler. GitHub concurrency prevents two
workflow jobs from starting together; the application lock remains the final
authority.

For another provider, schedule exactly:

```bash
HUNT_BOARD_PROCESS=cron uv run hunt-board ingest
```

every twelve hours with a 70-minute platform timeout. Do not put the scan in a
Vercel/serverless function and do not start the scheduler inside FastAPI.

## Smoke test

After deployment:

```bash
HUNT_BOARD_SMOKE_BASE_URL=https://<provider-host> uv run python scripts/deployment_smoke.py
curl -fsS https://<provider-host>/health/ingestion
```

Then sign in as the invited admin and confirm `/admin/operations` reports the
expected environment, release, deployment ID, healthy web/database state, and
no stale run. Save response headers `X-Request-ID` and `X-Trace-ID`.

## Rollback

Tag every stable release (`v0.6.2`, then patch tags) and retain its image. For
application-only failure, redeploy the last stable image. For a migration
problem, follow `docs/runbooks/rollback.md`; prefer forward fixes and
expand/contract migrations. Never run Alembic downgrade against production
until its data effects and backup restore point are reviewed.

## Alert hooks and retention

Use the hosting/log provider's optional email alerts for complete run failure
(`alert.scan.complete_failure`), repeated source failures
(`alert.source.repeated_failure`), quarantine (`alert.scan.quarantine`), no
successful run within four hours, and HTTP 5xx/auth spikes. No notification
vendor is mandatory in code. Retain
application/error logs 14–30 days, auth/security logs 30–90 days, raw debug logs
only a few days or disabled, and nonpersonal scan summaries at least 90 days.

Daily production backup, pre-migration backup, restore rehearsal, and corrupted
data recovery are specified in `docs/runbooks/backup-restore.md`.
