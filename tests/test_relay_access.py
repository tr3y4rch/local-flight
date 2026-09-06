from __future__ import annotations

import sqlite3
import time
import base64
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import relay.main as relay_main
from relay.access import (
    AccessConfigurationError,
    AccessRateLimited,
    InvalidChallenge,
    LicenseInactive,
    LicenseNotFound,
    LicenseService,
    PurchaseCatalog,
    PurchaseEnvironmentMismatch,
    PurchaseFulfillmentService,
    VerifiedPurchase,
)
from relay.access.adapters import FakePurchaseVerifier, RecordingLicenseMailer
from relay.access.backup import AccessBackupManager
from relay.access.crypto import normalize_license_key
from relay.access.mobile_verifiers import (
    ApplePaidAppVerifier,
    GooglePlayIntegrityVerifier,
    GooglePlayProductVerifier,
    PaidAppVerificationError,
)
from relay.access.policy import ProviderAccessPolicy
from relay.access.schema import ACCESS_SCHEMA_VERSION, access_schema_version, ensure_access_schema


@pytest.fixture()
def access_service(tmp_path: Path) -> LicenseService:
    database = tmp_path / "access.db"

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    conn = connect()
    ensure_access_schema(conn)
    conn.close()
    return LicenseService(
        connect,
        hash_secret="test-hash-secret-that-is-long-enough",
        key_secret="test-key-secret-that-is-long-enough",
    )


def purchase(external_id: str = "pi_test_purchase_001", *, email: str = "pilot@example.test") -> VerifiedPurchase:
    return VerifiedPurchase(
        provider="stripe",
        external_id=external_id,
        product_id="price_relay_test",
        environment="test",
        state="paid",
        email=email,
        evidence_hash="evidence_test_hash",
    )


def test_purchase_fulfillment_is_idempotent_and_key_is_valid(access_service: LicenseService) -> None:
    first, first_key, first_created = access_service.fulfill_purchase(purchase())
    second, second_key, second_created = access_service.fulfill_purchase(purchase())

    assert first_created is True
    assert second_created is False
    assert first.license_id == second.license_id
    assert first_key == second_key
    assert normalize_license_key(first_key).startswith("LFRA")
    assert first.key_last_four == normalize_license_key(first_key)[-4:]


def test_canonical_catalog_maps_every_paid_source_to_one_product(access_service: LicenseService) -> None:
    catalog = PurchaseCatalog(
        product_code="beacon_relay_lifetime_v1",
        stripe_price_id="price_relay_test",
        apple_product_id="cc.beacontools.localflight.paid-app",
        google_product_id="cc.beacontools.localflight.relay_access",
    )
    fulfillment = PurchaseFulfillmentService(access_service, catalog)
    results = [
        fulfillment.fulfill(purchase("stripe-payment"))[0],
        fulfillment.fulfill(VerifiedPurchase(
            provider="apple_app",
            external_id="apple-app-transaction",
            product_id="cc.beacontools.localflight.paid-app",
            environment="production",
        ))[0],
        fulfillment.fulfill(VerifiedPurchase(
            provider="google_play_product",
            external_id="google-product-purchase-token",
            product_id="cc.beacontools.localflight.relay_access",
            environment="production",
        ))[0],
    ]
    assert {item.product_code for item in results} == {"beacon_relay_lifetime_v1"}
    assert {item.purchase_source for item in results} == {
        "stripe",
        "apple_app",
        "google_play_product",
    }
    with pytest.raises(InvalidChallenge):
        fulfillment.fulfill(VerifiedPurchase(
            provider="apple_app",
            external_id="support-tip",
            product_id="cc.beacontools.localflight.support.small",
        ))


def test_purchase_catalog_rejects_proof_from_another_deployment_environment(
    access_service: LicenseService,
) -> None:
    production_catalog = PurchaseCatalog(
        product_code="beacon_relay_lifetime_v1",
        stripe_price_id="price_relay_test",
        apple_product_id="cc.beacontools.localflight.paid-app",
        google_product_id="cc.beacontools.localflight.relay_access",
        accepted_environments=frozenset({"production"}),
    )
    fulfillment = PurchaseFulfillmentService(access_service, production_catalog)

    with pytest.raises(PurchaseEnvironmentMismatch):
        fulfillment.fulfill(purchase("stripe-test-proof"))


def test_one_receiver_requires_explicit_confirmed_move(access_service: LicenseService) -> None:
    license_record, key, _ = access_service.fulfill_purchase(purchase())
    desktop = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Gate Mac",
        license_key=key,
    )
    assert desktop.activated is True
    assert desktop.credential is not None

    proposed = access_service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="mobile_standalone",
        device_name="Flight Phone",
        license_key=key,
    )
    assert proposed.activated is False
    assert proposed.move_token
    assert proposed.current_receiver == {
        "device_kind": "desktop",
        "device_name": "Gate Mac",
        "activated_at": proposed.current_receiver["activated_at"],
    }

    moved = access_service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="mobile_standalone",
        device_name="Flight Phone",
        license_key=key,
        confirm_move_token=proposed.move_token,
    )
    assert moved.activated is True
    assert moved.replaced_receiver is True
    assert moved.license.license_id == license_record.license_id
    assert moved.credential is not None
    with pytest.raises(LicenseInactive):
        access_service.resolve_credential(desktop.credential.credential)
    status = access_service.status(moved.credential.credential)
    assert status["device_kind"] == "mobile_standalone"
    assert status["receiver_role"] == "independent_receiver"
    assert status["purchase_environment"] == "test"
    assert status["transfer_available"] is True
    assert status["email_protected"] is True


def test_verified_purchase_can_activate_by_license_id_without_exposing_master_key(
    access_service: LicenseService,
) -> None:
    license_record, _key, _ = access_service.fulfill_purchase(purchase(email=""))
    result = access_service.activate_license(
        license_id=license_record.license_id,
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="mobile_standalone",
        device_name="Flight Phone",
    )
    assert result.activated is True
    assert result.credential is not None
    assert result.credential.credential.startswith("lfr_")


def test_stale_move_confirmation_cannot_replace_a_different_receiver(access_service: LicenseService) -> None:
    license_record, key, _ = access_service.fulfill_purchase(purchase())
    access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Gate A",
        license_key=key,
    )
    proposed = access_service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="desktop",
        device_name="Gate B",
        license_key=key,
    )
    access_service.admin_revoke_activation(license_record.license_id)
    access_service.activate(
        install_id="33333333-3333-4333-8333-333333333333",
        device_kind="desktop",
        device_name="Gate C",
        license_key=key,
    )
    with pytest.raises(InvalidChallenge, match="stale"):
        access_service.activate(
            install_id="22222222-2222-4222-8222-222222222222",
            device_kind="desktop",
            device_name="Gate B",
            license_key=key,
            confirm_move_token=proposed.move_token,
        )


def test_refund_revokes_active_receiver(access_service: LicenseService) -> None:
    _, key, _ = access_service.fulfill_purchase(purchase())
    activated = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Gate Mac",
        license_key=key,
    )
    assert activated.credential is not None

    access_service.update_purchase_state("stripe", "pi_test_purchase_001", "refunded")

    with pytest.raises(LicenseInactive):
        access_service.resolve_credential(activated.credential.credential)
    with pytest.raises(LicenseInactive):
        access_service.activate(
            install_id="11111111-1111-4111-8111-111111111111",
            device_kind="desktop",
            device_name="Gate Mac",
            license_key=key,
        )


def test_authoritative_reverification_restores_suspension_but_not_terminal_purchase(
    access_service: LicenseService,
) -> None:
    _license_record, key, _ = access_service.fulfill_purchase(purchase())
    active = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Gate Mac",
        license_key=key,
    )
    assert active.credential is not None
    suspended = access_service.update_purchase_state(
        "stripe", "pi_test_purchase_001", "suspended", reason="authoritative_negative"
    )
    assert suspended.status == "suspended"
    with pytest.raises(LicenseInactive):
        access_service.resolve_credential(active.credential.credential)

    restored, restored_key, created = access_service.fulfill_purchase(purchase())
    assert created is False
    assert restored.status == "active"
    assert restored_key == key

    refunded = access_service.update_purchase_state("stripe", "pi_test_purchase_001", "refunded")
    assert refunded.status == "refunded"
    public_refund = relay_main._access_license_payload(refunded)
    assert public_refund["access_state"] == "refunded"
    assert public_refund["reason_code"] == "purchase_refunded"
    with pytest.raises(LicenseInactive, match="permanently"):
        access_service.fulfill_purchase(purchase())
    with pytest.raises(LicenseInactive, match="permanently"):
        access_service.update_purchase_state("stripe", "pi_test_purchase_001", "paid")


