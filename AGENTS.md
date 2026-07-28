# AGENTS.md - Hunt Board Project Instructions

## Project mission
Hunt Board is a backend-first job intelligence system. The MVP is a single-user application that ingests jobs from curated ATS sources, stores normalized job records plus raw JSON, dedupes/repost-detects conservatively, ranks jobs against user preferences, exposes API endpoints, and records scrape run metrics.

## Current milestone
Milestones 1-4 are implemented. Milestone 4.1 is the active focused source-expansion scope: production-quality ingestion from explicitly configured public Workday Candidate Experience JSON boards, with complete pagination, bounded detail concurrency, withdrawal reconciliation, structured locations, and the existing lifecycle safety boundary.

Do not add authenticated Workday APIs, automatic board discovery, browser automation, a scheduler inside FastAPI, task queues, external search infrastructure, multi-user authentication, resume analysis, or delivery notifications unless explicitly asked.

## Tech stack rules
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Pydantic, httpx, pytest.
- Package manager: uv.
- Local infrastructure: Docker Compose.
- Source config: data/sources.yaml.
- Keep tests offline and fixture-based.
- Use environment variables for secrets/config. Never hardcode secrets.

## Architecture rules
- Keep module boundaries clean: api, auth, core, db, ingestion, jobs, matching, tracking, notifications, admin.
- Add users table now even though MVP is single-user.
- Keep applications separate from job_postings.
- Store latest raw_json, description_html, and description_text for job postings.
- Do not delete normalized job records during MVP; mark closed jobs inactive.
- Use scrape_runs and scrape_source_runs for observability.

## Ingestion rules
- Adapter interface first; individual ATS adapters second.
- Supported adapters are Greenhouse, Lever, Ashby, and the bounded public-JSON Workday adapter.
- Use httpx with timeouts and clean error handling.
- Tests must use fixture JSON, not live ATS calls.
- Support dry-run ingestion that performs fetch/normalize/dedupe/ranking without DB writes.

## Dedupe rules
Use conservative layered dedupe:
1. Same source + external_job_id -> same job.
2. Same canonical apply_url -> likely same job.
3. Same company + normalized title + normalized location -> possible duplicate; flag for review if uncertain.
4. Inactive job reappears -> mark reactivated/reposted.
5. Similar but uncertain -> keep separate and create duplicate_review.

## Matching/ranking rules
- Title-only matching for Milestone 1.
- Exact user keywords are strict.
- Built-in role groups are flexible.
- Exclude keywords are applied after include matching.
- Exact include phrase beats exclude.
- Ranking weights: title relevance 40%, job level 20%, freshness 20%, location/work type 15%, company/source priority 5%.

## Quality rules
- Prefer explicit, readable code over clever abstractions.
- Add tests for each core service.
- Keep API responses typed with Pydantic schemas.
- Add migrations whenever models change.
- Update README and docs when adding commands or architecture.
- Run tests before claiming completion.

## Completion report format
When finished, report:
1. What changed.
2. Files created/changed.
3. Commands to run.
4. Test results.
5. Known limitations.
6. Recommended next step.
