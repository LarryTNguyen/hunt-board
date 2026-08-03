# Milestone 6.1 — Generalized job discovery

Milestone 6.1 broadens Hunt Board from software-heavy matching to a fixed,
deterministic cross-industry catalog. It keeps the four public ATS adapters,
the central SQL query path, saved-search review semantics, Supabase identity
mapping, PostgreSQL RLS, and the Workday public-JSON safety boundary.

## Taxonomy and classification

`jobs/classification.py` owns the immutable 13-family vocabulary and rule
tables. Classification checks normalized source department/category labels,
then title phrases, then description phrases, and finally `Other`. It stores a
bounded confidence, method, and debugging reason. Administrator overrides use
`PATCH /admin/jobs/{job_id}/classification` and survive ingestion and default
reclassification.

```powershell
uv run hunt-board reclassify-jobs
uv run hunt-board coverage-report
```

`--replace-overrides` is intentionally explicit.

## Preferences, onboarding, searches, and relaxation

Canonical `UserPreference` rows now support families, related families,
desired titles, included/excluded terms, cities/regions, included/excluded
countries, workplace and employment types, experience shapes, sponsorship,
minimum salary, and excluded companies. Every new field may be blank.
`GET/POST /me/preferences/onboarding` reads or changes `pending`, `completed`,
or `skipped`. Skipping leaves a broad catalog usable. Updating preferences
immediately rescores stored jobs; `users.preferences_json` remains only a
compatibility mirror.

Saved searches accept the same generalized keys and still reject unknown
fields and database `source_id`. Counts, previews, facets, sorting, and
`first_seen_at` review state continue through `jobs/query.py`.

With `relax=true`, too-small result sets cumulatively relax minimum salary,
exact location text, experience, desired title, then family (only by adding
explicit related families). Excluded terms, excluded companies, employment
types, and excluded countries never relax. Responses distinguish strict and
relaxed counts/results. Unknown-salary jobs remain eligible below confirmed
minimum-salary matches.

## Tracking and public boundaries

- Saved/interested remains separate from application stage.
- Built-in and custom stages map to Applied, Interview, Offer, Rejected,
  Withdrawn, or Archived.
- A second catalog application still requires `create_new=true`.
- `POST /manual-jobs` atomically creates a private manual record/application.
- Plain notes and links are supported; attachments remain out of scope.
- Application deletion enters Recently Deleted for 30 days; restore and
  permanent deletion are explicit routes.
- `GET /public/jobs` exposes at most 50 privacy-safe normalized records. Full
  discovery/personalization/actions require authentication.

## Source coverage and measured target

The 2026-07-31 public-ATS dry run fetched 751 postings with zero adapter errors:

| Source | ATS | Postings |
| --- | --- | ---: |
| Reformation | Greenhouse | 126 |
| MarketAxess | Greenhouse | 6 |
| Figma | Greenhouse | 178 |
| Harvey | Ashby | 353 |
| Replit | Ashby | 88 |

Before backfill, the local catalog had 685 active jobs across all 13 families,
with 15.33% `Other`. Design (4), legal (4), and research (1) were thinnest. The
initial backfill target is therefore: ingest at least 700 of the 751 observed
postings, keep source errors at zero and `Other` below 20%, and verify that
design, legal, marketing, operations, HR, finance, product, data, consulting,
sales, and software counts do not regress. Research remains an honest gap until
a suitable curated public ATS board is validated.

## Observability and commands

Classification, preference/search mutation, strict/relaxed execution, manual
jobs, stage changes, and deletion actions emit structured events and bounded
metrics. Timed spans cover classification/query execution, saved-search work,
dashboard personalization, and manual-job transactions. Search text, terms,
locations, companies, titles, notes, links, descriptions, identities, and auth
material are redacted and never metric labels.

```powershell
uv run alembic upgrade head
uv run hunt-board seed
uv run hunt-board reclassify-jobs
uv run hunt-board coverage-report
uv run pytest
```

Repeat the source validation without writes:

```powershell
uv run hunt-board ingest --source reformation --source marketaxess --source figma --source harvey --source replit --dry-run
```

## Known limitations

- Classification is deterministic rules, not ML. Ambiguous chief-of-staff,
  program-management, and multidisciplinary roles may need an override.
- Exact-city relaxation uses source text; radius distance does not geocode.
- Sponsorship stays `unknown` unless normalized source evidence exists.
- Recently Deleted rows become purge-eligible after 30 days, but no scheduler
  or task queue was added; permanent deletion is explicit.
- Manual-job approval is prepared as `private`; approval UI is deferred.
