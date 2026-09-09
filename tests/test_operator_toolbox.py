from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from relay.access.service import LicenseService
from relay.access.schema import ACCESS_SCHEMA_VERSION, ensure_access_schema
from relay.access.models import (
    InvalidChallenge,
    LicenseInactive,
    VerifiedPurchase,
    PurchaseEnvironmentMismatch,
)


@pytest.fixture
def service(tmp_path):
    def connect():
        conn = sqlite3.connect(tmp_path / "toolbox.db", timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        ensure_access_schema(conn)
    return LicenseService(
        connect,
        hash_secret="fake-toolbox-hash-secret-0000001",
        key_secret="fake-toolbox-key-secret-00000002",
        encryption_secret="fake-toolbox-encryption-secret-03",
        deployment_environment="staging",
    )


def notice_payloads(service, purpose):
    with service._operator_connection() as conn:
        return [
            json.loads(
                service._open(
                    row["encryption_key_id"],
                    "notification-payload",
                    row["payload_ciphertext"],
                )
            )
            for row in conn.execute(
                "SELECT * FROM notification_outbox WHERE purpose=? ORDER BY rowid",
                (purpose,),
            )
        ]


def issue(service, *, expires_at=None, request_id="fake-issue-request-001"):
    return service.issue_operator_grant(
        kind="test",
        email="owner@example.test",
        reason="Fake test grant",
        request_id=request_id,
        expires_at=expires_at,
    )


def claimed(service):
    grant = issue(service)
    token = notice_payloads(service, "operator:invitation")[-1]["token"]
    result = service.claim_operator_invitation(token)
    with service._operator_connection() as conn:
        key = service._license_key_for_row(
            service._license_row(conn, result["license_id"])
        )
    return grant, result["license_id"], key


def test_operator_invitation_is_explicit_idempotent_and_not_a_purchase(service):
    first = issue(service)
    assert issue(service) == first
    assert first["recipient"] == "o***@example.test"
    token = notice_payloads(service, "operator:invitation")[0]["token"]
    assert (
        service.inspect_operator_confirmation(token, kind="invitation")["grant_kind"]
        == "test"
    )
    with service._operator_connection() as conn:
        assert conn.execute("SELECT count(*) FROM relay_licenses").fetchone()[0] == 0
    result = service.claim_operator_invitation(token)
    assert "license_key" not in result
    with service._operator_connection() as conn:
        assert conn.execute("SELECT count(*) FROM purchase_records").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM relay_licenses").fetchone()[0] == 1
    with pytest.raises(InvalidChallenge):
        service.claim_operator_invitation(token)


def test_operator_environment_boundary_and_expiry(service):
    grant, license_id, key = claimed(service)
    activation = service.activate(
        install_id="fake-install",
        device_kind="desktop",
        device_name="Test",
        license_key=key,
    )
    assert (
        service.resolve_credential(activation.credential.credential)[
            "purchase_environment"
        ]
        == "test"
    )
    service.deployment_environment = "production"
    with pytest.raises(PurchaseEnvironmentMismatch):
        service.resolve_credential(activation.credential.credential)
    service.deployment_environment = "staging"
    with service._operator_connection() as conn:
        conn.execute(
            "UPDATE operator_grants SET expires_at=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )
    with pytest.raises(LicenseInactive, match="expired"):
        service.activate(
            install_id="fake-other",
            device_kind="desktop",
            device_name="Other",
            license_key=key,
        )
    with pytest.raises(LicenseInactive):
        service.resolve_credential(activation.credential.credential)
    assert service.expire_operator_grants() == 1
    service.operator_grant_action(
        grant["grant_id"],
        action="renew",
        reason="Renew fake test",
        request_id="fake-renew-request-001",
    )
    assert service.authority(license_id)["effective_state"] == "active"
    with pytest.raises(LicenseInactive):
        service.resolve_credential(activation.credential.credential)


def test_operator_resend_keeps_key_and_receiver(service):
    _, license_id, key = claimed(service)
    activation = service.activate(
        install_id="fake-install",
        device_kind="desktop",
        device_name="Test",
        license_key=key,
    )
    old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with service._operator_connection() as conn:
        conn.execute(
            "UPDATE license_deliveries SET status='sent',created_at=?,next_attempt_at=NULL",
            (old,),
        )
    kwargs = dict(
        action="resend_key_email",
        reason="Requested copy",
        request_id="fake-resend-request-001",
    )
    result = service.operator_license_action(license_id, **kwargs)
    assert result["queued"]
    assert service.operator_license_action(license_id, **kwargs) == result
    assert service.resolve_credential(activation.credential.credential)
    with service._operator_connection() as conn:
        assert (
            service._license_key_for_row(service._license_row(conn, license_id)) == key
        )
        assert (
            conn.execute("SELECT count(*) FROM license_deliveries").fetchone()[0] == 2
        )


def test_operator_recovery_is_scoped_and_never_reveals_or_rotates(service):
    _, license_id, key = claimed(service)
    service.operator_license_action(
        license_id,
        action="send_recovery_link",
        reason="Recovery test",
        request_id="fake-scoped-recovery",
    )
    token = notice_payloads(service, "magic_link:operator_recovery")[-1]["token"]
    with service._operator_connection() as conn:
        count = conn.execute("SELECT count(*) FROM license_deliveries").fetchone()[0]
    session = service.exchange_magic_link(token)
    assert not session.license_key
    with service._operator_connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM license_deliveries").fetchone()[0]
            == count
        )
        assert (
            service._license_key_for_row(service._license_row(conn, license_id)) == key
        )


def test_version_eight_upgrade_preserves_purchase_and_encrypted_records(service):
    purchased, key, _ = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="fake-migration-purchase",
            product_id="fake-product",
            email="legacy@example.test",
        )
    )
    with service._operator_connection() as conn:
        holder_before = tuple(conn.execute("SELECT * FROM license_holders").fetchone())
        for table in (
            "operator_grants",
            "operator_audit",
            "operator_notes",
            "email_change_requests",
            "mail_attempts",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DROP INDEX idx_notification_operator_subject")
        conn.execute("ALTER TABLE notification_outbox DROP COLUMN subject_ref")
        conn.execute("DELETE FROM relay_access_schema_migrations WHERE version=8")
        ensure_access_schema(conn)
        ensure_access_schema(conn)
        assert (
            conn.execute(
                "SELECT MAX(version) FROM relay_access_schema_migrations"
            ).fetchone()[0]
            == ACCESS_SCHEMA_VERSION
        )
        assert (
            tuple(conn.execute("SELECT * FROM license_holders").fetchone())
            == holder_before
        )
        assert (
            service._license_key_for_row(
                service._license_row(conn, purchased.license_id)
            )
            == key
        )
    service.verify_keyring_references()


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_email_change_needs_both_addresses_and_preserves_other_licenses(service, order):
    _, license_id, key = claimed(service)
    other, _, _ = service.fulfill_purchase(
        VerifiedPurchase(
            provider="stripe",
            external_id="fake-other-purchase",
            product_id="fake-product",
            email="owner@example.test",
        )
    )
    activation = service.activate(
        install_id="fake-install",
        device_kind="desktop",
        device_name="Test",
        license_key=key,
    )
    service.operator_license_action(
        license_id,
        action="start_email_change",
        email="replacement@example.test",
        reason="Owner request",
        request_id="fake-email-request-001",
    )
    tokens = [
        item["token"] for item in notice_payloads(service, "operator:email_change")
    ]
    assert service.inspect_operator_confirmation(tokens[0], kind="email_change")[
        "disconnects_receiver"
    ]
    assert (
        service.confirm_operator_email_change(tokens[order[0]])["status"]
        == "awaiting_other_address"
    )
    assert service.resolve_credential(activation.credential.credential)
    assert (
        service.confirm_operator_email_change(tokens[order[1]])["status"] == "completed"
    )
    with pytest.raises(LicenseInactive):
        service.resolve_credential(activation.credential.credential)
    with service._operator_connection() as conn:
        row = service._license_row(conn, license_id)
        assert (
            row["holder_id"]
            != service._license_row(conn, other.license_id)["holder_id"]
        )
        assert (
            service._holder_email_conn(conn, row["holder_id"])
            == "replacement@example.test"
        )
        assert service._license_key_for_row(row) != key


def test_concurrent_claim_produces_one_license(service):
    issue(service)
    token = notice_payloads(service, "operator:invitation")[0]["token"]

    def claim():
        try:
            return service.claim_operator_invitation(token)["ok"]
        except InvalidChallenge:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]


