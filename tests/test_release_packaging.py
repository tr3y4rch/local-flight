from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from localflight.platform.detect import Platform
from localflight.platform.gui_launcher import decide_gui_launch
from scripts import (
    package_linux_appimage,
    package_linux_deb,
    package_macos_installer,
    package_pi_source,
    package_windows_installer,
)
from scripts.attest_release_artifact import _version_matches, create_attestation
from scripts.release_safety import (
    REQUIRED_FROZEN_RUNTIME_RESOURCES,
    frozen_runtime_resource_path,
    is_excluded_frozen_data_path,
    is_private_install_metadata_path,
    is_sensitive_release_path,
    validate_frozen_runtime_resources,
    validate_public_bundle,
)
from scripts.verify_release_artifacts import (
    artifact_contracts,
    artifact_names,
    attestation_name,
    inspection_method,
    sha256_file,
    verify_release_attestations,
    verify_release_directory,
)


ROOT = Path(__file__).resolve().parents[1]


def _load_build_module():
    module_name = "localflight_release_build"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_release_build_matrix_rejects_cross_compilation_and_invalid_flavors() -> None:
    release_build = _load_build_module()
    target = release_build.BuildTarget("linux", "x86_64", "desktop", "linux-release")
    release_build.validate_target(target, actual_arch="x86_64")

    with pytest.raises(ValueError, match="Cross-compilation"):
        release_build.validate_target(target, actual_arch="aarch64")
    with pytest.raises(ValueError, match="desktop flavor"):
        release_build.validate_target(
            release_build.BuildTarget("macos", "aarch64", "server", "installer"),
            actual_arch="aarch64",
        )
    with pytest.raises(ValueError, match="not valid"):
        release_build.validate_target(
            release_build.BuildTarget("linux", "x86_64", "server", "appimage"),
            actual_arch="x86_64",
        )


