from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from localflight.version import FALLBACK_VERSION


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.5.2"


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_release_version_is_consistent_across_desktop_mobile_and_worker() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    app = _json("mobile/app.json")["expo"]
    mobile_package = _json("mobile/package.json")
    mobile_lock = _json("mobile/package-lock.json")
    widget_package = _json("mobile/modules/localflight-widget-bridge/package.json")
    worker = (ROOT / "workers/beacontools.js").read_text(encoding="utf-8")
    windows = (ROOT / "installers/windows/LocalFlight.iss").read_text(encoding="utf-8")

    assert project["project"]["version"] == EXPECTED_VERSION
    assert FALLBACK_VERSION == EXPECTED_VERSION
    assert app["version"] == EXPECTED_VERSION
    assert app["extra"]["localFlightVersion"] == EXPECTED_VERSION
    assert mobile_package["version"] == EXPECTED_VERSION
    assert mobile_lock["version"] == EXPECTED_VERSION
    assert mobile_lock["packages"][""]["version"] == EXPECTED_VERSION
    assert mobile_lock["packages"]["modules/localflight-widget-bridge"]["version"] == EXPECTED_VERSION
    assert widget_package["version"] == EXPECTED_VERSION
    assert f'MINIMUM_PUBLIC_VERSION = "{EXPECTED_VERSION}"' in worker
    assert f'#define AppVersion "{EXPECTED_VERSION}"' in windows


def test_mobile_native_build_counters_match_052_contract() -> None:
    app = _json("mobile/app.json")["expo"]
    contract = (ROOT / "mobile/scripts/native-widget-contract.mjs").read_text(encoding="utf-8")

    assert app["ios"]["buildNumber"] == "8"
    assert app["android"]["versionCode"] == 11
    assert 'assert.equal(app.ios.buildNumber, "8")' in contract
    assert "assert.equal(app.android.versionCode, 11)" in contract


def test_current_release_help_and_notes_point_to_052() -> None:
    notes = ROOT / "docs/release-notes-0.5.2.md"
    server = (ROOT / "src/localflight/ui/server.py").read_text(encoding="utf-8")
    spec = (ROOT / "LocalFlight.spec").read_text(encoding="utf-8")

    assert notes.exists()
    assert "# Local Flight 0.5.2" in notes.read_text(encoding="utf-8")
    assert '"filename": "release-notes-0.5.2.md"' in server
    assert 'f"release-notes-{_VERSION}.md"' in spec
    assert re.search(r'current_release_notes[^\n]*localflight/ui/docs', spec, re.DOTALL)
