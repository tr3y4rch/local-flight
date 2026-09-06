from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import relay.main as relay_main
from relay.access import VerifiedPurchase
from relay.access.adapters import (
    FakePurchaseVerifier,
    SmtpLicenseMailer,
    StripeAdapter,
    StripeCheckout,
)


PRODUCT_CODE = "beacon_relay_lifetime_v1"
STORE_PRODUCT = "cc.beacontools.localflight.paid-app"
GOOGLE_RELAY_PRODUCT = "cc.beacontools.localflight.relay_access"
STRIPE_PRICE = "price_relay_e2e"
STRIPE_WEBHOOK_SECRET = "whsec_local_relay_access_e2e"


@dataclass
class LocalSmtpTransport:
    """In-process SMTP boundary: exercise message construction without a socket."""

    messages: list[EmailMessage] = field(default_factory=list)
    failures_remaining: int = 0
    connections: int = 0

    def connect(self, *_args: Any, **_kwargs: Any) -> "LocalSmtpSession":
        self.connections += 1
        return LocalSmtpSession(self)


class LocalSmtpSession:
    def __init__(self, transport: LocalSmtpTransport) -> None:
        self.transport = transport

    def __enter__(self) -> "LocalSmtpSession":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        if self.transport.failures_remaining:
            self.transport.failures_remaining -= 1
            raise TimeoutError("local SMTP timeout")
        self.transport.messages.append(message)


class LocalStripeAdapter(StripeAdapter):
    """Use Stripe's real signature parser while keeping Checkout entirely local."""

    def __init__(self) -> None:
        super().__init__(
            api_key="sk_test_local_only",
            webhook_secret=STRIPE_WEBHOOK_SECRET,
            price_id=STRIPE_PRICE,
        )
        self.session_ids: dict[str, str] = {}
        self.parse_error = ""

    def create_checkout(
        self,
        *,
        checkout_ref: str,
        success_url: str,
        cancel_url: str,
    ) -> StripeCheckout:
        assert success_url.startswith("https://beacontools.cc/")
        assert cancel_url.startswith("https://beacontools.cc/")
        session_id = f"cs_test_{checkout_ref}"
        self.session_ids[checkout_ref] = session_id
        return StripeCheckout(
            checkout_ref=checkout_ref,
            session_id=session_id,
            url=f"https://checkout.stripe.test/{checkout_ref}",
        )

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            return super().parse_webhook(payload, signature)
        except Exception as exc:
            self.parse_error = f"{exc.__class__.__name__}: {exc}"
            raise


@dataclass
class AccessHarness:
    client: TestClient
    database: Path
    smtp: LocalSmtpTransport
    stripe: LocalStripeAdapter


