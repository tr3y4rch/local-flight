from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import relay.main as relay_main
from relay.access import VerifiedPurchase
from relay.access.adapters import FakePurchaseVerifier, RecordingLicenseMailer, StripeCheckout
from relay.access.mobile_verifiers import PAID_APP_PRODUCT_ID


PUBLIC_HOST = {"host": "relay.beacontools.cc"}
ADMIN_HOST = {"host": "network.beacontools.cc"}
GOOGLE_RELAY_PRODUCT = "cc.beacontools.localflight.relay_access"


@dataclass
class DeterministicStripeAdapter:
    price_id: str = "price_route_e2e"
    sessions: dict[str, str] = field(default_factory=dict)

    def configured(self) -> bool:
        return True

    def create_checkout(self, *, checkout_ref: str, success_url: str, cancel_url: str) -> StripeCheckout:
        assert success_url.startswith("https://beacontools.cc/")
        assert cancel_url.startswith("https://beacontools.cc/")
        session_id = f"cs_test_{len(self.sessions) + 1}"
        self.sessions[checkout_ref] = session_id
        return StripeCheckout(
            checkout_ref=checkout_ref,
            session_id=session_id,
            url=f"https://checkout.stripe.test/{session_id}",
        )

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        if signature != "route-e2e-signature":
            raise ValueError("invalid signature")
        return json.loads(payload)


@pytest.fixture()
def access_stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay-access-routes.db"))
    monkeypatch.setenv("RELAY_PUBLIC_HOST", "relay.beacontools.cc")
    monkeypatch.setenv("RELAY_ADMIN_HOST", "network.beacontools.cc")
    monkeypatch.setenv("RELAY_ACCESS_MODE", "licensed")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET", "route-e2e-hash-secret-that-is-long-enough")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET", "route-e2e-key-secret-that-is-distinct")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET", "route-e2e-encryption-secret-that-is-distinct")
    monkeypatch.setenv("RELAY_ACCESS_HASH_SECRET_ID", "route-e2e-hash-v1")
    monkeypatch.setenv("RELAY_ACCESS_KEY_SECRET_ID", "route-e2e-v1")
    monkeypatch.setenv("RELAY_ACCESS_ENCRYPTION_SECRET_ID", "route-e2e-encryption-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_SECRET", "route-e2e-backup-secret-that-is-distinct")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_KEY_ID", "route-e2e-backup-v1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_DIRECTORY", str(tmp_path / "access-backups"))
    monkeypatch.setenv("RELAY_ACCESS_SITE_URL", "https://beacontools.cc")
    monkeypatch.setenv("RELAY_ACCESS_SALES_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_SCHEDULE_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_RADAR_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_REMOTE_COMPANION_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_AERODATABOX_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_AVIATIONSTACK_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_ADSBEXCHANGE_ENABLED", "1")
    monkeypatch.setenv("STRIPE_RELAY_ACCESS_PRICE_ID", "price_route_e2e")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_route_e2e")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_route_e2e")
    monkeypatch.setenv("GOOGLE_RELAY_ACCESS_PRODUCT_ID", GOOGLE_RELAY_PRODUCT)

    stripe = DeterministicStripeAdapter()
    mailer = RecordingLicenseMailer()
    monkeypatch.setattr(relay_main, "_stripe_adapter", lambda: stripe)
    monkeypatch.setattr(relay_main, "_license_mailer", lambda: mailer)
    relay_main._ensure_schema()
    return TestClient(relay_main.app), relay_main._license_service(), stripe, mailer


