# Backup, restore, and rehearsal

- Enable provider-managed daily production backups. Retain according to the
  selected Supabase plan and the private-beta policy.
- Create an on-demand backup before every potentially destructive migration.
- Keep Alembic history in Git; do not make manual production schema edits.
- Once per release cycle, restore the latest production backup into a new,
  access-restricted nonproduction project. Never overwrite staging in place and
  never expose restored personal data to staging users.

## Restore rehearsal

1. Record backup timestamp, production release, and Alembic revision.
2. Restore into an isolated project with invitations/sign-up disabled and no
   cron secrets.
3. Point a temporary operations-only deployment at it.
4. Run `alembic current`, `/health/ready`, table/count checks, RLS/auth checks,
   source/run history checks, and a dry run. Do not send external alerts.
5. Compare source, active/inactive job, application, duplicate, quarantine, and
   lifecycle counts with the backup manifest.
6. Delete or lock the rehearsal project according to the privacy retention
   policy and save only nonpersonal evidence.

For corrupted production data, restore the last known-good backup into a new
database, replay only reviewed migrations/events after that point, validate,
then rotate connection secrets and switch the web/cron deployments. Preserve
the corrupt database read-only until the incident review ends.
