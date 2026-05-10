"""Tests for the client-side relay_beat module."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from localflight.sources.web.relay_beat import _is_byok, _jitter, _send_now, _should_send


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
