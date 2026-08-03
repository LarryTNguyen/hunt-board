# Owner UI verification — Milestone 6.1

Run migration/seed, start the API, and sign in as an invited user. Keep Network
and Console open. For every failure capture the full page, response body, and
`X-Request-ID` with tokens hidden as `6.1-<step>-<failure>.png`.

1. **Skip onboarding:** reset onboarding, open `/app/preferences.html`, click
   **Skip for now**, then open `/app/job-discovery.html`. Expect a broad feed and
   “preferences improve” reminder. Capture preference state and first feed row.
2. **Immediate updates:** select only Finance and accounting, save, return to
   discovery. Expect “Preferences saved and feed updated” and finance rows
   without manual rescore. Capture toast, row, and failed response if needed.
3. **Classification examples:** seed Financial Analyst, Product Designer,
   Strategy Consultant, Growth Marketing Manager, Operations Analyst, Data
   Analyst, Product Manager, and Software Engineer. Expect the visible correct
   family beneath each title. Capture each incorrect specimen.
4. **Multiple/blank fields:** select Finance, Design, Research; clear titles,
   terms, countries, salary, sponsorship; save/reload. Expect all blanks accepted
   and three selections retained. Capture form plus PATCH response on failure.
5. **Saved routes:** on `/app/saved-searches.html` create, rename, switch, make
   default, and delete a route. Expect exactly one Default route and duplicate
   names rejected with “A saved search with this name already exists.”
6. **Relaxation banner:** make salary/city/experience/title/family too strict and
   open matches. Expect “Broadened results by relaxing,” listed steps, separate
   strict/relaxed counts, and broadened rows. Capture notice and JSON.
7. **Never-relaxed filters:** add excluded keyword `commission`, company
   `Blocked Co`, Full-time employment, and excluded country `CA`; force
   relaxation. Expect none in results. Capture offending row/request if violated.
8. **Salary/location/remote:** load an unknown-salary, two-office,
   US-restricted remote job. Expect salary-not-listed, both locations, restricted
   remote metadata, and ordering below a confirmed salary-floor match.
9. **Public boundary:** sign out and request `/public/jobs?limit=30`. Expect no
   more than 30 read-only rows and no raw JSON, reasons, user state, notes,
   source config, or score. `/jobs/feed` must return 401. Capture page/payload.
10. **Demo isolation:** mutate the public browser-local demo in a private window,
    reset/reload, then sign in. Expect no demo state in real saves/applications.
    Capture local storage and authenticated board if data crosses the boundary.
11. **Two users:** user A saves, hides/restores, and applies. User B opens the
    same job. Expect no A state/notes/application. Capture both sessions and IDs.
12. **Manual/second application:** use **Manual job** on
    `/app/application-tracker.html`; expect a Private manual job marker. Explicitly
    call Add another application (`create_new=true`) for a catalog job and expect
    two IDs. Capture dialogs/responses if privacy or explicitness fails.
13. **Custom reporting:** create Case Study mapped to Interview, move an
    application there, and open `/app/dashboard.html`. Expect Case Study in the
    tracker and its count under Interview. Capture both views.
14. **Recently Deleted:** delete an application, enable **Recently Deleted**,
    verify a 30-day purge date plus Restore/Delete permanently. Restore, delete
    again, then permanently delete. Capture every bad state/request.
15. **Override persistence:** admin PATCH `/admin/jobs/{id}/classification`, run
    fixture rescan or `hunt-board reclassify-jobs`, reopen job. Expect corrected
    family and `admin_override`. Capture before/after JSON and request ID.
16. **Trace/privacy:** send a safe `X-Request-ID` with classification/search,
    match returned IDs to `classification.*`, `job_query.execution`, or
    `search.executed`. Expect bounded IDs/families/methods/buckets/steps only—no
    terms, locations, companies, titles, notes, links, identity, or auth data.
