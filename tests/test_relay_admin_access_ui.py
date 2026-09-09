from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = (ROOT / "relay" / "admin" / "admin.html").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "relay" / "admin" / "admin.js").read_text(encoding="utf-8")
OPERATOR_JS = (ROOT / "relay" / "admin" / "operator.js").read_text(encoding="utf-8")
ADMIN_CSS = (ROOT / "relay" / "admin" / "admin.css").read_text(encoding="utf-8")


def test_relay_access_is_a_first_class_admin_view() -> None:
    assert 'id="workspace" aria-labelledby="viewTitle"' in ADMIN_HTML
    assert 'id: "access", group: "Operate"' in ADMIN_JS
    assert 'access: "/admin/api/access"' in ADMIN_JS
    assert 'workspaceHead("Relay Access"' in OPERATOR_JS
    assert "renderOperatorWorkspace(payload)" in ADMIN_JS
    assert "renderAccess(payload)" in ADMIN_JS


def test_relay_access_operator_actions_use_the_license_action_contract() -> None:
    assert "`/admin/api/operator/licenses/${encodeURIComponent(summary.license_id)}`" in OPERATOR_JS
    assert 'method: "POST"' in OPERATOR_JS
    assert "request_id:requestId" in OPERATOR_JS
    for action in (
        "revoke_license",
        "suspend_license",
        "reactivate_license",
        "revoke_receiver",
        "resend_key_email",
        "send_recovery_link",
        "retry_reconciliation",
        "rotate_key",
    ):
        assert f'"{action}"' in OPERATOR_JS
    assert "record_repurchase" not in ADMIN_JS
    assert "data-event-action" in ADMIN_JS
    assert "retry_reconciliation" in OPERATOR_JS
    assert '"retry_deliveries"' not in OPERATOR_JS
    assert '"retry_notifications"' not in OPERATOR_JS


def test_relay_access_ui_keeps_operator_identifiers_masked_and_never_receives_keys() -> None:
    assert "function maskedRef(" in ADMIN_JS
    assert "function licenseKeyRef(" in ADMIN_JS
    assert "maskedRef(row.install_ref)" in ADMIN_JS
    assert "d.recipient" in OPERATOR_JS
    assert "r.support_id" in OPERATOR_JS
    assert 'kind: "access_license", sortable: false' in ADMIN_JS
    assert "delete drawer.dataset.row" in ADMIN_JS
    assert "No secret values can be displayed or exported." in OPERATOR_JS
    assert "payload.license_key" not in ADMIN_JS
    assert "one-time-license-key" not in ADMIN_JS
    assert "payload.license_key" not in OPERATOR_JS
    assert "localStorage" not in OPERATOR_JS
    assert "sessionStorage" not in OPERATOR_JS
    assert "drawerBody.replaceChildren()" in ADMIN_JS
    assert ".access-operator-note" in ADMIN_CSS
