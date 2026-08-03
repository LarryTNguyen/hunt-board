from __future__ import annotations


def test_dashboard_page_and_script_are_served(client) -> None:
    page = client.get("/app/dashboard.html")
    assert page.status_code == 200
    for marker in (
        "data-dashboard",
        "data-daily-totals",
        "data-search-summary",
        "data-new-matches",
        "data-application-pipeline",
        "data-follow-ups",
        "data-dashboard-message",
    ):
        assert marker in page.text
    assert "Source signal" not in page.text
    assert client.get("/app/assets/pages/dashboard.js").status_code == 200


def test_saved_searches_page_and_script_are_served(client) -> None:
    page = client.get("/app/saved-searches.html")
    assert page.status_code == 200
    for marker in (
        "data-saved-searches",
        "data-search-form",
        "data-search-list",
        "data-search-matches",
        "data-mark-reviewed",
        "data-search-message",
    ):
        assert marker in page.text
    assert client.get("/app/assets/pages/saved-searches.js").status_code == 200


def test_frontend_clients_navigation_and_discovery_save_route(client) -> None:
    api_script = client.get("/app/assets/api.js").text
    assert "savedSearches:" in api_script
    assert "savedSearchMatches:" in api_script
    assert "dailyDashboard:" in api_script
    navigation = client.get("/app/assets/navigation.js").text
    assert "/app/dashboard.html" in navigation
    assert "/app/saved-searches.html" in navigation
    discovery = client.get("/app/job-discovery.html")
    assert discovery.status_code == 200
    assert "data-save-route" in discovery.text