def test_lost_key_rotation_revokes_active_device_credential(access_service: LicenseService) -> None:
    license_record, key, _ = access_service.fulfill_purchase(purchase())
    activated = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Gate Mac",
        license_key=key,
    )
    assert activated.credential is not None
    magic = access_service.request_magic_link("pilot@example.test")
    assert magic is not None
    holder = access_service.exchange_magic_link(magic.token)
    _, rotated_key = access_service.rotate_license_key(holder.token, license_record.license_id)
    assert rotated_key != key
    summary = access_service.holder_license_summaries(holder.token)[0]
    assert summary["key_delivery"]["status"] == "pending"
    assert summary["key_delivery"]["channel"] == "email"
    queued = access_service.claim_due_license_emails()
    assert queued[0]["license_key"] == rotated_key
    access_service.finish_license_email(queued[0]["delivery_id"], sent=True)
    assert access_service.holder_license_summaries(holder.token)[0]["key_delivery"]["state"] == "sent"
    with pytest.raises(LicenseInactive):
        access_service.resolve_credential(activated.credential.credential)


def test_magic_link_attaches_unclaimed_license_and_issues_grant(access_service: LicenseService) -> None:
    license_record, key, _ = access_service.fulfill_purchase(purchase(email=""))
    activated = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="mobile_standalone",
        device_name="Flight Phone",
        license_key=key,
    )
    assert activated.credential is not None

    delivery = access_service.request_magic_link(
        "pilot@example.test",
        credential=activated.credential.credential,
        purpose="protect",
    )
    assert delivery is not None
    holder = access_service.exchange_magic_link(delivery.token)
    assert [item.license_id for item in holder.licenses] == [license_record.license_id]
    assert holder.delivered_license_id == license_record.license_id
    assert holder.license_key == key

    grant = access_service.create_activation_grant(
        holder.token,
        license_record.license_id,
        install_id="22222222-2222-4222-8222-222222222222",
    )
    proposed = access_service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="desktop",
        device_name="Gate PC",
        activation_grant=grant,
    )
    assert proposed.activated is False
    assert proposed.move_token

    moved = access_service.activate(
        install_id="22222222-2222-4222-8222-222222222222",
        device_kind="desktop",
        device_name="Gate PC",
        activation_grant=grant,
        confirm_move_token=proposed.move_token,
    )
    assert moved.activated is True

    with pytest.raises(InvalidChallenge):
        access_service.exchange_magic_link(delivery.token)


def test_license_email_delivery_retries_without_persisting_key(access_service: LicenseService) -> None:
    license_record, key, _ = access_service.fulfill_purchase(purchase())
    delivery_id = access_service.queue_license_email(license_record.license_id, purpose="test_purchase")
    first = access_service.claim_due_license_emails()
    assert first[0]["delivery_id"] == delivery_id
    assert first[0]["license_key"] == key
    access_service.finish_license_email(delivery_id, sent=False, detail_code="smtp_timeout")
    conn = access_service._connect()
    try:
        conn.execute(
            "UPDATE license_deliveries SET next_attempt_at=? WHERE delivery_id=?",
            ("2000-01-01T00:00:00+00:00", delivery_id),
        )
        conn.commit()
    finally:
        conn.close()
    retried = access_service.claim_due_license_emails()
    assert retried[0]["attempt_count"] == 2
    access_service.finish_license_email(delivery_id, sent=True)
    snapshot = access_service.admin_delivery_snapshot()
    assert snapshot[0]["status"] == "sent"
    conn = access_service._connect()
    try:
        assert key not in "\n".join(conn.iterdump())
    finally:
        conn.close()


def test_access_rate_limit_is_durable_and_returns_retry_after(access_service: LicenseService) -> None:
    access_service.check_rate_limit(subject="net_test", action="activate", limit=1, window_seconds=60)
    with pytest.raises(AccessRateLimited) as exc_info:
        access_service.check_rate_limit(subject="net_test", action="activate", limit=1, window_seconds=60)
    assert 1 <= exc_info.value.retry_after <= 60
    conn = access_service._connect()
    try:
        assert "net_test" not in "\n".join(conn.iterdump())
    finally:
        conn.close()


def test_checkout_key_is_revealed_once(access_service: LicenseService) -> None:
    checkout_ref, result_secret = access_service.create_checkout_claim()
    access_service.bind_checkout_session(checkout_ref, "cs_test_should_not_be_stored_raw")
    access_service.validate_checkout_session(checkout_ref, "cs_test_should_not_be_stored_raw")
    with pytest.raises(InvalidChallenge):
        access_service.validate_checkout_session(checkout_ref, "cs_test_wrong_session")
    pending = access_service.checkout_result(checkout_ref, result_secret)
    assert pending == {"state": "pending", "checkout_ref": checkout_ref}

    access_service.fulfill_checkout(checkout_ref, purchase())
    completed = access_service.checkout_result(checkout_ref, result_secret)
    assert completed["state"] == "active"
    assert completed["license_key"].startswith("LFRA-")
    repeated = access_service.checkout_result(checkout_ref, result_secret)
    assert repeated["state"] == "active"
    assert "license_key" not in repeated
    conn = access_service._connect()
    try:
        assert "cs_test_should_not_be_stored_raw" not in "\n".join(conn.iterdump())
        assert conn.execute(
            "SELECT status FROM license_deliveries WHERE channel='browser'"
        ).fetchone()[0] == "revealed"
    finally:
        conn.close()


def test_purchase_event_deduplication(access_service: LicenseService) -> None:
    assert access_service.begin_purchase_event("stripe", "evt_test_001", "checkout.session.completed") is True
    assert access_service.begin_purchase_event("stripe", "evt_test_001", "checkout.session.completed") is False
    access_service.finish_purchase_event("stripe", "evt_test_001", status="processed")
    assert access_service.begin_purchase_event("stripe", "evt_test_001", "checkout.session.completed") is False


def test_failed_purchase_event_can_be_retried(access_service: LicenseService) -> None:
    assert access_service.begin_purchase_event("stripe", "evt_retry", "checkout.session.completed") is True
    access_service.finish_purchase_event("stripe", "evt_retry", status="failed", detail_code="temporary")
    assert access_service.begin_purchase_event("stripe", "evt_retry", "checkout.session.completed") is True


def test_cleanup_removes_old_processed_purchase_events(access_service: LicenseService) -> None:
    assert access_service.begin_purchase_event("stripe", "evt_old", "checkout.session.completed") is True
    access_service.finish_purchase_event("stripe", "evt_old", status="processed")
    conn = access_service._connect()
    try:
        conn.execute("UPDATE purchase_events SET created_at='2000-01-01T00:00:00+00:00'")
        conn.commit()
    finally:
        conn.close()
    assert access_service.cleanup(audit_days=30)["purchase_events"] == 1


def test_simultaneous_activation_keeps_exactly_one_receiver(access_service: LicenseService) -> None:
    _, key, _ = access_service.fulfill_purchase(purchase())

    def activate(index: int):
        return access_service.activate(
            install_id=f"{index:08d}-1111-4111-8111-111111111111",
            device_kind="desktop",
            device_name=f"Gate {index}",
            license_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate, (1, 2)))
    assert sum(result.activated for result in results) == 1
    assert sum(bool(result.move_token) for result in results) == 1

    conn = access_service._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_activations WHERE status='active'").fetchone()[0] == 1
    finally:
        conn.close()


def test_mobile_claim_protects_license_without_consuming_seat(access_service: LicenseService) -> None:
    license_record, _key, _ = access_service.fulfill_purchase(purchase(email=""))
    claim = access_service.create_mobile_license_claim(
        license_id=license_record.license_id,
        install_id="11111111-1111-4111-8111-111111111111",
    )
    delivery = access_service.request_magic_link(
        "Pilot@Example.Test",
        credential=claim,
        purpose="protect_and_transfer",
    )
    assert delivery is not None
    holder = access_service.exchange_magic_link(delivery.token)
    assert holder.licenses[0].license_id == license_record.license_id
    assert access_service.notification_email_for_license(license_record.license_id) == "pilot@example.test"
    with pytest.raises(InvalidChallenge):
        access_service.request_magic_link("pilot@example.test", credential=claim)

    conn = access_service._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_activations").fetchone()[0] == 0
    finally:
        conn.close()


