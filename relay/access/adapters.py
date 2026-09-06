from __future__ import annotations

import smtplib
import base64
import json
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol
from urllib.parse import quote

from .models import AccessConfigurationError, VerifiedPurchase


class PurchaseVerifier(Protocol):
    def verify(self, proof: dict[str, Any]) -> VerifiedPurchase: ...


class LicenseMailer(Protocol):
    def send_license(self, *, email: str, license_key: str, recovery_url: str) -> None: ...

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None: ...

    def send_receiver_moved(self, *, email: str, device_name: str) -> None: ...


@dataclass(frozen=True)
class StripeCheckout:
    checkout_ref: str
    session_id: str
    url: str


class StripeAdapter:
    """Small Stripe SDK boundary; no Stripe objects escape this adapter."""

    def __init__(self, *, api_key: str, webhook_secret: str, price_id: str) -> None:
        self.api_key = api_key.strip()
        self.webhook_secret = webhook_secret.strip()
        self.price_id = price_id.strip()

    @staticmethod
    def _stripe() -> Any:
        try:
            import stripe
        except ImportError as exc:
            raise AccessConfigurationError("Stripe support is not installed") from exc
        return stripe

    @staticmethod
    def _plain_dict(value: Any) -> dict[str, Any]:
        """Normalize Stripe resources across supported stripe-python releases."""
        if hasattr(value, "to_dict_recursive"):
            return dict(value.to_dict_recursive())
        if hasattr(value, "to_dict"):
            return dict(value.to_dict())
        if isinstance(value, dict):
            return dict(value)
        raise AccessConfigurationError("Stripe returned an unreadable response")

    def configured(self) -> bool:
        return bool(self.api_key and self.webhook_secret and self.price_id)

    def create_checkout(
        self,
        *,
        checkout_ref: str,
        success_url: str,
        cancel_url: str,
    ) -> StripeCheckout:
        if not self.configured():
            raise AccessConfigurationError("Stripe Checkout is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_creation="always",
            line_items=[{"price": self.price_id, "quantity": 1}],
            metadata={"checkout_ref": checkout_ref},
            payment_intent_data={"metadata": {"checkout_ref": checkout_ref}},
            success_url=success_url,
            cancel_url=cancel_url,
        )
        session_id = str(getattr(session, "id", "") or session.get("id", ""))
        url = str(getattr(session, "url", "") or session.get("url", ""))
        if not session_id or not url:
            raise AccessConfigurationError("Stripe did not create a usable Checkout Session")
        return StripeCheckout(checkout_ref=checkout_ref, session_id=session_id, url=url)

    def parse_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        if not self.webhook_secret:
            raise AccessConfigurationError("Stripe webhook verification is not configured")
        stripe = self._stripe()
        event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        return self._plain_dict(event)

    def retrieve_checkout(self, session_id: str) -> dict[str, Any]:
        if not self.api_key:
            raise AccessConfigurationError("Stripe Checkout is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        session = stripe.checkout.Session.retrieve(session_id)
        return self._plain_dict(session)


class GooglePlayDeveloperAdapter:
    """Authenticated Android Publisher API boundary for one-time products."""

    _SCOPE = "https://www.googleapis.com/auth/androidpublisher"
    _BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"

    def __init__(self, *, service_account_json_base64: str) -> None:
        self._encoded_credentials = service_account_json_base64.strip()

    def configured(self) -> bool:
        if not self._encoded_credentials:
            return False
        try:
            value = json.loads(base64.b64decode(self._encoded_credentials, validate=True))
            return bool(isinstance(value, dict) and value.get("client_email") and value.get("private_key"))
        except (ValueError, TypeError, json.JSONDecodeError):
            return False

    def _session(self) -> Any:
        if not self.configured():
            raise AccessConfigurationError("Google Play Developer API is not configured")
        try:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            info = json.loads(base64.b64decode(self._encoded_credentials, validate=True))
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=[self._SCOPE],
            )
            return AuthorizedSession(credentials)
        except AccessConfigurationError:
            raise
        except Exception as exc:
            raise AccessConfigurationError("Google Play Developer credentials are invalid") from exc

    @staticmethod
    def _response_json(response: Any, operation: str) -> dict[str, Any]:
        if int(getattr(response, "status_code", 0) or 0) not in range(200, 300):
            raise AccessConfigurationError(f"Google Play {operation} is temporarily unavailable")
        try:
            value = response.json()
        except Exception as exc:
            raise AccessConfigurationError(f"Google Play {operation} returned an unreadable response") from exc
        if not isinstance(value, dict):
            raise AccessConfigurationError(f"Google Play {operation} returned an unreadable response")
        return value

    def lookup_product_purchase(self, package_name: str, purchase_token: str) -> dict[str, Any]:
        package = quote(package_name.strip(), safe="")
        token = quote(purchase_token.strip(), safe="")
        response = self._session().get(
            f"{self._BASE}/applications/{package}/purchases/productsv2/tokens/{token}",
            timeout=15,
        )
        return self._response_json(response, "purchase lookup")

    def acknowledge_product_purchase(
        self,
        *,
        package_name: str,
        product_id: str,
        purchase_token: str,
    ) -> None:
        package = quote(package_name.strip(), safe="")
        product = quote(product_id.strip(), safe="")
        token = quote(purchase_token.strip(), safe="")
        response = self._session().post(
            f"{self._BASE}/applications/{package}/purchases/products/{product}/tokens/{token}:acknowledge",
            json={},
            timeout=15,
        )
        if int(getattr(response, "status_code", 0) or 0) not in range(200, 300):
            raise AccessConfigurationError("Google Play purchase acknowledgement is temporarily unavailable")

    def list_voided_purchases(
        self,
        *,
        package_name: str,
        start_time_ms: int | None = None,
        page_token: str = "",
        max_results: int = 500,
    ) -> dict[str, Any]:
        package = quote(package_name.strip(), safe="")
        params: dict[str, Any] = {
            "pageSelection.maxResults": max(1, min(int(max_results), 1000)),
            "type": 0,
        }
        if start_time_ms is not None and int(start_time_ms) > 0:
            params["startTime"] = int(start_time_ms)
        if page_token.strip():
            params["pageSelection.token"] = page_token.strip()
        response = self._session().get(
            f"{self._BASE}/applications/{package}/purchases/voidedpurchases",
            params=params,
            timeout=20,
        )
        return self._response_json(response, "voided-purchase lookup")


