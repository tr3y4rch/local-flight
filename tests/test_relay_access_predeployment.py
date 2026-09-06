from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import relay.main as relay_main
from relay.access import (
    AccessConfigurationError,
    InvalidChallenge,
    LicenseInactive,
    LicenseService,
    VerifiedPurchase,
)
from relay.access.adapters import FakePurchaseVerifier, RecordingLicenseMailer
from relay.access.backup import AccessBackupManager
from relay.access.schema import ensure_access_schema


PUBLIC_HOST = {"host": "relay.beacontools.cc"}
ADMIN_HOST = {"host": "network.beacontools.cc"}
ADMIN_AUTH = ("operator", "predeployment-password")
GOOGLE_PRODUCT = "cc.beacontools.localflight.relay_access"


@pytest.fixture()
def licensed_stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "licensed-predeployment.db"
    values = {
        "DB_PATH": str(database),
        "RELAY_PUBLIC_HOST": "relay.beacontools.cc",
        "RELAY_ADMIN_HOST": "network.beacontools.cc",
        "RELAY_ADMIN_PASSWORD": ADMIN_AUTH[1],
        "RELAY_ACCESS_MODE": "licensed",
        "RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT": "production",
        "RELAY_ACCESS_HASH_SECRET": "predeploy-hash-secret-that-is-long-and-distinct",
        "RELAY_ACCESS_HASH_SECRET_ID": "predeploy-hash-v1",
        "RELAY_ACCESS_KEY_SECRET": "predeploy-license-secret-that-is-long-and-distinct",
        "RELAY_ACCESS_KEY_SECRET_ID": "predeploy-license-v1",
        "RELAY_ACCESS_ENCRYPTION_SECRET": "predeploy-encryption-secret-that-is-long-and-distinct",
        "RELAY_ACCESS_ENCRYPTION_SECRET_ID": "predeploy-encryption-v1",
        "RELAY_ACCESS_BACKUP_ENABLED": "1",
        "RELAY_ACCESS_BACKUP_SECRET": "predeploy-backup-secret-that-is-long-and-distinct",
        "RELAY_ACCESS_BACKUP_KEY_ID": "predeploy-backup-v1",
        "RELAY_ACCESS_BACKUP_DIRECTORY": str(tmp_path / "backups"),
        "RELAY_ACCESS_SITE_URL": "https://beacontools.cc",
        "RELAY_ACCESS_SCHEDULE_ENABLED": "1",
        "RELAY_ACCESS_RADAR_ENABLED": "1",
        "RELAY_ACCESS_REMOTE_COMPANION_ENABLED": "1",
        "RELAY_ACCESS_AERODATABOX_ENABLED": "1",
        "RELAY_ACCESS_AVIATIONSTACK_ENABLED": "1",
        "RELAY_ACCESS_ADSBEXCHANGE_ENABLED": "1",
        "GOOGLE_PLAY_PACKAGE_NAME": "cc.beacontools.localflight",
        "GOOGLE_PLAY_PURCHASE_ENVIRONMENT": "production",
        "GOOGLE_RELAY_ACCESS_PRODUCT_ID": GOOGLE_PRODUCT,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    relay_main._admin_auth_failures.clear()
    relay_main._ensure_schema()
    return TestClient(relay_main.app), relay_main._license_service(), database


def _purchase(
    external_id: str,
    *,
    provider: str = "stripe",
    email: str = "",
    state: str = "paid",
) -> VerifiedPurchase:
    return VerifiedPurchase(
        provider=provider,
        external_id=external_id,
        product_id=(
            GOOGLE_PRODUCT
            if provider == "google_play_product"
            else "cc.beacontools.localflight.paid-app"
            if provider == "apple_app"
            else "price_predeployment"
        ),
        environment="production",
        state=state,
        email=email,
        evidence_hash=hashlib.sha256(f"proof:{external_id}:{state}".encode()).hexdigest(),
        verified_at_ms=int(time.time() * 1000),
        identity_kind=(
            "google_play_purchase_token"
            if provider == "google_play_product"
            else "apple_app_entitlement"
            if provider == "apple_app"
            else "stripe_payment_intent"
        ),
        reconciliation_mode=(
            "server_authoritative" if provider == "google_play_product" else "device_and_server"
            if provider == "apple_app" else "webhook"
        ),
        reconciliation_handle=external_id if provider != "stripe" else "",
        acknowledgement_state="acknowledged" if provider == "google_play_product" else "",
    )


def _prepare_and_commit(
    client: TestClient,
    *,
    install_id: str,
    license_key: str,
    device_name: str,
    confirm_move_token: str = "",
):
    prepared = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": install_id,
            "device_kind": "desktop",
            "device_name": device_name,
            "license_key": license_key,
            "confirm_move_token": confirm_move_token,
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["activation_state"] == "pending_commit"
    credential = prepared.json()["credential"]
    committed = client.post(
        "/v1/access/activate/commit",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {credential}"},
        json={"install_id": install_id},
    )
    assert committed.status_code == 200, committed.text
    return credential, committed


def test_licensed_mode_issues_no_legacy_credentials_and_rejects_managed_data(
    licensed_stack,
) -> None:
    client, _service, _database = licensed_stack
    install_id = "11111111-1111-4111-8111-111111111111"
    managed_token = "lfm_predeployment_managed_token"
    community_token = "lfm_predeployment_community_token"
    conn = relay_main._connect()
    try:
        relay_main._store_activation_token(
            conn,
            token=managed_token,
            label="Old managed token",
            schedule_limit=100,
            radar_limit=100,
            created_by="test",
            bound_install_id=install_id,
            access_plan="managed",
        )
        relay_main._store_activation_token(
            conn,
            token=community_token,
            label="Old community token",
            schedule_limit=50,
            radar_limit=50,
            created_by="test",
            access_plan="community",
        )
        conn.commit()
        before = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM activation_tokens), "
                "(SELECT COUNT(*) FROM activation_requests)"
            ).fetchone()
        )
    finally:
        conn.close()

    issued = client.post(
        "/v1/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "requested_mode": "community",
            "app_version": "0.6.0",
        },
    )
    assert issued.status_code == 403
    assert issued.json()["detail"] == {
        "code": "relay_license_required",
        "message": "Legacy Community and Managed credentials are not issued in licensed mode.",
        "credential_state": "unknown",
        "reason_code": "legacy_issuance_disabled",
        "retryable": False,
    }

    conn = relay_main._connect()
    try:
        after = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM activation_tokens), "
                "(SELECT COUNT(*) FROM activation_requests)"
            ).fetchone()
        )
    finally:
        conn.close()
    assert after == before

    for token in (managed_token, community_token):
        for service_name in ("aviationstack", "radar", "remote_companion"):
            with pytest.raises(HTTPException) as exc_info:
                relay_main._resolve_access(
                    install_id=install_id,
                    activation_token=token,
                    service=service_name,
                )
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["code"] == "relay_license_required"
            assert exc_info.value.detail["reason_code"] == "licensed_credential_required"

    status = client.get(
        "/v1/client/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {managed_token}"},
        params={"install_id": install_id},
    )
    assert status.status_code == 403
    assert status.json()["detail"]["code"] == "relay_license_required"


