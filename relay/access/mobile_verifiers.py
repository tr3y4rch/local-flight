from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from .models import AccessConfigurationError, InvalidChallenge, VerifiedPurchase


PAID_APP_PRODUCT_ID = "cc.beacontools.localflight.paid-app"


class PaidAppVerificationError(InvalidChallenge):
    code = "paid_app_verification_failed"


@dataclass(frozen=True)
class ApplePaidAppVerifier:
    bundle_id: str
    app_apple_id: int | None
    root_certificates: tuple[bytes, ...]
    online_checks: bool = True
    max_age_seconds: int = 300

    def _validate_device_and_freshness(
        self,
        transaction: Any,
        proof: dict[str, Any],
        signed: str,
    ) -> int:
        device_id_raw = str(proof.get("device_verification_id") or "").strip()
        device_nonce_raw = str(getattr(transaction, "deviceVerificationNonce", "") or "").strip()
        device_verification_raw = str(getattr(transaction, "deviceVerification", "") or "").strip()
        if not device_id_raw or not device_nonce_raw or not device_verification_raw:
            raise PaidAppVerificationError("Apple device verification proof is incomplete")
        try:
            device_id = str(uuid.UUID(device_id_raw)).lower()
            device_nonce = str(uuid.UUID(device_nonce_raw)).lower()
            padded = device_verification_raw + "=" * (-len(device_verification_raw) % 4)
            device_verification = base64.b64decode(padded, validate=True)
        except (ValueError, TypeError) as exc:
            raise PaidAppVerificationError("Apple device verification proof is invalid") from exc
        expected = hashlib.sha384(f"{device_nonce}{device_id}".encode("ascii")).digest()
        if not hmac.compare_digest(expected, device_verification):
            raise PaidAppVerificationError("Apple app purchase does not belong to this device")

        # The current Apple library models receiptCreationDate; newer payloads
        # can use signedDate. Decode only after the JWS signature was verified.
        signed_at = int(getattr(transaction, "receiptCreationDate", 0) or 0)
        payload: dict[str, Any] = {}
        try:
            payload_segment = signed.split(".", 2)[1]
            payload_segment += "=" * (-len(payload_segment) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload_segment).decode("utf-8"))
            payload = decoded if isinstance(decoded, dict) else {}
            signed_at = int(payload.get("signedDate") or payload.get("receiptCreationDate") or signed_at)
        except (IndexError, ValueError, TypeError, json.JSONDecodeError):
            pass
        if signed_at <= 0:
            raise PaidAppVerificationError("Apple AppTransaction signing date is missing")
        age_seconds = time.time() - (signed_at / 1000.0)
        if age_seconds > self.max_age_seconds or age_seconds < -60:
            raise PaidAppVerificationError("Apple AppTransaction proof has expired")
        return signed_at

    def verify(self, proof: dict[str, Any]) -> VerifiedPurchase:
        signed = str(proof.get("signed_app_transaction") or "").strip()
        if not signed:
            raise PaidAppVerificationError("Apple AppTransaction proof is required")
        if not self.root_certificates:
            raise AccessConfigurationError("Apple AppTransaction roots are not configured")
        try:
            from appstoreserverlibrary.models.Environment import Environment
            from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier, VerificationException
        except ImportError as exc:
            raise AccessConfigurationError("Apple paid-app verification is unavailable") from exc

        last_error: Exception | None = None
        environments = (
            (Environment.PRODUCTION, Environment.SANDBOX)
            if self.app_apple_id is not None
            else (Environment.SANDBOX,)
        )
        for environment in environments:
            try:
                verifier = SignedDataVerifier(
                    list(self.root_certificates),
                    self.online_checks,
                    environment,
                    self.bundle_id,
                    self.app_apple_id if environment == Environment.PRODUCTION else None,
                )
                transaction = verifier.verify_and_decode_app_transaction(signed)
                app_transaction_id = str(getattr(transaction, "appTransactionId", "") or "")
                if not app_transaction_id:
                    raise PaidAppVerificationError("Apple AppTransaction identity is incomplete")
                signed_at = self._validate_device_and_freshness(transaction, proof, signed)
                try:
                    payload_segment = signed.split(".", 2)[1]
                    payload_segment += "=" * (-len(payload_segment) % 4)
                    decoded_payload = json.loads(base64.urlsafe_b64decode(payload_segment).decode("utf-8"))
                    signed_payload = decoded_payload if isinstance(decoded_payload, dict) else {}
                except (IndexError, ValueError, TypeError, json.JSONDecodeError):
                    signed_payload = {}
                revocation_raw = (
                    getattr(transaction, "revocationDate", None)
                    or signed_payload.get("revocationDate")
                )
                try:
                    if hasattr(revocation_raw, "timestamp"):
                        revoked = float(revocation_raw.timestamp()) > 0
                    else:
                        revoked = int(revocation_raw or 0) > 0
                except (TypeError, ValueError, OverflowError):
                    revoked = False
                return VerifiedPurchase(
                    provider="apple_app",
                    external_id=app_transaction_id,
                    product_id=PAID_APP_PRODUCT_ID,
                    environment="production" if environment == Environment.PRODUCTION else "sandbox",
                    state="revoked" if revoked else "paid",
                    evidence_hash=hashlib.sha256(signed.encode("utf-8")).hexdigest(),
                    verified_at_ms=signed_at,
                    identity_kind="apple_app_entitlement",
                    reconciliation_mode="device_and_server",
                    reconciliation_handle=app_transaction_id,
                )
            except VerificationException as exc:
                last_error = exc
                continue
        if self.app_apple_id is None:
            raise AccessConfigurationError(
                "Apple production app identity is not configured; only sandbox proof can be checked"
            ) from last_error
        raise PaidAppVerificationError("Apple could not verify this app purchase") from last_error

    def verify_server(self, signed: str) -> VerifiedPurchase:
        """Verify Apple's signed server lookup without client device binding."""

        signed = (signed or "").strip()
        if not signed:
            raise PaidAppVerificationError("Apple server ownership proof is required")
        if not self.root_certificates:
            raise AccessConfigurationError("Apple AppTransaction roots are not configured")
        try:
            from appstoreserverlibrary.models.Environment import Environment
            from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier, VerificationException
        except ImportError as exc:
            raise AccessConfigurationError("Apple paid-app verification is unavailable") from exc
        last_error: Exception | None = None
        environments = (
            (Environment.PRODUCTION, Environment.SANDBOX)
            if self.app_apple_id is not None
            else (Environment.SANDBOX,)
        )
        for environment in environments:
            try:
                verifier = SignedDataVerifier(
                    list(self.root_certificates),
                    self.online_checks,
                    environment,
                    self.bundle_id,
                    self.app_apple_id if environment == Environment.PRODUCTION else None,
                )
                transaction = verifier.verify_and_decode_app_transaction(signed)
                app_transaction_id = str(getattr(transaction, "appTransactionId", "") or "")
                if not app_transaction_id:
                    raise PaidAppVerificationError("Apple AppTransaction identity is incomplete")
                try:
                    payload_segment = signed.split(".", 2)[1]
                    payload_segment += "=" * (-len(payload_segment) % 4)
                    decoded_payload = json.loads(base64.urlsafe_b64decode(payload_segment).decode("utf-8"))
                    payload = decoded_payload if isinstance(decoded_payload, dict) else {}
                except (IndexError, ValueError, TypeError, json.JSONDecodeError):
                    payload = {}
                signed_at = int(
                    payload.get("signedDate")
                    or payload.get("receiptCreationDate")
                    or getattr(transaction, "receiptCreationDate", 0)
                    or 0
                )
                revocation_raw = getattr(transaction, "revocationDate", None) or payload.get("revocationDate")
                try:
                    revoked = (
                        float(revocation_raw.timestamp()) > 0
                        if hasattr(revocation_raw, "timestamp")
                        else int(revocation_raw or 0) > 0
                    )
                except (TypeError, ValueError, OverflowError):
                    revoked = False
                return VerifiedPurchase(
                    provider="apple_app",
                    external_id=app_transaction_id,
                    product_id=PAID_APP_PRODUCT_ID,
                    environment="production" if environment == Environment.PRODUCTION else "sandbox",
                    state="revoked" if revoked else "paid",
                    evidence_hash=hashlib.sha256(signed.encode("utf-8")).hexdigest(),
                    verified_at_ms=signed_at,
                    identity_kind="apple_app_entitlement",
                    reconciliation_mode="device_and_server",
                    reconciliation_handle=app_transaction_id,
                )
            except VerificationException as exc:
                last_error = exc
                continue
        raise PaidAppVerificationError("Apple could not verify server ownership state") from last_error


