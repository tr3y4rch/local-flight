"""Single runtime version and user-agent source for Local Flight."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


# ``pyproject.toml`` remains the release source of truth.  This fallback keeps
# source bundles and the relay image useful when package metadata is not
# installed; the release consistency test requires it to match pyproject.
FALLBACK_VERSION = "0.6.0"
PRODUCT_URL = "https://beacontools.cc/local-flight"


def app_version() -> str:
    """Return installed package metadata, or the checked source fallback."""

    try:
        return version("localflight")
    except PackageNotFoundError:
        return FALLBACK_VERSION


def user_agent(product: str = "local-flight") -> str:
    """Return a release-identifying, public-safe HTTP User-Agent value."""

    safe_product = str(product or "local-flight").strip() or "local-flight"
    return f"{safe_product}/{app_version()} (+{PRODUCT_URL})"
