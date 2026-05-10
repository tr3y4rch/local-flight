"""Tests for the relay /v1/heartbeat endpoint."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import relay.main as relay_main

_VALID_UUID = "00000000-0000-0000-0000-000000000042"
_VALID_UUID_2 = "00000000-0000-0000-0000-000000000043"


def _use_temp_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay.db"))
    relay_main._ensure_schema()


@pytest.fixture(autouse=True)
def _clear_heartbeat_state():
    """Clear the in-memory rate-limiter between tests."""
    relay_main._heartbeat_last_seen.clear()
    yield
    relay_main._heartbeat_last_seen.clear()


def _beat(client: TestClient, install_id: str = _VALID_UUID, **extra) -> object:
    return client.post("/v1/heartbeat", json={"install_id": install_id, **extra})


def test_heartbeat_returns_ok(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    resp = _beat(client, app_version="0.2.6", os_family="Darwin", source_mode="real")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_heartbeat_writes_install_profile(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    _beat(client, app_version="0.2.6", os_family="Linux")
    conn = relay_main._connect()
    row = conn.execute(
        "SELECT install_id, app_version, os_family FROM install_profiles WHERE install_id=?",
        (_VALID_UUID,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["app_version"] == "0.2.6"
    assert row["os_family"] == "Linux"


def test_heartbeat_updates_last_seen(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    before = relay_main._utc_now()
    _beat(client)
    conn = relay_main._connect()
    last_seen = conn.execute(
        "SELECT last_seen FROM install_profiles WHERE install_id=?",
        (_VALID_UUID,),
    ).fetchone()["last_seen"]
    conn.close()
    assert last_seen >= before


def test_heartbeat_rate_limited_within_cooldown(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    # Pre-seed the rate limiter to simulate a very recent beat
    relay_main._heartbeat_last_seen[_VALID_UUID] = time.time()
    client = TestClient(relay_main.app)
    resp = _beat(client)
    assert resp.status_code == 429


def test_heartbeat_allowed_after_cooldown(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    # Seed an old timestamp (6 minutes ago) — past the 5-minute cooldown
    relay_main._heartbeat_last_seen[_VALID_UUID_2] = time.time() - 360
    client = TestClient(relay_main.app)
    resp = _beat(client, install_id=_VALID_UUID_2)
    assert resp.status_code == 200


def test_heartbeat_rejects_malformed_install_id(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    resp = client.post("/v1/heartbeat", json={"install_id": "not-a-uuid"})
    assert resp.status_code == 400


def test_heartbeat_does_not_log_to_request_log(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)
    _beat(client)
    conn = relay_main._connect()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM request_log WHERE install_id=?",
        (_VALID_UUID,),
    ).fetchone()["n"]
    conn.close()
    assert count == 0
