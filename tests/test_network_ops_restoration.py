from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient

import relay.main as relay_main


@pytest.fixture
def operator_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "operator.db"))
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "fake-operator-password")
    monkeypatch.setenv("RELAY_ADMIN_HOST", "network.example.test")
    monkeypatch.setenv("RELAY_PUBLIC_HOST", "relay.example.test")
    monkeypatch.setenv("RELAY_ACCESS_MODE", "legacy")
    relay_main._admin_auth_failures.clear()
    relay_main._ensure_schema()
    client = TestClient(relay_main.app, base_url="http://network.example.test")
    client.auth = ("operator", "fake-operator-password")
    return client


def test_operator_browser_navigation_actions_and_mobile(
    operator_client: TestClient, tmp_path: Path
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        executable = os.environ.get("OPERATOR_TEST_CHROMIUM")
        if not Path(executable or runtime.chromium.executable_path).is_file():
            pytest.skip("Install Playwright Chromium to run the operator browser contract")
        browser = runtime.chromium.launch(executable_path=executable or None)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        calls: list[tuple[str, str, int]] = []

        def serve(route):
            request = route.request
            response = operator_client.request(
                request.method, request.url,
                headers={key: value for key, value in request.headers.items() if key in {"origin", "referer", "sec-fetch-site", "content-type"}},
                content=request.post_data,
            )
            calls.append((request.method, request.url, response.status_code))
            headers = {key: value for key, value in response.headers.items() if key not in {"content-length", "content-encoding"}}
            route.fulfill(status=response.status_code, headers=headers, body=response.content)

        context.route("http://network.example.test/**", serve)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://network.example.test/admin")
        page.locator("#syncStatus").get_by_text("Updated", exact=False).wait_for()
        for view in ("fleet", "traffic", "schedules", "surfaces", "reports", "activations", "access", "providers", "retention", "maintenance", "overview"):
            page.locator(f'button[data-view="{view}"]').click()
            page.locator("#syncStatus").get_by_text("Updated", exact=False).wait_for()
            assert not page.locator(".error-state").count(), view
            assert page.locator(".workspace").count() == 1
        page.screenshot(path=str(tmp_path / "network-ops-desktop.png"), full_page=True)
        page.locator('button[data-view="activations"]').click()
        page.locator('button[data-command="create-token"]').click()
        page.locator('#actionDialog input[name="label"]').fill("Fake browser token")
        page.locator("#actionDialogConfirm").click()
        page.locator("#secretDialog[open]").wait_for()
        secret = page.locator("#secretValue").inner_text()
        assert secret.startswith("lfm_")
        page.locator("#closeSecretBtn").click()
        assert page.locator("#secretValue").inner_text() == ""
        page.locator(".table-link").first.click()
        page.locator('button[data-row-action="rotate-token"]').click()
        page.locator("#actionDialogConfirm").click()
        page.locator("#secretDialog[open]").wait_for()
        assert page.locator("#secretValue").inner_text() != secret
        page.locator("#closeSecretBtn").click()
        page.locator('button[data-view="retention"]').click()
        page.locator('button[data-command="place-hold"]').click()
        page.locator('#actionDialog input[name="record_key"]').fill("fake-browser-hold")
        page.locator('#actionDialog input[name="reason"]').fill("Browser verification")
        page.locator("#actionDialogConfirm").click()
        page.locator("button[data-release-hold]").first.click()
        page.locator('#actionDialog input[name="verification"]').fill("RELEASE")
        page.locator("#actionDialogConfirm").click()
        page.get_by_text("No active retention holds.", exact=True).wait_for()
        page.locator('button[data-view="access"]').click()
        page.get_by_role("button", name="Licenses", exact=True).click()
        page.locator('#operatorSearch input[name="q"]').fill("fake-email@example.test")
        with page.expect_response("**/admin/api/operator/licenses/search"):
            page.locator('#operatorSearch button[type="submit"]').click()
        assert any(method == "POST" and url.endswith("/admin/api/operator/licenses/search") for method, url, _ in calls)
        assert all("fake-email" not in url for _, url, _ in calls)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#menuButton").click()
        page.locator('button[data-view="fleet"]').click()
        page.locator("#syncStatus").get_by_text("Updated", exact=False).wait_for(state="attached")
        page.locator("#sidebar").wait_for(state="hidden")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / "network-ops-mobile.png"), full_page=True)
        assert not errors, errors
        assert all(status < 400 for _, _, status in calls), calls
        context.close()
        browser.close()


