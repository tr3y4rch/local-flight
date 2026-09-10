"""Single runtime version and user-agent source for Local Flight."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


# ``pyproject.toml`` remains the release source of truth.  This fallback keeps
# source bundles and the relay image useful when package metadata is not
# installed; the release consistency test requires it to match pyproject.
FALLBACK_VERSION = "0.7.1"
PRODUCT_URL = "https://beacontools.cc/local-flight"


def app_version() -> str:
    """Return the version represented by this source tree."""

    try:
        installed = version("localflight")
    except PackageNotFoundError:
        return FALLBACK_VERSION
    # Editable environments can retain stale distribution metadata after a
    # release bump. The checked source is authoritative and both values are
    # required to match by the release gate in packaged builds.
    return installed if installed == FALLBACK_VERSION else FALLBACK_VERSION


def user_agent(product: str = "local-flight") -> str:
    """Return a release-identifying, public-safe HTTP User-Agent value."""

    safe_product = str(product or "local-flight").strip() or "local-flight"
    return f"{safe_product}/{app_version()} (+{PRODUCT_URL})"
