from __future__ import annotations

from pathlib import Path

def test_live_frontend_index_is_served(client) -> None:
    response = client.get("/app/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Plot a cleaner route" in response.text
    assert "/app/job-discovery.html" in response.text


def test_live_frontend_asset_is_served(client) -> None:
    response = client.get("/app/assets/api.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert "export async function request" in response.text


def test_job_detail_uses_one_versioned_module_graph(client) -> None:
    page = client.get("/app/job-detail.html")
    script = client.get("/app/assets/pages/job-detail.js?v=20260721-2")
    formatter = client.get("/app/assets/format.js?v=20260721-2")

    assert page.status_code == 200
    assert "/app/assets/pages/job-detail.js?v=20260721-2" in page.text
    assert "../format.js?v=20260721-2" in script.text
    assert "export function activateCompanyLogos" in formatter.text
    assert "requestAnimationFrame" in formatter.text
    assert "image.isConnected" in formatter.text
    assert "export function descriptionText" in formatter.text
    assert "descriptionText(job.description_html, job.description_text)" in script.text


def test_discovery_drawer_keeps_company_and_hides_source(client) -> None:
    stylesheet = client.get("/app/assets/app.css?v=20260721-2")

    assert stylesheet.status_code == 200
    assert "body.drawer-open .ledger th:nth-child(7)" in stylesheet.text
    assert "body.drawer-open .ledger th:nth-child(3)" not in stylesheet.text


def test_live_frontend_page_and_legacy_api_coexist(client) -> None:
    page = client.get("/app/job-discovery.html")
    legacy_api = client.get("/api/jobs")

    assert page.status_code == 200
    assert "Live sightings ledger" in page.text
    assert 'data-country' in page.text
    assert legacy_api.status_code == 200
    assert legacy_api.json() == []


def test_saved_jobs_has_nine_card_pages_and_company_location_filters(client) -> None:
    page = client.get("/app/saved-jobs.html")
    script = client.get("/app/assets/pages/saved-jobs.js")

    assert page.status_code == 200
    assert all(marker in page.text for marker in ("data-company", "data-location", "data-pagination"))
    assert "const PAGE_SIZE = 9" in script.text
    assert "limit: PAGE_SIZE + 1" in script.text
    assert "company: state.company" in script.text
    assert "location: state.location" in script.text


def test_frontend_uses_shared_auth_and_content_skeletons(client) -> None:
    stylesheet = client.get("/app/assets/app.css").text
    auth_script = client.get("/app/assets/auth.js").text
    ui_script = client.get("/app/assets/ui.js").text

    assert "html:not([data-auth-ready]) body::after" in stylesheet
    assert "@keyframes skeleton-pulse" in stylesheet
    assert "prefers-reduced-motion" in stylesheet
    assert "location.pathname === '/app/sign-in.html'" in auth_script
    assert "dataset.authReady = 'true'" in auth_script
    assert "export function loading" in ui_script
    assert "skeleton-state skeleton-${kind}" in ui_script


def test_saved_job_cards_can_move_directly_to_the_tracker(client) -> None:
    page = client.get("/app/saved-jobs.html")
    script = (
        Path(__file__).parents[1]
        / "src"
        / "hunt_board"
        / "web"
        / "static"
        / "assets"
        / "pages"
        / "saved-jobs.js"
    ).read_text(encoding="utf-8")

    assert page.status_code == 200
    assert "/app/assets/pages/saved-jobs.js" in page.text
    assert "data-track" in script
    assert "Add to tracker" in script
    assert "await api.createApplication(item.job.id" in script
    assert "await api.unsaveJob(item.job.id)" in script
    assert "Job added to the tracker and removed from saved jobs." in script
    assert "safeUrl(item.job.apply_url)" in script
    assert "Open official posting" in script
    assert 'rel="noopener noreferrer"' in script


def test_discovery_drawer_marks_a_job_seen_before_the_full_dossier(client) -> None:
    discovery = client.get("/app/assets/pages/discovery.js").text
    api_script = client.get("/app/assets/api.js").text
    detail = client.get("/app/assets/pages/job-detail.js").text

    assert "if (job.is_seen) return 'Seen'" in discovery
    assert "const shouldMarkSeen = !isAnonymous && !job.is_seen" in discovery
    assert "void persistSeen(job)" in discovery
    assert "markJobSeen:" in api_script
    assert "job = await api.markJobSeen(id)" in detail


def test_signed_out_discovery_uses_the_public_catalog(client) -> None:
    page = client.get("/app/job-discovery.html").text
    discovery = client.get("/app/assets/pages/discovery.js").text
    api_script = client.get("/app/assets/api.js").text

    assert "Public discovery board" in page
    assert "const isAnonymous = !auth.session" in discovery
    assert "api.publicJobs({ limit: 50 })" in discovery
    assert "Sign in to save or track" in discovery
    assert "publicJobs:" in api_script
    assert "/public/jobs?" in api_script


def test_discovery_seen_column_uses_the_official_posted_timestamp(client) -> None:
    discovery = client.get("/app/assets/pages/discovery.js").text

    assert "relativeDate(job.posted_at, 'Not provided')" in discovery
    assert "relativeDate(job.first_seen_at))}</td>" not in discovery


def test_inbox_open_sighting_marks_the_dispatch_read_before_navigation(client) -> None:
    script = client.get("/app/assets/pages/notifications.js").text

    assert "data-open-sighting" in script
    assert "event.preventDefault()" in script
    assert "await api.readNotification(item.id)" in script
    assert "await refreshUnreadCount()" in script
    assert "window.location.assign(href)" in script