def test_macos_bundle_architecture_is_passed_through_spec_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_build = _load_build_module()
    monkeypatch.setattr(release_build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(release_build, "BUILD", tmp_path / "build")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        assert check is True
        assert cwd == release_build.ROOT
        calls.append((command, env))
        dist = Path(command[command.index("--distpath") + 1])
        (dist / "LocalFlight.app").mkdir(parents=True)

    monkeypatch.setattr(release_build.subprocess, "run", fake_run)
    validated: list[Path] = []
    monkeypatch.setattr(
        release_build,
        "validate_frozen_runtime_resources",
        lambda bundle: validated.append(bundle),
    )
    target = release_build.BuildTarget("macos", "aarch64", "desktop", "bundle")

    bundle = release_build.build_bundle(target, clean=True)

    assert bundle == tmp_path / "dist" / "bundles" / target.build_key / "LocalFlight.app"
    assert len(calls) == 1
    assert validated == [bundle]
    command, env = calls[0]
    assert "--target-architecture" not in command
    assert env["LOCALFLIGHT_TARGET_ARCH"] == "arm64"


def test_clean_bundle_build_reports_stale_output_permission_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_build = _load_build_module()
    monkeypatch.setattr(release_build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(release_build, "BUILD", tmp_path / "build")
    monkeypatch.setattr(
        release_build.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("owned by another user")),
    )
    target = release_build.BuildTarget("macos", "aarch64", "desktop", "bundle")

    with pytest.raises(SystemExit, match="ownership and permissions"):
        release_build.build_bundle(target, clean=True)


def test_public_artifact_names_match_release_matrix() -> None:
    assert artifact_names("0.5.2") == (
        "LocalFlight-0.5.2-Setup.exe",
        "LocalFlight-0.5.2-macos-arm64.pkg",
        "LocalFlight-0.5.2-macos-x86_64.pkg",
        "LocalFlight-0.5.2-linux-x86_64.AppImage",
        "LocalFlight-0.5.2-linux-aarch64.AppImage",
        "localflight-desktop_0.5.2_amd64.deb",
        "localflight-desktop_0.5.2_arm64.deb",
        "localflight-server_0.5.2_amd64.deb",
        "localflight-server_0.5.2_arm64.deb",
        "LocalFlight-pi-source-0.5.2.zip",
    )


def test_windows_attestation_accepts_only_surrounding_pe_version_padding() -> None:
    assert _version_matches("0.5.2                                             ", "0.5.2")
    assert _version_matches("\0\t0.5.2.0 \r\n", "0.5.2")
    assert not _version_matches("0.5. 2", "0.5.2")
    assert not _version_matches("0.5.3", "0.5.2")


def _write_release_files(directory: Path) -> None:
    for name in artifact_names("0.5.2"):
        data = f"fake release artifact: {name}\n".encode()
        (directory / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        (directory / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="ascii")


def test_release_verifier_requires_exact_twenty_file_matrix(tmp_path: Path) -> None:
    _write_release_files(tmp_path)
    assert len(verify_release_directory(tmp_path, "0.5.2")) == 20

    (tmp_path / "unexpected.txt").write_text("not part of the release", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected release files"):
        verify_release_directory(tmp_path, "0.5.2")


def _write_release_attestations(
    directory: Path,
    artifacts: Path,
    *,
    source_sha: str = "a" * 40,
) -> None:
    directory.mkdir()
    for contract in artifact_contracts("0.5.2"):
        artifact = artifacts / contract.name
        record = {
            "schema_version": 1,
            "source_sha": source_sha,
            "artifact": {
                "name": contract.name,
                "sha256": sha256_file(artifact),
                "size": artifact.stat().st_size,
            },
            "release": {
                "version": "0.5.2",
                "platform": contract.platform,
                "architecture": contract.architecture,
                "flavor": contract.flavor,
                "kind": contract.kind,
            },
            "inspection": {"method": inspection_method(contract)},
        }
        (directory / attestation_name(contract.name)).write_text(
            json.dumps(record),
            encoding="utf-8",
        )


def test_final_release_verifier_binds_all_ten_attestations_to_package_bytes(tmp_path: Path) -> None:
    artifacts = tmp_path / "release-files"
    artifacts.mkdir()
    _write_release_files(artifacts)
    attestations = tmp_path / "release-attestations"
    _write_release_attestations(attestations, artifacts)

    assert len(
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )
    ) == 10

    artifact = artifacts / "LocalFlight-0.5.2-linux-aarch64.AppImage"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="Artifact attestation mismatch"):
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )


def test_final_release_verifier_rejects_wrong_attested_architecture(tmp_path: Path) -> None:
    artifacts = tmp_path / "release-files"
    artifacts.mkdir()
    _write_release_files(artifacts)
    attestations = tmp_path / "release-attestations"
    _write_release_attestations(attestations, artifacts)
    path = attestations / attestation_name("LocalFlight-0.5.2-macos-arm64.pkg")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["release"]["architecture"] = "x86_64"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="Release identity attestation mismatch"):
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )


def test_final_release_verifier_rejects_wrong_attested_version(tmp_path: Path) -> None:
    artifacts = tmp_path / "release-files"
    artifacts.mkdir()
    _write_release_files(artifacts)
    attestations = tmp_path / "release-attestations"
    _write_release_attestations(attestations, artifacts)
    path = attestations / attestation_name("localflight-server_0.5.2_arm64.deb")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["release"]["version"] = "0.5.1"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="Release identity attestation mismatch"):
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )


