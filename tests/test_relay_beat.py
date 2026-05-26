"""Tests for the client-side relay_beat module."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import localflight.sources.web.relay_beat as relay_beat
from localflight.sources.web.relay_beat import _claim_send_slot, _is_byok, _jitter, _send_now, _should_send


@pytest.fixture(autouse=True)
def _reset_local_send_slot():
    relay_beat._last_send_at = 0.0
    yield
    relay_beat._last_send_at = 0.0


# ── _jitter ──────────────────────────────────────────────────────────────────

def test_jitter_within_bounds():
    base, spread = 30 * 60, 5 * 60
    for _ in range(1000):
        result = _jitter(base, spread)
        assert base - spread <= result <= base + spread, f"Out of bounds: {result}"


# ── _is_byok ─────────────────────────────────────────────────────────────────

def test_is_byok_false_when_no_key(monkeypatch):
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    assert _is_byok() is False


def test_is_byok_true_when_key_set_no_override(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "somekey")
    monkeypatch.delenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", raising=False)
    assert _is_byok() is True


def test_is_byok_true_when_key_and_enabled_one(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "somekey")
    monkeypatch.setenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "1")
    assert _is_byok() is True


def test_is_byok_true_when_aerodatabox_key_enabled(monkeypatch):
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-key")
    monkeypatch.setenv("LOCALFLIGHT_AERODATABOX_ENABLED", "1")
    assert _is_byok() is True


def test_is_byok_false_when_aerodatabox_key_disabled(monkeypatch):
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    monkeypatch.setenv("AERODATABOX_API_KEY", "adb-key")
    monkeypatch.setenv("LOCALFLIGHT_AERODATABOX_ENABLED", "0")
    assert _is_byok() is False


# ── _should_send ──────────────────────────────────────────────────────────────

def _make_config_path(tmp_path: Path) -> Path:
    """Return a fake config path whose parent dir exists (no setup_complete)."""
    cfg_dir = tmp_path / ".localflight"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "config.json"


def test_should_send_false_when_no_setup_complete(tmp_path):
    fake_cfg = _make_config_path(tmp_path)
    # setup_complete does NOT exist
    with patch("localflight.storage.config.config_path", return_value=fake_cfg), \
         patch("localflight.sources.web.relay_beat._is_byok", return_value=False):
        result = _should_send()
    assert result is False


def test_should_send_false_when_source_virtual(tmp_path):
    fake_cfg = _make_config_path(tmp_path)
    (fake_cfg.parent / "setup_complete").touch()
    cfg_mock = MagicMock()
    cfg_mock.source = "virtual"

    with patch("localflight.storage.config.config_path", return_value=fake_cfg), \
         patch("localflight.storage.config.load_config", return_value=cfg_mock), \
         patch("localflight.sources.web.relay_beat._is_byok", return_value=False):
        result = _should_send()
    assert result is False


def test_should_send_false_when_byok(tmp_path):
    fake_cfg = _make_config_path(tmp_path)
    (fake_cfg.parent / "setup_complete").touch()
    cfg_mock = MagicMock()
    cfg_mock.source = "real"

    with patch("localflight.storage.config.config_path", return_value=fake_cfg), \
         patch("localflight.storage.config.load_config", return_value=cfg_mock), \
         patch("localflight.sources.web.relay_beat._is_byok", return_value=True):
        result = _should_send()
    assert result is False


def test_should_send_returns_false_on_exception():
    with patch("localflight.storage.config.config_path", side_effect=RuntimeError("boom")):
        result = _should_send()
    assert result is False


# ── local send backstop ──────────────────────────────────────────────────────

def test_claim_send_slot_rate_limits_within_local_cooldown(monkeypatch):
    monkeypatch.setattr(relay_beat.time, "monotonic", lambda: 1000.0)

    assert _claim_send_slot() is True
    assert _claim_send_slot() is False


def test_claim_send_slot_allows_after_local_cooldown(monkeypatch):
    ticks = iter([1000.0, 1301.0])
    monkeypatch.setattr(relay_beat.time, "monotonic", lambda: next(ticks))

    assert _claim_send_slot() is True
    assert _claim_send_slot() is True


def test_fire_heartbeat_respects_should_send_gate(monkeypatch):
    claimed = MagicMock(return_value=True)
    sent = MagicMock()
    monkeypatch.setattr(relay_beat, "_should_send", lambda: False)
    monkeypatch.setattr(relay_beat, "_claim_send_slot", claimed)
    monkeypatch.setattr(relay_beat, "_send_now", sent)

    async def _run() -> None:
        relay_beat.fire_heartbeat()
        await asyncio.sleep(0)

    asyncio.run(_run())

    claimed.assert_not_called()
    sent.assert_not_called()


def test_fire_heartbeat_respects_local_cooldown(monkeypatch):
    sent = MagicMock()
    monkeypatch.setattr(relay_beat, "_should_send", lambda: True)
    monkeypatch.setattr(relay_beat, "_claim_send_slot", lambda: False)
    monkeypatch.setattr(relay_beat, "_send_now", sent)

    async def _run() -> None:
        relay_beat.fire_heartbeat()
        await asyncio.sleep(0)

    asyncio.run(_run())

    sent.assert_not_called()


# ── _send_now (silent failure) ────────────────────────────────────────────────

def test_send_now_does_not_raise_on_connection_error():
    with patch("requests.post", side_effect=ConnectionError("network down")):
        _send_now()  # must not raise


def test_send_now_does_not_raise_on_timeout():
    import requests
    with patch("requests.post", side_effect=requests.exceptions.Timeout("timed out")):
        _send_now()  # must not raise


def test_send_now_does_not_raise_on_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("requests.post", return_value=mock_resp):
        _send_now()  # must not raise