def test_sensitive_values_are_not_persisted_raw(access_service: LicenseService) -> None:
    email = "private-pilot@example.test"
    external_id = "pi_should_never_appear_raw"
    _, key, _ = access_service.fulfill_purchase(purchase(external_id, email=email))
    activated = access_service.activate(
        install_id="11111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Private Gate",
        license_key=key,
    )
    assert activated.credential is not None
    conn = access_service._connect()
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert email not in dump
    assert external_id not in dump
    assert key not in dump
    assert activated.credential.credential not in dump


def test_mobile_ownership_evidence_cannot_move_between_installations(
    access_service: LicenseService,
) -> None:
    evidence = hashlib.sha256(b"signed-store-evidence").hexdigest()
    first_install = "11111111-1111-4111-8111-111111111111"
    second_install = "22222222-2222-4222-8222-222222222222"

    assert access_service.claim_mobile_ownership_evidence(
        provider="apple_app",
        evidence_hash=evidence,
        install_id=first_install,
    ) is True
    assert access_service.claim_mobile_ownership_evidence(
        provider="apple_app",
        evidence_hash=evidence,
        install_id=first_install,
    ) is False
    with pytest.raises(InvalidChallenge, match="another installation"):
        access_service.claim_mobile_ownership_evidence(
            provider="apple_app",
            evidence_hash=evidence,
            install_id=second_install,
        )

    conn = access_service._connect()
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert evidence not in dump
    assert first_install not in dump
    assert second_install not in dump


def test_refunded_purchase_cannot_be_manually_reactivated(access_service: LicenseService) -> None:
    license_record, _key, _ = access_service.fulfill_purchase(purchase())
    access_service.update_purchase_state("stripe", "pi_test_purchase_001", "refunded")
    with pytest.raises(LicenseInactive):
        access_service.admin_set_license_status(license_record.license_id, "active")


def test_google_fresh_paid_proof_after_terminal_state_creates_one_repurchase_license(
    access_service: LicenseService,
) -> None:
    original_purchase = VerifiedPurchase(
        provider="google_app",
        external_id="stable-google-owner",
        product_id="cc.beacontools.localflight.paid-app",
        environment="production",
        verified_at_ms=int(time.time() * 1000),
    )
    original, _key, _ = access_service.fulfill_purchase(original_purchase)
    access_service.update_purchase_state("google_app", "stable-google-owner", "refunded")
    repurchase_proof = VerifiedPurchase(
        **{
            **original_purchase.__dict__,
            "evidence_hash": "fresh-signed-google-proof",
            "verified_at_ms": int((time.time() + 1) * 1000),
        }
    )
    replacement, replacement_key, created = access_service.fulfill_purchase(repurchase_proof)
    replay, replay_key, replay_created = access_service.fulfill_purchase(repurchase_proof)

    assert created is True
    assert replay_created is False
    assert replacement.license_id != original.license_id
    assert replay.license_id == replacement.license_id
    assert replay_key == replacement_key
    conn = access_service._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_licenses").fetchone()[0] == 2
        assert [row[0] for row in conn.execute("SELECT state FROM purchase_records ORDER BY created_at")] == [
            "refunded",
            "paid",
        ]
    finally:
        conn.close()


