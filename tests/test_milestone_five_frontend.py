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


def test_application_tracker_colors_rows_by_stage(client) -> None:
    script = client.get("/app/assets/pages/applications.js").text

    assert "function stageTone(item)" in script
    assert "status-tone-${stageTone(item)}" in script
    assert "['interview', 'offer'].includes(category)" in script
    assert "['rejected', 'withdrawn'].includes(category)" in script


def test_application_tracker_has_inline_delete_tab(client) -> None:
    script = client.get("/app/assets/pages/applications.js").text
    stylesheet = client.get("/app/assets/app.css").text

    assert "data-delete-inline" in script
    assert "Move application to Recently Deleted" in script
    assert "film-role-link" in script
    assert "View job dossier" in script
    assert "Official posting" in script
    assert "<span>Actions</span>" not in script
    assert ".tracker-delete-tab" in stylesheet
    assert "right: -56px" in stylesheet
    assert "padding-right: 56px" in stylesheet


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