def test_concurrent_email_approvals_rotate_exactly_once(service):
    _, license_id, _ = claimed(service)
    service.operator_license_action(
        license_id,
        action="start_email_change",
        email="concurrent@example.test",
        reason="Concurrent mailbox approvals",
        request_id="fake-concurrent-change",
    )
    tokens = [p["token"] for p in notice_payloads(service, "operator:email_change")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(service.confirm_operator_email_change, tokens))
    assert sorted(o["status"] for o in outcomes) == [
        "awaiting_other_address",
        "completed",
    ]
    with service._operator_connection() as conn:
        assert service._license_row(conn, license_id)["key_version"] == 2
    for token in tokens:
        with pytest.raises(InvalidChallenge):
            service.confirm_operator_email_change(token)


def test_production_complimentary_authority_is_not_a_purchase(service):
    service.deployment_environment = "production"
    grant = service.issue_operator_grant(
        kind="complimentary",
        email="complimentary@example.test",
        reason="Production grant fixture",
        request_id="fake-production-comp",
        expires_at=None,
    )
    token = notice_payloads(service, "operator:invitation")[0]["token"]
    license_id = service.claim_operator_invitation(token)["license_id"]
    authority = service.authority(license_id)
    assert (
        authority["source"] == "operator_complimentary"
        and authority["environment"] == "production"
    )
    assert (
        authority["expires_at"] is None and authority["grant_id"] == grant["grant_id"]
    )
    with service._operator_connection() as conn:
        assert conn.execute("SELECT count(*) FROM purchase_records").fetchone()[0] == 0