def test_apple_authoritative_repurchase_restores_the_same_license_identity(
    access_service: LicenseService,
) -> None:
    apple = VerifiedPurchase(
        provider="apple_app",
        external_id="stable-apple-app-transaction",
        product_id="cc.beacontools.localflight.paid-app",
        environment="production",
        verified_at_ms=int(time.time() * 1000),
    )
    original, original_key, _ = access_service.fulfill_purchase(apple)
    access_service.update_purchase_state("apple_app", apple.external_id, "revoked")

    restored, restored_key, created = access_service.fulfill_purchase(
        VerifiedPurchase(
            **{
                **apple.__dict__,
                "evidence_hash": hashlib.sha256(b"fresh-authoritative-apple-proof").hexdigest(),
                "verified_at_ms": int((time.time() + 1) * 1000),
            }
        )
    )
    replay, replay_key, replay_created = access_service.fulfill_purchase(apple)

    assert created is False
    assert replay_created is False
    assert restored.license_id == original.license_id == replay.license_id
    assert restored.status == "active"
    assert restored_key == original_key == replay_key
    conn = access_service._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_licenses").fetchone()[0] == 1
        transitions = [
            row[0]
            for row in conn.execute(
                "SELECT to_state FROM purchase_state_transitions ORDER BY created_at"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert transitions[-2:] == ["revoked", "paid"]


def test_admin_key_rotation_queues_protected_email_without_returning_secret(
    access_service: LicenseService,
) -> None:
    license_record, original_key, _ = access_service.fulfill_purchase(
        purchase("pi_admin_rotation", email="protected@example.test")
    )
    activated = access_service.activate(
        install_id="31313131-3131-4131-8131-313131313131",
        device_kind="desktop",
        device_name="Rotation receiver",
        license_key=original_key,
    )
    rotated = access_service.admin_rotate_license_key(license_record.license_id)

    assert rotated.license_id == license_record.license_id
    with pytest.raises(LicenseInactive):
        access_service.resolve_credential(activated.credential.credential)
    delivery = access_service.claim_due_license_emails(limit=1)
    assert len(delivery) == 1
    assert delivery[0]["purpose"] == "admin_key_rotation"
    assert delivery[0]["license_key"] != original_key

    unprotected, _unprotected_key, _ = access_service.fulfill_purchase(
        purchase("pi_unprotected_rotation", email="")
    )
    with pytest.raises(InvalidChallenge, match="verified email"):
        access_service.admin_rotate_license_key(unprotected.license_id)


def test_admin_delivery_retry_never_requeues_a_superseded_key(
    access_service: LicenseService,
) -> None:
    license_record, _original_key, _ = access_service.fulfill_purchase(
        purchase("pi_admin_retry_rotation", email="protected@example.test")
    )
    obsolete_delivery_id = access_service.queue_license_email(
        license_record.license_id,
        purpose="initial",
    )
    access_service.admin_rotate_license_key(license_record.license_id)

    current = access_service.claim_due_license_emails(limit=10)
    assert len(current) == 1
    current_delivery_id = current[0]["delivery_id"]
    assert current_delivery_id != obsolete_delivery_id
    access_service.finish_license_email(current_delivery_id, sent=False, detail_code="smtp_timeout")

    assert access_service.admin_retry_deliveries(license_record.license_id) == 1
    conn = access_service._connect()
    try:
        rows = {
            str(row["delivery_id"]): row
            for row in conn.execute(
                "SELECT delivery_id, key_version, status, detail_code FROM license_deliveries "
                "WHERE license_id=?",
                (license_record.license_id,),
            ).fetchall()
        }
    finally:
        conn.close()
    assert rows[obsolete_delivery_id]["status"] == "failed"
    assert rows[obsolete_delivery_id]["detail_code"] == "superseded_by_key_rotation"
    assert rows[current_delivery_id]["status"] == "pending"
    assert rows[current_delivery_id]["detail_code"] is None


def test_admin_key_rotation_api_delivers_by_email_without_returning_a_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    service = relay_main._license_service()
    license_record, original_key, _ = service.fulfill_purchase(
        purchase("pi_admin_api_rotation", email="protected@example.test")
    )

    response = TestClient(relay_main.app).post(
        f"/admin/api/access/{license_record.license_id}/action",
        headers={"host": "network.beacontools.cc"},
        auth=("admin", "correct-horse"),
        json={"action": "rotate_key"},
    )

    assert response.status_code == 200
    payload_text = json.dumps(response.json())
    assert response.json()["delivery"] == "queued"
    assert "license_key" not in payload_text
    assert original_key not in payload_text
    delivered = [message for message in mailer.messages if message["kind"] == "license"]
    assert len(delivered) == 1
    assert delivered[0]["license_key"] != original_key
    assert delivered[0]["license_key"] not in payload_text


def _apple_device_transaction(*, age_seconds: int = 0) -> tuple[SimpleNamespace, dict[str, str], str]:
    device_id = str(uuid.uuid4())
    device_nonce = str(uuid.uuid4())
    verification = hashlib.sha384(f"{device_nonce}{device_id}".encode("ascii")).digest()
    signed_at = int((time.time() - age_seconds) * 1000)
    payload = base64.urlsafe_b64encode(json.dumps({"signedDate": signed_at}).encode()).decode().rstrip("=")
    transaction = SimpleNamespace(
        deviceVerificationNonce=device_nonce,
        deviceVerification=base64.b64encode(verification).decode(),
        receiptCreationDate=signed_at,
    )
    return transaction, {"device_verification_id": device_id}, f"header.{payload}.signature"


def test_apple_proof_is_recent_and_matches_storekit_device() -> None:
    verifier = ApplePaidAppVerifier(
        bundle_id="cc.beacontools.localflight",
        app_apple_id=123,
        root_certificates=(b"test-only",),
    )
    transaction, proof, signed = _apple_device_transaction()
    assert verifier._validate_device_and_freshness(transaction, proof, signed) > 0
    with pytest.raises(PaidAppVerificationError, match="belong to this device"):
        verifier._validate_device_and_freshness(
            transaction,
            {"device_verification_id": str(uuid.uuid4())},
            signed,
        )
    stale, stale_proof, stale_signed = _apple_device_transaction(age_seconds=600)
    with pytest.raises(PaidAppVerificationError, match="expired"):
        verifier._validate_device_and_freshness(stale, stale_proof, stale_signed)


def test_mobile_proof_must_be_signed_inside_its_challenge_window(access_service: LicenseService) -> None:
    install_id = "31313131-3131-4131-8131-313131313131"
    old_proof_ms = int((time.time() - 120) * 1000)
    stale_nonce = access_service.create_attestation_challenge(
        platform="ios",
        install_id=install_id,
        intent="inspect",
    )
    with pytest.raises(InvalidChallenge, match="challenge window"):
        access_service.consume_attestation_challenge(
            platform="ios",
            install_id=install_id,
            nonce=stale_nonce,
            intent="inspect",
            proof_signed_at_ms=old_proof_ms,
        )

    fresh_nonce = access_service.create_attestation_challenge(
        platform="ios",
        install_id=install_id,
        intent="inspect",
    )
    access_service.consume_attestation_challenge(
        platform="ios",
        install_id=install_id,
        nonce=fresh_nonce,
        intent="inspect",
        proof_signed_at_ms=int(time.time() * 1000),
    )


def test_provider_policy_is_fail_closed_and_provider_overridable() -> None:
    policy = ProviderAccessPolicy(capabilities={"schedule": True, "schedule:blocked-provider": False})
    assert policy.allows("schedule") is True
    assert policy.allows("schedule", "blocked-provider") is False
    assert policy.allows("radar") is False


def test_relay_provider_environment_overrides_inherit_or_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_ACCESS_SCHEDULE_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_RADAR_ENABLED", "1")
    monkeypatch.delenv("RELAY_ACCESS_AERODATABOX_ENABLED", raising=False)
    monkeypatch.setenv("RELAY_ACCESS_AVIATIONSTACK_ENABLED", "0")
    monkeypatch.setenv("RELAY_ACCESS_ADSBEXCHANGE_ENABLED", "0")

    policy = relay_main._provider_access_policy()

    assert policy.allows("schedule", "aerodatabox") is True
    assert policy.allows("schedule", "aviationstack") is False
    assert policy.allows("radar", "adsbexchange") is False


GOOGLE_RELAY_PRODUCT = "cc.beacontools.localflight.relay_access"


def _google_product_payload(
    *,
    state: str = "PURCHASED",
    acknowledgement: str = "ACKNOWLEDGEMENT_STATE_PENDING",
    product_id: str = GOOGLE_RELAY_PRODUCT,
    quantity: int = 1,
    test_purchase: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "purchaseStateContext": {"purchaseState": state},
        "acknowledgementState": acknowledgement,
        "productLineItem": [
            {
                "productId": product_id,
                "productOfferDetails": {"quantity": quantity},
            }
        ],
    }
    if test_purchase:
        payload["testPurchaseContext"] = {"fopType": "TEST"}
    return payload


def _test_apple_root_certificates_json() -> str:
    import base64
    import json
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Relay Access Test Root")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    encoded = base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode("ascii")
    return json.dumps([encoded])


def _configure_mobile_platform(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    if platform == "ios":
        monkeypatch.setenv("RELAY_ACCESS_IOS_STATE", "available")
        monkeypatch.setenv("RELAY_ACCESS_IOS_STORE_URL", "https://apps.apple.com/app/local-flight/id123456789")
        monkeypatch.setenv("APPLE_IAP_BUNDLE_ID", "cc.beacontools.localflight")
        monkeypatch.setenv("APPLE_APP_ID", "123456789")
        monkeypatch.setenv("APPLE_ROOT_CERTIFICATES_B64_JSON", _test_apple_root_certificates_json())
        monkeypatch.setattr(
            relay_main,
            "_apple_app_transaction_adapter",
            lambda: SimpleNamespace(configured=lambda: True),
        )
        return
    monkeypatch.setenv("RELAY_ACCESS_ANDROID_STATE", "available")
    monkeypatch.setenv(
        "RELAY_ACCESS_ANDROID_STORE_URL",
        "https://play.google.com/store/apps/details?id=cc.beacontools.localflight",
    )
    monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", "cc.beacontools.localflight")
    monkeypatch.setenv("GOOGLE_PLAY_PURCHASE_ENVIRONMENT", "production")
    monkeypatch.setenv("GOOGLE_RELAY_ACCESS_PRODUCT_ID", GOOGLE_RELAY_PRODUCT)
    monkeypatch.setenv("GOOGLE_RTDN_AUDIENCE", "https://relay.beacontools.cc/v1/access/google/rtdn")
    monkeypatch.setenv("GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL", "rtdn@example.test")
    monkeypatch.setattr(
        relay_main,
        "_google_play_developer_adapter",
        lambda: SimpleNamespace(configured=lambda: True),
    )


def test_google_non_consumable_verification_uses_server_authority() -> None:
    purchase_token = "google-play-purchase-token-secret"
    looked_up: list[tuple[str, str]] = []
    verifier = GooglePlayProductVerifier(
        package_name="cc.beacontools.localflight",
        product_id=GOOGLE_RELAY_PRODUCT,
        lookup=lambda package, token: (
            looked_up.append((package, token)) or _google_product_payload()
        ),
        environment="production",
    )
    verified = verifier.verify(
        {
            "google_play_purchase_token": purchase_token,
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
        }
    )
    assert looked_up == [("cc.beacontools.localflight", purchase_token)]
    assert verified.provider == "google_play_product"
    assert verified.external_id == purchase_token
    assert verified.environment == "production"
    assert verified.state == "paid"
    assert verified.identity_kind == "google_play_purchase_token"
    assert verified.reconciliation_mode == "server_authoritative"
    assert verified.reconciliation_handle == purchase_token
    assert verified.acknowledgement_state == "pending"


@pytest.mark.parametrize(
    ("purchase_state", "expected_state"),
    [
        ("PENDING", "suspended"),
        ("CANCELLED", "revoked"),
    ],
)
def test_google_non_consumable_maps_authoritative_non_active_states(
    purchase_state: str,
    expected_state: str,
) -> None:
    verifier = GooglePlayProductVerifier(
        package_name="cc.beacontools.localflight",
        product_id=GOOGLE_RELAY_PRODUCT,
        lookup=lambda _package, _token: _google_product_payload(state=purchase_state),
        environment="production",
    )
    verified = verifier.verify(
        {
            "google_play_purchase_token": "purchase-token",
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
        }
    )
    assert verified.state == expected_state


@pytest.mark.parametrize(
    ("proof", "payload"),
    [
        ({}, _google_product_payload()),
        (
            {"google_play_purchase_token": "token", "google_play_product_id": "another.product"},
            _google_product_payload(),
        ),
        (
            {"google_play_purchase_token": "token", "google_play_product_id": GOOGLE_RELAY_PRODUCT},
            _google_product_payload(product_id="support.product"),
        ),
        (
            {"google_play_purchase_token": "token", "google_play_product_id": GOOGLE_RELAY_PRODUCT},
            _google_product_payload(quantity=2),
        ),
        (
            {"google_play_purchase_token": "token", "google_play_product_id": GOOGLE_RELAY_PRODUCT},
            _google_product_payload(acknowledgement="ACKNOWLEDGEMENT_STATE_UNSPECIFIED"),
        ),
    ],
)
def test_google_non_consumable_rejects_wrong_or_malformed_purchase(
    proof: dict[str, object],
    payload: dict[str, object],
) -> None:
    verifier = GooglePlayProductVerifier(
        package_name="cc.beacontools.localflight",
        product_id=GOOGLE_RELAY_PRODUCT,
        lookup=lambda _package, _token: payload,
    )
    with pytest.raises(PaidAppVerificationError):
        verifier.verify(proof)


def test_google_test_purchase_is_kept_out_of_production_identity() -> None:
    verifier = GooglePlayProductVerifier(
        package_name="cc.beacontools.localflight",
        product_id=GOOGLE_RELAY_PRODUCT,
        lookup=lambda _package, _token: _google_product_payload(test_purchase=True),
        environment="production",
    )
    verified = verifier.verify(
        {
            "google_play_purchase_token": "internal-track-token",
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
        }
    )
    assert verified.environment == "test"


def test_google_play_integrity_binds_transfer_to_nonce_install_and_grant() -> None:
    nonce = "attestation-nonce"
    install_id = "11111111-1111-4111-8111-111111111111"
    grant = "lfrag_test-grant"
    request_hash = GooglePlayIntegrityVerifier.request_hash(
        nonce=nonce,
        install_id=install_id,
        activation_grant=grant,
    )
    verifier = GooglePlayIntegrityVerifier(
        package_name="cc.beacontools.localflight",
        decode=lambda _package, token: {
            "tokenPayloadExternal": {
                "requestDetails": {
                    "requestPackageName": "cc.beacontools.localflight",
                    "requestHash": request_hash,
                    "timestampMillis": str(int(time.time() * 1000)),
                },
                "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED"},
            }
        } if token == "integrity-token" else {},
    )
    verifier.verify_grant(
        integrity_token="integrity-token",
        nonce=nonce,
        install_id=install_id,
        activation_grant=grant,
    )
    with pytest.raises(PaidAppVerificationError, match="does not match"):
        verifier.verify_grant(
            integrity_token="integrity-token",
            nonce=nonce,
            install_id=install_id,
            activation_grant=f"{grant}-captured",
        )


def test_apple_paid_app_verification_rejects_missing_proof() -> None:
    verifier = ApplePaidAppVerifier(bundle_id="cc.beacontools.localflight", app_apple_id=None, root_certificates=())
    with pytest.raises(PaidAppVerificationError):
        verifier.verify({})


def test_apple_server_proof_maps_signed_revocation_and_preserves_store_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from appstoreserverlibrary import signed_data_verifier as signed_module

    stable_app_transaction_id = "apple-stable-app-transaction-id"

    class StubSignedDataVerifier:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def verify_and_decode_app_transaction(self, signed: str):
            payload_segment = signed.split(".", 2)[1]
            payload = json.loads(
                base64.urlsafe_b64decode(
                    payload_segment + "=" * (-len(payload_segment) % 4)
                ).decode("utf-8")
            )
            return SimpleNamespace(
                appTransactionId=stable_app_transaction_id,
                receiptCreationDate=payload["signedDate"],
                # Exercise the signed-payload fallback used by current Apple
                # library versions that do not model this field yet.
                revocationDate=None,
            )

    monkeypatch.setattr(signed_module, "SignedDataVerifier", StubSignedDataVerifier)
    verifier = ApplePaidAppVerifier(
        bundle_id="cc.beacontools.localflight",
        app_apple_id=123456789,
        root_certificates=(b"test-root-is-replaced-by-the-stub",),
        online_checks=False,
    )

    def signed_payload(*, revoked: bool) -> str:
        payload = {
            "signedDate": int(time.time() * 1000),
            "revocationDate": int(time.time() * 1000) if revoked else 0,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"test-header.{encoded}.test-signature"

    revoked = verifier.verify_server(signed_payload(revoked=True))
    restored = verifier.verify_server(signed_payload(revoked=False))

    assert revoked.provider == restored.provider == "apple_app"
    assert revoked.external_id == restored.external_id == stable_app_transaction_id
    assert revoked.identity_kind == restored.identity_kind == "apple_app_entitlement"
    assert revoked.state == "revoked"
    assert restored.state == "paid"


def test_schema_upgrade_adds_encrypted_notification_column(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    conn = sqlite3.connect(database)
    conn.execute(
        """
        CREATE TABLE license_holders (
            holder_id TEXT PRIMARY KEY, email_hmac TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, verified_at TEXT, last_seen_at TEXT
        )
        """
    )
    ensure_access_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(license_holders)")}
    version = access_schema_version(conn)
    delivery_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='license_deliveries'"
    ).fetchone()
    migration_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_access_schema_migrations'"
    ).fetchone()
    conn.close()
    assert "notification_email_ciphertext" in columns
    assert version == ACCESS_SCHEMA_VERSION
    assert delivery_table is not None
    assert migration_table is not None


def test_schema_upgrade_imports_legacy_migration_history(tmp_path: Path) -> None:
    database = tmp_path / "legacy-migrations.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE access_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO access_schema_migrations (version, applied_at) VALUES (1, '2026-01-01T00:00:00+00:00')"
    )
    ensure_access_schema(conn)
    imported = conn.execute(
        "SELECT applied_at FROM relay_access_schema_migrations WHERE version=1"
    ).fetchone()
    purchase_columns = {row[1] for row in conn.execute("PRAGMA table_info(purchase_records)")}
    conn.close()
    assert imported == ("2026-01-01T00:00:00+00:00",)
    assert "state_changed_at" in purchase_columns


def test_schema_upgrade_rolls_back_every_access_change_on_failure(tmp_path: Path) -> None:
    database = tmp_path / "broken-access-schema.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE relay_licenses (license_id TEXT PRIMARY KEY)")
    conn.commit()
    with pytest.raises(sqlite3.OperationalError):
        ensure_access_schema(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "relay_access_schema_migrations" not in tables
    assert "license_holders" not in tables
    assert tables == {"relay_licenses"}


def test_production_access_requires_external_distinct_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licensed")
    monkeypatch.delenv("RELAY_ACCESS_HASH_SECRET", raising=False)
    monkeypatch.delenv("RELAY_ACCESS_KEY_SECRET", raising=False)
    with pytest.raises(AccessConfigurationError):
        relay_main._license_service()
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET", "same-production-secret-that-is-long")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET", "same-production-secret-that-is-long")
    with pytest.raises(AccessConfigurationError, match="differ"):
        relay_main._license_service()


