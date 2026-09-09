from __future__ import annotations

from dataclasses import dataclass

from .models import (
    InvalidChallenge,
    PurchaseEnvironmentMismatch,
    RelayLicense,
    VerifiedPurchase,
)
from .service import LicenseService


@dataclass(frozen=True)
class PurchaseCatalog:
    """Maps verified commerce identities onto one internal Relay Access product."""

    product_code: str
    stripe_price_id: str
    apple_product_id: str
    google_product_id: str
    entitlement_kind: str = "permanent"
    accepted_environments: frozenset[str] = frozenset({"production", "test", "sandbox"})

    def validate_identity(self, purchase: VerifiedPurchase) -> VerifiedPurchase:
        provider = purchase.provider.strip().lower()
        expected_products = {
            "stripe": self.stripe_price_id,
            "apple_app": self.apple_product_id,
            "apple_subscription": self.apple_product_id,
            # google_app is retained only so historical test records remain
            # readable. New Android releases use the non-consumable product.
            "google_app": self.apple_product_id,
            "google_play_product": self.google_product_id,
            "google_play_subscription": self.google_product_id,
        }
        expected = expected_products.get(provider)
        if expected is None:
            raise InvalidChallenge("Purchase source is not supported for Relay Access")
        if not expected or purchase.product_id.strip() != expected:
            raise InvalidChallenge("Purchase does not contain the Relay Access product")
        environment = purchase.environment.strip().lower()
        if environment not in {"production", "test", "sandbox"}:
            raise InvalidChallenge("Purchase environment is not supported")
        if environment not in self.accepted_environments:
            raise PurchaseEnvironmentMismatch(
                "This purchase proof belongs to a different Relay Access environment"
            )
        state = purchase.state.strip().lower()
        if state not in {
            "paid", "purchased", "active", "grace", "cancelled_active",
            "past_due", "expired", "suspended", "refunded", "revoked",
        }:
            raise InvalidChallenge("Purchase state is not supported")
        entitlement_kind = (purchase.entitlement_kind or self.entitlement_kind).strip().lower()
        effective_state = (purchase.effective_state or "active").strip().lower()
        if entitlement_kind != "subscription":
            effective_state = {
                "paid": "active",
                "purchased": "active",
                "active": "active",
                "refunded": "refunded",
                "revoked": "revoked",
            }.get(state, "suspended")
        return VerifiedPurchase(
            provider=provider,
            external_id=purchase.external_id.strip(),
            product_id=expected,
            environment=environment,
            state=state,
            email=purchase.email.strip(),
            evidence_hash=purchase.evidence_hash.strip(),
            verified_at_ms=max(0, int(purchase.verified_at_ms or 0)),
            identity_kind=purchase.identity_kind.strip(),
            reconciliation_mode=(purchase.reconciliation_mode or "device_only").strip(),
            reconciliation_handle=purchase.reconciliation_handle.strip(),
            acknowledgement_state=purchase.acknowledgement_state.strip(),
            entitlement_kind=entitlement_kind,
            effective_state=effective_state,
            current_period_start=purchase.current_period_start.strip(),
            current_period_end=purchase.current_period_end.strip(),
            grace_expires_at=purchase.grace_expires_at.strip(),
            auto_renews=bool(purchase.auto_renews),
            provider_state=purchase.provider_state.strip().lower(),
            license_product_code=self.product_code,
            customer_reference=purchase.customer_reference.strip(),
        )

    def validate(self, purchase: VerifiedPurchase) -> VerifiedPurchase:
        normalized = self.validate_identity(purchase)
        if normalized.effective_state not in {"active", "grace", "cancelled_active"}:
            raise InvalidChallenge("Purchase is not active")
        return normalized

    def public_product(self) -> dict[str, object]:
        annual = self.entitlement_kind == "subscription"
        return {
            "name": "Beacon Relay Access",
            "product_code": self.product_code,
            "license_kind": "annual_subscription" if annual else "permanent",
            "billing_period": "P1Y" if annual else None,
            "independent_receivers": 1,
            "portable": True,
            "seat_rule": "one_independent_receiver",
            "companion_clients_included": True,
            "desktop_routes": ["relay", "byok", "vatsim"],
        }


class PurchaseFulfillmentService:
    """The only commerce-to-license boundary used by public integrations."""

    def __init__(self, licenses: LicenseService, catalog: PurchaseCatalog) -> None:
        self.licenses = licenses
        self.catalog = catalog

    def fulfill(self, purchase: VerifiedPurchase) -> tuple[RelayLicense, str, bool]:
        return self.licenses.fulfill_purchase(self.catalog.validate(purchase))

    def fulfill_checkout(
        self,
        checkout_ref: str,
        purchase: VerifiedPurchase,
    ) -> tuple[RelayLicense, str, bool]:
        return self.licenses.fulfill_checkout(checkout_ref, self.catalog.validate(purchase))