@pytest.fixture()
def access_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccessHarness:
    database = tmp_path / "relay-access-fulfillment-e2e.db"
    settings = {
        "DB_PATH": str(database),
        "RELAY_ACCESS_MODE": "licensed",
        "RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT": "staging",
        "RELAY_ACCESS_PRODUCT_CODE": PRODUCT_CODE,
        "RELAY_ACCESS_HASH_SECRET": "e2e-hash-secret-that-never-leaves-this-test",
        "RELAY_ACCESS_KEY_SECRET": "e2e-key-secret-that-is-distinct-and-local",
        "RELAY_ACCESS_ENCRYPTION_SECRET": "e2e-encryption-secret-that-is-distinct-and-local",
        "RELAY_ACCESS_HASH_SECRET_ID": "test-hash-v1",
        "RELAY_ACCESS_KEY_SECRET_ID": "test-v1",
        "RELAY_ACCESS_ENCRYPTION_SECRET_ID": "test-encryption-v1",
        "RELAY_ACCESS_SITE_URL": "https://beacontools.cc",
        "RELAY_ACCESS_SALES_ENABLED": "1",
        "RELAY_ACCESS_SCHEDULE_ENABLED": "1",
        "RELAY_ACCESS_AERODATABOX_ENABLED": "1",
        "RELAY_ACCESS_AVIATIONSTACK_ENABLED": "1",
        "RELAY_ACCESS_RADAR_ENABLED": "1",
        "RELAY_ACCESS_ADSBEXCHANGE_ENABLED": "1",
        "RELAY_ACCESS_REMOTE_COMPANION_ENABLED": "1",
        "RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED": "1",
        "RELAY_ACCESS_IOS_STATE": "testing",
        "RELAY_ACCESS_ANDROID_STATE": "testing",
        "STRIPE_SECRET_KEY": "sk_test_local_only",
        "STRIPE_WEBHOOK_SECRET": STRIPE_WEBHOOK_SECRET,
        "STRIPE_RELAY_ACCESS_PRICE_ID": STRIPE_PRICE,
        "GOOGLE_RELAY_ACCESS_PRODUCT_ID": GOOGLE_RELAY_PRODUCT,
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    smtp = LocalSmtpTransport()
    monkeypatch.setattr("relay.access.adapters.smtplib.SMTP", smtp.connect)
    mailer = SmtpLicenseMailer(
        host="smtp.local.test",
        port=2525,
        sender="licenses@beacontools.test",
        security="none",
    )
    stripe = LocalStripeAdapter()
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    monkeypatch.setattr(relay_main, "_stripe_adapter", lambda: stripe)
    # Store verifier cryptography has dedicated tests. This suite exercises the
    # common routed boundary after each native verifier has authenticated proof.
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    relay_main._ensure_schema()
    return AccessHarness(
        client=TestClient(relay_main.app),
        database=database,
        smtp=smtp,
        stripe=stripe,
    )


def _stripe_signature(payload: bytes) -> str:
    timestamp = int(time.time())
    digest = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _post_stripe_event(client: TestClient, event: dict[str, Any]):
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    return client.post(
        "/v1/access/stripe/webhook",
        content=payload,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature(payload),
        },
    )


def _stripe_checkout_event(
    *,
    event_id: str,
    checkout_ref: str,
    session_id: str,
    payment_id: str,
    email: str,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "livemode": False,
                "payment_status": "paid",
                "payment_intent": payment_id,
                "metadata": {"checkout_ref": checkout_ref},
                "customer_details": {"email": email},
            }
        },
    }


def _checkout(harness: AccessHarness, *, payment_id: str, event_id: str, email: str) -> dict[str, Any]:
    created = harness.client.post("/v1/access/stripe/checkout", json={})
    assert created.status_code == 200, created.text
    checkout = created.json()
    assert checkout["checkout_url"].startswith("https://checkout.stripe.test/")
    event = _stripe_checkout_event(
        event_id=event_id,
        checkout_ref=checkout["checkout_ref"],
        session_id=harness.stripe.session_ids[checkout["checkout_ref"]],
        payment_id=payment_id,
        email=email,
    )
    fulfilled = _post_stripe_event(harness.client, event)
    assert fulfilled.status_code == 200, f"{fulfilled.text} ({harness.stripe.parse_error})"
    assert fulfilled.json() == {"ok": True, "duplicate": False}
    return {**checkout, "event": event}


def _email_messages(transport: LocalSmtpTransport, subject: str) -> list[EmailMessage]:
    return [item for item in transport.messages if str(item["Subject"]) == subject]


def _protect_mobile_license(
    harness: AccessHarness,
    *,
    delivery_claim: str,
    email: str,
) -> tuple[str, str]:
    requested = harness.client.post(
        "/v1/access/magic-links/request",
        headers={"Authorization": f"Bearer {delivery_claim}"},
        json={"email": email, "purpose": "protect_and_transfer"},
    )
    assert requested.status_code == 202
    magic = _email_messages(harness.smtp, "Your Beacon Relay Access link")[-1]
    magic_body = magic.get_content()
    magic_url = next(line for line in magic_body.splitlines() if "#token=" in line)
    assert "?token=" not in magic_url
    magic_token = magic_url.split("#token=", 1)[1]
    exchanged = harness.client.post(
        "/v1/access/magic-links/exchange",
        json={"token": magic_token},
    )
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.headers["cache-control"] == "no-store"
    key = exchanged.json()["license_key"]
    assert key.startswith("LFRA-")
    delivered = _email_messages(harness.smtp, "Your Beacon Relay Access license")[-1]
    assert delivered["To"] == email
    assert f"License key: {key}" in delivered.get_content()
    return key, magic_token