def test_unknown_access_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licenced")
    with pytest.raises(AccessConfigurationError, match="legacy or licensed"):
        relay_main._access_mode()


def test_purchase_environment_boundary_defaults_to_production_and_separates_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", raising=False)
    assert relay_main._accepted_purchase_environments() == frozenset({"production"})

    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", "staging")
    assert relay_main._accepted_purchase_environments() == frozenset({"sandbox", "test"})

    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", "preview")
    with pytest.raises(AccessConfigurationError, match="production or staging"):
        relay_main._accepted_purchase_environments()


def _use_relay_access_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay-access-api.db"))
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licensed")
    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("RELAY_ACCESS_SCHEDULE_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_RADAR_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_REMOTE_COMPANION_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET", "api-test-hash-secret-that-is-long-enough")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET", "api-test-key-secret-that-is-different")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET", "api-test-encryption-secret-that-is-also-distinct")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET_ID", "test-hash-v1")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET_ID", "test-v1")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET_ID", "test-encryption-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_SECRET", "api-test-backup-secret-that-is-distinct-too")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_KEY_ID", "test-backup-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_DIRECTORY", str(tmp_path / "access-backups"))
    relay_main._ensure_schema()


def _commit_public_activation(client: TestClient, prepared, install_id: str):
    payload = prepared.json()
    assert prepared.status_code == 200
    assert payload["activated"] is False
    assert payload["activation_state"] == "pending_commit"
    assert payload["pending_expires_in"] == 600
    credential = payload["credential"]
    pending_status = client.get(
        "/v1/access/status",
        params={"install_id": install_id},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert pending_status.status_code == 403
    assert pending_status.json()["detail"]["credential_state"] == "pending_commit"
    assert pending_status.json()["detail"]["reason_code"] == "activation_not_committed"
    committed = client.post(
        "/v1/access/activate/commit",
        json={"install_id": install_id},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["activated"] is True
    assert committed.json()["activation_state"] == "active"
    return committed


def test_access_api_activates_moves_and_invalidates_old_receiver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    service = relay_main._license_service()
    _license, key, _created = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="pi_api_receiver_move",
            product_id="price_relay_test",
            environment="production",
            state="paid",
        )
    )
    client = TestClient(relay_main.app)
    desktop_id = "11111111-1111-4111-8111-111111111111"
    mobile_id = "22222222-2222-4222-8222-222222222222"

    first = client.post(
        "/v1/access/activate",
        json={"install_id": desktop_id, "device_kind": "desktop", "device_name": "Gate Mac", "license_key": key},
    )
    assert first.status_code == 200
    first_credential = first.json()["credential"]
    assert first_credential.startswith("lfr_")
    assert "install_id" not in first.json()["receiver"]
    first_commit = _commit_public_activation(client, first, desktop_id)
    assert first_commit.json()["credential"] == first_credential
    assert client.get(
        "/v1/access/status",
        params={"install_id": desktop_id},
        headers={"Authorization": f"Bearer {first_credential}"},
    ).status_code == 200

    occupied = client.post(
        "/v1/access/activate",
        json={"install_id": mobile_id, "device_kind": "desktop", "device_name": "Gate PC", "license_key": key},
    )
    assert occupied.status_code == 409
    assert occupied.json()["code"] == "seat_in_use"
    moved = client.post(
        "/v1/access/activate",
        json={
            "install_id": mobile_id,
            "device_kind": "desktop",
            "device_name": "Gate PC",
            "license_key": key,
            "confirm_move_token": occupied.json()["move_token"],
        },
    )
    assert moved.status_code == 200
    moved_credential = moved.json()["credential"]
    # Preparing a move is deliberately non-destructive: the old receiver keeps
    # serving until the new client has persisted its credential and commits it.
    assert client.get(
        "/v1/access/status",
        params={"install_id": desktop_id},
        headers={"Authorization": f"Bearer {first_credential}"},
    ).status_code == 200
    moved = _commit_public_activation(client, moved, mobile_id)
    assert moved.json()["credential"] == moved_credential
    assert client.get(
        "/v1/access/status",
        params={"install_id": desktop_id},
        headers={"Authorization": f"Bearer {first_credential}"},
    ).status_code == 403
    deactivated = client.post(
        "/v1/access/deactivate",
        json={"install_id": mobile_id},
        headers={"Authorization": f"Bearer {moved.json()['credential']}"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["seat_state"] == "available"
    repeated_deactivation = client.post(
        "/v1/access/deactivate",
        json={"install_id": mobile_id},
        headers={"Authorization": f"Bearer {moved.json()['credential']}"},
    )
    assert repeated_deactivation.status_code == 200
    assert repeated_deactivation.json()["credential_state"] == "deactivated"
    assert client.get(
        "/v1/access/status",
        params={"install_id": mobile_id},
        headers={"Authorization": f"Bearer {moved.json()['credential']}"},
    ).status_code == 403


def test_licensed_remote_companion_websocket_requires_one_time_ticket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    service = relay_main._license_service()
    _license, key, _created = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="pi_remote_ws_ticket",
            product_id="price_relay_test",
            environment="production",
        )
    )
    client = TestClient(relay_main.app)
    install_id = "12121212-1212-4212-8212-121212121212"
    activated = client.post(
        "/v1/access/activate",
        json={
            "install_id": install_id,
            "device_kind": "desktop",
            "device_name": "Remote Host",
            "license_key": key,
        },
    )
    activated = _commit_public_activation(client, activated, install_id).json()
    credential = activated["credential"]
    grant_payload = {
        "install_id": install_id,
        "install_ref": relay_main._install_fingerprint(install_id),
        "grant_ref": "rcg_licensed_phone",
        "companion_ref": "lfc_licensed_phone",
        "action": "register",
        "client_name": "Licensed phone",
        "device_type": "phone",
        "app_version": "0.5.1",
    }
    registered = client.post(
        "/v1/remote-companion/grants",
        headers={"Authorization": f"Bearer {credential}"},
        json=grant_payload,
    )
    assert registered.status_code == 200
    without_header = client.post("/v1/remote-companion/grants", json=grant_payload)
    assert without_header.status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/remote-companion/host/ws?install_id={install_id}"
            f"&activation_token={credential}&app_version=0.5.1"
        ):
            pass

    issued = client.post(
        "/v1/remote-companion/host/ticket",
        headers={"Authorization": f"Bearer {credential}"},
        json={"install_id": install_id},
    )
    assert issued.status_code == 200
    ticket = issued.json()["ticket"]
    ws_url = f"{issued.json()['websocket_path']}?install_id={install_id}&app_version=0.5.1"
    assert credential not in ws_url
    assert ticket not in ws_url
    with client.websocket_connect(ws_url, headers={"Authorization": f"Bearer {ticket}"}):
        assert relay_main._install_fingerprint(install_id) in relay_main._REMOTE_COMPANION_HOSTS


