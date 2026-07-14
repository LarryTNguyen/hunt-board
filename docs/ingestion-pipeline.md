# Ingestion Pipeline

An ingestion run follows these stages:

1. Load and validate `data/sources.yaml`. Both the milestone field names (`ats_type`, `ats_slug`, and high/medium/low priority) and the original project field names remain accepted.
2. Select an explicitly requested source, or all enabled sources whose `next_due_at` has passed.
3. Create `scrape_runs` and per-source `scrape_source_runs` records for a real run. Dry runs create no records.
4. Fetch through the shared adapter interface using `httpx` timeouts and source-isolated error handling.
5. Normalize ATS fields into `NormalizedJob`, including posting/apply URLs, HTML/plain descriptions, timestamps, and raw JSON.
6. Apply title-only include, role-group, exclude, level, freshness, location/work-type, and source-priority scoring.
7. Deduplicate in layers: source plus external ID, canonical apply URL, then the uncertain company/title/location signal. Uncertain matches remain separate and create an open duplicate review.
8. Insert or update the normalized posting. A changed description hash creates a `job_versions` row, raw JSON receives a 60-day retention timestamp, and the user's `job_matches` row is refreshed.
9. Reset the miss counter for observed postings. Unseen postings increment their counter and become inactive only after 12 consecutive successful source runs. Reappearing inactive postings are reactivated and stamped as reposted.
10. Finalize source health/due state and aggregate new, updated, closed, duplicate, error, and duration metrics.

Dry-run mode executes fetch, normalization, database-aware dedupe checks, and ranking but does not mutate sources, jobs, matches, reviews, or scrape metrics.

Failures are isolated to one source through a database savepoint. Other configured sources continue, and unhealthy sources remain in the registry with a delayed next attempt.