def _verify_mobile_purchase(
    harness: AccessHarness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    platform: str,
    provider: str,
    external_id: str,
    proof: str,
    install_id: str,
) -> dict[str, Any]:
    verified = VerifiedPurchase(
        provider=provider,
        external_id=external_id,
        product_id=GOOGLE_RELAY_PRODUCT if platform == "android" else STORE_PRODUCT,
        environment="test",
        state="paid",
        evidence_hash=hashlib.sha256(proof.encode("utf-8")).hexdigest(),
        verified_at_ms=int(time.time() * 1000),
        identity_kind="google_play_purchase_token" if platform == "android" else "apple_app_transaction_id",
        reconciliation_mode="server_authoritative" if platform == "android" else "device_only",
        reconciliation_handle=external_id if platform == "android" else "",
        acknowledgement_state="acknowledged" if platform == "android" else "",
    )
    verifier = FakePurchaseVerifier(verified)
    if platform == "ios":
        monkeypatch.setattr(relay_main, "_apple_paid_app_verifier", lambda: verifier)
        proof_fields = {"signed_app_transaction": proof}
        intent = "companion"
    else:
        monkeypatch.setattr(relay_main, "_google_play_product_verifier", lambda: verifier)
        proof_fields = {
            "google_play_purchase_token": external_id,
            "google_play_product_id": GOOGLE_RELAY_PRODUCT,
        }
        intent = "standalone"
    challenge = harness.client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": platform, "install_id": install_id, "intent": intent},
    )
    assert challenge.status_code == 200, challenge.text
    response = harness.client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": platform,
            "install_id": install_id,
            "intent": intent,
            "nonce": challenge.json()["nonce"],
            **proof_fields,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True
    assert body["activated"] is False
    assert body.get("seat_state", body.get("included_seat_state")) == "available"
    assert body["license"]["product_code"] == PRODUCT_CODE
    assert body["license"]["purchase_source"] == provider
    assert body["delivery_claim"].startswith("lfrclaim_")
    assert "license_key" not in body

    replay_challenge = harness.client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": platform, "install_id": install_id, "intent": intent},
    )
    assert replay_challenge.status_code == 200
    replayed = harness.client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": platform,
            "install_id": install_id,
            "intent": intent,
            "nonce": replay_challenge.json()["nonce"],
            **proof_fields,
        },
    )
    assert replayed.status_code == 200, replayed.text
    replayed_body = replayed.json()
    assert replayed_body["license"]["license_ref"] == body["license"]["license_ref"]
    # Issuing a fresh claim deliberately retires the older bearer claim.
    assert replayed_body["delivery_claim"] != body["delivery_claim"]
    return {**replayed_body, "proof_fields": proof_fields}