def test_generic_activation_endpoint_is_desktop_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    response = TestClient(relay_main.app).post(
        "/v1/access/activate",
        json={
            "install_id": "11111111-1111-4111-8111-111111111111",
            "device_kind": "mobile_standalone",
            "license_key": "LFRA-0000-0000-0000-0000-0000-0000-000",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "receiver_type_invalid"


def test_portable_credential_requires_bearer_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    service = relay_main._license_service()
    _license, key, _created = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="pi_bearer_transport",
            product_id="price_relay_test",
            environment="production",
        )
    )
    install_id = "80808080-8080-4080-8080-808080808080"
    activation = service.activate(
        install_id=install_id,
        device_kind="desktop",
        device_name="Bearer-only desktop",
        license_key=key,
    )
    assert activation.credential is not None
    credential = activation.credential.credential
    client = TestClient(relay_main.app)

    leaked_query = client.get(
        "/v1/client/status",
        params={"install_id": install_id, "activation_token": credential},
    )
    assert leaked_query.status_code == 401

    authorized = client.get(
        "/v1/client/status",
        params={"install_id": install_id},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["plan"] == "licensed"

    managed_query = client.get(
        "/v1/managed/config",
        params={"install_id": install_id, "activation_token": credential},
    )
    assert managed_query.status_code == 401


def test_public_activation_endpoint_is_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_ACTIVATION_10M_LIMIT", "1")
    client = TestClient(relay_main.app)
    payload = {
        "install_id": "88888888-8888-4888-8888-888888888888",
        "device_kind": "desktop",
        "license_key": "not-a-license",
    }
    assert client.post("/v1/access/activate", json=payload).status_code == 422
    limited = client.post("/v1/access/activate", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"]
    assert limited.json()["detail"]["code"] == "access_rate_limited"


def test_mobile_attestation_intent_creates_universal_license_and_activates_standalone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_IOS_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    verified = VerifiedPurchase(
        provider="apple_app",
        external_id="apple-universal-purchase",
        product_id="cc.beacontools.localflight.paid-app",
        environment="production",
        state="paid",
        evidence_hash=hashlib.sha256(b"apple-proof-hash").hexdigest(),
        verified_at_ms=int(time.time() * 1000),
    )
    monkeypatch.setattr(relay_main, "_apple_paid_app_verifier", lambda: FakePurchaseVerifier(verified))
    client = TestClient(relay_main.app)
    install_id = "44444444-4444-4444-8444-444444444444"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "ios", "install_id": install_id, "intent": "standalone"},
    )
    assert challenge.status_code == 200
    activation = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge.json()["nonce"],
            "device_name": "Flight Phone",
            "signed_app_transaction": "test-proof",
        },
    )
    assert activation.status_code == 200
    body = activation.json()
    assert body["activated"] is False
    assert body["activation_state"] == "pending_commit"
    assert body["credential"].startswith("lfr_")
    assert body["included_seat_state"] == "available"
    assert body["receiver"] is None
    assert body["license"]["product_code"] == "beacon_relay_lifetime_v1"
    assert body["included_license"]["license_ref"] == body["license"]["license_ref"]
    assert body["delivery_claim"].startswith("lfrclaim_")
    committed = _commit_public_activation(client, activation, install_id)
    assert committed.json()["license"]["license_ref"] == body["license"]["license_ref"]
    assert committed.json()["receiver"]["device_name"] == "Flight Phone"
    assert "install_id" not in committed.json()["receiver"]
    inspect_challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "ios", "install_id": install_id, "intent": "inspect"},
    ).json()
    inspected = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "inspect",
            "nonce": inspect_challenge["nonce"],
            "signed_app_transaction": "test-proof",
        },
    )
    assert inspected.status_code == 200
    assert inspected.json()["seat_state"] == "active_here"
    assert inspected.json()["receiver"]["device_kind"] == "mobile_standalone"
    assert "install_id" not in inspected.json()["receiver"]

    other_install_id = "45454545-4545-4545-8545-454545454545"
    other_challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "ios", "install_id": other_install_id, "intent": "inspect"},
    ).json()
    replayed_elsewhere = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "ios",
            "install_id": other_install_id,
            "intent": "inspect",
            "nonce": other_challenge["nonce"],
            "signed_app_transaction": "captured-test-proof",
        },
    )
    assert replayed_elsewhere.status_code == 422
    assert replayed_elsewhere.json()["detail"]["code"] == "invalid_challenge"