def test_two_phase_move_preserves_old_receiver_and_stale_commit_cannot_replace_newer(
    licensed_stack,
) -> None:
    client, service, _database = licensed_stack
    _license, key, _ = service.fulfill_purchase(_purchase("move-commit-purchase"))
    first_id = "21111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    first_credential, _ = _prepare_and_commit(
        client,
        install_id=first_id,
        license_key=key,
        device_name="Gate A",
    )

    occupied = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": second_id,
            "device_kind": "desktop",
            "device_name": "Gate B",
            "license_key": key,
        },
    )
    assert occupied.status_code == 409
    pending = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": second_id,
            "device_kind": "desktop",
            "device_name": "Gate B",
            "license_key": key,
            "confirm_move_token": occupied.json()["move_token"],
        },
    )
    assert pending.status_code == 200
    pending_credential = pending.json()["credential"]

    # This represents a local credential-write failure: no commit is sent, and
    # the receiver that was working before preparation remains authoritative.
    assert service.resolve_credential(first_credential, install_id=first_id)["device_name"] == "Gate A"
    with pytest.raises(LicenseInactive) as pending_error:
        service.resolve_credential(pending_credential, install_id=second_id)
    assert pending_error.value.credential_state == "pending_commit"

    # Model an independently completed receiver change while this commit was in
    # flight. The expected activation ID recorded by the pending row must make
    # the stale commit fail closed.
    conn = service._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT * FROM relay_activations WHERE status='active'"
        ).fetchone()
        pending_row = conn.execute(
            "SELECT * FROM relay_activations WHERE status='pending_commit'"
        ).fetchone()
        conn.execute(
            "UPDATE relay_activations SET status='replaced', revoke_reason='receiver_replaced' "
            "WHERE activation_id=?",
            (active["activation_id"],),
        )
        conn.execute(
            """
            INSERT INTO relay_activations (
                activation_id, license_id, install_id, device_kind, device_name,
                credential_hash, credential_prefix, credential_hash_secret_id,
                status, activated_at, last_seen_at
            ) VALUES (?, ?, ?, 'desktop', 'Gate C', ?, 'lfr_masked', ?, 'active', ?, ?)
            """,
            (
                "act_independent_receiver",
                pending_row["license_id"],
                "23333333-3333-4333-8333-333333333333",
                "independent-non-secret-test-hash",
                pending_row["credential_hash_secret_id"],
                service.now(),
                service.now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    stale = client.post(
        "/v1/access/activate/commit",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {pending_credential}"},
        json={"install_id": second_id},
    )
    assert stale.status_code == 422
    assert stale.json()["detail"]["credential_state"] == "pending_commit"
    assert stale.json()["detail"]["reason_code"] == "activation_commit_stale"
    assert stale.json()["detail"]["current_main_device"]["device_name"] == "Ga… C"


def test_concurrent_commit_is_idempotent_and_leaves_exactly_one_receiver(
    licensed_stack,
) -> None:
    _client, service, _database = licensed_stack
    _license, key, _ = service.fulfill_purchase(_purchase("concurrent-commit"))
    install_id = "31111111-1111-4111-8111-111111111111"
    prepared = service.activate(
        install_id=install_id,
        device_kind="desktop",
        device_name="Concurrent gate",
        license_key=key,
        prepare_only=True,
    )
    assert prepared.credential is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: service.commit_activation(
                    prepared.credential.credential,
                    install_id=install_id,
                ),
                (1, 2),
            )
        )
    assert all(result.activated for result in results)
    assert {result.credential.activation_id for result in results if result.credential} == {
        prepared.credential.activation_id
    }
    conn = service._connect()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM relay_activations WHERE status='active'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("purchase_state", "access_state", "reason_code"),
    [
        ("suspended", "suspended", "purchase_suspended"),
        ("refunded", "refunded", "purchase_refunded"),
        ("revoked", "revoked", "purchase_revoked"),
    ],
)
def test_access_errors_preserve_license_and_credential_state(
    licensed_stack,
    purchase_state: str,
    access_state: str,
    reason_code: str,
) -> None:
    client, service, _database = licensed_stack
    external_id = f"structured-{purchase_state}"
    _license, key, _ = service.fulfill_purchase(_purchase(external_id))
    install_id = {
        "suspended": "41111111-1111-4111-8111-111111111111",
        "refunded": "42222222-2222-4222-8222-222222222222",
        "revoked": "43333333-3333-4333-8333-333333333333",
    }[purchase_state]
    credential, _ = _prepare_and_commit(
        client,
        install_id=install_id,
        license_key=key,
        device_name=f"{purchase_state.title()} phone",
    )
    service.update_purchase_state("stripe", external_id, purchase_state)
    response = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {credential}"},
        params={"install_id": install_id},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "license_inactive"
    assert detail["access_state"] == access_state
    assert detail["credential_state"] == "revoked"
    assert detail["reason_code"] == reason_code
    assert detail["retryable"] is False


