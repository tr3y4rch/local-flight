from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = (ROOT / "relay" / "admin" / "admin.html").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "relay" / "admin" / "admin.js").read_text(encoding="utf-8")
ADMIN_CSS = (ROOT / "relay" / "admin" / "admin.css").read_text(encoding="utf-8")


def test_relay_access_is_a_first_class_admin_view() -> None:
    assert 'id="access" aria-label="Relay Access"' in ADMIN_HTML
    assert '["access", "Relay Access"]' in ADMIN_JS
    assert 'access: "/admin/api/access"' in ADMIN_JS
    assert 'panel("access", "Relay Access"' in ADMIN_JS
    assert "renderAccess(payload)" in ADMIN_JS


def test_relay_access_operator_actions_use_the_license_action_contract() -> None:
    assert "`/admin/api/access/${encodeURIComponent(licenseId)}`" in ADMIN_JS
    assert "`/admin/api/access/${encodeURIComponent(licenseId)}/action`" in ADMIN_JS
    for action in (
        "revoke_license",
        "suspend_license",
        "reactivate_license",
        "revoke_receiver",
        "retry_deliveries",
        "retry_notifications",
        "retry_reconciliation",
        "rotate_key",
    ):
        assert f'data-access-action="{action}"' in ADMIN_JS
        assert f"{action}: `" in ADMIN_JS
    assert "record_repurchase" not in ADMIN_JS
    assert "data-event-action" in ADMIN_JS
    assert "retry_reconciliation" in ADMIN_JS


def test_relay_access_ui_keeps_operator_identifiers_masked_and_never_receives_keys() -> None:
    assert "function maskedRef(" in ADMIN_JS
    assert "function licenseKeyRef(" in ADMIN_JS
    assert "maskedRef(row.install_ref)" in ADMIN_JS
    assert "maskedRef(row.evidence_ref)" in ADMIN_JS
    assert 'data-kind="access_license" data-index=' in ADMIN_JS
    assert "delete drawer.dataset.row" in ADMIN_JS
    assert "sent only to the protected holder email" in ADMIN_JS
    assert "no raw key was returned to admin" in ADMIN_JS
    assert "payload.license_key" not in ADMIN_JS
    assert "one-time-license-key" not in ADMIN_JS
    assert "drawerBody.replaceChildren()" in ADMIN_JS
    assert ".access-operator-note" in ADMIN_CSS
