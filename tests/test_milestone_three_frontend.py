from __future__ import annotations

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