def test_final_release_verifier_requires_exact_attestation_set(tmp_path: Path) -> None:
    artifacts = tmp_path / "release-files"
    artifacts.mkdir()
    _write_release_files(artifacts)
    attestations = tmp_path / "release-attestations"
    _write_release_attestations(attestations, artifacts)
    missing = attestations / attestation_name("LocalFlight-0.5.2-Setup.exe")
    missing.unlink()
    with pytest.raises(ValueError, match="Missing attestation files"):
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )

    missing.write_text("{}", encoding="utf-8")
    (attestations / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected attestation files"):
        verify_release_attestations(
            attestations,
            artifacts,
            "0.5.2",
            source_sha="a" * 40,
        )


@pytest.mark.parametrize(
    "path",
    (
        Path("AGENTS.md"),
        Path("operator/operations.md"),
        Path("operator/.env.example"),
        Path("docs/release-handoff.md"),
        Path("docs/internal_notes.txt"),
        Path("mobile/APP_STORE_REVIEW_NOTES.md"),
        Path("keys/signing.p12"),
        Path("assets/.DS_Store"),
    ),
)
def test_release_safety_rejects_internal_and_sensitive_names(path: Path) -> None:
    assert is_sensitive_release_path(path)


def test_release_safety_allows_only_certifi_public_ca_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    for relative in (
        Path("_internal/certifi/cacert.pem"),
        Path("Contents/Resources/certifi/cacert.pem"),
    ):
        certifi = bundle / relative
        certifi.parent.mkdir(parents=True, exist_ok=True)
        certifi.write_text(
            "-----BEGIN CERTIFICATE-----\nFAKE-PUBLIC-CA-FOR-TESTS\n"
            "-----END CERTIFICATE-----\n",
            encoding="ascii",
        )

    validate_public_bundle(bundle)

    for relative in (
        Path("cacert.pem"),
        Path("certifi/cacert.pem"),
        Path("_internal/other/cacert.pem"),
        Path("_internal/certifi/client.pem"),
        Path("_internal/certifi/CACERT.pem"),
        Path("Contents/Frameworks/certifi/cacert.pem"),
        Path("Contents/Resources/other/cacert.pem"),
        Path("Contents/Resources/certifi/client.pem"),
    ):
        assert is_sensitive_release_path(relative)


def test_release_safety_rejects_direct_url_metadata_even_without_private_path(
    tmp_path: Path,
) -> None:
    relative = Path("_internal/localflight-0.5.2.dist-info/direct_url.json")
    assert is_private_install_metadata_path(relative)
    assert is_sensitive_release_path(relative)

    bundle = tmp_path / "bundle"
    metadata = bundle / relative
    metadata.parent.mkdir(parents=True)
    metadata.write_text('{"url":"https://example.invalid/localflight.whl"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="direct_url.json"):
        validate_public_bundle(bundle)


@pytest.mark.parametrize(
    "relative",
    (
        Path("_internal/localflight-0.5.2.dist-info/direct_url.json"),
        Path("cryptography-50.0.1.dist-info/sboms/cryptography-rust.cyclonedx.json"),
        Path("localflight/decode/mappings/__pycache__/airports.cpython-311.pyc"),
    ),
)
def test_release_safety_excludes_runtime_irrelevant_frozen_data(relative: Path) -> None:
    assert is_excluded_frozen_data_path(relative)
    assert is_sensitive_release_path(relative)


def test_pyinstaller_spec_excludes_unsafe_frozen_data_before_collect() -> None:
    spec = (ROOT / "LocalFlight.spec").read_text(encoding="utf-8")
    analysis = spec.index("a = Analysis(")
    exclusion = spec.index("is_excluded_frozen_data_path(Path(entry[0]))", analysis)
    collect = spec.index("coll = COLLECT(", exclusion)

    assert analysis < exclusion < collect


def test_pyinstaller_and_wheel_metadata_include_matrix_generator_template() -> None:
    spec = (ROOT / "LocalFlight.spec").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '("src/localflight/sources/matrix/client.py", "localflight/sources/matrix")' in spec
    assert '"sources/matrix/client.py"' in pyproject
    assert package_pi_source._is_release_file(Path("src/localflight/sources/matrix/client.py"))


def _write_frozen_runtime_resources(bundle: Path, prefix: Path) -> None:
    for relative in REQUIRED_FROZEN_RUNTIME_RESOURCES:
        target = bundle / prefix / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"runtime resource: {relative.as_posix()}\n", encoding="utf-8")


@pytest.mark.parametrize("prefix", (Path("_internal"), Path("Contents/Resources")))
def test_frozen_runtime_resource_contract_supports_binary_bundle_layouts(
    tmp_path: Path,
    prefix: Path,
) -> None:
    bundle = tmp_path / "bundle"
    _write_frozen_runtime_resources(bundle, prefix)

    validate_frozen_runtime_resources(bundle)
    for relative in REQUIRED_FROZEN_RUNTIME_RESOURCES:
        assert frozen_runtime_resource_path(bundle, relative) == bundle / prefix / relative


def test_frozen_runtime_resource_contract_rejects_missing_matrix_generator(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    prefix = Path("_internal")
    _write_frozen_runtime_resources(bundle, prefix)
    (bundle / prefix / "localflight/sources/matrix/client.py").unlink()

    with pytest.raises(RuntimeError, match="localflight/sources/matrix/client.py"):
        validate_frozen_runtime_resources(bundle)


@pytest.mark.parametrize(
    "workstation_path",
    (
        "/Users/example/Projects/local-flight",
        "/home/example/local-flight",
        r"C:\Users\example\local-flight",
    ),
)
def test_release_safety_rejects_workstation_paths(tmp_path: Path, workstation_path: str) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "metadata.txt").write_text(f"built from {workstation_path}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="workstation path"):
        validate_public_bundle(bundle)


def test_release_safety_does_not_decode_binary_payloads(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "payload.txt").write_bytes(b"\0/Users/example/private")
    validate_public_bundle(bundle)


def test_release_safety_allows_public_pi_runtime_homes_and_env_example(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env.example").write_text("FAKE_PROVIDER_KEY=replace-me\n", encoding="utf-8")
    (bundle / "service.txt").write_text(
        "/home/pi/.localflight\n/home/localflight/.localflight\n/home/$SERVICE_USER/.Xauthority\n",
        encoding="utf-8",
    )
    validate_public_bundle(bundle)


def test_windows_packager_scans_bundle_before_inno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _fake_bundle(tmp_path / "windows-bundle", "LocalFlight.exe")
    (bundle / "AGENTS.md").write_text("internal context", encoding="utf-8")
    monkeypatch.setattr(package_windows_installer.sys, "platform", "win32")

    with pytest.raises(SystemExit, match="unsafe public-release paths"):
        package_windows_installer.main(["--app-dir", str(bundle)])


def test_macos_packager_scans_bundle_before_signing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tmp_path / "LocalFlight.app"
    app.mkdir()
    (app / "operator").mkdir()
    (app / "operator" / "notes.md").write_text("private", encoding="utf-8")
    monkeypatch.setattr(package_macos_installer.sys, "platform", "darwin")
    monkeypatch.setattr(package_macos_installer, "native_architecture", lambda: "arm64")
    monkeypatch.setattr(
        package_macos_installer,
        "require_release_credentials",
        lambda: {
            "CODESIGN_IDENTITY": "Developer ID Application: Test",
            "PKG_SIGN_IDENTITY": "Developer ID Installer: Test",
            "NOTARIZE_PROFILE": "test",
        },
    )

    with pytest.raises(SystemExit, match="unsafe public-release paths"):
        package_macos_installer.main(["--app", str(app), "--target-arch", "arm64"])


def test_pi_packager_scans_fully_staged_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.5.2"\n', encoding="utf-8")
    (root / "README.md").write_text("built in /Users/private/local-flight\n", encoding="utf-8")
    monkeypatch.setattr(package_pi_source, "ROOT", root)
    monkeypatch.setattr(package_pi_source, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(package_pi_source, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(
        package_pi_source,
        "_release_files",
        lambda: [Path("pyproject.toml"), Path("README.md")],
    )

    with pytest.raises(SystemExit, match="workstation path"):
        package_pi_source.main()


def test_generic_linux_native_is_windowed_unless_kiosk_is_explicit() -> None:
    windowed = decide_gui_launch(
        Platform.LINUX,
        {"LOCALFLIGHT_GUI_MODE": "auto", "DISPLAY": ":0"},
        native_probe=lambda: True,
    )
    fullscreen = decide_gui_launch(
        Platform.LINUX,
        {
            "LOCALFLIGHT_GUI_MODE": "native",
            "LOCALFLIGHT_NATIVE_FULLSCREEN": "1",
            "WAYLAND_DISPLAY": "wayland-0",
        },
        native_probe=lambda: True,
    )

    assert windowed.effective_mode == "native"
    assert windowed.fullscreen is False
    assert fullscreen.effective_mode == "native"
    assert fullscreen.fullscreen is True


def _stop_headless_loop(*_args, **_kwargs) -> None:
    raise KeyboardInterrupt


def test_headless_first_run_defers_scheduler_until_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    import localflight.__main__ as main_module

    scheduler_calls: list[str] = []
    watcher_calls: list[bool] = []
    monkeypatch.setattr(main_module, "_is_first_launch", lambda: True)
    monkeypatch.setattr(main_module, "_start_scheduler", lambda: scheduler_calls.append("start"))
    monkeypatch.setattr(main_module, "_start_uvicorn", lambda: None)
    monkeypatch.setattr(main_module, "_wait_for_server", lambda **_kwargs: True)
    monkeypatch.setattr(
        main_module,
        "_start_setup_watcher",
        lambda *_args, open_display=True: watcher_calls.append(open_display),
    )
    monkeypatch.setattr(main_module.time, "sleep", _stop_headless_loop)

    with pytest.raises(SystemExit) as exc_info:
        main_module._run_headless()

    assert exc_info.value.code == 0
    assert scheduler_calls == []
    assert watcher_calls == [False]


def test_headless_configured_run_starts_scheduler_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    import localflight.__main__ as main_module

    scheduler_calls: list[str] = []
    monkeypatch.setattr(main_module, "_is_first_launch", lambda: False)
    monkeypatch.setattr(main_module, "_start_scheduler", lambda: scheduler_calls.append("start"))
    monkeypatch.setattr(main_module, "_start_uvicorn", lambda: None)
    monkeypatch.setattr(main_module, "_wait_for_server", lambda **_kwargs: True)
    monkeypatch.setattr(main_module, "_start_setup_watcher", lambda *_args, **_kwargs: pytest.fail("unexpected watcher"))
    monkeypatch.setattr(main_module.time, "sleep", _stop_headless_loop)

    with pytest.raises(SystemExit):
        main_module._run_headless()

    assert scheduler_calls == ["start"]


def _fake_bundle(path: Path, executable_name: str) -> Path:
    path.mkdir(parents=True)
    executable = path / executable_name
    executable.write_bytes(b"frozen executable")
    executable.chmod(0o755)
    (path / "_internal").mkdir()
    (path / "_internal" / "runtime.bin").write_bytes(b"runtime")
    return path


def test_appimage_stage_uses_user_runtime_and_no_autostart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _fake_bundle(tmp_path / "bundle", "LocalFlight")
    monkeypatch.setattr(package_linux_appimage, "BUILD", tmp_path / "build")
    appdir = package_linux_appimage.stage_appdir(bundle, "x86_64")

    apprun = (appdir / "AppRun").read_text(encoding="utf-8")
    desktop = (appdir / "cc.beacontools.localflight.desktop").read_text(encoding="utf-8")
    assert 'exec "$HERE/usr/lib/localflight/LocalFlight" "$@"' in apprun
    assert "Exec=LocalFlight" in desktop
    assert os.readlink(appdir / "usr" / "bin" / "LocalFlight") == "../lib/localflight/LocalFlight"
    assert not (appdir / "etc" / "systemd").exists()
    metadata = json.loads(
        (appdir / "usr" / "share" / "localflight" / "release-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata == {
        "schema_version": 1,
        "version": "0.6.0",
        "platform": "linux",
        "architecture": "x86_64",
        "flavor": "desktop",
        "kind": "appimage",
    }


def test_pi_source_attestation_reads_embedded_version_and_source_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "LocalFlight-pi-source-0.6.0.zip"
    root = "LocalFlight-pi-source-0.6.0"
    metadata = {
        "schema_version": 1,
        "version": "0.6.0",
        "platform": "raspberry-pi",
        "architecture": "source",
        "flavor": "source",
        "kind": "zip",
    }
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(f"{root}/release-metadata.json", json.dumps(metadata))
        archive.writestr(f"{root}/pyproject.toml", '[project]\nversion = "0.6.0"\n')
    digest = sha256_file(artifact)
    (tmp_path / f"{artifact.name}.sha256").write_text(
        f"{digest}  {artifact.name}\n",
        encoding="ascii",
    )

    output = create_attestation(artifact, tmp_path / "attestations", source_sha="b" * 40)
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["artifact"]["sha256"] == digest
    assert record["release"] == {key: value for key, value in metadata.items() if key != "schema_version"}
    assert record["inspection"] == {"method": "pi-source-embedded-metadata-v1"}


def test_debian_desktop_and_server_layout_contracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(package_linux_deb, "BUILD", tmp_path / "build")
    desktop_bundle = _fake_bundle(tmp_path / "desktop-bundle", "LocalFlight")
    server_bundle = _fake_bundle(tmp_path / "server-bundle", "localflight-server")

    desktop = package_linux_deb.stage_package(desktop_bundle, "amd64", "desktop", "0.5.2")
    server = package_linux_deb.stage_package(server_bundle, "arm64", "server", "0.5.2")
    desktop_control = (desktop / "DEBIAN" / "control").read_text(encoding="utf-8")
    server_control = (server / "DEBIAN" / "control").read_text(encoding="utf-8")

    assert os.readlink(desktop / "usr" / "bin" / "localflight") == "../../opt/localflight/LocalFlight"
    assert "Conflicts: localflight-server" in desktop_control
    assert "libxcb-cursor0" in desktop_control
    assert "libxkbcommon-x11-0" in desktop_control
    assert "libwayland-client0" in desktop_control
    assert "libopengl0" in desktop_control
    assert "Package: localflight-server" in server_control
    assert "Depends: adduser," in server_control
    assert "Conflicts: localflight-desktop" in server_control
    assert (server / "lib" / "systemd" / "system" / "localflight-server.service").is_file()


def test_server_maintainer_scripts_respect_policy_and_preserve_state() -> None:
    scripts = ROOT / "installers" / "linux" / "debian" / "server"
    postinst = (scripts / "postinst").read_text(encoding="utf-8")
    prerm = (scripts / "prerm").read_text(encoding="utf-8")
    postrm = (scripts / "postrm").read_text(encoding="utf-8")

    assert "deb-systemd-invoke restart" in postinst
    assert "deb-systemd-invoke start" in postinst
    assert "/usr/sbin/policy-rc.d" in postinst
    assert "systemctl enable --now" not in postinst
    assert "deb-systemd-invoke stop" in prerm
    assert "retain /var/lib/localflight" in postrm
    assert "rm -rf /var/lib/localflight" not in postrm


def test_server_service_is_headless_and_hardened() -> None:
    service = (ROOT / "installers" / "linux" / "localflight-server.service").read_text(encoding="utf-8")
    assert "User=localflight" in service
    assert "Environment=HOME=/var/lib/localflight" in service
    assert "Environment=LOCALFLIGHT_GUI_MODE=headless" in service
    assert "UMask=0077" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths=/var/lib/localflight" in service
    assert "ExecStart=/opt/localflight-server/localflight-server" in service


def test_macos_bundle_architecture_and_deployment_target_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "LocalFlight.app" / "Contents" / "MacOS" / "LocalFlight"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mach-o")

    def valid_output(command: list[str]) -> str:
        if command[0] == "file":
            return "Mach-O 64-bit executable arm64\n"
        if command[0] == "lipo":
            return "arm64\n"
        return """Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 12.0
      sdk 15.0
"""

    monkeypatch.setattr(package_macos_installer, "run_output", valid_output)
    assert package_macos_installer.validate_macos_bundle(executable.parents[2], "arm64") == [executable]

    monkeypatch.setattr(
        package_macos_installer,
        "run_output",
        lambda command: "Mach-O 64-bit executable arm64\n"
        if command[0] == "file"
        else ("x86_64 arm64\n" if command[0] == "lipo" else "minos 12.0\n"),
    )
    with pytest.raises(RuntimeError, match="Unexpected Mach-O slices"):
        package_macos_installer.validate_macos_bundle(executable.parents[2], "arm64")


def test_macos_bundle_accepts_legacy_intel_deployment_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "LocalFlight.app" / "Contents" / "MacOS" / "LocalFlight"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mach-o")

    def legacy_output(command: list[str]) -> str:
        if command[0] == "file":
            return "Mach-O 64-bit executable x86_64\n"
        if command[0] == "lipo":
            return "x86_64\n"
        return """Load command 7
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.9
      sdk 26.5
"""

    monkeypatch.setattr(package_macos_installer, "run_output", legacy_output)

    assert package_macos_installer.validate_macos_bundle(executable.parents[2], "x86_64") == [executable]


@pytest.mark.parametrize(
    "build_info",
    (
        "Load command 7\n      cmd LC_VERSION_MIN_MACOSX\n  cmdsize 16\n      sdk 26.5\n",
        "Load command 7\n      cmd LC_SOURCE_VERSION\n  cmdsize 16\n  version 10.9\n",
    ),
)
def test_macos_bundle_rejects_missing_or_unrelated_deployment_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build_info: str,
) -> None:
    executable = tmp_path / "LocalFlight.app" / "Contents" / "MacOS" / "LocalFlight"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mach-o")

    def output(command: list[str]) -> str:
        if command[0] == "file":
            return "Mach-O 64-bit executable x86_64\n"
        if command[0] == "lipo":
            return "x86_64\n"
        return build_info

    monkeypatch.setattr(package_macos_installer, "run_output", output)

    with pytest.raises(RuntimeError, match="Could not read a deployment target"):
        package_macos_installer.validate_macos_bundle(executable.parents[2], "x86_64")


def test_macos_bundle_rejects_legacy_deployment_target_above_release_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "LocalFlight.app" / "Contents" / "MacOS" / "LocalFlight"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mach-o")

    def output(command: list[str]) -> str:
        if command[0] == "file":
            return "Mach-O 64-bit executable x86_64\n"
        if command[0] == "lipo":
            return "x86_64\n"
        return "Load command 7\n      cmd LC_VERSION_MIN_MACOSX\n  version 13.0\n"

    monkeypatch.setattr(package_macos_installer, "run_output", output)

    with pytest.raises(RuntimeError, match=r"requires macOS 13\.0"):
        package_macos_installer.validate_macos_bundle(executable.parents[2], "x86_64")


def test_release_locks_are_hash_pinned_from_python_311() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = set(project["project"]["dependencies"])
    assert (
        "cryptography>=48.0.1,<49; sys_platform == 'darwin' and platform_machine == 'x86_64'"
        in project_dependencies
    )
    assert (
        "cryptography>=50.0.1; sys_platform != 'darwin' or platform_machine != 'x86_64'"
        in project_dependencies
    )

    core_input = (ROOT / "requirements" / "release-core.in").read_text(encoding="utf-8")
    assert (
        'cryptography==48.0.1 ; sys_platform == "darwin" and platform_machine == "x86_64"'
        in core_input
    )
    assert (
        'cryptography==50.0.1 ; sys_platform != "darwin" or platform_machine != "x86_64"'
        in core_input
    )

    locks: dict[str, str] = {}
    for name in (
        "release-core.txt",
        "release-server.txt",
        "release-native.txt",
        "release-pi-bookworm.txt",
        "release-pi-trixie.txt",
    ):
        text = (ROOT / "requirements" / name).read_text(encoding="utf-8")
        locks[name] = text
        assert "uv pip compile --universal --python-version 3.11" in text
        assert "--hash=sha256:" in text
        assert (
            "cryptography==48.0.1 ; platform_machine == 'x86_64' and sys_platform == 'darwin'"
            in text
        )
        assert (
            "cryptography==50.0.1 ; platform_machine != 'x86_64' or sys_platform != 'darwin'"
            in text
        )
        assert "3e4a1a3232eef2e6c732827d5722db29a0cc8b27af2a4d865b094cf954be9ca1" in text
    native = locks["release-native.txt"]
    bookworm = locks["release-pi-bookworm.txt"]
    trixie = locks["release-pi-trixie.txt"]
    assert "pyside6==6.8.3" in native
    assert "pystray==0.19.5" in native
    assert "pyside6==6.7.3" in bookworm
    assert "pyside6==6.8.3" in trixie


def test_release_workflow_limits_write_permission_to_draft_job() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "release_suffix:" in workflow
    assert "RELEASE_SUFFIX: ${{ inputs.release_suffix }}" in workflow
    draft = workflow.split("  draft-release:", 1)[1]
    assert "permissions:\n      contents: write" in draft
    assert "LocalFlight-*-linux-${{ matrix.public_arch }}.AppImage" in workflow
    assert "releases/download/12/$asset" in workflow
    assert "d918b4df547b388ef253f3c9e7f6529ca81a885395c31f619d9aaf7030499a13" in workflow
    assert "c9d058310a4e04b9fbbd81340fff2b5fb44943a630b31881e321719f271bd41a" in workflow
    assert "pattern: package-*\n          path: release-files" in workflow
    assert "pattern: attestation-*\n          path: release-attestations" in workflow
    assert "--attestations release-attestations" in workflow
    assert 'test "${#files[@]}" -eq 20' in workflow
    assert "Draft release asset inventory does not match the verified 20-file matrix." in workflow
    assert '--json isDraft --jq .isDraft' in workflow
    assert '--json targetCommitish --jq .targetCommitish' in workflow
    assert 'test "$target_commitish" = "$SOURCE_SHA"' in workflow
    assert 'tag="${tag}-${RELEASE_SUFFIX}"' in workflow
    assert "Maintenance artifact rebuild" in workflow
    assert 'gh api "repos/${GITHUB_REPOSITORY}/releases/${release_id}"' in workflow
    assert workflow.count("keychain=\"$RUNNER_TEMP/localflight-release.keychain-db\"") == 1
    assert workflow.count("deb=\"$(find dist -maxdepth 1 -name 'localflight-desktop_*.deb'") == 1
    macos_job = workflow.split("  macos:", 1)[1].split("  linux-desktop:", 1)[0]
    assert macos_job.count("--only-binary=:all:") == 1
    assert "Verify the native cryptography wheel" in macos_job
    assert "cryptography.__version__ == expected" in macos_job
    assert "unexpectedly depends on host OpenSSL libraries" in macos_job
    fly_workflow = (ROOT / ".github" / "workflows" / "fly-deploy.yml").read_text(encoding="utf-8")
    assert "Smoke-test oversized public bug-report rejection" in fly_workflow
    assert 'b"x" * (512 * 1024)' in fly_workflow
    assert 'expected = {"detail": "Bug report request exceeds the 512 KiB limit."}' in fly_workflow
