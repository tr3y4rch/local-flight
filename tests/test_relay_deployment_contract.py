from __future__ import annotations

import pytest

from scripts.check_relay_access_deployment import source_contract, validate_payloads


def _payloads() -> tuple[dict, dict, str, int]:
    version, schema = source_contract()
    health = {
        "ok": True,
        "service": "beacon-relay",
        "version": version,
        "revision": "a" * 40,
        "access": {
            "schema_version": schema,
            "expected_schema_version": schema,
            "catalog_ready": True,
            "keyrings_ready": True,
            "license_core_ready": True,
            "smtp_ready": False,
            "backup_ready": False,
            "sales_ready": False,
            "providers": {
                "stripe": False,
                "apple_app": False,
                "google_play": False,
            },
        },
    }
    catalog = {
        "ok": True,
        "schema_version": schema,
        "product": {
            "product_code": "beacon_relay_lifetime_v1",
            "purchase_sources": {
                "stripe": {},
                "apple_app": {},
                "google_play": {},
            },
        },
    }
    return health, catalog, version, schema


def test_relay_deployment_contract_accepts_matching_release() -> None:
    health, catalog, version, schema = _payloads()
    validate_payloads(
        health,
        catalog,
        expected_version=version,
        expected_schema=schema,
        expected_revision="a" * 40,
    )


def test_closed_relay_deployment_does_not_require_license_keyrings() -> None:
    health, catalog, version, schema = _payloads()
    health["access"]["keyrings_ready"] = False
    health["access"]["license_core_ready"] = False

    validate_payloads(
        health,
        catalog,
        expected_version=version,
        expected_schema=schema,
        expected_revision="a" * 40,
    )

    with pytest.raises(RuntimeError, match="keyrings"):
        validate_payloads(
            health,
            catalog,
            expected_version=version,
            expected_schema=schema,
            expected_revision="a" * 40,
            require_license_core=True,
        )


def test_relay_deployment_contract_rejects_false_sales_readiness() -> None:
    health, catalog, version, schema = _payloads()
    health["access"]["sales_ready"] = True

    with pytest.raises(RuntimeError, match="sales readiness"):
        validate_payloads(
            health,
            catalog,
            expected_version=version,
            expected_schema=schema,
            expected_revision="a" * 40,
        )


@pytest.mark.parametrize("missing", ["identity", "version", "revision", "access", "catalog"])
def test_relay_deployment_contract_rejects_stale_or_incomplete_image(missing: str) -> None:
    health, catalog, version, schema = _payloads()
    if missing == "identity":
        health.pop("service")
    elif missing == "version":
        health["version"] = "0.5.2"
    elif missing == "revision":
        health["revision"] = "b" * 40
    elif missing == "access":
        health.pop("access")
    else:
        catalog["product"] = {"product_code": "legacy", "purchase_sources": {}}
    with pytest.raises(RuntimeError):
        validate_payloads(
            health,
            catalog,
            expected_version=version,
            expected_schema=schema,
            expected_revision="a" * 40,
        )
