from __future__ import annotations

import smtplib
import base64
import json
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Protocol
from urllib.parse import quote

from .models import AccessConfigurationError, VerifiedPurchase
from .email_templates import (EmailContent, license_email, magic_email, moved_email, operator_email, valid_mailbox)


class PurchaseVerifier(Protocol):
    def verify(self, proof: dict[str, Any]) -> VerifiedPurchase: ...


class LicenseMailer(Protocol):
    def send_license(self, *, email: str, license_key: str, recovery_url: str, purpose: str = "delivery") -> None: ...

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None: ...

    def send_receiver_moved(self, *, email: str, device_name: str) -> None: ...


@dataclass(frozen=True)
class StripeCheckout:
    checkout_ref: str
    session_id: str
    url: str


class StripeAdapter:
    """Small Stripe SDK boundary; no Stripe objects escape this adapter."""

    # Shown beside Stripe's terms-of-service checkbox. EU consumers keep a
    # fourteen-day withdrawal right unless they expressly ask for immediate
    # performance of digital content and acknowledge losing it, so the consent
    # has to be collected at checkout rather than merely published.
    WITHDRAWAL_CONSENT_MESSAGE = (
        "Relay Access is delivered immediately: your licence key is issued as soon as this "
        "checkout completes. By agreeing you expressly ask for that immediate start and "
        "acknowledge that you lose your 14-day right of withdrawal once the licence has been "
        "delivered in full. A 14-day refund is offered regardless."
    )

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        price_id: str,
        subscription_mode: bool = False,
        withdrawal_consent: bool = False,
    ) -> None:
        self.api_key = api_key.strip()
        self.webhook_secret = webhook_secret.strip()
        self.price_id = price_id.strip()
        self.subscription_mode = bool(subscription_mode)
        # Requires a Terms of Service URL on the Stripe account (Dashboard →
        # Settings → Public details). Stripe rejects the session without one, so
        # this stays switchable rather than hard-coded on.
        self.withdrawal_consent = bool(withdrawal_consent)

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
        request: dict[str, Any] = {
            "mode": "subscription" if self.subscription_mode else "payment",
            "line_items": [{"price": self.price_id, "quantity": 1}],
            "metadata": {"checkout_ref": checkout_ref},
            "automatic_tax": {"enabled": True},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "idempotency_key": f"relay-checkout:{checkout_ref}",
        }
        if self.withdrawal_consent:
            request["consent_collection"] = {"terms_of_service": "required"}
            request["custom_text"] = {
                "terms_of_service_acceptance": {"message": self.WITHDRAWAL_CONSENT_MESSAGE},
            }
        if self.subscription_mode:
            request["subscription_data"] = {"metadata": {"checkout_ref": checkout_ref}}
        else:
            request["customer_creation"] = "always"
            request["payment_intent_data"] = {"metadata": {"checkout_ref": checkout_ref}}
        session = stripe.checkout.Session.create(**request)
        session_id = str(getattr(session, "id", "") or session.get("id", ""))
        url = str(getattr(session, "url", "") or session.get("url", ""))
        if not session_id or not url:
            raise AccessConfigurationError("Stripe did not create a usable Checkout Session")
        return StripeCheckout(checkout_ref=checkout_ref, session_id=session_id, url=url)

    @staticmethod
    def checkout_consent_accepted(session: dict[str, Any]) -> bool:
        """True when the buyer ticked the terms-of-service consent on this session."""
        consent = session.get("consent")
        if not isinstance(consent, dict):
            return False
        return str(consent.get("terms_of_service") or "").strip().lower() == "accepted"

    def create_billing_portal(self, *, customer_reference: str, return_url: str) -> str:
        if not self.api_key or not customer_reference.strip() or not return_url.startswith("https://"):
            raise AccessConfigurationError("Stripe billing management is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        session = stripe.billing_portal.Session.create(
            customer=customer_reference.strip(),
            return_url=return_url,
            idempotency_key=f"relay-portal:{customer_reference.strip()}",
        )
        url = str(getattr(session, "url", "") or session.get("url", ""))
        if not url.startswith("https://"):
            raise AccessConfigurationError("Stripe did not create a usable billing session")
        return url

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

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if not self.api_key or not subscription_id.strip():
            raise AccessConfigurationError("Stripe subscription lookup is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        return self._plain_dict(stripe.Subscription.retrieve(subscription_id.strip()))

    def retrieve_invoice(self, invoice_id: str) -> dict[str, Any]:
        if not self.api_key or not invoice_id.strip():
            raise AccessConfigurationError("Stripe invoice lookup is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        return self._plain_dict(stripe.Invoice.retrieve(invoice_id.strip()))

    def retrieve_charge(self, charge_id: str) -> dict[str, Any]:
        if not self.api_key or not charge_id.strip():
            raise AccessConfigurationError("Stripe charge lookup is not configured")
        stripe = self._stripe()
        stripe.api_key = self.api_key
        return self._plain_dict(stripe.Charge.retrieve(charge_id.strip()))


class GooglePlayDeveloperAdapter:
    """Authenticated Android Publisher API boundary for products and subscriptions."""

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

    def lookup_subscription_purchase(self, package_name: str, purchase_token: str) -> dict[str, Any]:
        package = quote(package_name.strip(), safe="")
        token = quote(purchase_token.strip(), safe="")
        response = self._session().get(
            f"{self._BASE}/applications/{package}/purchases/subscriptionsv2/tokens/{token}",
            timeout=15,
        )
        return self._response_json(response, "subscription lookup")

    def acknowledge_subscription_purchase(
        self,
        *,
        package_name: str,
        subscription_id: str,
        purchase_token: str,
    ) -> None:
        package = quote(package_name.strip(), safe="")
        subscription = quote(subscription_id.strip(), safe="")
        token = quote(purchase_token.strip(), safe="")
        response = self._session().post(
            f"{self._BASE}/applications/{package}/purchases/subscriptions/{subscription}/tokens/{token}:acknowledge",
            json={},
            timeout=15,
        )
        if int(getattr(response, "status_code", 0) or 0) not in range(200, 300):
            raise AccessConfigurationError("Google Play subscription acknowledgement is temporarily unavailable")

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

    def get_subscription_status(
        self,
        original_transaction_id: str,
        environment: str,
    ) -> tuple[str, str, int]:
        """Return only Apple's signed current transaction and renewal facts."""
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
            response = client.get_all_subscription_statuses(original_transaction_id.strip())
            for group in list(getattr(response, "data", None) or []):
                for item in list(getattr(group, "lastTransactions", None) or []):
                    if str(getattr(item, "originalTransactionId", "") or "") != original_transaction_id:
                        continue
                    transaction = str(getattr(item, "signedTransactionInfo", "") or "").strip()
                    renewal = str(getattr(item, "signedRenewalInfo", "") or "").strip()
                    if transaction:
                        status_value = getattr(item, "status", None)
                        try:
                            status = int(getattr(status_value, "value", status_value) or 0)
                        except (TypeError, ValueError):
                            status = int(getattr(item, "rawStatus", 0) or 0)
                        return transaction, renewal, status
            raise AccessConfigurationError("App Store subscription lookup returned no current transaction")
        except AccessConfigurationError:
            raise
        except Exception as exc:
            raise AccessConfigurationError("App Store subscription lookup is temporarily unavailable") from exc


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

    def send_license(self, *, email: str, license_key: str, recovery_url: str, purpose: str = "delivery") -> None:
        self.messages.append({"kind": "license", "email": email, "license_key": license_key, "url": recovery_url, "purpose": purpose})

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None:
        self.messages.append({"kind": "magic_link", "email": email, "url": magic_url, "purpose": purpose})

    def send_receiver_moved(self, *, email: str, device_name: str) -> None:
        self.messages.append({"kind": "receiver_moved", "email": email, "device_name": device_name})

    def send_operator_message(self, *, email: str, purpose: str, action_url: str = "", expires_at: str = "") -> None:
        self.messages.append({"kind": purpose, "email": email, "url": action_url, "expires_at": expires_at})


class MailTransportError(Exception):
    """Sanitized evidence only; never include SMTP responses or recipient data."""

    def __init__(self, *, stage: str, detail_code: str, uncertain: bool = False, smtp_code: int | None = None):
        super().__init__(detail_code)
        self.stage, self.detail_code = stage, detail_code
        self.uncertain, self.smtp_code = uncertain, smtp_code


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
        self.message_id = ""

    def configured(self) -> bool:
        return bool(
            self.host
            and valid_mailbox(self.sender)
            and (not self.reply_to or valid_mailbox(self.reply_to))
            and self.port > 0
        )

    def secure_transport(self) -> bool:
        return self.security in {"starttls", "tls", "ssl", "smtps"}

    def _send(self, *, email: str, subject: str, text: str, html_text: str = "") -> None:
        if not self.configured():
            raise AccessConfigurationError("Relay Access email is not configured")
        if not valid_mailbox(email):
            raise AccessConfigurationError("Email recipient is invalid")
        message = EmailMessage()
        message["Date"] = formatdate(localtime=False)
        message["From"] = self.sender
        message["To"] = email
        message["Subject"] = subject
        message["Message-ID"] = self.message_id or make_msgid()
        if self.reply_to and "@" in self.reply_to and "\n" not in self.reply_to and "\r" not in self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(text)
        if html_text:
            message.add_alternative(html_text, subtype="html")
        use_ssl = self.security in {"ssl", "smtps"} or self.port == 465
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        stage = "connect"
        accepted = False
        try:
            with smtp_cls(self.host, self.port, timeout=12) as smtp:
                if self.security in {"starttls", "tls"} and not use_ssl:
                    stage = "tls"
                    smtp.starttls()
                if self.username:
                    stage = "authenticate"
                    smtp.login(self.username, self.password)
                stage = "transmit"
                refused = smtp.send_message(message)
                if refused:
                    raise MailTransportError(stage=stage, detail_code="recipient_rejected")
                accepted = True
        except MailTransportError:
            raise
        except (smtplib.SMTPException, OSError) as exc:
            # A failure while closing an accepted SMTP transaction cannot undo it.
            if accepted:
                return
            code = getattr(exc, "smtp_code", None)
            known_rejection = isinstance(exc,(smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError))
            category = "authentication_failed" if isinstance(exc,smtplib.SMTPAuthenticationError) else "recipient_rejected" if isinstance(exc,smtplib.SMTPRecipientsRefused) else "smtp_rejected" if known_rejection else "smtp_timeout" if isinstance(exc,TimeoutError) else "smtp_connection_failed"
            raise MailTransportError(stage=stage,detail_code=category,uncertain=stage=="transmit" and not known_rejection,smtp_code=int(code) if isinstance(code,int) else None) from None

    def _send_content(self, email: str, content: EmailContent) -> None:
        self._send(email=email, subject=content.subject, text=content.text, html_text=content.html)

    def send_operator_message(self, *, email: str, purpose: str, action_url: str = "", expires_at: str = "") -> None:
        self._send_content(email, operator_email(purpose=purpose, action_url=action_url, expires_at=expires_at))

    def send_license(self, *, email: str, license_key: str, recovery_url: str, purpose: str = "delivery") -> None:
        self._send_content(email, license_email(license_key=license_key, recovery_url=recovery_url, purpose=purpose))

    def send_magic_link(self, *, email: str, magic_url: str, purpose: str) -> None:
        self._send_content(email, magic_email(magic_url=magic_url, purpose=purpose))

    def send_receiver_moved(self, *, email: str, device_name: str) -> None:
        self._send_content(email, moved_email(device_name=device_name))