def test_stripe_ios_entitlement_and_google_product_create_portable_distinct_licenses(
    access_harness: AccessHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = access_harness
    stripe_email = "stripe-pilot@example.test"
    stripe_payment = "pi_raw_stripe_purchase_must_not_persist"
    stripe_event = "evt_raw_stripe_event_must_not_persist"

    # Webhook fulfillment only queues delivery, so SMTP latency or failure cannot
    # delay Stripe's acknowledgement. The durable outbox sends and retries the key.
    harness.smtp.failures_remaining = 1
    first = _checkout(
        harness,
        payment_id=stripe_payment,
        event_id=stripe_event,
        email=stripe_email,
    )
    service = relay_main._license_service()
    queued = service.admin_delivery_snapshot()
    assert len(queued) == 1
    assert queued[0]["status"] == "pending"
    assert queued[0]["attempt_count"] == 0
    assert relay_main._deliver_pending_license_emails(limit=1) == 0
    failed = service.admin_delivery_snapshot()
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert failed[0]["attempt_count"] == 1
    conn = sqlite3.connect(harness.database)
    try:
        conn.execute(
            "UPDATE license_deliveries SET next_attempt_at=? WHERE delivery_id=?",
            ("2000-01-01T00:00:00+00:00", failed[0]["delivery_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    assert relay_main._deliver_pending_license_emails(limit=10) == 1
    assert service.admin_delivery_snapshot()[0]["status"] == "sent"

    revealed = harness.client.post(
        "/v1/access/stripe/result",
        json={
            "checkout_ref": first["checkout_ref"],
            "result_secret": first["result_secret"],
        },
    )
    assert revealed.status_code == 200
    stripe_key = revealed.json()["license_key"]
    assert stripe_key.startswith("LFRA-")
    assert f"License key: {stripe_key}" in _email_messages(
        harness.smtp, "Your Beacon Relay Access license"
    )[-1].get_content()
    repeated_result = harness.client.post(
        "/v1/access/stripe/result",
        json={
            "checkout_ref": first["checkout_ref"],
            "result_secret": first["result_secret"],
        },
    )
    assert repeated_result.status_code == 200
    assert "license_key" not in repeated_result.json()

    duplicate_event = _post_stripe_event(harness.client, first["event"])
    assert duplicate_event.status_code == 200
    assert duplicate_event.json() == {"ok": True, "duplicate": True}

    # A genuinely separate purchase is never merged into the first license.
    second = _checkout(
        harness,
        payment_id="pi_second_distinct_purchase",
        event_id="evt_second_distinct_purchase",
        email=stripe_email,
    )
    second_result = harness.client.post(
        "/v1/access/stripe/result",
        json={
            "checkout_ref": second["checkout_ref"],
            "result_secret": second["result_secret"],
        },
    ).json()
    assert second_result["license"]["license_ref"] != revealed.json()["license"]["license_ref"]
    assert second_result["license_key"] != stripe_key
    assert relay_main._deliver_pending_license_emails(limit=10) == 1

    ios_install = "11111111-1111-4111-8111-111111111111"
    android_install = "22222222-2222-4222-8222-222222222222"
    apple_external = "apple-raw-app-transaction-must-not-persist"
    google_external = "google-raw-purchase-token-must-not-persist"
    apple_proof = "apple-jws-raw-proof-must-not-persist"
    google_proof = "google-developer-api-evidence-must-not-persist"
    apple_email = "apple-pilot@example.test"
    google_email = "google-pilot@example.test"
    apple = _verify_mobile_purchase(
        harness,
        monkeypatch,
        platform="ios",
        provider="apple_app",
        external_id=apple_external,
        proof=apple_proof,
        install_id=ios_install,
    )
    google = _verify_mobile_purchase(
        harness,
        monkeypatch,
        platform="android",
        provider="google_play_product",
        external_id=google_external,
        proof=google_proof,
        install_id=android_install,
    )
    apple_key, apple_magic = _protect_mobile_license(
        harness,
        delivery_claim=apple["delivery_claim"],
        email=apple_email,
    )
    google_key, google_magic = _protect_mobile_license(
        harness,
        delivery_claim=google["delivery_claim"],
        email=google_email,
    )

    # Store-created keys are the same portable LFRA format and activate through
    # the desktop-only public activation route.
    issued_credentials: list[str] = []
    for index, key in enumerate((stripe_key, apple_key, google_key), start=3):
        install_id = (
            f"{index}{index}{index}{index}{index}{index}{index}{index}-"
            f"{index}{index}{index}{index}-4{index}{index}{index}-8{index}{index}{index}-"
            f"{index}{index}{index}{index}{index}{index}{index}{index}{index}{index}{index}{index}"
        )
        activated = harness.client.post(
            "/v1/access/activate",
            json={
                "install_id": install_id,
                "device_kind": "desktop",
                "device_name": f"E2E desktop {index}",
                "license_key": key,
            },
        )
        assert activated.status_code == 200, activated.text
        credential = activated.json()["credential"]
        assert activated.json()["activation_state"] == "pending_commit"
        committed = harness.client.post(
            "/v1/access/activate/commit",
            headers={"authorization": f"Bearer {credential}"},
            json={"install_id": install_id},
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["activated"] is True
        issued_credentials.append(credential)

    conn = sqlite3.connect(harness.database)
    try:
        rows = conn.execute(
            "SELECT license_id, product_code, purchase_source, key_version "
            "FROM relay_licenses ORDER BY created_at"
        ).fetchall()
        assert len(rows) == 4
        assert {row[1] for row in rows} == {PRODUCT_CODE}
        assert {row[2] for row in rows} == {"stripe", "apple_app", "google_play_product"}
        assert len({row[0] for row in rows}) == 4
        assert {row[3] for row in rows} == {1}
        assert conn.execute("SELECT COUNT(*) FROM purchase_records").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM license_deliveries WHERE status='sent'").fetchone()[0] == 4
        database_dump = "\n".join(conn.iterdump())
    finally:
        conn.close()

    raw_secrets = [
        stripe_email,
        apple_email,
        google_email,
        stripe_payment,
        stripe_event,
        "pi_second_distinct_purchase",
        "evt_second_distinct_purchase",
        harness.stripe.session_ids[first["checkout_ref"]],
        harness.stripe.session_ids[second["checkout_ref"]],
        first["result_secret"],
        second["result_secret"],
        apple_external,
        google_external,
        apple_proof,
        google_proof,
        apple["delivery_claim"],
        google["delivery_claim"],
        apple_magic,
        google_magic,
        stripe_key,
        apple_key,
        google_key,
        *issued_credentials,
    ]
    for secret in raw_secrets:
        assert secret not in database_dump
    captured = capsys.readouterr()
    combined_logs = captured.out + captured.err + "\n".join(record.getMessage() for record in caplog.records)
    for secret in raw_secrets:
        assert secret not in combined_logs


@pytest.mark.parametrize(
    "support_product",
    [
        "cc.beacontools.localflight.support.small",
        "cc.beacontools.localflight.support.medium",
        "cc.beacontools.localflight.support.large",
    ],
)
def test_support_consumables_are_rejected_before_license_or_evidence_creation(
    access_harness: AccessHarness,
    monkeypatch: pytest.MonkeyPatch,
    support_product: str,
) -> None:
    harness = access_harness
    install_id = {
        "cc.beacontools.localflight.support.small": "55555555-5555-4555-8555-555555555555",
        "cc.beacontools.localflight.support.medium": "66666666-6666-4666-8666-666666666666",
        "cc.beacontools.localflight.support.large": "77777777-7777-4777-8777-777777777777",
    }[support_product]
    proof = f"raw-{support_product}-proof"
    verifier = FakePurchaseVerifier(
        VerifiedPurchase(
            provider="apple_app",
            external_id=f"raw-{support_product}-purchase",
            product_id=support_product,
            environment="test",
            evidence_hash=hashlib.sha256(proof.encode("utf-8")).hexdigest(),
            verified_at_ms=int(time.time() * 1000),
        )
    )
    monkeypatch.setattr(relay_main, "_apple_paid_app_verifier", lambda: verifier)
    challenge = harness.client.post(
        "/v1/access/mobile/attestation/challenge",
        json={"platform": "ios", "install_id": install_id, "intent": "inspect"},
    )
    assert challenge.status_code == 200
    rejected = harness.client.post(
        "/v1/access/mobile/attestation/verify",
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "inspect",
            "nonce": challenge.json()["nonce"],
            "signed_app_transaction": proof,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "invalid_challenge"

    conn = sqlite3.connect(harness.database)
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_licenses").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM purchase_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mobile_ownership_evidence").fetchone()[0] == 0
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    assert support_product not in dump
    assert proof not in dump