class GooglePlayIntegrityAdapter:
    """Server-side decoder for Play Integrity standard-request tokens."""

    _SCOPE = "https://www.googleapis.com/auth/playintegrity"
    _BASE = "https://playintegrity.googleapis.com/v1"

    def __init__(self, *, service_account_json_base64: str) -> None:
        self._encoded_credentials = service_account_json_base64.strip()

    def configured(self) -> bool:
        if not self._encoded_credentials:
            return False
        try:
            value = json.loads(base64.b64decode(self._encoded_credentials, validate=True))
            return bool(isinstance(value, dict) and value.get("client_email") and value.get("private_key"))
        except (ValueError, TypeError, json.JSONDecodeError):
            return False

    def decode(self, package_name: str, integrity_token: str) -> dict[str, Any]:
        if not self.configured():
            raise AccessConfigurationError("Google Play Integrity is not configured")
        try:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            info = json.loads(base64.b64decode(self._encoded_credentials, validate=True))
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=[self._SCOPE],
            )
            session = AuthorizedSession(credentials)
            package = quote(package_name.strip(), safe="")
            response = session.post(
                f"{self._BASE}/{package}:decodeIntegrityToken",
                json={"integrityToken": integrity_token.strip()},
                timeout=15,
            )
            return GooglePlayDeveloperAdapter._response_json(response, "integrity verification")
        except AccessConfigurationError:
            raise
        except Exception as exc:
            raise AccessConfigurationError("Google Play Integrity verification is unavailable") from exc


