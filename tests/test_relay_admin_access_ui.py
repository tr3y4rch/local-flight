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
    # The operator workspace loads and pages its own data, so the access view
    # must not fetch a payload it would discard.
    assert "renderOperatorWorkspace()" in ADMIN_JS
    assert "renderAccess()" in ADMIN_JS
    assert "renderAccess(payload)" not in ADMIN_JS


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
    assert "function licenseKeyRef(" in ADMIN_JS
    assert "d.recipient" in OPERATOR_JS
    assert "delete drawer.dataset.row" in ADMIN_JS
    # The operator workspace shows the public Support ID and a masked key
    # reference. Raw install UUIDs must never reach an operator surface.
    assert "r.support_id" in OPERATOR_JS
    assert "licenseKeyRef(" in OPERATOR_JS
    assert "install_id" not in OPERATOR_JS
    # The legacy access drawer and its tables were unreachable dead paths.
    for removed in ("accessLicenseTable", "accessDeliveryTable", "accessNotificationTable",
                    "openAccessDrawer", "runAccessAction", "maskedRef"):
        assert removed not in ADMIN_JS, removed
    assert "No secret values can be displayed or exported." in OPERATOR_JS
    assert "payload.license_key" not in ADMIN_JS
    assert "one-time-license-key" not in ADMIN_JS
    assert "payload.license_key" not in OPERATOR_JS
    assert "localStorage" not in OPERATOR_JS
    assert "sessionStorage" not in OPERATOR_JS
    assert "drawerBody.replaceChildren()" in ADMIN_JS
    assert ".access-operator-note" in ADMIN_CSS


def test_operator_console_surfaces_the_annual_entitlement_model() -> None:
    """The relay resolves subscription facts; the console must show them.

    Built for permanent licences, the workspace displayed only an ambiguous
    duration date, so an operator could not tell a renewing subscriber from one
    cancelled through period end, nor a founder from a paid licence.
    """
    assert "function opEntitlementKind(" in OPERATOR_JS
    assert "function opRenewal(" in OPERATOR_JS
    assert "Annual subscription" in OPERATOR_JS
    assert "Renews yearly" in OPERATOR_JS
    assert "Ends at period end" in OPERATOR_JS
    assert "Paid through" in OPERATOR_JS
    assert "grace_expires_at" in OPERATOR_JS
    assert "founder_legacy" in OPERATOR_JS

    # Operators must be able to find the accounts that need attention.
    for state in ("grace", "cancelled_active", "past_due"):
        assert f'"{state}"' in OPERATOR_JS
    for source in ("apple_subscription", "google_play_subscription"):
        assert f'"{source}"' in OPERATOR_JS


def test_operator_action_gate_only_disables_what_the_server_gates() -> None:
    """Absence means ungated, not unavailable.

    The server returns an enabled flag and a reason only for the four actions
    whose availability depends on licence state. Everything else is ungated by
    design and must stay clickable, with the POST still requiring a typed
    reason, explicit confirmation, and server-side validation.
    """
    assert "const blocked = Boolean(state) && !state.enabled;" in OPERATOR_JS
    assert "An absent key therefore means" in OPERATOR_JS


def test_operator_console_shows_founder_bridge_progress() -> None:
    assert '"/admin/api/operator/founders"' in OPERATOR_JS
    assert "Founder migration" in OPERATOR_JS
    assert "Still on the legacy bridge" in OPERATOR_JS
    # Executing the snapshot is irreversible and already done; the console is
    # read-only about it.
    assert "founders/snapshot" not in OPERATOR_JS
    assert "founders/snapshot" not in ADMIN_JS


def test_issuance_readiness_distinguishes_a_switch_from_an_unmet_gate() -> None:
    assert "Switched off" in OPERATOR_JS
    assert "config.issuance_enabled === false" in OPERATOR_JS
    assert "Issuance is switched off for this deployment" in OPERATOR_JS
