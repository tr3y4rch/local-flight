from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class AccessError(Exception):
    """Base class for safe, expected access-domain failures.

    The fields are deliberately presentation-safe. Public routes can preserve
    the state machine without exposing purchase, activation, or provider IDs.
    """

    code = "access_error"

    def __init__(
        self,
        message: str,
        *,
        access_state: str | None = None,
        credential_state: str = "unknown",
        reason_code: str = "",
        retryable: bool = False,
        current_receiver: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.access_state = access_state
        self.credential_state = credential_state
        self.reason_code = reason_code or self.code
        self.retryable = bool(retryable)
        self.current_receiver = current_receiver


class AccessConfigurationError(AccessError):
    code = "access_not_configured"


class InvalidLicenseKey(AccessError):
    code = "invalid_license_key"


class LicenseNotFound(AccessError):
    code = "license_not_found"


class LicenseInactive(AccessError):
    code = "license_inactive"


class InvalidChallenge(AccessError):
    code = "invalid_challenge"


class PurchaseEnvironmentMismatch(InvalidChallenge):
    """The proof is valid for a different deployment environment."""

    code = "purchase_environment_mismatch"


class AccessRateLimited(AccessError):
    code = "access_rate_limited"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message, reason_code="rate_limited", retryable=True)
        self.retry_after = max(1, int(retry_after))


@dataclass(frozen=True)
class VerifiedPurchase:
    provider: str
    external_id: str
    product_id: str
    environment: str = "production"
    state: str = "paid"
    email: str = ""
    evidence_hash: str = ""
    # Provider-signed proof time, not the relay receipt time. It is used only
    # where the provider's signed proof has a freshness guarantee. The
    # challenge window uses it for both stores; Google Play can additionally
    # use a later proof to distinguish a repurchase after terminal revocation.
    verified_at_ms: int = 0
    identity_kind: str = ""
    reconciliation_mode: str = "device_only"
    reconciliation_handle: str = ""
    acknowledgement_state: str = ""


@dataclass(frozen=True)
class RelayLicense:
    license_id: str
    license_ref: str
    product_code: str
    purchase_source: str
    status: str
    holder_id: str | None
    key_prefix: str
    key_last_four: str
    created_at: str


@dataclass(frozen=True)
class DeviceCredential:
    credential: str
    credential_prefix: str
    activation_id: str
    license_ref: str
    install_id: str
    device_kind: str
    device_name: str


@dataclass(frozen=True)
class ActivationResult:
    activated: bool
    license: RelayLicense
    credential: DeviceCredential | None = None
    move_token: str = ""
    current_receiver: Mapping[str, Any] | None = None
    replaced_receiver: bool = False
    activation_state: str = "active"
    pending_expires_in: int = 0


@dataclass(frozen=True)
class MagicLinkDelivery:
    email: str
    token: str
    purpose: str


@dataclass(frozen=True)
class HolderSession:
    token: str
    holder_id: str
    licenses: tuple[RelayLicense, ...]
    delivered_license_id: str = ""
    license_key: str = ""