class AppleAppTransactionAdapter:
    """App Store Server API boundary for authoritative app-ownership lookup."""

    def __init__(
        self,
        *,
        issuer_id: str,
        key_id: str,
        private_key_base64: str,
        bundle_id: str,
    ) -> None:
        self.issuer_id = issuer_id.strip()
        self.key_id = key_id.strip()
        self.private_key_base64 = private_key_base64.strip()
        self.bundle_id = bundle_id.strip()

    def configured(self) -> bool:
        if not all((self.issuer_id, self.key_id, self.private_key_base64, self.bundle_id)):
            return False
        try:
            return bool(base64.b64decode(self.private_key_base64, validate=True))
        except (TypeError, ValueError):
            return False

    def get_app_transaction_info(self, app_transaction_id: str, environment: str) -> str:
        if not self.configured():
            raise AccessConfigurationError("App Store Server API is not configured")
        try:
            from appstoreserverlibrary.api_client import AppStoreServerAPIClient
            from appstoreserverlibrary.models.Environment import Environment

            selected = (
                Environment.PRODUCTION
                if environment.strip().lower() == "production"
                else Environment.SANDBOX
            )
            client = AppStoreServerAPIClient(
                base64.b64decode(self.private_key_base64, validate=True),
                self.key_id,
                self.issuer_id,
                self.bundle_id,
                selected,
            )
            response = client.get_app_transaction_info(app_transaction_id.strip())
            signed = str(getattr(response, "signedAppTransactionInfo", "") or "").strip()
            if not signed:
                raise AccessConfigurationError("App Store ownership lookup returned no signed transaction")
            return signed
        except AccessConfigurationError:
            raise
        except Exception as exc:
            raise AccessConfigurationError("App Store ownership lookup is temporarily unavailable") from exc


class FakePurchaseVerifier:
    """Deterministic adapter for unit/integration tests; never enabled by routes."""

    def __init__(self, purchase: VerifiedPurchase) -> None:
        self.purchase = purchase

    def verify(self, _proof: dict[str, Any]) -> VerifiedPurchase:
        return self.purchase


class RecordingLicenseMailer:
    """In-memory mail adapter for tests without SMTP or real addresses."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def configured(self) -> bool:
        return True

    def send_license(self, *, email: str, license_key: str, recovery_url: str) -> None:
        self.messages.append({"kind": "license", "email": email, "license_key": license_key, "url": recovery_url})

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None:
        self.messages.append({"kind": "magic_link", "email": email, "url": magic_url, "purpose": purpose})

    def send_receiver_moved(self, *, email: str, device_name: str) -> None:
        self.messages.append({"kind": "receiver_moved", "email": email, "device_name": device_name})


class SmtpLicenseMailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        security: str = "starttls",
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.sender = sender.strip()
        self.username = username
        self.password = password
        self.security = security.strip().lower()

    def configured(self) -> bool:
        return bool(self.host and self.sender and self.port > 0)

    def _send(self, *, email: str, subject: str, text: str) -> None:
        if not self.configured():
            raise AccessConfigurationError("Relay Access email is not configured")
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email
        message["Subject"] = subject
        message.set_content(text)
        use_ssl = self.security in {"ssl", "smtps"} or self.port == 465
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(self.host, self.port, timeout=12) as smtp:
            if self.security in {"starttls", "tls"} and not use_ssl:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    def send_license(self, *, email: str, license_key: str, recovery_url: str) -> None:
        self._send(
            email=email,
            subject="Your Beacon Relay Access license",
            text=(
                "Your one-time Beacon Relay Access purchase is ready.\n\n"
                f"License key: {license_key}\n\n"
                "Enter this key in Local Flight's Beacon Relay setup. The key controls one "
                "main device at a time: one Local Flight desktop or one phone in Standalone "
                "mode. Keep it private.\n\n"
                f"Recovery and license management: {recovery_url}\n"
            ),
        )

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None:
        self._send(
            email=email,
            subject="Your Beacon Relay Access link",
            text=(
                "Use this one-time link to manage Beacon Relay Access. It expires in 15 minutes.\n\n"
                f"{magic_url}\n\n"
                f"Request: {purpose or 'license access'}\n\n"
                "If you did not request this link, you can ignore this message.\n"
            ),
        )

    def send_receiver_moved(self, *, email: str, device_name: str) -> None:
        self._send(
            email=email,
            subject="Beacon Relay Access moved",
            text=(
                "Your Beacon Relay Access was moved to a new main device.\n\n"
                f"New device: {device_name}\n\n"
                "The previous device can no longer use Beacon Relay directly. If this was not you, "
                "use your recovery link or contact Beacon Tools support.\n"
            ),
        )
