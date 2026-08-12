# Milestone 4.1: Production Workday source integration

Milestone 4.1 adds one bounded adapter for the public Workday Candidate Experience JSON surface. It does not use authenticated Workday REST, SOAP, Graph, or recruiting APIs and does not add automatic source discovery, browser automation, candidate login, application submission, CAPTCHA bypass, proxy rotation, or per-company request hacks.

## Configuration contract

A source uses ATS key `workday` and explicitly supplies an HTTPS `careers_url`, a bare public host ending in `.myworkdayjobs.com` or `.myworkdaysite.com`, one safe tenant path segment, and one safe site path segment.

Locale defaults to `en-US`, page size to 20, detail concurrency to 3, request pacing to 200 ms, and the safety ceiling to 5,000 jobs. Each value is range checked before a request. The career URL host must equal the configured host. New sources remain disabled until the owner validates them.

## Request and completeness contract

Listings use a retry-aware read-only JSON POST to `/wday/cxs/{tenant}/{site}/jobs` with empty search and facets. Pagination is sequential. The adapter treats the first-page total as authoritative and permits Workday's observed `total: 0` sentinel only on later nonempty pages. It otherwise requires a stable total, a list of object postings, safe unique `/job/` paths, exact first-page-count completion, and progress within the maximum page count. It retries one complete scan after a possible churn inconsistency and never truncates at the safety ceiling.

Details use HTTPS GET requests built only from the validated host and paths. A fixed worker pool bounds concurrency and source pacing spaces request starts. Transient errors retry; bounded `Retry-After` is honored for 429 and 503. Non-JSON, malformed JSON, access denial, unsupported endpoints/contracts, unsafe redirects, and exhausted errors produce actionable adapter failures without logging payload bodies.

A detail 404, 410, or explicit `posted: false` triggers one fresh complete listing. A withdrawn path that disappeared is omitted, and newly listed paths are fetched. Individually identified paths that remain unavailable are skipped in a non-authoritative partial result. Complete jobs may be upserted, but source status is `completed_with_errors` and lifecycle closure is suppressed. Further listing churn or another failure that prevents complete enumeration still fails the entire source.

## Normalization contract

Identity priority is detail `id`, `jobPostingId`, then `jobReqId`. Company name always comes from source configuration. Exact `startDate` wins over conservative English relative dates. Imprecise `30+ Days Ago` remains unknown. Workplace type comes only from structured remote-type values.

Descriptions pass through the existing sanitizer. URLs must remain HTTPS on the configured host. Raw JSON is a deterministic `{listing, detail}` object and remains excluded from public APIs. `locations_json` preserves the primary and additional locations in a source-independent collection; scalar location and country fields remain backward compatible.

## Integration and rollout

Workday uses the existing registry, ingestion service, global lock, scheduler, cadence, source health, operations page, discovery feed, ATS facets, saved jobs, and application tracker. Failed fetches cannot advance missed-run counters or close jobs. Successful empty scans remain authoritative and follow the configured closure threshold.

```powershell
uv run alembic upgrade head
uv run hunt-board sync-sources
uv run hunt-board ingest --source <owner-selected-workday-slug> --dry-run
```

Perform at least two stable dry runs, inspect sample normalized jobs and public URLs, run one real manual ingestion, and only then enable scheduling. Default tests are offline. Live verification is optional and must use an owner-selected explicitly configured board.

## Known boundaries

The public Candidate Experience contract is undocumented and can change. Boards requiring authentication, persistent access-denied responses, custom domains, source-side facet partitioning, undocumented payloads, or anti-bot bypass remain unsupported. Country filters continue to use the primary scalar country fields; the complete structured locations remain visible through job APIs and the detail UI.
