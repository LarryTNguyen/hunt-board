# Scan failure and source recovery

1. Open Operations and note release/environment, active/pending IDs, latest run
   status, failed source rows, request ID, and trace ID.
2. If a run exceeds `HUNT_BOARD_STALE_RUN_MINUTES`, choose **Recover stale run**.
   If it is still responsive but unsafe, choose **Cancel**; cancellation is
   cooperative and takes effect after the current fetch boundary.
3. Confirm failed/quarantined source jobs stayed active and missed counters did
   not advance. Never treat provider outage, parse/auth failure, or quarantine
   as closure evidence.
4. Use **Retry failed** on the run. This selects failed/abandoned companies only
   and leaves successful companies alone.
5. For timeout/rate-limit failure, check the 30-second request timeout, three
   total attempts, retry counts, jittered backoff, and provider status. Do not
   increase concurrency reflexively.
6. For quarantine, compare sanitized counts with the provider board. Approve
   only when the mass change is real; approval performs a fresh authorized scan.
   Reject broken/uncertain results.
7. If every company failed or no successful run exists within four hours, fire
   the configured provider email alert and keep invitations/launch paused.
