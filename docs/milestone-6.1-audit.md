# Milestone 6.1 implementation audit

Date: 2026-07-31

## Existing reusable boundaries

- `jobs/query.py` is the canonical SQL path. `JobQueryFilters`, `apply_job_filters`, `apply_job_sort`, `count_jobs`, and `feed_facets` are already reused by `/jobs/feed`, saved-search matches, and the Daily Hunt dashboard.
- `searches/` already rejects unknown filter keys, stores portable `source_slug`, enforces per-user names, supports one selected default, previews, facets, and `first_seen_at` review state.
- `UserPreference` is canonical at runtime. `users.preferences_json` is only a compatibility snapshot, although preference creation currently bootstraps from it.
- Saved jobs and discarded jobs are separate from applications. Creating a second application already requires `create_new=true`.
- Authenticated reads and mutations are owner-scoped, and the Milestone 6.0 migration enables RLS on the existing private tables.
- All four supported public ATS adapters populate the shared `NormalizedJob` contract. Workday remains bounded to public JSON and already carries multi-location data.
- Request and trace IDs, structured JSON logs, spans, and an in-process Prometheus-style registry provide a provider-neutral observability base.

## Gaps against 6.1

### Taxonomy and classification

- There is no immutable job-family table, classification service, job classification metadata, or durable administrator override.
- Ranking role groups and seed defaults are software-centric. Classification must remain separate from ranking and use centralized, data-driven rules.
- Ingestion does not classify jobs, and the CLI has no safe reclassification or coverage report command.

### Preferences, onboarding, and discovery

- Preferences cover title keywords, role groups, levels, one home location/country, remote allowed, and a score threshold. They lack selected families, desired titles, multiple countries, employment types, sponsorship, minimum salary, excluded companies, workplace preference, and related-family configuration.
- Onboarding timestamps exist on `User`, but no API or UI updates them. Current defaults mean a skipped user is not truly broad.
- The canonical query path lacks families, list-valued titles/keywords/countries/employment types, excluded companies, experience levels, sponsorship, and minimum salary.
- Public `/jobs` and `/jobs/feed` expose the complete catalog and full internal payload. A bounded privacy-safe public endpoint is needed, while authenticated routes retain full behavior.

### Relaxation

- No deterministic relaxation planner or response metadata exists.
- Strict and relaxed counts are not separate. Unknown salaries can only be selected as a facet, not ranked below confirmed salary matches.
- Structured locations exist, but only the primary country/location columns are filterable. Remote country restrictions are not explicit.

### Tracking

- Application statuses do not map to fixed reporting categories and are globally seeded with legacy labels.
- Deleting an application is permanent. There is no 30-day Recently Deleted flow.
- Applications have plain-text notes but no link field.
- Manual jobs and their private ownership/approval-ready metadata do not exist.

### Dashboard, sources, and operations

- Dashboard fallback uses the global posting score and threshold rather than a default preference-derived search. Pipeline aggregation uses raw status slugs, not standard reporting categories.
- `data/sources.yaml` has four technology-heavy employers and no documented cross-industry validation target.
- Operations has no family/ATS/company coverage report.

### UI and copy

- The static application and navigation are reusable, but preferences and saved-search examples emphasize backend/software roles.
- Discovery lacks family, employment, salary floor, sponsorship, and transparent relaxation controls.
- Tracker lacks manual job, custom-stage reporting, duplicate-application labeling, and Recently Deleted controls.

## Implementation decisions

1. Add an immutable seeded `job_families` lookup and store a stable family slug on jobs and preferences/searches. Taxonomy mutations are intentionally absent from APIs.
2. Put deterministic rules in `jobs/classification.py`. Preserve override columns during ingestion and make reclassification default to non-overridden jobs.
3. Extend `JobQueryFilters` and saved-search conversion once; all APIs, counts, facets, dashboard selection, and relaxation continue through that path.
4. Add a deterministic relaxation service that executes the canonical statement repeatedly, returns strict and relaxed counts, and never drops exclusion, employment-type, or excluded-country constraints.
5. Make preference lists optional/empty by default for broad feeds. Update canonical preferences and rescore within the same preference mutation request; `preferences_json` remains a compatibility mirror only.
6. Soft-delete applications with a 30-day purge boundary. Add explicit restore and permanent-delete routes. Add private `manual_jobs` whose creation transaction also creates an application.
7. Map every application status to one of Applied, Interview, Offer, Rejected, Withdrawn, or Archived. Preserve existing display names and allow owner-created custom stages with a required standard mapping.
8. Add `/public/jobs` as a limited safe sample and require authentication for full `/jobs` and `/jobs/feed`; keep the static demo browser-local.
9. Extend the current field-kit/safari UI rather than replace it. Job-family specimen tags are the signature visual, with existing typography, spacing, focus, and reduced-motion behavior retained.
10. Add bounded metrics and sanitized events only. Free text, keywords, locations, companies, titles, notes, links, identities, and descriptions must not enter logs or labels.

## Compatibility and safety notes

- Existing saved-search JSON remains valid because all new fields are optional and old keys retain their meanings.
- Existing application status rows are backfilled to standard reporting categories; legacy names remain visible.
- Existing jobs are backfilled to `Other` in the migration and can then be deterministically reclassified with `hunt-board reclassify-jobs`.
- No adapter contract, Workday network behavior, scheduler placement, auth provider, or frontend stack changes.
- Offline tests will construct source/job fixtures and never call live employer endpoints.