def test_mobile_magic_link_uses_fragment_and_delivers_existing_key_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    service = relay_main._license_service()
    license_record, original_key, _ = service.fulfill_purchase(
        VerifiedPurchase(
            provider="apple_app",
            external_id="apple-claim-delivery",
            product_id="cc.beacontools.localflight.paid-app",
            environment="production",
        )
    )
    claim = service.create_mobile_license_claim(
        license_id=license_record.license_id,
        install_id="77777777-7777-4777-8777-777777777777",
    )
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    client = TestClient(relay_main.app)
    requested = client.post(
        "/v1/access/magic-links/request",
        headers={"Authorization": f"Bearer {claim}"},
        json={"email": "pilot@example.test", "purpose": "protect_and_transfer"},
    )
    assert requested.status_code == 202
    magic_url = next(item["url"] for item in mailer.messages if item["kind"] == "magic_link")
    assert "/manage/#token=" in magic_url
    assert "?token=" not in magic_url
    token = magic_url.split("#token=", 1)[1]
    exchanged = client.post("/v1/access/magic-links/exchange", json={"token": token})
    assert exchanged.status_code == 200
    assert exchanged.headers["cache-control"] == "no-store"
    assert exchanged.headers["pragma"] == "no-cache"
    assert exchanged.headers["referrer-policy"] == "no-referrer"
    assert exchanged.json()["license_key"] == original_key
    assert exchanged.json()["key_delivery"]["license_key"] == original_key
    assert exchanged.json()["licenses"][0]["key_delivery"]["status"] == "sent"
    assert client.post("/v1/access/magic-links/exchange", json={"token": token}).status_code == 422
    assert any(item["kind"] == "license" and item["license_key"] == original_key for item in mailer.messages)

    repeated_claim = service.create_mobile_license_claim(
        license_id=license_record.license_id,
        install_id="77777777-7777-4777-8777-777777777777",
    )
    assert client.post(
        "/v1/access/magic-links/request",
        headers={"Authorization": f"Bearer {repeated_claim}"},
        json={"email": "pilot@example.test", "purpose": "protect_and_transfer"},
    ).status_code == 202
    repeated_url = [item["url"] for item in mailer.messages if item["kind"] == "magic_link"][-1]
    repeated = client.post(
        "/v1/access/magic-links/exchange",
        json={"token": repeated_url.split("#token=", 1)[1]},
    )
    assert repeated.status_code == 200
    assert "license_key" not in repeated.json()
    assert "key_delivery" not in repeated.json()


def test_public_catalog_exposes_one_source_neutral_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    response = client.get("/v1/access/catalog")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == ACCESS_SCHEMA_VERSION
    assert body["product"]["product_code"] == "beacon_relay_lifetime_v1"
    assert body["product"]["name"] == "Beacon Relay Access"
    assert body["product"]["portable"] is True
    assert body["product"]["verification_environment"] == "production"
    assert body["product"]["seat_rule"] == "one_independent_receiver"
    assert body["product"]["independent_receivers"] == 1
    assert body["product"]["desktop_routes"] == ["relay", "byok", "vatsim"]
    assert set(body["product"]["purchase_sources"]) == {
        "stripe",
        "apple_app",
        "google_play",
        "google_app",
    }
    assert body["product"]["purchase_sources"]["google_play"]["acquisition_model"] == (
        "free_download_in_app_purchase"
    )
    assert body["product"]["purchase_sources"]["google_play"]["free_modes"] == [
        "companion",
        "vatsim",
    ]
    assert body["product"]["platform_rules"]["android"] == {
        "download": "free",
        "free_modes": ["companion", "vatsim"],
        "relay_access_purchase": "one_time_non_consumable",
        "activation_grants_supported": True,
    }
    assert body["product"]["purchase_sources"]["apple_app"]["state"] == "unavailable"
    assert body["product"]["purchase_sources"]["apple_app"]["reconciliation_ready"] is False
    cors = client.options(
        "/v1/access/catalog",
        headers={
            "Origin": "https://beacontools.cc",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert cors.status_code == 200
    assert "GET" in cors.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    ("platform", "broken_setting"),
    [
        ("ios", "bundle"),
        ("ios", "application_id"),
        ("ios", "root_certificates"),
        ("android", "package"),
        ("android", "product_id"),
        ("android", "developer_api"),
        ("android", "environment"),
    ],
)
def test_mobile_catalog_and_challenge_fail_closed_for_platform_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    broken_setting: str,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    _configure_mobile_platform(monkeypatch, platform)
    if broken_setting == "bundle":
        monkeypatch.delenv("APPLE_IAP_BUNDLE_ID", raising=False)
    elif broken_setting == "application_id":
        monkeypatch.setenv("APPLE_APP_ID", "not-an-id")
    elif broken_setting == "root_certificates":
        monkeypatch.setenv("APPLE_ROOT_CERTIFICATES_B64_JSON", "[]")
    elif broken_setting == "package":
        monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    elif broken_setting == "product_id":
        monkeypatch.delenv("GOOGLE_RELAY_ACCESS_PRODUCT_ID", raising=False)
    elif broken_setting == "developer_api":
        monkeypatch.setattr(
            relay_main,
            "_google_play_developer_adapter",
            lambda: SimpleNamespace(configured=lambda: False),
        )
    else:
        monkeypatch.setenv("GOOGLE_PLAY_PURCHASE_ENVIRONMENT", "staging")

    client = TestClient(relay_main.app)
    source = "apple_app" if platform == "ios" else "google_play"
    catalog = client.get("/v1/access/catalog").json()["product"]["purchase_sources"][source]
    assert catalog["available"] is False
    assert catalog["verification_ready"] is False
    assert catalog["configuration_ready"] is False
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={
            "platform": platform,
            "install_id": "34343434-3434-4434-8434-343434343434",
            "intent": "inspect",
        },
    )
    assert challenge.status_code == 503
    assert challenge.json()["detail"]["code"] == "access_not_configured"
    conn = relay_main._connect()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM access_challenges WHERE purpose='mobile_attestation'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize(("platform", "source"), [("ios", "apple_app"), ("android", "google_play")])
def test_mobile_platform_ready_catalog_matches_challenge_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    source: str,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    _configure_mobile_platform(monkeypatch, platform)
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: RecordingLicenseMailer())
    client = TestClient(relay_main.app)
    catalog = client.get("/v1/access/catalog").json()["product"]["purchase_sources"][source]
    assert catalog["configuration_ready"] is True
    assert catalog["verification_ready"] is True
    assert catalog["delivery_ready"] is True
    assert catalog["reconciliation_ready"] is True
    assert catalog["available"] is True
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={
            "platform": platform,
            "install_id": "56565656-5656-4656-8656-565656565656",
            "intent": "inspect",
        },
    )
    assert challenge.status_code == 200
    assert challenge.json()["platform"] == platform


