"""Provider-neutral Relay Access licensing primitives."""

from .models import (
    AccessConfigurationError,
    AccessError,
    AccessRateLimited,
    ActivationResult,
    DeviceCredential,
    InvalidChallenge,
    InvalidLicenseKey,
    LicenseInactive,
    LicenseNotFound,
    PurchaseEnvironmentMismatch,
    RelayLicense,
    VerifiedPurchase,
)
from .fulfillment import PurchaseCatalog, PurchaseFulfillmentService
from .policy import ProviderAccessPolicy
from .schema import ensure_access_schema
from .service import LicenseService

__all__ = [
    "AccessConfigurationError",
    "AccessError",
    "AccessRateLimited",
    "ActivationResult",
    "DeviceCredential",
    "InvalidChallenge",
    "InvalidLicenseKey",
    "LicenseInactive",
    "LicenseNotFound",
    "LicenseService",
    "PurchaseEnvironmentMismatch",
    "PurchaseCatalog",
    "PurchaseFulfillmentService",
    "ProviderAccessPolicy",
    "RelayLicense",
    "VerifiedPurchase",
    "ensure_access_schema",
]
