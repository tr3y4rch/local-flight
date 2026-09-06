from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import relay.main as relay_main
from relay.access import LicenseInactive, VerifiedPurchase
from relay.access.adapters import RecordingLicenseMailer
from relay.access.schema import ACCESS_SCHEMA_VERSION


ADMIN_HOST = {"host": "network.beacontools.cc"}
PUBLIC_HOST = {"host": "relay.beacontools.cc"}
ADMIN_AUTH = ("operator", "correct-horse")


def _configure_access_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay-access-admin.db"))
    monkeypatch.setenv("RELAY_ADMIN_HOST", "network.beacontools.cc")
    monkeypatch.setenv("RELAY_PUBLIC_HOST", "relay.beacontools.cc")
    monkeypatch.setenv("RELAY_ADMIN_ON_PUBLIC", "0")
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", ADMIN_AUTH[1])
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licensed")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET", "admin-e2e-hash-secret-that-is-long-enough")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET", "admin-e2e-key-secret-that-is-different")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET", "admin-e2e-encryption-secret-that-is-distinct")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET_ID", "admin-e2e-hash-v1")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET_ID", "admin-e2e-v1")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET_ID", "admin-e2e-encryption-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_SECRET", "admin-e2e-backup-secret-that-is-distinct")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_KEY_ID", "admin-e2e-backup-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_DIR", str(tmp_path / "access-backups"))
    monkeypatch.setenv("RELAY_ACCESS_SALES_ENABLED", "0")
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "0")
    monkeypatch.setenv("RELAY_ACCESS_APPLE_RECONCILIATION_READY", "0")
    monkeypatch.setenv("RELAY_ACCESS_GOOGLE_RECONCILIATION_READY", "0")
    monkeypatch.setenv("RELAY_ACCESS_SITE_URL", "https://beacontools.cc")
    relay_main._admin_auth_failures.clear()
    relay_main._ensure_schema()


def _purchase(
    external_id: str,
    *,
    provider: str = "stripe",
    email: str = "operator-test@example.test",
) -> VerifiedPurchase:
    product = {
        "stripe": "price_relay_test",
        "apple_app": "cc.beacontools.localflight.paid-app",
        "google_play_product": "cc.beacontools.localflight.relay_access",
    }.get(provider, "cc.beacontools.localflight.paid-app")
    return VerifiedPurchase(
        provider=provider,
        external_id=external_id,
        product_id=product,
        environment="test",
        state="paid",
        email=email,
        evidence_hash=hashlib.sha256(f"signed-proof:{external_id}".encode()).hexdigest(),
    )


def _action(client: TestClient, license_id: str, action: str):
    return client.post(
        f"/admin/api/access/{license_id}/action",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={"action": action},
    )


def test_operator_ui_hides_actions_the_backend_must_reject() -> None:
    source = (Path(__file__).resolve().parents[1] / "relay" / "admin" / "admin.js").read_text(
        encoding="utf-8"
    )
    assert 'const authoritativePurchase = ["paid", "purchased"]' in source
    assert '&& authoritativePurchase) actions.push' in source
    assert 'status === "active" && protectedHolder ? "" : "disabled"' in source
    assert '["Email protection", license.email_protected ? "protected" : "not protected"]' in source


