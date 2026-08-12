# Privacy-safe incident debugging

Start with the UI, not raw data:

1. Copy the `X-Request-ID` shown in browser Network headers or the request/trace
   ID displayed on the Operations run ledger.
2. Paste it into **Find operational evidence**. The secure endpoint returns only
   matching run IDs, status, timestamps, and correlation IDs.
3. Search the log provider for the exact `request_id` or `trace_id`. Filter by
   environment and release, then follow `run_id` to `source_id`/controlled
   `source_slug` events.
4. Open the run and source-run detail in Operations. Compare duration, retries,
   timeouts, parser failures, fetched/upserted/closed counts, status, and
   quarantine decision.
5. Read bounded `/metrics` labels and the safe 24-hour Operations summary. Do
   not add user, job, title, email, or raw URL values as metric labels.
6. If a trace exporter is configured, find the trace by `trace_id` and inspect
   HTTP, scheduler/CLI root, source fetch, normalize/classify/dedupe/upsert, and
   reconcile timing spans. Safe attributes are environment, release, ATS,
   controlled source slug, IDs, status, counts, and durations only.

Logs and traces must not contain ATS payloads, descriptions, source
`config_json`, names/emails, tokens, cookies, magic links, user notes, service
keys, request bodies, or URL query secrets. The formatter redacts sensitive
keys, email patterns, bearer values, and common secret query parameters. If any
private value appears, revoke/rotate it, restrict the log, open a security
incident, and fix redaction before resuming scans.