@pytest.mark.parametrize(("platform", "source"), [("ios", "apple_app"), ("android", "google_play")])
def test_mobile_public_acquisition_requires_official_store_link_and_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    source: str,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    _configure_mobile_platform(monkeypatch, platform)
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: RecordingLicenseMailer())
    if platform == "ios":
        monkeypatch.setenv("RELAY_ACCESS_IOS_STORE_URL", "https://example.test/not-the-app-store")
    else:
        monkeypatch.setenv("RELAY_ACCESS_ANDROID_STORE_URL", "https://example.test/not-google-play")

    client = TestClient(relay_main.app)
    without_link = client.get("/v1/access/catalog").json()["product"]["purchase_sources"][source]
    assert without_link["available"] is False
    assert without_link["store_url"] == ""

    _configure_mobile_platform(monkeypatch, platform)
    if platform == "ios":
        monkeypatch.setattr(
            relay_main,
            "_apple_app_transaction_adapter",
            lambda: SimpleNamespace(configured=lambda: False),
        )
    else:
        monkeypatch.delenv("GOOGLE_RTDN_AUDIENCE", raising=False)
    without_reconciliation = client.get("/v1/access/catalog").json()["product"]["purchase_sources"][source]
    assert without_reconciliation["available"] is False
    assert without_reconciliation["reconciliation_ready"] is False

    # Purchase discovery stays closed, but existing owners may still restore
    # through cryptographic ownership verification.
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={
            "platform": platform,
            "install_id": "58585858-5858-4858-8858-585858585858",
            "intent": "inspect",
        },
    )
    assert challenge.status_code == 200


@pytest.mark.parametrize(("platform", "source"), [("ios", "apple_app"), ("android", "google_play")])
def test_mobile_catalog_requires_delivery_for_public_acquisition_but_not_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    source: str,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    _configure_mobile_platform(monkeypatch, platform)
    client = TestClient(relay_main.app)

    catalog = client.get("/v1/access/catalog").json()["product"]["purchase_sources"][source]
    assert catalog["configuration_ready"] is True
    assert catalog["verification_ready"] is True
    assert catalog["delivery_ready"] is False
    assert catalog["available"] is False

    # Existing store owners can still restore/activate while mail delivery is
    # unconfigured or temporarily unavailable.
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={
            "platform": platform,
            "install_id": "57575757-5757-4757-8757-575757575757",
            "intent": "inspect",
        },
    )
    assert challenge.status_code == 200


def test_attested_mobile_grant_selects_existing_cross_platform_license(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_IOS_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    service = relay_main._license_service()
    desktop_license, desktop_key, _ = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="stripe-license-for-mobile",
            product_id="price_relay_test",
            environment="production",
            email="pilot@example.test",
        )
    )
    magic = service.request_magic_link("pilot@example.test")
    assert magic is not None
    holder = service.exchange_magic_link(magic.token)
    grant = service.create_activation_grant(holder.token, desktop_license.license_id)
    verified = VerifiedPurchase(
        provider="apple_app",
        external_id="apple-included-license",
        product_id="cc.beacontools.localflight.paid-app",
        environment="production",
        evidence_hash=hashlib.sha256(b"apple-included-proof").hexdigest(),
        verified_at_ms=int(time.time() * 1000),
    )
    monkeypatch.setattr(relay_main, "_apple_paid_app_verifier", lambda: FakePurchaseVerifier(verified))
    client = TestClient(relay_main.app)
    install_id = "55555555-5555-4555-8555-555555555555"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "ios", "install_id": install_id, "intent": "standalone"},
    ).json()
    response = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge["nonce"],
            "signed_app_transaction": "test-proof",
            "activation_grant": grant,
        },
    )
    assert response.status_code == 200
    assert response.json()["license"]["license_ref"] == desktop_license.license_id
    assert response.json()["included_license"]["license_ref"] != desktop_license.license_id
    assert response.json()["email_protected"] is True
    assert response.json()["included_email_protected"] is False
    assert response.json()["activation_state"] == "pending_commit"
    # The grant is reserved during preparation and consumed only once the
    # credential has been stored and committed.
    committed = _commit_public_activation(client, response, install_id)
    assert committed.json()["license"]["license_ref"] == desktop_license.license_id
    with pytest.raises(InvalidChallenge):
        service.activate(
            install_id="66666666-6666-4666-8666-666666666666",
            device_kind="desktop",
            device_name="Replay",
            activation_grant=grant,
        )
    assert desktop_key.startswith("LFRA-")


def test_google_server_purchase_pending_suspends_then_purchased_reactivates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_ANDROID_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    service = relay_main._license_service()
    license_record, key, _ = service.fulfill_purchase(
        VerifiedPurchase(
            provider="google_play_product",
            external_id="google-purchase-token",
            product_id=GOOGLE_RELAY_PRODUCT,
            environment="production",
            identity_kind="google_play_purchase_token",
            reconciliation_mode="server_authoritative",
            reconciliation_handle="google-purchase-token",
        )
    )
    install_id = "99999999-9999-4999-8999-999999999999"
    active = service.activate(
        install_id=install_id,
        device_kind="mobile_standalone",
        device_name="Android Phone",
        license_key=key,
    )
    assert active.credential is not None
    client = TestClient(relay_main.app)

    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "android", "install_id": install_id, "intent": "standalone"},
    ).json()
    monkeypatch.setattr(
        relay_main,
        "_google_play_product_verifier",
        lambda: GooglePlayProductVerifier(
            package_name="cc.beacontools.localflight",
            product_id=GOOGLE_RELAY_PRODUCT,
            lookup=lambda _package, _token: _google_product_payload(
                state="PENDING"
            ),
            environment="production",
        ),
    )
    suspended = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "android",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge["nonce"],
            "google_play_purchase_token": "google-purchase-token",
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
        },
    )
    assert suspended.status_code == 403
    assert suspended.json()["detail"]["access_state"] == "suspended"
    assert suspended.json()["detail"]["reason_code"] == "store_purchase_pending"
    with pytest.raises(LicenseInactive):
        service.resolve_credential(active.credential.credential)

    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "android", "install_id": install_id, "intent": "standalone"},
    ).json()
    restored_verifier = GooglePlayProductVerifier(
        package_name="cc.beacontools.localflight",
        product_id=GOOGLE_RELAY_PRODUCT,
        lookup=lambda _package, _token: _google_product_payload(
            acknowledgement="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        ),
        environment="production",
    )
    monkeypatch.setattr(relay_main, "_google_play_product_verifier", lambda: restored_verifier)
    restored = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "android",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge["nonce"],
            "google_play_purchase_token": "google-purchase-token",
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
            "device_name": "Android Phone",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["license"]["license_ref"] == license_record.license_id
    assert restored.json()["credential"].startswith("lfr_")
    committed = _commit_public_activation(client, restored, install_id)
    assert committed.json()["license"]["license_ref"] == license_record.license_id


def test_test_store_license_cannot_authorize_production_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    service = relay_main._license_service()
    _license, key, _created = service.fulfill_purchase(
        VerifiedPurchase(
            provider="google_play_product",
            external_id="google-internal-test-token",
            product_id=GOOGLE_RELAY_PRODUCT,
            environment="test",
            state="paid",
            identity_kind="google_play_purchase_token",
            reconciliation_mode="server_authoritative",
            reconciliation_handle="google-internal-test-token",
        )
    )
    install_id = "33333333-3333-4333-8333-333333333333"
    activated = service.activate(
        install_id=install_id,
        device_kind="mobile_standalone",
        device_name="Internal test phone",
        license_key=key,
    )
    assert activated.credential is not None
    with pytest.raises(HTTPException) as exc_info:
        relay_main._resolve_access(
            install_id=install_id,
            activation_token=activated.credential.credential,
            service="aviationstack",
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "test_license_not_authorized"


def test_checkout_does_not_create_claim_without_launch_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_relay_access_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_SALES_ENABLED", "1")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_RELAY_ACCESS_PRICE_ID", raising=False)
    response = TestClient(relay_main.app).post("/v1/access/stripe/checkout", json={})
    assert response.status_code == 503
    conn = relay_main._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM access_challenges WHERE purpose='checkout_result'").fetchone()[0] == 0
    finally:
        conn.close()