@dataclass(frozen=True)
class GooglePlayProductVerifier:
    """Verify the Relay Access non-consumable with Google as authority.

    The purchase token is never trusted as a receipt on its own. ``lookup`` is
    the small authenticated Android Publisher API boundary, which keeps Google
    credentials out of this proof parser and makes lifecycle fixtures testable.
    """

    package_name: str
    product_id: str
    lookup: Callable[[str, str], dict[str, Any]]
    environment: str = "production"

    def verify(self, proof: dict[str, Any]) -> VerifiedPurchase:
        token = str(proof.get("google_play_purchase_token") or "").strip()
        claimed_product = str(proof.get("google_play_product_id") or "").strip()
        if not token or len(token) > 4096:
            raise PaidAppVerificationError("Google Play purchase token is required")
        if claimed_product != self.product_id:
            raise PaidAppVerificationError("Google Play purchase is for another product")
        payload = self.lookup(self.package_name, token)
        if not isinstance(payload, dict):
            raise PaidAppVerificationError("Google Play returned an unreadable purchase")

        state_context = payload.get("purchaseStateContext")
        state_name = str(
            state_context.get("purchaseState") if isinstance(state_context, dict) else ""
        ).strip().upper()
        line_items = payload.get("productLineItem") or payload.get("productLineItems") or []
        if not isinstance(line_items, list) or not line_items:
            raise PaidAppVerificationError("Google Play purchase contains no product")
        matching = [
            item for item in line_items
            if isinstance(item, dict) and str(item.get("productId") or "") == self.product_id
        ]
        if len(matching) != 1:
            raise PaidAppVerificationError("Google Play purchase does not contain Relay Access")
        offer_details = matching[0].get("productOfferDetails")
        offer_details = offer_details if isinstance(offer_details, dict) else {}
        try:
            quantity = int(offer_details.get("quantity") or 1)
        except (TypeError, ValueError) as exc:
            raise PaidAppVerificationError("Google Play purchase quantity is invalid") from exc
        if quantity != 1:
            raise PaidAppVerificationError("Google Play purchase quantity is not supported")

        acknowledgement = str(payload.get("acknowledgementState") or "").strip().upper()
        if acknowledgement not in {"ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED", "ACKNOWLEDGEMENT_STATE_PENDING"}:
            raise PaidAppVerificationError("Google Play acknowledgement state is invalid")
        configured_environment = self.environment.strip().lower()
        if configured_environment not in {"production", "test"}:
            raise AccessConfigurationError("Google Play purchase environment must be test or production")
        environment = "test" if payload.get("testPurchaseContext") else configured_environment
        state = {
            "PURCHASED": "paid",
            "PENDING": "suspended",
            "CANCELLED": "revoked",
        }.get(state_name)
        if state is None:
            raise PaidAppVerificationError("Google Play purchase state is not supported")
        verified_at_ms = int(time.time() * 1000)
        evidence = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return VerifiedPurchase(
            provider="google_play_product",
            external_id=token,
            product_id=self.product_id,
            environment=environment,
            state=state,
            evidence_hash=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            verified_at_ms=verified_at_ms,
            identity_kind="google_play_purchase_token",
            reconciliation_mode="server_authoritative",
            reconciliation_handle=token,
            acknowledgement_state=(
                "acknowledged"
                if acknowledgement == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
                else "pending"
            ),
        )


