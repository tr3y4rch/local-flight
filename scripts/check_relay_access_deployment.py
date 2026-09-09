#!/usr/bin/env python3
"""Fail closed when a deployed relay does not match the licensing release."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import tomllib
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_CODE = "beacon_relay_annual_v1"
CATALOG_CONTRACT_VERSION = 2


def source_contract() -> tuple[str, int]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    schema_source = (ROOT / "relay" / "access" / "schema.py").read_text(encoding="utf-8")
    match = re.search(r"^ACCESS_SCHEMA_VERSION\s*=\s*(\d+)\s*$", schema_source, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read the Relay Access schema version from source")
    return str(project["project"]["version"]), int(match.group(1))


def fetch_json(url: str, *, host_header: str = "", timeout: float = 10.0) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "localflight-relay-deploy-check/1"}
    if host_header:
        headers["Host"] = host_header
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return payload


def validate_payloads(
    health: dict[str, Any],
    catalog: dict[str, Any],
    *,
    expected_version: str,
    expected_schema: int,
    expected_revision: str = "",
    expected_environment: str = "",
    require_license_core: bool = False,
) -> None:
    if health.get("ok") is not True or health.get("service") != "beacon-relay":
        raise RuntimeError("Relay health identity is missing or invalid")
    if health.get("version") != expected_version:
        raise RuntimeError(
            f"Relay version mismatch: expected {expected_version}, got {health.get('version') or 'missing'}"
        )
    if expected_revision and health.get("revision") != expected_revision.lower():
        raise RuntimeError(
            f"Relay revision mismatch: expected {expected_revision.lower()}, got {health.get('revision') or 'missing'}"
        )
    access = health.get("access")
    if not isinstance(access, dict):
        raise RuntimeError("Relay health does not expose the safe access readiness contract")
    if expected_environment and access.get("deployment_environment") != expected_environment:
        raise RuntimeError("Relay deployment environment does not match the intended target")
    if access.get("schema_version") != expected_schema:
        raise RuntimeError("Relay health reports the wrong access schema version")
    if access.get("expected_schema_version") != expected_schema or access.get("catalog_ready") is not True:
        raise RuntimeError("Relay Access catalog is not ready for this source release")
    readiness_fields = {
        "keyrings_ready",
        "license_core_ready",
        "smtp_ready",
        "backup_ready",
        "sales_ready",
    }
    if any(not isinstance(access.get(field), bool) for field in readiness_fields):
        raise RuntimeError("Relay health is missing safe Relay Access readiness fields")
    if require_license_core and (
        access.get("keyrings_ready") is not True
        or access.get("license_core_ready") is not True
    ):
        raise RuntimeError("Relay Access core or versioned keyrings are not ready")
    providers = access.get("providers")
    if not isinstance(providers, dict) or any(
        not isinstance(providers.get(provider), bool)
        for provider in ("stripe", "apple_subscription", "google_play")
    ):
        raise RuntimeError("Relay health is missing safe provider readiness fields")
    if access.get("sales_ready") is True and not all(
        (
            access.get("keyrings_ready"),
            access.get("license_core_ready"),
            access.get("smtp_ready"),
            access.get("backup_ready"),
            providers.get("stripe"),
        )
    ):
        raise RuntimeError("Relay claims sales readiness without its required safety gates")

    product = catalog.get("product")
    if (
        catalog.get("ok") is not True
        or catalog.get("schema_version") != expected_schema
        or catalog.get("catalog_contract_version") != CATALOG_CONTRACT_VERSION
    ):
        raise RuntimeError("Relay Access catalog schema is missing or incompatible")
    if not isinstance(product, dict) or product.get("product_code") != PRODUCT_CODE:
        raise RuntimeError("Relay Access catalog does not expose the canonical product")
    sources = product.get("purchase_sources")
    if not isinstance(sources, dict) or not {
        "stripe",
        "apple_subscription",
        "google_play",
    }.issubset(sources):
        raise RuntimeError("Relay Access catalog is missing a supported purchase path")
    pricing = product.get("pricing")
    if (
        product.get("billing_period") != "P1Y"
        or not isinstance(pricing, dict)
        or pricing.get("kind") != "annual_auto_renewing"
        or pricing.get("localized_price_owner") != "checkout_or_store"
    ):
        raise RuntimeError("Relay Access catalog does not expose the annual pricing contract")
    capabilities = catalog.get("capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("radar") is not False:
        raise RuntimeError("Relay Access catalog must explicitly disable shared real radar")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Relay origin, for example https://relay.beacontools.cc")
    parser.add_argument("--host-header", default="", help="Host header for a local container smoke test")
    parser.add_argument("--expected-revision", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--expected-environment", choices=("staging", "production"), default="")
    parser.add_argument(
        "--require-license-core",
        action="store_true",
        help="Also require configured versioned licensing keyrings",
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    version, schema = source_contract()
    base = args.base_url.rstrip("/")
    last_error: Exception | None = None
    for attempt in range(max(1, min(args.attempts, 60))):
        try:
            health = fetch_json(f"{base}/health", host_header=args.host_header, timeout=args.timeout)
            catalog = fetch_json(
                f"{base}/v1/access/catalog",
                host_header=args.host_header,
                timeout=args.timeout,
            )
            validate_payloads(
                health,
                catalog,
                expected_version=version,
                expected_schema=schema,
                expected_revision=args.expected_revision,
                expected_environment=args.expected_environment,
                require_license_core=args.require_license_core,
            )
            print(
                f"Relay {version} ({health.get('revision')}) exposes access schema {schema} "
                f"and {PRODUCT_CODE}; core_ready={health['access']['license_core_ready']}, "
                f"sales_ready={health['access']['sales_ready']}."
            )
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < max(1, args.attempts):
                time.sleep(max(0.1, args.delay))
    raise SystemExit(f"Relay deployment check failed: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
