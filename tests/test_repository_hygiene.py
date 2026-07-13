from __future__ import annotations

import json
import importlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

from localflight.core.notices import NoticeRegistry, attach_notices, make_notice
from localflight.storage.private_files import ensure_private_dir, write_private_text


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "audit/server.pem",
        "audit/signing.pfx",
        "audit/private.key",
        "audit/device.crt",
        "audit/service-account.json",
        "mobile/google-services.json",
        "mobile/GoogleService-Info.plist",
        "audit/credentials.json",
        ".npmrc",
        ".pypirc",
        ".netrc",
    ],
)
def test_representative_credentials_are_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, path


@pytest.mark.parametrize(
    "path",
    [
        "credentials.example.json",
        "secrets.example.json",
        "service-account.example.json",
        "server.example.pem",
        ".npmrc.example",
        ".env.example",
    ],
)
def test_explicit_credential_examples_remain_trackable(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1, path


def test_pi_package_sensitive_classifier_and_internal_exclusions() -> None:
    from scripts import package_pi_source

    for path in (
        Path("keys/server.pem"),
        Path("mobile/google-services.json"),
        Path("credentials.json"),
        Path("publish/app-store-connect-key.json"),
    ):
        assert package_pi_source._is_sensitive_release_path(path)
    for path in (Path("credentials.example.json"), Path("service-account.example.json")):
        assert not package_pi_source._is_sensitive_release_path(path)
    for path in (
        Path("AGENTS.md"),
        Path("operator/OPERATIONS.md"),
        Path("docs/native-first-redesign.md"),
        Path("docs/brand-renditions/v2/index.html"),
        Path("tmp/render.png"),
    ):
        assert not package_pi_source._is_release_file(path)


def test_client_info_uses_support_fingerprint_not_raw_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.storage import install
    from localflight.ui import server

    raw_id = "550e8400-e29b-41d4-a716-446655440000"
    fingerprint = "lf-7d4c9e2a91b3"
    monkeypatch.setattr(install, "get_install_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(install, "get_activation_token", lambda: "")
    payload = server.setup_client_info()
    encoded = json.dumps(payload)
    assert payload["install_id"] == fingerprint
    assert payload["install_fingerprint"] == fingerprint
    assert raw_id not in encoded


def test_admin_system_returns_logical_snapshot_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.storage import install
    from localflight.ui import api

    monkeypatch.setattr(install, "get_install_fingerprint", lambda: "lf-public-support")
    payload = api.api_admin_system()
    assert payload["snapshot_dir"] == "~/.localflight/storage/data"
    assert str(Path.home()) not in json.dumps(payload)
    assert payload["install_id"] == payload["install_fingerprint"] == "lf-public-support"


def test_mobile_summary_redacts_raw_identity_and_home_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.ui import api

    raw_id = "550e8400-e29b-41d4-a716-446655440000"
    home_path = "/Users/private-person/.localflight/storage/data"
    monkeypatch.setattr(api, "api_health", lambda: {"ok": False, "last_error": f"failed at {home_path}"})
    monkeypatch.setattr(api, "api_get_config", lambda: {})
    monkeypatch.setattr(api, "api_admin_system", lambda: {"install_id": raw_id, "snapshot_dir": home_path})
    monkeypatch.setattr(api, "api_admin_connections", lambda: {})
    monkeypatch.setattr(api, "api_admin_updates", lambda: {})
    monkeypatch.setattr(api, "api_admin_budget", lambda: {})
    monkeypatch.setattr(api, "api_admin_scheduler_status", lambda: {})
    monkeypatch.setattr(api, "api_metar", lambda: {})

    encoded = json.dumps(api._mobile_summary_payload())
    assert raw_id not in encoded
    assert home_path not in encoded


def test_feedback_and_user_templates_do_not_reference_raw_identity_helpers() -> None:
    templates = ROOT / "src" / "localflight" / "ui" / "templates"
    rendered_sources = "\n".join(path.read_text(encoding="utf-8") for path in templates.glob("*.html"))
    assert "get_install_id" not in rendered_sources
    feedback = (templates / "feedback.html").read_text(encoding="utf-8")
    assert "client.install_fingerprint || sys.install_id" in feedback


def test_notice_contract_redacts_raw_ids_paths_and_secrets() -> None:
    raw_uuid = "550e8400-e29b-41d4-a716-446655440000"
    notice = make_notice(
        "radar.test_failure",
        "warning",
        f"Failed at /Users/private/person/data.json for {raw_uuid} token=super-secret",
        next_step="Open /home/person/.localflight/logs/app.log",
        action={"kind": "logs", "label": "Open Logs", "target": "/logs"},
    )
    encoded = json.dumps(notice)
    assert raw_uuid not in encoded
    assert "/Users/private" not in encoded
    assert "/home/person" not in encoded
    assert "super-secret" not in encoded
    assert notice["action"]["target"] == "/logs"

    registry = NoticeRegistry(max_entries=10)
    payload = attach_notices(
        {},
        [notice],
        route_family="radar",
        source_category="traffic",
    )
    registry.record(notice, route_family="radar", source_category="traffic")
    assert payload["notices"][0]["code"] == "radar.test_failure"
    row = registry.recent()[0]
    assert set(row) == {
        "code", "tone", "message", "route_family", "source_category",
        "first_seen", "last_seen", "occurrence_count",
    }


@pytest.mark.skipif(os.name == "nt", reason="Windows uses ACLs rather than POSIX modes")
def test_private_file_helpers_repair_posix_modes(tmp_path: Path) -> None:
    secret_dir = tmp_path / ".localflight"
    ensure_private_dir(secret_dir)
    secret_dir.chmod(0o755)
    ensure_private_dir(secret_dir)
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700

    secret_file = secret_dir / "activation_token"
    write_private_text(secret_file, "secret")
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600


def test_public_context_and_brand_manifests_are_path_free() -> None:
    public_context = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    forbidden = (
        "/Users/",
        "C:\\Users\\",
        "build ID",
        "SHA256",
        "flyctl auth login",
        "wrangler login",
        "RELAY_ADMIN_PASSWORD",
    )
    for term in forbidden:
        assert term not in public_context

    for manifest_path in (
        ROOT / "assets" / "brand-manifest.json",
        ROOT / "docs" / "brand-renditions" / "v2" / "manifest.json",
    ):
        manifest = manifest_path.read_text(encoding="utf-8")
        assert "/Users/" not in manifest
        assert "C:\\Users\\" not in manifest


def test_brand_master_paths_accept_cli_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import render_brand_renditions, sync_brand_v2

    masters = {}
    for name in ("beacon_lockup", "beacon_mark", "local_flight_dark", "local_flight_light"):
        path = tmp_path / f"{name}.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>', encoding="utf-8")
        masters[name] = path

    sync_module = importlib.reload(sync_brand_v2)
    sync_module.configure_masters([
        "--beacon-lockup", str(masters["beacon_lockup"]),
        "--beacon-mark", str(masters["beacon_mark"]),
        "--local-flight-dark", str(masters["local_flight_dark"]),
        "--local-flight-light", str(masters["local_flight_light"]),
    ])
    assert sync_module.BEACON_LOCKUP == masters["beacon_lockup"]

    render_module = importlib.reload(render_brand_renditions)
    for key, env_name in render_module.BRAND_ENV.items():
        monkeypatch.setenv(env_name, str(masters[key]))
    render_module.configure_masters([])
    assert render_module.source_label(render_module.LOCAL_FLIGHT_LIGHT) == "local-flight-light-master"


def test_public_and_engineering_changelogs_have_separate_audiences() -> None:
    public = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    engineering = (ROOT / "docs" / "engineering-changelog.md").read_text(encoding="utf-8")
    assert "public, user-facing" in public
    assert "for\ncontributors" in engineering
    assert "/admin/api/" not in public