def test_access_operator_routes_are_admin_host_only_authenticated_and_uncacheable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access_admin(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    assert client.get("/admin", headers=PUBLIC_HOST, auth=ADMIN_AUTH).status_code == 404
    assert client.get("/admin/api/access", headers=PUBLIC_HOST, auth=ADMIN_AUTH).status_code == 404

    unauthorized = client.get("/admin/api/access", headers=ADMIN_HOST)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"].lower().startswith("basic")
    assert client.get("/admin/api/access", headers=ADMIN_HOST, auth=("operator", "wrong")).status_code == 401

    dashboard = client.get("/admin", headers=ADMIN_HOST, auth=ADMIN_AUTH)
    assert dashboard.status_code == 200
    assert "Relay Access" in dashboard.text
    assert 'access: "/admin/api/access"' in dashboard.text
    assert dashboard.headers["cache-control"] == "no-store"
    assert dashboard.headers["pragma"] == "no-cache"
    assert dashboard.headers["x-frame-options"] == "DENY"
    assert dashboard.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in dashboard.headers["content-security-policy"]

    access = client.get("/admin/api/access", headers=ADMIN_HOST, auth=ADMIN_AUTH)
    assert access.status_code == 200
    assert access.headers["cache-control"] == "no-store"
    assert access.headers["referrer-policy"] == "no-referrer"


def test_operator_overview_and_detail_are_masked_and_show_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access_admin(tmp_path, monkeypatch)
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    service = relay_main._license_service()
    external_id = "pi_raw_purchase_must_not_render"
    raw_email = "private-operator-test@example.test"
    raw_install = "11111111-1111-4111-8111-111111111111"
    license_record, master_key, _created = service.fulfill_purchase(
        _purchase(external_id, email=raw_email)
    )
    activation = service.activate(
        install_id=raw_install,
        device_kind="desktop",
        device_name="Gate Operations Mac",
        license_key=master_key,
    )
    assert activation.credential is not None

    delivery_id = service.queue_license_email(license_record.license_id, purpose="operator_test")
    claimed = service.claim_due_license_emails(limit=1)
    assert [row["delivery_id"] for row in claimed] == [delivery_id]
    service.finish_license_email(delivery_id, sent=False, detail_code="smtp_timeout")
    event_id = "evt_raw_provider_identifier"
    assert service.begin_purchase_event("stripe", event_id, "checkout.session.completed") is True
    service.finish_purchase_event(
        "stripe",
        event_id,
        status="failed",
        detail_code="signature_invalid",
        license_id=license_record.license_id,
    )

    client = TestClient(relay_main.app)
    overview_response = client.get("/admin/api/access", headers=ADMIN_HOST, auth=ADMIN_AUTH)
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["mode"] == "licensed"
    assert overview["schema_version"] == ACCESS_SCHEMA_VERSION
    assert overview["configuration_ready"] is True
    assert overview["delivery_ready"] is True
    assert overview["sales_enabled"] is False
    assert overview["mobile_ownership_enabled"] is False
    assert overview["reconciliation_ready"] == {"apple": False, "google": False}
    assert overview["licenses"][0]["email_protected"] is True
    assert overview["licenses"][0]["install_ref"]
    assert overview["licenses"][0]["install_ref"] != raw_install
    assert overview["deliveries"][0]["status"] == "failed"
    assert overview["deliveries"][0]["detail_code"] == "smtp_timeout"
    assert overview["purchase_events"][0] == {
        "event_ref": overview["purchase_events"][0]["event_ref"],
        "provider": "stripe",
        "event_type": "checkout.session.completed",
        "status": "failed",
        "detail_code": "signature_invalid",
        "created_at": overview["purchase_events"][0]["created_at"],
        "processed_at": overview["purchase_events"][0]["processed_at"],
    }

    detail_response = client.get(
        f"/admin/api/access/{license_record.license_id}",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["license"]["email_protected"] is True
    assert detail["license"]["key_ref"].endswith(license_record.key_last_four)
    assert detail["activations"][0]["install_ref"]
    assert "install_id" not in detail["activations"][0]
    assert "evidence_hash" not in detail["purchases"][0]
    assert len(detail["purchases"][0]["evidence_ref"]) == 12
    assert detail["deliveries"][0]["detail_code"] == "smtp_timeout"

    rendered = json.dumps({"overview": overview, "detail": detail})
    for raw_secret in (
        external_id,
        event_id,
        raw_email,
        raw_install,
        master_key,
        activation.credential.credential,
        _purchase(external_id).evidence_hash,
    ):
        assert raw_secret not in rendered


def test_operator_license_lifecycle_actions_and_email_delivery_work_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access_admin(tmp_path, monkeypatch)
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    service = relay_main._license_service()
    license_record, original_key, _created = service.fulfill_purchase(
        _purchase("pi_operator_lifecycle")
    )
    activation = service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="desktop",
        device_name="Gate Desk",
        license_key=original_key,
    )
    assert activation.credential is not None
    client = TestClient(relay_main.app)

    suspended = _action(client, license_record.license_id, "suspend_license")
    assert suspended.status_code == 200
    assert suspended.json()["license"]["status"] == "suspended"
    with pytest.raises(LicenseInactive):
        service.resolve_credential(activation.credential.credential)

    reactivated = _action(client, license_record.license_id, "reactivate_license")
    assert reactivated.status_code == 200
    assert reactivated.json()["license"]["status"] == "active"
    second_activation = service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="desktop",
        device_name="Gate Desk",
        license_key=original_key,
    )
    assert second_activation.credential is not None
    receiver_revoke = _action(client, license_record.license_id, "revoke_receiver")
    assert receiver_revoke.status_code == 200
    assert receiver_revoke.json() == {"ok": True, "revoked": True}
    with pytest.raises(LicenseInactive):
        service.resolve_credential(second_activation.credential.credential)

    delivery_id = service.queue_license_email(license_record.license_id, purpose="retry_test")
    [claimed] = service.claim_due_license_emails(limit=1)
    assert claimed["delivery_id"] == delivery_id
    service.finish_license_email(delivery_id, sent=False, detail_code="smtp_timeout")
    retried = _action(client, license_record.license_id, "retry_deliveries")
    assert retried.status_code == 200
    assert retried.json() == {"ok": True, "retried": 1}

    rotated = _action(client, license_record.license_id, "rotate_key")
    assert rotated.status_code == 200
    assert rotated.json()["delivery"] == "queued"
    rotated_payload = json.dumps(rotated.json())
    assert "license_key" not in rotated_payload
    assert original_key not in rotated_payload
    license_messages = [message for message in mailer.messages if message["kind"] == "license"]
    assert len(license_messages) == 1
    assert license_messages[0]["email"] == "operator-test@example.test"
    assert license_messages[0]["license_key"].startswith("LFRA-")
    assert license_messages[0]["license_key"] != original_key
    assert license_messages[0]["license_key"] not in rotated_payload

    revoked = _action(client, license_record.license_id, "revoke_license")
    assert revoked.status_code == 200
    assert revoked.json()["license"]["status"] == "revoked"
    rotate_inactive = _action(client, license_record.license_id, "rotate_key")
    assert rotate_inactive.status_code == 403
    assert rotate_inactive.json()["detail"]["code"] == "license_inactive"
    restored = _action(client, license_record.license_id, "reactivate_license")
    assert restored.status_code == 200
    assert restored.json()["license"]["status"] == "active"
    unsupported = _action(client, license_record.license_id, "delete_everything")
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["code"] == "invalid_challenge"


@pytest.mark.parametrize("provider", ["apple_app", "google_play_product"])
def test_operator_cannot_synthesize_a_store_repurchase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    _configure_access_admin(tmp_path, monkeypatch)
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    service = relay_main._license_service()
    external_id = f"stable-{provider}-owner"
    original, original_key, _created = service.fulfill_purchase(
        _purchase(external_id, provider=provider)
    )
    service.update_purchase_state(provider, external_id, "refunded", reason="store_refund")
    client = TestClient(relay_main.app)

    forbidden = _action(client, original.license_id, "reactivate_license")
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "license_inactive"

    replacement = _action(client, original.license_id, "record_repurchase")
    assert replacement.status_code == 422
    assert replacement.json()["detail"]["code"] == "invalid_challenge"
    assert not [message for message in mailer.messages if message["kind"] == "license"]

    detail = client.get(
        f"/admin/api/access/{original.license_id}",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
    ).json()
    assert detail["license"]["status"] == "refunded"
    assert detail["purchases"][0]["state"] == "refunded"
    assert original_key not in json.dumps(detail)
