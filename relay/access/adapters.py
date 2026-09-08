from __future__ import annotations

import smtplib
import base64
import html
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
            idempotency_key=f"relay-checkout:{checkout_ref}",
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
        reply_to: str = "",
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.sender = sender.strip()
        self.username = username
        self.password = password
        self.security = security.strip().lower()
        self.reply_to = reply_to.strip()

    def configured(self) -> bool:
        return bool(
            self.host
            and self.sender
            and "@" in self.sender
            and "\n" not in self.sender
            and "\r" not in self.sender
            and self.port > 0
        )

    def secure_transport(self) -> bool:
        return self.security in {"starttls", "tls", "ssl", "smtps"}

    @staticmethod
    def _html_message(*, heading: str, paragraphs: list[str], action_url: str = "", action_label: str = "") -> str:
        body = "".join(
            f'<p style="margin:0 0 16px;color:#c7d7e5;line-height:1.6">{paragraph}</p>'
            for paragraph in paragraphs
        )
        action = ""
        if action_url and action_label:
            action = (
                '<p style="margin:24px 0">'
                f'<a href="{html.escape(action_url, quote=True)}" '
                'style="display:inline-block;padding:12px 18px;border-radius:10px;'
                'background:#65bff3;color:#06131d;text-decoration:none;font-weight:700">'
                f'{html.escape(action_label)}</a></p>'
            )
        return (
            '<!doctype html><html><body style="margin:0;background:#07131d;padding:24px;'
            'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'
            '<div style="max-width:620px;margin:0 auto;border:1px solid #214057;border-radius:18px;'
            'background:#0d202d;padding:28px">'
            '<p style="margin:0 0 10px;color:#65bff3;font-size:12px;font-weight:700;'
            'letter-spacing:.12em">BEACON RELAY ACCESS</p>'
            f'<h1 style="margin:0 0 20px;color:#f4f8fb;font-size:26px">{html.escape(heading)}</h1>'
            f'{body}{action}'
            '<p style="margin:24px 0 0;color:#7890a3;font-size:12px;line-height:1.5">'
            'Local Flight never receives payment-card details. Payment receipts come separately '
            'from Stripe, Apple, or Google.</p></div></body></html>'
        )

    def _send(self, *, email: str, subject: str, text: str, html_text: str = "") -> None:
        if not self.configured():
            raise AccessConfigurationError("Relay Access email is not configured")
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email
        message["Subject"] = subject
        if self.reply_to and "@" in self.reply_to and "\n" not in self.reply_to and "\r" not in self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(text)
        if html_text:
            message.add_alternative(html_text, subtype="html")
        use_ssl = self.security in {"ssl", "smtps"} or self.port == 465
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(self.host, self.port, timeout=12) as smtp:
            if self.security in {"starttls", "tls"} and not use_ssl:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    def send_license(self, *, email: str, license_key: str, recovery_url: str) -> None:
        escaped_key = html.escape(license_key)
        self._send(
            email=email,
            subject="Your Beacon Relay Access license",
            text=(
                "Your Beacon Relay Access license is ready.\n\n"
                f"License key: {license_key}\n\n"
                "Enter this key in Local Flight's Beacon Relay setup. The key controls one "
                "main device at a time: one Local Flight desktop or one phone in Standalone "
                "mode. Keep it private.\n\n"
                f"Recovery and license management: {recovery_url}\n\n"
                "This is your Local Flight access-delivery email. Any payment receipt comes "
                "separately from Stripe, Apple, or Google.\n"
            ),
            html_text=self._html_message(
                heading="Your Relay Access license is ready",
                paragraphs=[
                    "Your portable license key is:",
                    f'<code style="display:block;padding:14px;border-radius:10px;background:#07131d;'
                    f'color:#f4f8fb;font-size:16px;word-break:break-all">{escaped_key}</code>',
                    "Enter this key in Local Flight's Beacon Relay setup. It controls one main "
                    "device at a time. Keep it private.",
                ],
                action_url=recovery_url,
                action_label="Manage or recover Relay Access",
            ),
        )

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None:
        purpose_label = {
            "recovery": "recover or manage Relay Access",
            "protect_and_deliver": "protect Relay Access and receive its portable key",
            "protect_and_transfer": "protect Relay Access before moving it",
        }.get((purpose or "").strip().lower(), "manage Relay Access")
        self._send(
            email=email,
            subject="Your Beacon Relay Access link",
            text=(
                f"Use this one-time link to {purpose_label}. It expires in 15 minutes.\n\n"
                f"{magic_url}\n\n"
                "If you did not request this link, you can ignore this message.\n"
            ),
            html_text=self._html_message(
                heading="Your private Relay Access link",
                paragraphs=[
                    f"Use this one-time link to {html.escape(purpose_label)}. It expires in 15 minutes.",
                    "If you did not request this link, you can ignore this message.",
                ],
                action_url=magic_url,
                action_label="Open Relay Access management",
            ),
        )

    def send_receiver_moved(self, *, email: str, device_name: str) -> None:
        safe_device_name = html.escape(device_name)
        self._send(
            email=email,
            subject="Beacon Relay Access moved",
            text=(
                "Your Beacon Relay Access was moved to a new main device.\n\n"
                f"New device: {device_name}\n\n"
                "The previous device can no longer use Beacon Relay directly. If this was not you, "
                "use your recovery link or contact Beacon Tools support.\n"
            ),
            html_text=self._html_message(
                heading="Relay Access moved",
                paragraphs=[
                    f"Your main device is now <strong style=\"color:#f4f8fb\">{safe_device_name}</strong>.",
                    "The previous device can no longer use Beacon Relay directly. If this was not "
                    "you, recover the license or contact Beacon Tools support.",
                ],
            ),
        )