def test_restored_operator_routes_and_revision(operator_client: TestClient) -> None:
    shell = operator_client.get("/admin")
    assert shell.status_code == 200
    assert 'content="network-ops-v2"' in shell.text
    assert len(shell.headers["x-localflight-admin-revision"]) == 12
    assert shell.headers["cache-control"] == "no-store"
    for view in ("overview", "fleet", "usage", "schedules", "surfaces", "reports", "activations", "retention", "access"):
        response = operator_client.get(f"/admin/api/{view}")
        assert response.status_code == 200, (view, response.text)
        assert response.headers["cache-control"] == "no-store"
    for path in ("/admin/api/retention/run", "/admin/api/retention/hold"):
        forbidden = operator_client.post(path, headers={"origin": "https://unrelated.example.test"}, json={})
        assert forbidden.status_code == 403


def test_provider_readiness_tracks_current_access_policy(
    operator_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AERODATABOX_API_KEY", "fake-test-provider-key")
    monkeypatch.setenv("RELAY_ACCESS_SCHEDULE_ENABLED", "0")
    monkeypatch.delenv("RELAY_ACCESS_AERODATABOX_ENABLED", raising=False)
    legacy = operator_client.get("/admin/api/overview").json()["providers"]["aerodatabox"]
    assert legacy["hosted_authorized"] is False
    assert legacy["hosted_display_enabled"] is True
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licensed")
    disabled = operator_client.get("/admin/api/overview").json()["providers"]["aerodatabox"]
    assert disabled["hosted_display_enabled"] is False
    monkeypatch.setenv("RELAY_ACCESS_AERODATABOX_ENABLED", "1")
    enabled = operator_client.get("/admin/api/overview").json()["providers"]["aerodatabox"]
    assert enabled["hosted_authorized"] is True
    assert enabled["hosted_display_enabled"] is True
    assert "fake-test-provider-key" not in str(enabled)


def test_retention_hold_protects_rows_and_releases_by_safe_id(operator_client: TestClient) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with relay_main._connect() as conn:
        conn.execute(
            "INSERT INTO activation_requests (request_id, install_id, install_fingerprint, network_tag, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("fake-held-request", "fake-install", "fake-network", "test", "dismissed", old, old),
        )
        conn.execute("INSERT INTO request_log (ts, install_id, service, plan) VALUES (?, ?, ?, ?)", (old, "fake-install", "radar", "community"))
    placed = operator_client.post("/admin/api/retention/hold", json={
        "action": "place", "category": "activation_request", "record_key": "fake-held-request", "reason": "test hold",
    })
    assert placed.status_code == 200
    hold_id = placed.json()["hold_id"]
    listed = operator_client.get("/admin/api/retention").json()
    assert listed["holds"][0]["hold_id"] == hold_id
    assert "record_key" not in listed["holds"][0]
    first = operator_client.post("/admin/api/retention/run").json()["result"]
    assert first["status"] == "ok"
    assert first["deleted"]["request_log"] == 1
    assert first["deleted"]["activation_requests"] == 0
    released = operator_client.post("/admin/api/retention/hold", json={
        "action": "release", "category": "legal_acceptance", "hold_id": hold_id,
    })
    assert released.status_code == 200
    assert released.json()["category"] == "activation_request"
    second = operator_client.post("/admin/api/retention/run").json()["result"]
    assert second["status"] == "ok"
    assert second["deleted"]["activation_requests"] == 1


def test_erase_install_is_scoped_and_preserves_held_requests(operator_client: TestClient) -> None:
    now = relay_main._utc_now()
    target, other = "00000000-0000-0000-0000-000000000901", "00000000-0000-0000-0000-000000000902"
    with relay_main._connect() as conn:
        for install in (target, other):
            conn.execute("INSERT INTO request_log (ts, install_id, service, plan) VALUES (?, ?, ?, ?)", (now, install, "radar", "community"))
        conn.execute(
            "INSERT INTO activation_requests (request_id, install_id, install_fingerprint, network_tag, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("fake-protected-request", target, "fake-network", "test", "dismissed", now, now),
        )
    operator_client.post("/admin/api/retention/hold", json={
        "action": "place", "category": "activation_request", "record_key": "fake-protected-request", "reason": "test hold",
    }).raise_for_status()
    result = operator_client.post("/admin/api/install/access", json={"action": "erase_data", "install_id": target})
    assert result.status_code == 200
    assert result.json()["deleted"]["request_log"] == 1
    assert result.json()["deleted"]["activation_requests"] == 0
    with relay_main._connect() as conn:
        assert conn.execute("SELECT install_id FROM request_log").fetchone()[0] == other
        assert conn.execute("SELECT COUNT(*) FROM activation_requests").fetchone()[0] == 1
