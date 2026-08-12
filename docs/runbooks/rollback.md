# Application and migration rollback

1. Declare the incident, pause the two-hour workflow, and record the current
   release, deployment ID, latest successful run, request ID, and trace ID.
2. Stop owner mutations if data integrity is uncertain. Do not delete catalog
   rows; disable scans while investigating.
3. For application-only failure, deploy the last stable tagged image with its
   original environment variables. Verify `/health/live`, `/health/ready`, sign
   in, and run `scripts/deployment_smoke.py`.
4. For a schema failure, inspect `uv run alembic current` and migration Git
   history. Prefer a forward corrective migration. Milestone migrations use
   expand/contract: add nullable/defaulted structures, deploy compatible code,
   backfill, then remove old structures in a later release.
5. If a downgrade is the reviewed safe choice, create an extra backup, rehearse
   it against staging, then run the exact single-revision downgrade. Never edit
   production schema manually.
6. If data is corrupted, restore into a new nonproduction database first and
   follow `backup-restore.md`; swap production only after counts and auth/RLS
   checks pass.
7. Resume scans, run one manual scan, watch queue/quarantine/closure metrics, and
   save evidence. Record root cause and corrective release.