def _assert_private_response(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"


def _commit(client: TestClient, prepared, install_id: str):
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["activated"] is False
    assert prepared.json()["activation_state"] == "pending_commit"
    credential = prepared.json()["credential"]
    response = client.post(
        "/v1/access/activate/commit",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {credential}"},
        json={"install_id": install_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["activated"] is True
    return response


def _purchase(
    external_id: str,
    *,
    provider: str = "stripe",
    email: str = "pilot@example.test",
) -> VerifiedPurchase:
    return VerifiedPurchase(
        provider=provider,
        external_id=external_id,
        product_id=(
            "price_route_e2e"
            if provider == "stripe"
            else GOOGLE_RELAY_PRODUCT
            if provider == "google_play_product"
            else PAID_APP_PRODUCT_ID
        ),
        environment="production",
        state="paid",
        email=email,
        evidence_hash=hashlib.sha256(f"proof:{provider}:{external_id}".encode()).hexdigest(),
        verified_at_ms=int(time.time() * 1000),
    )


def test_access_route_manifest_host_split_cors_and_private_headers(access_stack) -> None:
    client, _service, _stripe, _mailer = access_stack
    registered = {
        (method, route.path)
        for route in relay_main.app.routes
        if route.path.startswith("/v1/access")
        for method in (route.methods or set())
    }
    assert registered == {
        ("GET", "/v1/access/catalog"),
        ("POST", "/v1/access/stripe/checkout"),
        ("POST", "/v1/access/stripe/result"),
        ("POST", "/v1/access/stripe/webhook"),
        ("POST", "/v1/access/activate"),
        ("POST", "/v1/access/activate/commit"),
        ("POST", "/v1/access/deactivate"),
        ("POST", "/v1/access/google/rtdn"),
        ("POST", "/v1/access/mobile/attestation/challenge"),
        ("POST", "/v1/access/mobile/attestation/verify"),
        ("POST", "/v1/access/magic-links/request"),
        ("POST", "/v1/access/magic-links/exchange"),
        ("POST", "/v1/access/activation-grants"),
        ("POST", "/v1/access/licenses/action"),
        ("GET", "/v1/access/status"),
    }

    catalog = client.get("/v1/access/catalog", headers=PUBLIC_HOST)
    assert catalog.status_code == 200
    assert catalog.json()["product"]["product_code"] == "beacon_relay_lifetime_v1"
    assert catalog.json()["product"]["desktop_routes"] == ["relay", "byok", "vatsim"]
    _assert_private_response(catalog)

    # Public access routes and operator routes cannot cross host surfaces.
    assert client.get("/v1/access/catalog", headers=ADMIN_HOST).status_code == 404
    assert client.get("/admin/api/access", headers=PUBLIC_HOST).status_code == 404
    assert client.get("/admin/api/access", headers=ADMIN_HOST).status_code == 401

    allowed = client.options(
        "/v1/access/catalog",
        headers={
            **PUBLIC_HOST,
            "origin": "https://beacontools.cc",
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization, content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://beacontools.cc"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    _assert_private_response(allowed)

    denied = client.options(
        "/v1/access/catalog",
        headers={
            **PUBLIC_HOST,
            "origin": "https://untrusted.example",
            "access-control-request-method": "GET",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    _assert_private_response(denied)


def test_every_access_path_is_live_and_never_cacheable(access_stack) -> None:
    client, _service, _stripe, _mailer = access_stack
    probes = [
        client.get("/v1/access/catalog", headers=PUBLIC_HOST),
        client.post("/v1/access/stripe/checkout", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/stripe/result", headers=PUBLIC_HOST, json={}),
        client.post(
            "/v1/access/stripe/webhook",
            headers={**PUBLIC_HOST, "stripe-signature": "wrong"},
            content=b"{}",
        ),
        client.post("/v1/access/activate", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/activate/commit", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/deactivate", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/google/rtdn", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/mobile/attestation/challenge", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/mobile/attestation/verify", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/magic-links/request", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/magic-links/exchange", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/activation-grants", headers=PUBLIC_HOST, json={}),
        client.post("/v1/access/licenses/action", headers=PUBLIC_HOST, json={}),
        client.get("/v1/access/status", headers=PUBLIC_HOST),
    ]
    assert [response.status_code for response in probes] == [
        200,
        200,
        422,
        400,
        422,
        422,
        422,
        401,
        422,
        422,
        422,
        422,
        422,
        422,
        401,
    ]
    for response in probes:
        _assert_private_response(response)


def test_stripe_checkout_webhook_result_recovery_and_email_are_one_flow(access_stack) -> None:
    client, _service, stripe, mailer = access_stack
    checkout = client.post("/v1/access/stripe/checkout", headers=PUBLIC_HOST, json={})
    assert checkout.status_code == 200
    checkout_body = checkout.json()
    assert checkout_body["checkout_url"].startswith("https://checkout.stripe.test/")
    assert checkout_body["result_secret"].startswith("lfrs_")

    pending = client.post(
        "/v1/access/stripe/result",
        headers=PUBLIC_HOST,
        json={
            "checkout_ref": checkout_body["checkout_ref"],
            "result_secret": checkout_body["result_secret"],
        },
    )
    assert pending.status_code == 200
    assert pending.json()["state"] == "pending"
    assert "license_key" not in pending.json()

    event = {
        "id": "evt_route_e2e_checkout",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": stripe.sessions[checkout_body["checkout_ref"]],
                "payment_intent": "pi_route_e2e_checkout",
                "payment_status": "paid",
                "livemode": True,
                "metadata": {"checkout_ref": checkout_body["checkout_ref"]},
                "customer_details": {"email": "pilot@example.test"},
            }
        },
    }
    webhook = client.post(
        "/v1/access/stripe/webhook",
        headers={**PUBLIC_HOST, "stripe-signature": "route-e2e-signature"},
        content=json.dumps(event).encode(),
    )
    assert webhook.status_code == 200
    assert webhook.json() == {"ok": True, "duplicate": False}
    sent_license = [message for message in mailer.messages if message["kind"] == "license"]
    assert len(sent_license) == 1
    assert sent_license[0]["email"] == "pilot@example.test"
    assert sent_license[0]["license_key"].startswith("LFRA-")

    fulfilled = client.post(
        "/v1/access/stripe/result",
        headers=PUBLIC_HOST,
        json={
            "checkout_ref": checkout_body["checkout_ref"],
            "result_secret": checkout_body["result_secret"],
        },
    )
    assert fulfilled.status_code == 200
    assert fulfilled.json()["state"] == "active"
    assert fulfilled.json()["license_key"] == sent_license[0]["license_key"]
    license_ref = fulfilled.json()["license"]["license_ref"]

    revealed_once = client.post(
        "/v1/access/stripe/result",
        headers=PUBLIC_HOST,
        json={
            "checkout_ref": checkout_body["checkout_ref"],
            "result_secret": checkout_body["result_secret"],
        },
    )
    assert revealed_once.status_code == 200
    assert revealed_once.json()["state"] == "active"
    assert "license_key" not in revealed_once.json()

    duplicate = client.post(
        "/v1/access/stripe/webhook",
        headers={**PUBLIC_HOST, "stripe-signature": "route-e2e-signature"},
        content=json.dumps(event).encode(),
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == {"ok": True, "duplicate": True}

    recovery = client.post(
        "/v1/access/magic-links/request",
        headers=PUBLIC_HOST,
        json={"email": "pilot@example.test", "purpose": "recovery"},
    )
    assert recovery.status_code == 202
    magic = [message for message in mailer.messages if message["kind"] == "magic_link"][-1]
    assert "#token=" in magic["url"]
    assert "?token=" not in magic["url"]
    holder = client.post(
        "/v1/access/magic-links/exchange",
        headers=PUBLIC_HOST,
        json={"token": magic["url"].split("#token=", 1)[1]},
    )
    assert holder.status_code == 200
    assert holder.json()["holder_session"].startswith("lfrhs_")
    assert [item["license_ref"] for item in holder.json()["licenses"]] == [license_ref]
    assert "license_key" not in holder.json()

    conn = relay_main._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_licenses").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM purchase_records").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM purchase_events").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("platform", "provider", "verifier_name"),
    [
        ("ios", "apple_app", "_apple_paid_app_verifier"),
        ("android", "google_play_product", "_google_play_product_verifier"),
    ],
)
def test_each_mobile_store_route_creates_portable_license_and_delivers_key_by_email(
    access_stack,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    provider: str,
    verifier_name: str,
) -> None:
    client, _service, _stripe, mailer = access_stack
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv(f"RELAY_ACCESS_{'IOS' if platform == 'ios' else 'ANDROID'}_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    verified = _purchase(f"{provider}-route-owner", provider=provider, email="")
    monkeypatch.setattr(relay_main, verifier_name, lambda: FakePurchaseVerifier(verified))

    install_id = "22222222-2222-4222-8222-222222222222"
    intent = "companion" if platform == "ios" else "standalone"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        headers=PUBLIC_HOST,
        json={"platform": platform, "install_id": install_id, "intent": intent},
    )
    assert challenge.status_code == 200
    proof = {
        "platform": platform,
        "install_id": install_id,
        "intent": intent,
        "nonce": challenge.json()["nonce"],
    }
    if platform == "ios":
        proof["signed_app_transaction"] = "signed-test-app-transaction"
    else:
        proof.update(
            {
                "google_play_purchase_token": "google-play-product-purchase-token",
                "google_play_product_id": GOOGLE_RELAY_PRODUCT,
            }
        )
    ownership = client.post(
        "/v1/access/mobile/attestation/verify",
        headers=PUBLIC_HOST,
        json=proof,
    )
    assert ownership.status_code == 200
    ownership_body = ownership.json()
    assert ownership_body["activated"] is False
    assert ownership_body["license"]["product_code"] == "beacon_relay_lifetime_v1"
    assert ownership_body["license"]["purchase_source"] == provider
    assert ownership_body["license"]["access_state"] == "active"
    assert ownership_body["license"]["reason_code"] == "license_active"
    assert ownership_body["delivery_claim"].startswith("lfrclaim_")
    if platform == "ios":
        assert ownership_body["seat_state"] == "available"
        assert "credential" not in ownership_body
    else:
        assert ownership_body["included_seat_state"] == "available"
        assert ownership_body["credential"].startswith("lfr_")
        assert ownership_body["activation_state"] == "pending_commit"
    assert "license_key" not in ownership_body

    protection = client.post(
        "/v1/access/magic-links/request",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {ownership_body['delivery_claim']}"},
        json={"email": f"{platform}-pilot@example.test", "purpose": "protect_and_transfer"},
    )
    assert protection.status_code == 202
    magic = [message for message in mailer.messages if message["kind"] == "magic_link"][-1]
    exchanged = client.post(
        "/v1/access/magic-links/exchange",
        headers=PUBLIC_HOST,
        json={"token": magic["url"].split("#token=", 1)[1]},
    )
    assert exchanged.status_code == 200
    delivered_key = exchanged.json()["license_key"]
    assert delivered_key.startswith("LFRA-")
    assert exchanged.json()["licenses"][0]["purchase_source"] == provider
    assert any(
        message["kind"] == "license"
        and message["email"] == f"{platform}-pilot@example.test"
        and message["license_key"] == delivered_key
        for message in mailer.messages
    )


def test_production_mobile_route_rejects_sandbox_purchase_proof(
    access_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _service, _stripe, _mailer = access_stack
    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_IOS_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    sandbox_purchase = VerifiedPurchase(
        provider="apple_app",
        external_id="sandbox-app-owner",
        product_id=PAID_APP_PRODUCT_ID,
        environment="sandbox",
        state="paid",
        evidence_hash=hashlib.sha256(b"sandbox-app-proof").hexdigest(),
        verified_at_ms=int(time.time() * 1000),
    )
    monkeypatch.setattr(
        relay_main,
        "_apple_paid_app_verifier",
        lambda: FakePurchaseVerifier(sandbox_purchase),
    )
    install_id = "92929292-9292-4292-8292-929292929292"
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        headers=PUBLIC_HOST,
        json={"platform": "ios", "install_id": install_id, "intent": "companion"},
    )
    assert challenge.status_code == 200

    response = client.post(
        "/v1/access/mobile/attestation/verify",
        headers=PUBLIC_HOST,
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "companion",
            "nonce": challenge.json()["nonce"],
            "signed_app_transaction": "sandbox-proof",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "purchase_environment_mismatch"
    conn = relay_main._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM relay_licenses").fetchone()[0] == 0
    finally:
        conn.close()


def test_desktop_activation_status_move_deactivate_and_error_contract(access_stack) -> None:
    client, service, _stripe, _mailer = access_stack
    _license, license_key, _ = service.fulfill_purchase(_purchase("desktop-route-lifecycle"))
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "33333333-3333-4333-8333-333333333333"

    unauthenticated = client.get("/v1/access/status", headers=PUBLIC_HOST)
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "relay_credential_required"

    malformed = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={"install_id": first_id, "device_kind": "desktop", "license_key": "not-a-key"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_license_key"

    mobile_on_generic = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={"install_id": first_id, "device_kind": "mobile_standalone", "license_key": license_key},
    )
    assert mobile_on_generic.status_code == 422
    assert mobile_on_generic.json()["detail"]["code"] == "receiver_type_invalid"

    first = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": first_id,
            "device_kind": "desktop",
            "device_name": "Gate Mac",
            "license_key": license_key,
        },
    )
    assert first.status_code == 200
    first_credential = first.json()["credential"]
    pending = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {first_credential}"},
        params={"install_id": first_id},
    )
    assert pending.status_code == 403
    assert pending.json()["detail"]["credential_state"] == "pending_commit"
    first = _commit(client, first, first_id)
    active = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {first_credential}"},
        params={"install_id": first_id},
    )
    assert active.status_code == 200
    assert active.json()["receiver_role"] == "independent_receiver"

    occupied = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": second_id,
            "device_kind": "desktop",
            "device_name": "Gate PC",
            "license_key": license_key,
        },
    )
    assert occupied.status_code == 409
    assert occupied.json()["code"] == "seat_in_use"
    assert occupied.json()["current_receiver"]["device_name"] == "Ga…ac"

    moved = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": second_id,
            "device_kind": "desktop",
            "device_name": "Gate PC",
            "license_key": license_key,
            "confirm_move_token": occupied.json()["move_token"],
        },
    )
    assert moved.status_code == 200
    # A persisted-but-uncommitted replacement never interrupts the receiver
    # that is currently serving Relay data.
    still_active = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {first_credential}"},
        params={"install_id": first_id},
    )
    assert still_active.status_code == 200
    moved = _commit(client, moved, second_id)
    old_receiver = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {first_credential}"},
        params={"install_id": first_id},
    )
    assert old_receiver.status_code == 403
    assert old_receiver.json()["detail"]["code"] == "license_inactive"

    wrong_install = client.post(
        "/v1/access/deactivate",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {moved.json()['credential']}"},
        json={"install_id": first_id},
    )
    assert wrong_install.status_code == 403
    deactivated = client.post(
        "/v1/access/deactivate",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {moved.json()['credential']}"},
        json={"install_id": second_id},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["seat_state"] == "available"

    for response in (
        unauthenticated,
        malformed,
        mobile_on_generic,
        first,
        pending,
        active,
        occupied,
        moved,
        still_active,
        old_receiver,
        wrong_install,
        deactivated,
    ):
        _assert_private_response(response)


def test_mobile_grant_requires_fresh_attestation_and_generic_endpoint_cannot_consume_it(
    access_stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, _stripe, _mailer = access_stack
    web_license, _key, _ = service.fulfill_purchase(_purchase("web-license-for-attested-grant"))
    magic = service.request_magic_link("pilot@example.test")
    assert magic is not None
    holder = service.exchange_magic_link(magic.token)
    install_id = "44444444-4444-4444-8444-444444444444"
    grant_response = client.post(
        "/v1/access/activation-grants",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {holder.token}"},
        json={"license_id": web_license.license_id, "install_id": install_id},
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()["activation_grant"]

    rejected = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": install_id,
            "device_kind": "mobile_standalone",
            "activation_grant": grant,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "receiver_type_invalid"

    monkeypatch.setenv("RELAY_ACCESS_MOBILE_OWNERSHIP_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_IOS_STATE", "testing")
    monkeypatch.setattr(relay_main, "_mobile_platform_preflight_errors", lambda _platform: [])
    monkeypatch.setattr(
        relay_main,
        "_apple_paid_app_verifier",
        lambda: FakePurchaseVerifier(_purchase("apple-owner-for-grant", provider="apple_app", email="")),
    )
    challenge = client.post(
        "/v1/access/mobile/attestation/challenge",
        headers=PUBLIC_HOST,
        json={"platform": "ios", "install_id": install_id, "intent": "standalone"},
    )
    activation = client.post(
        "/v1/access/mobile/attestation/verify",
        headers=PUBLIC_HOST,
        json={
            "platform": "ios",
            "install_id": install_id,
            "intent": "standalone",
            "nonce": challenge.json()["nonce"],
            "signed_app_transaction": "fresh-store-proof",
            "activation_grant": grant,
        },
    )
    assert activation.status_code == 200
    assert activation.json()["activated"] is False
    assert activation.json()["activation_state"] == "pending_commit"
    assert activation.json()["license"]["license_ref"] == web_license.license_id
    assert activation.json()["included_license"]["purchase_source"] == "apple_app"
    activation = _commit(client, activation, install_id)

    replay = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": "55555555-5555-4555-8555-555555555555",
            "device_kind": "desktop",
            "activation_grant": grant,
        },
    )
    assert replay.status_code == 422
    assert replay.json()["detail"]["code"] == "invalid_challenge"


def test_holder_grant_activates_desktop_and_license_action_returns_fresh_state(access_stack) -> None:
    client, service, _stripe, _mailer = access_stack
    license_record, _key, _ = service.fulfill_purchase(_purchase("desktop-holder-grant"))
    magic = service.request_magic_link("pilot@example.test")
    assert magic is not None
    holder = service.exchange_magic_link(magic.token)
    install_id = "77777777-7777-4777-8777-777777777777"

    issued = client.post(
        "/v1/access/activation-grants",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {holder.token}"},
        json={"license_id": license_record.license_id, "install_id": install_id},
    )
    assert issued.status_code == 200
    activated = client.post(
        "/v1/access/activate",
        headers=PUBLIC_HOST,
        json={
            "install_id": install_id,
            "device_kind": "desktop",
            "device_name": "Granted desktop",
            "activation_grant": issued.json()["activation_grant"],
        },
    )
    assert activated.status_code == 200
    assert activated.json()["receiver"]["device_kind"] == "desktop"
    activated = _commit(client, activated, install_id)

    revoked = client.post(
        "/v1/access/licenses/action",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {holder.token}"},
        json={"license_id": license_record.license_id, "action": "revoke_receiver"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert revoked.json()["receiver"] is None
    assert revoked.json()["license"]["status"] == "active"
    stale_credential = client.get(
        "/v1/access/status",
        headers={**PUBLIC_HOST, "authorization": f"Bearer {activated.json()['credential']}"},
        params={"install_id": install_id},
    )
    assert stale_credential.status_code == 403


def test_access_rate_limit_maps_to_429_with_retry_after(access_stack, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service, _stripe, _mailer = access_stack
    monkeypatch.setenv("RELAY_ACCESS_ACTIVATION_10M_LIMIT", "1")
    payload = {
        "install_id": "66666666-6666-4666-8666-666666666666",
        "device_kind": "desktop",
        "license_key": "invalid-key",
    }
    first = client.post("/v1/access/activate", headers=PUBLIC_HOST, json=payload)
    assert first.status_code == 422
    limited = client.post("/v1/access/activate", headers=PUBLIC_HOST, json=payload)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "access_rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    _assert_private_response(limited)