@dataclass(frozen=True)
class GooglePlayIntegrityVerifier:
    package_name: str
    decode: Callable[[str, str], dict[str, Any]]
    max_age_seconds: int = 300

    @staticmethod
    def request_hash(*, nonce: str, install_id: str, activation_grant: str) -> str:
        material = f"localflight-relay-grant-v1:{nonce}:{install_id}:{activation_grant}".encode("utf-8")
        return base64.urlsafe_b64encode(hashlib.sha256(material).digest()).decode("ascii").rstrip("=")

    def verify_grant(
        self,
        *,
        integrity_token: str,
        nonce: str,
        install_id: str,
        activation_grant: str,
    ) -> None:
        if not integrity_token.strip():
            raise PaidAppVerificationError("Play Integrity proof is required for a mobile transfer")
        payload = self.decode(self.package_name, integrity_token.strip())
        token_payload = payload.get("tokenPayloadExternal")
        if not isinstance(token_payload, dict):
            raise PaidAppVerificationError("Play Integrity response is incomplete")
        request = token_payload.get("requestDetails")
        app = token_payload.get("appIntegrity")
        if not isinstance(request, dict) or not isinstance(app, dict):
            raise PaidAppVerificationError("Play Integrity response is incomplete")
        if str(request.get("requestPackageName") or "") != self.package_name:
            raise PaidAppVerificationError("Play Integrity proof belongs to another app")
        expected_hash = self.request_hash(
            nonce=nonce,
            install_id=install_id,
            activation_grant=activation_grant,
        )
        if not hmac.compare_digest(str(request.get("requestHash") or ""), expected_hash):
            raise PaidAppVerificationError("Play Integrity request does not match this transfer")
        try:
            timestamp_ms = int(request.get("timestampMillis") or 0)
        except (TypeError, ValueError) as exc:
            raise PaidAppVerificationError("Play Integrity timestamp is invalid") from exc
        age_seconds = time.time() - (timestamp_ms / 1000.0)
        if timestamp_ms <= 0 or age_seconds > self.max_age_seconds or age_seconds < -60:
            raise PaidAppVerificationError("Play Integrity proof has expired")
        if str(app.get("appRecognitionVerdict") or "") != "PLAY_RECOGNIZED":
            raise PaidAppVerificationError("Android app build is not recognized by Google Play")
        package = str(app.get("packageName") or self.package_name)
        if package != self.package_name:
            raise PaidAppVerificationError("Play Integrity app identity does not match")


def apple_root_certificates(raw_base64_json: str) -> tuple[bytes, ...]:
    if not raw_base64_json.strip():
        return ()
    try:
        parsed = json.loads(raw_base64_json)
        if not isinstance(parsed, list):
            raise ValueError
        return tuple(base64.b64decode(str(item), validate=True) for item in parsed)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AccessConfigurationError("Apple root certificate configuration is invalid") from exc
