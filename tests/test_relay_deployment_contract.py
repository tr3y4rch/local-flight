from __future__ import annotations

import pytest

from scripts.check_relay_access_deployment import source_contract, validate_payloads


def test_container_copy_contract_can_initialize_schedule_modules(tmp_path) -> None:
    """Exercise the actual Docker COPY inventory without importing checkout files."""
    import os
    from pathlib import Path
    import shlex
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    image = tmp_path / "image"
    image.mkdir()
    for line in (root / "relay" / "Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        _, source, destination = shlex.split(line)
        origin, target = root / source, image / destination
        if origin.is_dir():
            shutil.copytree(origin, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
    for name in ("schedule_service.py", "schedule_transport.py"):
        assert (image / "relay" / name).is_file(), f"Relay image is missing {name}"
    probe = """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import main
from relay import schedule_service, schedule_transport
for module in (main, schedule_service, schedule_transport):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]))
main._ensure_schema()
main._schedule_service().close()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(image)],
        cwd=image, env={"PATH": os.defpath, "DB_PATH": str(tmp_path / "fake-relay.db"),
                        "LOCALFLIGHT_HOME": str(tmp_path / "fake-home")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


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
                "apple_subscription": False,
                "google_play": False,
            },
        },
    }
    catalog = {
        "ok": True,
        "schema_version": schema,
        "catalog_contract_version": 2,
        "capabilities": {"schedule": True, "remote_companion": True, "radar": True},
        "product": {
            "product_code": "beacon_relay_annual_v1",
            "billing_period": "P1Y",
            "pricing": {
                "kind": "annual_auto_renewing",
                "localized_price_owner": "checkout_or_store",
            },
            "purchase_sources": {
                "stripe": {},
                "apple_subscription": {},
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


def test_relay_deployment_contract_rejects_production_for_staging() -> None:
    health, catalog, version, schema = _payloads()
    health["access"]["deployment_environment"] = "production"
    with pytest.raises(RuntimeError, match="environment"):
        validate_payloads(health, catalog, expected_version=version,
                          expected_schema=schema, expected_environment="staging")
    health["access"]["deployment_environment"] = "staging"
    validate_payloads(health, catalog, expected_version=version,
                      expected_schema=schema, expected_environment="staging")


@pytest.mark.parametrize("environment,host,other", [
    ("production", "beacontools.cc", "staging.beacontools.cc"),
    ("staging", "staging.beacontools.cc", "beacontools.cc"),
])
def test_recovery_and_cors_cannot_cross_environments(monkeypatch, environment, host, other) -> None:
    import relay.main as relay
    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", environment)
    monkeypatch.delenv("RELAY_ACCESS_SITE_URL", raising=False)
    assert relay._access_site_url("recover/#token=fake") == f"https://{host}/recover/#token=fake"
    cors = relay._EnvironmentCorsMiddleware(relay.app)
    assert cors.is_allowed_origin(f"https://{host}")
    assert not cors.is_allowed_origin(f"https://{other}")
    for invalid in (f"https://{other}", f"https://user@{host}", f"https://{host}/unexpected",
                    f"https://{host}?redirect=bad", f"http://{host}", f"https://{host}:444"):
        monkeypatch.setenv("RELAY_ACCESS_SITE_URL", invalid)
        with pytest.raises(relay.AccessConfigurationError):
            relay._access_site_url("recover/")


def test_smoke_check_retries_a_startup_connection_reset(monkeypatch) -> None:
    import scripts.check_relay_access_deployment as check
    health, catalog, _version, _schema = _payloads()
    responses = iter([ConnectionResetError("starting"), health, catalog])
    def fetch(*args, **kwargs):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item
    sleeps = []
    monkeypatch.setattr(check, "fetch_json", fetch)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    monkeypatch.setattr("sys.argv", ["check", "http://localhost", "--attempts", "2", "--delay", "0.1",
                                   "--expected-revision", "a" * 40])
    assert check.main() == 0
    assert sleeps == [0.1]


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


@pytest.mark.parametrize("reported", [False, None, "yes"])
def test_relay_deployment_contract_rejects_a_relay_that_cannot_serve_radar(reported) -> None:
    """Shared real radar is part of the annual entitlement, so a relay that does
    not state it can serve it must not be accepted. ``None`` and a truthy string
    are rejected alongside ``False``: the catalog has to answer, not be inferred."""
    health, catalog, version, schema = _payloads()
    catalog["capabilities"]["radar"] = reported

    with pytest.raises(RuntimeError, match="radar"):
        validate_payloads(health, catalog, expected_version=version, expected_schema=schema)

    catalog["capabilities"]["radar"] = True
    validate_payloads(health, catalog, expected_version=version, expected_schema=schema)


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
