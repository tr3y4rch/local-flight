"""Real browser workflow checks against the actual isolated FastAPI test app."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from test_operator_toolbox_api import stack, issue_and_claim
from test_relay_access_admin_e2e import ADMIN_AUTH


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_operator_browser_workspace_keyboard_and_privacy(
    stack, tmp_path, width, height
):
    playwright = pytest.importorskip("playwright.sync_api")
    client, service, mailer = stack
    _, license_id, key = issue_and_claim(stack)
    errors = []
    requests = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("OPERATOR_TEST_CHROMIUM") or None
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )

        def route_request(route):
            req = route.request
            parsed = urlparse(req.url)
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            requests.append(req.url)
            response = client.request(
                req.method,
                path,
                headers={
                    "host": parsed.hostname,
                    "content-type": req.headers.get("content-type", "application/json"),
                    "origin": req.headers.get(
                        "origin", "https://network.beacontools.cc"
                    ),
                },
                auth=ADMIN_AUTH,
                content=req.post_data,
            )
            headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in {"content-length", "content-encoding"}
            }
            route.fulfill(
                status=response.status_code, headers=headers, body=response.content
            )

        page.route("**/*", route_request)
        page.goto("https://network.beacontools.cc/admin#access")
        try:
            page.locator('[data-op-view="licenses"]').first.wait_for(timeout=5000)
        except Exception:
            pytest.fail(
                str(
                    {
                        "errors": errors,
                        "body": page.locator("body").inner_text(),
                        "requests": requests,
                    }
                )
            )
        page.locator('[data-op-view="licenses"]').first.focus()
        page.keyboard.press("Enter")
        page.locator('form#operatorSearch input[name="q"]').fill(
            "recipient@example.test"
        )
        page.locator('form#operatorSearch button[type="submit"]').click()
        page.locator('[data-op-action="open_license"]').first.wait_for()
        page.locator('[data-op-action="open_license"]').first.click()
        page.get_by_role("button", name="Resend license", exact=True).wait_for()
        assert "recipient@example.test" not in page.locator("#workspace").inner_text()
        assert key not in page.content()
        for tab in ("email", "receiver", "ownership", "history", "summary"):
            page.locator(f'[data-op-tab="{tab}"]').focus()
            page.keyboard.press("Enter")
            assert (
                page.locator(f'[data-op-tab="{tab}"]').get_attribute("aria-current")
                == "page"
            )
        page.locator('[data-op-tab="history"]').click()
        page.get_by_role("button", name="Add support note", exact=True).click()
        page.locator('#actionDialog textarea[name="note"]').fill(
            "Browser troubleshooting note"
        )
        page.locator('#actionDialog textarea[name="reason"]').fill(
            "Validate operator support"
        )
        page.locator('#actionDialog button[type="submit"]').click()
        try:
            page.get_by_text("Browser troubleshooting note", exact=True).wait_for(
                timeout=5000
            )
        except Exception:
            pytest.fail(
                str(
                    {
                        "errors": errors,
                        "body": page.locator("body").inner_text(),
                        "requests": requests,
                    }
                )
            )
        page.locator('[data-op-tab="summary"]').click()
        page.locator(".operator-danger summary").click()
        page.get_by_role("button", name="Revoke license", exact=True).click()
        page.locator('#actionDialog textarea[name="reason"]').fill(
            "Do not submit this test"
        )
        assert page.locator('#actionDialog input[name="verification"]').is_visible()
        page.locator("#actionDialogCancel").click()
        assert service.authority(license_id)["effective_state"] == "active"
        assert not errors
        assert all(
            "recipient@example.test" not in url and "lfrop_" not in url
            for url in requests
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        output = Path(os.environ.get("OPERATOR_QA_OUTPUT", str(tmp_path)))
        page.evaluate("document.activeElement?.blur(); window.scrollTo(0,0)")
        page.screenshot(path=str(output / f"operator-{width}.png"), full_page=True)
        page.locator('[data-op-view="toolbox"]').first.click()
        page.get_by_role("button", name="Issue test license", exact=True).wait_for()
        page.get_by_role("button", name="Issue test license", exact=True).click()
        page.locator('#actionDialog input[name="email"]').fill("invited@example.test")
        page.locator('#actionDialog textarea[name="reason"]').fill(
            "Browser invitation test"
        )
        page.locator('#actionDialog button[type="submit"]').click()
        page.get_by_text("Confirm operator grant", exact=True).wait_for()
        assert "i***@example.test" in page.locator("#actionDialog").inner_text()
        page.locator('#actionDialog input[name="verification"]').fill("ISSUE")
        page.locator('#actionDialog button[type="submit"]').click()
        page.get_by_text("Test · i***@example.test", exact=True).wait_for()
        assert len(service.operator_grants()["items"]) == 2
        browser.close()