def test_deactivation_is_idempotent_for_active_replaced_and_terminal_credentials(
    licensed_stack,
) -> None:
    client, service, _database = licensed_stack
    _license, key, _ = service.fulfill_purchase(_purchase("idempotent-release"))
    install_id = "51111111-1111-4111-8111-111111111111"
    credential, _ = _prepare_and_commit(
        client,
        install_id=install_id,
        license_key=key,
        device_name="Release test",
    )
    first = client.post(
        "/v1/access/deactivate",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {credential}"},
        json={"install_id": install_id},
    )
    second = client.post(
        "/v1/access/deactivate",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {credential}"},
        json={"install_id": install_id},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["credential_state"] == second.json()["credential_state"] == "deactivated"
    assert first.json()["seat_state"] == second.json()["seat_state"] == "available"


def test_google_purchase_acknowledgement_is_durable_and_rtdn_is_idempotent(
    licensed_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, database = licensed_stack
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_ANDROID_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    purchase_token = "raw-google-purchase-token-never-persist"
    verified = VerifiedPurchase(
        **{
            **_purchase(purchase_token, provider="google_play_product").__dict__,
            "acknowledgement_state": "pending",
        }
    )
    monkeypatch.setattr(
        relay_main,
        "_google_play_product_verifier",
        lambda: FakePurchaseVerifier(verified),
    )
    install_id = "61111111-1111-4111-8111-111111111111"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        headers=PUBLIC_HOST,
        json={"platform": "android", "install_id": install_id, "intent": "standalone"},
    )
    activated = client.post(
        "/v1/access/mobile/attestation/verify",
        headers=PUBLIC_HOST,
        json={
            "platform": "android",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge.json()["nonce"],
            "google_play_purchase_token": purchase_token,
            "google_play_product_id": GOOGLE_PRODUCT,
        },
    )
    assert activated.status_code == 200
    license_ref = activated.json()["license"]["license_ref"]
    queued = service.admin_notification_snapshot()
    assert queued[0]["purpose"] == "google_play_product:acknowledge"
    assert queued[0]["status"] == "pending"

    acknowledgements: list[tuple[str, str, str]] = []
    adapter = SimpleNamespace(
        configured=lambda: True,
        acknowledge_product_purchase=lambda **kwargs: acknowledgements.append(
            (
                kwargs["package_name"],
                kwargs["product_id"],
                kwargs["purchase_token"],
            )
        ),
    )
    monkeypatch.setattr(relay_main, "_google_play_developer_adapter", lambda: adapter)
    assert relay_main._process_provider_operations(limit=10) == 1
    assert acknowledgements == [
        ("cc.beacontools.localflight", GOOGLE_PRODUCT, purchase_token)
    ]
    detail = service.admin_license_detail(license_ref)
    assert detail["purchases"][0]["acknowledgement_state"] == "acknowledged"
    assert detail["notifications"][0]["status"] == "sent"

    # Google later reports that the same non-consumable was canceled. RTDN is
    # authenticated at the route boundary and provider lookup is authoritative.
    revoked = VerifiedPurchase(**{**verified.__dict__, "state": "revoked"})
    monkeypatch.setattr(relay_main, "_verify_google_rtdn_request", lambda _request: None)
    monkeypatch.setattr(
        relay_main,
        "_google_play_product_verifier",
        lambda: FakePurchaseVerifier(revoked),
    )
    notification = {
        "version": "1.0",
        "packageName": "cc.beacontools.localflight",
        "eventTimeMillis": str(int(time.time() * 1000)),
        "oneTimeProductNotification": {
            "version": "1.0",
            "notificationType": 1,
            "purchaseToken": purchase_token,
            "sku": GOOGLE_PRODUCT,
        },
    }
    envelope = {
        "message": {
            "messageId": "rtdn-idempotent-event",
            "data": base64.b64encode(json.dumps(notification).encode()).decode(),
        }
    }
    first = client.post("/v1/access/google/rtdn", headers=PUBLIC_HOST, json=envelope)
    replay = client.post("/v1/access/google/rtdn", headers=PUBLIC_HOST, json=envelope)
    assert first.status_code == replay.status_code == 204
    assert service.admin_license_detail(license_ref)["license"].status == "revoked"
    conn = sqlite3.connect(database)
    try:
        dump = "\n".join(conn.iterdump())
        assert conn.execute(
            "SELECT COUNT(*) FROM purchase_events WHERE provider='google_play'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
    assert purchase_token not in dump
    assert "rtdn-idempotent-event" not in dump


def test_google_pending_purchase_creates_no_license(
    licensed_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, _database = licensed_stack
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_ANDROID_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    pending = _purchase("pending-google-token", provider="google_play_product", state="suspended")
    monkeypatch.setattr(
        relay_main,
        "_google_play_product_verifier",
        lambda: FakePurchaseVerifier(pending),
    )
    install_id = "62222222-2222-4222-8222-222222222222"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "android", "install_id": install_id, "intent": "standalone"},
    ).json()
    response = client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "android",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge["nonce"],
            "google_play_purchase_token": "pending-google-token",
            "google_play_product_id": GOOGLE_PRODUCT,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["access_state"] == "suspended"
    assert response.json()["detail"]["reason_code"] == "store_purchase_pending"
    assert service.admin_search()["total"] == 0


def test_encrypted_wal_backup_restores_keys_activations_and_historical_keyrings(
    tmp_path: Path,
) -> None:
    database = tmp_path / "access.db"

    def connect(path: Path = database) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    conn = connect()
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_access_schema(conn)
    conn.close()
    old_hash = "old-hash-secret-that-must-remain-readable"
    old_key = "old-license-secret-that-must-remain-readable"
    old_encryption = "old-encryption-secret-that-must-remain-readable"
    original = LicenseService(
        connect,
        hash_secret=old_hash,
        hash_secret_id="old-hash",
        key_secret=old_key,
        key_secret_id="old-license",
        encryption_secret=old_encryption,
        encryption_secret_id="old-encryption",
    )
    raw_email = "backup-owner@example.test"
    raw_purchase = "apple-backup-app-transaction"
    license_record, master_key, _ = original.fulfill_purchase(
        _purchase(raw_purchase, provider="apple_app", email=raw_email)
    )
    activation = original.activate(
        install_id="71111111-1111-4111-8111-111111111111",
        device_kind="desktop",
        device_name="Backup receiver",
        license_key=master_key,
    )
    assert activation.credential is not None

    backup_secret = "backup-artifact-secret-that-is-separate"
    manager = AccessBackupManager(
        database_path=database,
        backup_directory=tmp_path / "encrypted-backups",
        active_key_id="backup-v1",
        active_secret=backup_secret,
    )
    inspection = manager.create_backup()
    artifact = inspection.path.read_bytes()
    for raw_value in (raw_email, raw_purchase, master_key, activation.credential.credential):
        assert raw_value.encode() not in artifact

    restored_path = tmp_path / "restored.db"

    def restored_validator(path: Path) -> None:
        def restored_connect() -> sqlite3.Connection:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn

        service = LicenseService(
            restored_connect,
            hash_secret="new-hash-secret-used-for-current-writes",
            hash_secret_id="new-hash",
            key_secret="new-license-secret-used-for-current-writes",
            key_secret_id="new-license",
            encryption_secret="new-encryption-secret-used-for-current-writes",
            encryption_secret_id="new-encryption",
            historical_hash_secrets={"old-hash": old_hash},
            historical_key_secrets={"old-license": old_key},
            historical_encryption_secrets={"old-encryption": old_encryption},
        )
        assert service.verify_keyring_references() == {
            "hash": ["old-hash"],
            "license": ["old-license"],
            "encryption": ["old-encryption"],
        }

    manager.restore(
        inspection.path,
        restored_path,
        database_validator=restored_validator,
    )

    def restored_connect() -> sqlite3.Connection:
        conn = sqlite3.connect(restored_path)
        conn.row_factory = sqlite3.Row
        return conn

    rotated = LicenseService(
        restored_connect,
        hash_secret="new-hash-secret-used-for-current-writes",
        hash_secret_id="new-hash",
        key_secret="new-license-secret-used-for-current-writes",
        key_secret_id="new-license",
        encryption_secret="new-encryption-secret-used-for-current-writes",
        encryption_secret_id="new-encryption",
        historical_hash_secrets={"old-hash": old_hash},
        historical_key_secrets={"old-license": old_key},
        historical_encryption_secrets={"old-encryption": old_encryption},
    )
    assert rotated.resolve_credential(
        activation.credential.credential,
        install_id="71111111-1111-4111-8111-111111111111",
    )["license_id"] == license_record.license_id
    assert rotated.notification_email_for_license(license_record.license_id) == raw_email

    missing_history = LicenseService(
        restored_connect,
        hash_secret="new-hash-secret-used-for-current-writes",
        hash_secret_id="new-hash",
        key_secret="new-license-secret-used-for-current-writes",
        key_secret_id="new-license",
        encryption_secret="new-encryption-secret-used-for-current-writes",
        encryption_secret_id="new-encryption",
    )
    with pytest.raises(AccessConfigurationError, match="unavailable key IDs"):
        missing_history.verify_keyring_references()


def test_operator_search_paginates_over_six_hundred_and_csrf_protects_actions(
    licensed_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, _database = licensed_stack
    target_email = "Exact.Lookup+Pilot@Example.Test"
    target, _key, _ = service.fulfill_purchase(
        _purchase("operator-search-target", email=target_email)
    )
    for index in range(604):
        service.fulfill_purchase(_purchase(f"operator-pagination-{index:04d}"))

    seen: set[str] = set()
    cursor = ""
    page_count = 0
    while True:
        response = client.get(
            "/admin/api/access",
            headers=ADMIN_HOST,
            auth=ADMIN_AUTH,
            params={"limit": 200, "cursor": cursor},
        )
        assert response.status_code == 200
        payload = response.json()
        page_count += 1
        seen.update(item["license_id"] for item in payload["licenses"])
        cursor = payload["next_cursor"]
        if not cursor:
            break
    assert page_count == 4
    assert len(seen) == 605

    exact = client.post(
        "/admin/api/access/search",
        headers={
            **ADMIN_HOST,
            "origin": "https://network.beacontools.cc",
            "sec-fetch-site": "same-origin",
        },
        auth=ADMIN_AUTH,
        json={"q": " exact.lookup+pilot@example.test ", "source": "stripe", "state": "active"},
    )
    assert exact.status_code == 200
    assert [item["license_id"] for item in exact.json()["licenses"]] == [target.license_id]
    assert target_email.casefold() not in json.dumps(exact.json()).casefold()
    unsafe_get = client.get(
        "/admin/api/access",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        params={"q": target_email},
    )
    assert unsafe_get.status_code == 422
    assert unsafe_get.json()["detail"]["code"] == "secure_search_required"

    cross_site = client.post(
        f"/admin/api/access/{target.license_id}/action",
        headers={
            **ADMIN_HOST,
            "origin": "https://attacker.example",
            "sec-fetch-site": "cross-site",
        },
        auth=ADMIN_AUTH,
        json={"action": "suspend_license"},
    )
    assert cross_site.status_code == 403
    assert cross_site.json()["detail"]["code"] == "admin_csrf_rejected"

    same_origin = client.post(
        f"/admin/api/access/{target.license_id}/action",
        headers={
            **ADMIN_HOST,
            "origin": "https://network.beacontools.cc",
            "sec-fetch-site": "same-origin",
        },
        auth=ADMIN_AUTH,
        json={"action": "suspend_license"},
    )
    assert same_origin.status_code == 200
    assert same_origin.json()["license"]["status"] == "suspended"


def test_operator_retries_notifications_reconciliation_and_resolves_events(
    licensed_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, _database = licensed_stack
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    purchase = _purchase(
        "operator-google-reconciliation-token",
        provider="google_play_product",
        email="operator-notify@example.test",
    )
    license_record, _key, _ = service.fulfill_purchase(purchase)

    magic = service.request_magic_link("operator-notify@example.test")
    assert magic is not None
    service.queue_magic_link_notification(magic)
    [claimed] = service.claim_due_notifications(limit=1)
    service.finish_notification(
        claimed["notification_id"],
        sent=False,
        detail_code="smtp_timeout",
    )
    retry_notice = client.post(
        f"/admin/api/access/{license_record.license_id}/action",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={"action": "retry_notifications"},
    )
    assert retry_notice.status_code == 200
    assert retry_notice.json()["retried"] == 1
    assert service.admin_notification_snapshot()[0]["status"] == "sent"
    assert [message for message in mailer.messages if message["kind"] == "magic_link"]

    monkeypatch.setattr(relay_main, "_process_provider_operations", lambda **_kwargs: 0)
    reconciliation = client.post(
        f"/admin/api/access/{license_record.license_id}/action",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={"action": "retry_reconciliation"},
    )
    assert reconciliation.status_code == 200
    assert reconciliation.json()["queued"] is True
    assert len(reconciliation.json()["operation_ref"]) == 16

    event_id = "operator-unresolved-provider-event"
    assert service.begin_purchase_event("google_play", event_id, "rtdn") is True
    service.finish_purchase_event(
        "google_play",
        event_id,
        status="reconciliation_required",
        detail_code="unlinked_purchase_event",
    )
    event = service.admin_purchase_events()[0]
    resolved = client.post(
        f"/admin/api/access/events/{event['event_ref']}/action",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={"action": "mark_resolved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "processed"
    rendered = json.dumps(
        client.get("/admin/api/access", headers=ADMIN_HOST, auth=ADMIN_AUTH).json()
    )
    for secret in (
        "operator-google-reconciliation-token",
        "operator-notify@example.test",
        event_id,
        magic.token,
    ):
        assert secret not in rendered


def test_retry_limits_stop_automatic_email_reclaims(licensed_stack) -> None:
    _client, service, database = licensed_stack
    license_record, _key, _ = service.fulfill_purchase(
        _purchase("bounded-license-email", email="bounded@example.test")
    )
    service.queue_license_email(license_record.license_id, purpose="bounded-test")

    magic = service.request_magic_link("bounded@example.test")
    assert magic is not None
    service.queue_magic_link_notification(magic)

    for claim, finish in (
        (service.claim_due_license_emails, service.finish_license_email),
        (service.claim_due_notifications, service.finish_notification),
    ):
        for attempt in range(8):
            [item] = claim(limit=1)
            record_id = item.get("delivery_id") or item.get("notification_id")
            finish(record_id, sent=False, detail_code="deliberate_failure")
            if attempt < 7:
                with sqlite3.connect(database) as conn:
                    table = "license_deliveries" if "delivery_id" in item else "notification_outbox"
                    id_column = "delivery_id" if "delivery_id" in item else "notification_id"
                    conn.execute(
                        f"UPDATE {table} SET next_attempt_at=? WHERE {id_column}=?",
                        (service.now(), record_id),
                    )
        assert claim(limit=1) == []


def test_operator_cannot_override_suspended_purchase_authority(licensed_stack) -> None:
    _client, service, _database = licensed_stack
    license_record, _key, _ = service.fulfill_purchase(_purchase("authority-suspended"))
    service.update_purchase_state(
        "stripe",
        "authority-suspended",
        "suspended",
        reason="payment_review",
    )
    with pytest.raises(LicenseInactive, match="purchase authority must be active"):
        service.admin_set_license_status(license_record.license_id, "active")


def test_stale_backup_is_not_reported_healthy(
    licensed_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, _service, _database = licensed_stack
    fake_manager = SimpleNamespace(
        latest_backup=lambda: Path("stale.lfrbak"),
        inspect=lambda _path, verify_database=True: SimpleNamespace(
            created_at="2000-01-01T00:00:00+00:00",
            key_id="predeploy-backup-v1",
        ),
    )
    monkeypatch.setattr(relay_main, "_access_backup_manager", lambda: fake_manager)
    health = relay_main._access_backup_health()
    assert health["healthy"] is False
    assert health["detail_code"] == "backup_stale"
