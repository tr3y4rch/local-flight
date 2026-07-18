from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
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
from scripts.attest_release_artifact import create_attestation
from scripts.release_safety import is_sensitive_release_path, validate_public_bundle
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
        "version": "0.5.2",
        "platform": "linux",
        "architecture": "x86_64",
        "flavor": "desktop",
        "kind": "appimage",
    }


def test_pi_source_attestation_reads_embedded_version_and_source_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "LocalFlight-pi-source-0.5.2.zip"
    root = "LocalFlight-pi-source-0.5.2"
    metadata = {
        "schema_version": 1,
        "version": "0.5.2",
        "platform": "raspberry-pi",
        "architecture": "source",
        "flavor": "source",
        "kind": "zip",
    }
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(f"{root}/release-metadata.json", json.dumps(metadata))
        archive.writestr(f"{root}/pyproject.toml", '[project]\nversion = "0.5.2"\n')
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
        return "platform MACOS\nminos 12.0\nsdk 15.0\n"

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


def test_release_locks_are_hash_pinned_from_python_311() -> None:
    for name in (
        "release-core.txt",
        "release-server.txt",
        "release-native.txt",
        "release-pi-bookworm.txt",
        "release-pi-trixie.txt",
    ):
        text = (ROOT / "requirements" / name).read_text(encoding="utf-8")
        assert "uv pip compile --universal --python-version 3.11" in text
        assert "--hash=sha256:" in text
    native = (ROOT / "requirements" / "release-native.txt").read_text(encoding="utf-8")
    bookworm = (ROOT / "requirements" / "release-pi-bookworm.txt").read_text(encoding="utf-8")
    trixie = (ROOT / "requirements" / "release-pi-trixie.txt").read_text(encoding="utf-8")
    assert "pyside6==6.8.3" in native
    assert "pystray==0.19.5" in native
    assert "pyside6==6.7.3" in bookworm
    assert "pyside6==6.8.3" in trixie


def test_release_workflow_limits_write_permission_to_draft_job() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-artifacts.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
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
    assert "gh api \"repos/${GITHUB_REPOSITORY}/releases/tags/${tag}\"" in workflow
    assert workflow.count("keychain=\"$RUNNER_TEMP/localflight-release.keychain-db\"") == 1
    assert workflow.count("deb=\"$(find dist -maxdepth 1 -name 'localflight-desktop_*.deb'") == 1
    fly_workflow = (ROOT / ".github" / "workflows" / "fly-deploy.yml").read_text(encoding="utf-8")
    assert "Smoke-test oversized public bug-report rejection" in fly_workflow
    assert 'b"x" * (512 * 1024)' in fly_workflow
    assert 'expected = {"detail": "Bug report request exceeds the 512 KiB limit."}' in fly_workflow