def test_new_key_references_are_checked(service):
    issue(service)
    assert service.verify_keyring_references()["encryption"] == ["v1"]
    with service._operator_connection() as conn:
        conn.execute("UPDATE operator_grants SET encryption_key_id='fake-missing'")
    with pytest.raises(Exception, match="unavailable key IDs"):
        service.verify_keyring_references()


def test_invitation_expiry_and_revocation_cannot_be_claimed(service):
    grant = issue(service)
    token = notice_payloads(service, "operator:invitation")[0]["token"]
    with service._operator_connection() as conn:
        conn.execute(
            "UPDATE access_challenges SET expires_at='2000-01-01T00:00:00+00:00' WHERE purpose='operator_claim'"
        )
    with pytest.raises(InvalidChallenge):
        service.claim_operator_invitation(token)
    service.operator_grant_action(
        grant["grant_id"],
        action="renew",
        reason="Renew expired invitation",
        request_id="fake-renew-invitation",
    )
    next_token = notice_payloads(service, "operator:invitation")[-1]["token"]
    assert next_token != token
    service.operator_grant_action(
        grant["grant_id"],
        action="revoke",
        reason="Withdraw offer",
        request_id="fake-revoke-invitation",
    )
    with pytest.raises(InvalidChallenge):
        service.claim_operator_invitation(next_token)


def test_cancelled_and_stale_email_changes_cannot_complete(service):
    _, license_id, key = claimed(service)
    service.operator_license_action(
        license_id,
        action="start_email_change",
        email="new@example.test",
        reason="Test change",
        request_id="fake-email-change-stale",
    )
    tokens = [p["token"] for p in notice_payloads(service, "operator:email_change")]
    service.confirm_operator_email_change(tokens[0])
    service.operator_license_action(
        license_id,
        action="cancel_email_change",
        reason="Cancel test change",
        request_id="fake-email-change-cancel",
    )
    with pytest.raises(InvalidChallenge):
        service.confirm_operator_email_change(tokens[1])
    with service._operator_connection() as conn:
        assert (
            service._license_key_for_row(service._license_row(conn, license_id)) == key
        )
    service.operator_license_action(
        license_id,
        action="start_email_change",
        email="another@example.test",
        reason="New test change",
        request_id="fake-email-change-later",
    )
    tokens = [p["token"] for p in notice_payloads(service, "operator:email_change")][
        -2:
    ]
    service.operator_license_action(
        license_id,
        action="rotate_key",
        reason="Superseding rotation",
        request_id="fake-change-rotate",
    )
    for token in tokens:
        with pytest.raises(InvalidChallenge):
            service.confirm_operator_email_change(token)


def test_grant_authority_notes_and_pending_confirmations_restore_with_historical_keys(
    service, tmp_path
):
    from relay.access.backup import AccessBackupManager

    _, license_id, key = claimed(service)
    service.operator_license_action(
        license_id,
        action="add_note",
        reason="Test record",
        note="Retain this support note",
        request_id="fake-backup-note",
    )
    service.operator_license_action(
        license_id,
        action="start_email_change",
        reason="Pending backup test",
        email="new@example.test",
        request_id="fake-backup-change",
    )
    tokens = [p["token"] for p in notice_payloads(service, "operator:email_change")]
    backup = AccessBackupManager(
        database_path=tmp_path / "toolbox.db",
        backup_directory=tmp_path / "backup",
        active_key_id="backup-old",
        active_secret="fake-old-backup-key-that-is-long-enough",
    )
    snapshot = backup.create_backup()
    rotated = AccessBackupManager(
        database_path=tmp_path / "toolbox.db",
        backup_directory=tmp_path / "backup",
        active_key_id="backup-new",
        active_secret="fake-new-backup-key-that-is-long-enough",
        historical_secrets={"backup-old": "fake-old-backup-key-that-is-long-enough"},
    )
    destination = tmp_path / "restored.db"
    rotated.restore(snapshot.path, destination)

    def connect():
        conn = sqlite3.connect(destination)
        conn.row_factory = sqlite3.Row
        return conn

    restored = LicenseService(
        connect,
        hash_secret="fake-new-hash-secret-for-backup",
        key_secret="fake-new-key-secret-for-backup",
        encryption_secret="fake-new-encryption-for-backup",
        hash_secret_id="new",
        key_secret_id="new",
        encryption_secret_id="new",
        historical_hash_secrets={"v1": "fake-toolbox-hash-secret-0000001"},
        historical_key_secrets={"v1": "fake-toolbox-key-secret-00000002"},
        historical_encryption_secrets={"v1": "fake-toolbox-encryption-secret-03"},
        deployment_environment="staging",
    )
    restored.verify_keyring_references()
    assert (
        restored.operator_license_support(license_id)["notes"][0]["text"]
        == "Retain this support note"
    )
    assert restored.authority(license_id)["source"] == "operator_test"
    assert (
        restored.confirm_operator_email_change(tokens[1])["status"]
        == "awaiting_other_address"
    )
    assert restored.confirm_operator_email_change(tokens[0])["status"] == "completed"
    with restored._operator_connection() as conn:
        assert (
            restored._license_key_for_row(restored._license_row(conn, license_id))
            != key
        )
