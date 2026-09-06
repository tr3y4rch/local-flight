from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient


REMOTE_TEST_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
REMOTE_TEST_KEY_BYTES = bytes(range(32))
REMOTE_TEST_NONCE = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"
REMOTE_TEST_INSTALL_REF = "abc123def456"
REMOTE_TEST_GRANT_REF = "rcg_test"
REMOTE_TEST_REQUEST_ID = "rcr_test"


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def test_lan_pairing_link_stays_compatible() -> None:
    from localflight.companion_pairing import build_pairing_deep_link

    link = build_pairing_deep_link("http://192.168.1.42:8000", source="qt", server_fingerprint="abc123")

    assert link.startswith("localflight://pair?")
    assert "server=http%3A%2F%2F192.168.1.42%3A8000" in link
    assert "server_fingerprint=abc123" in link
    assert "remote=1" not in link


def test_remote_host_exchanges_bearer_credential_for_one_time_ws_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.sources.web import remote_companion_agent

    captured: dict[str, object] = {}

    def _post(_url, **kwargs):
        captured.update(kwargs)
        return type(
            "Response",
            (),
            {
                "ok": True,
                "status_code": 200,
                "json": lambda self: {
                    "ok": True,
                    "ticket": "lfrws_one_time_ticket",
                    "websocket_path": "/v1/remote-companion/host/ws",
                },
            },
        )()

    monkeypatch.setattr(remote_companion_agent.requests, "post", _post)
    result = remote_companion_agent._request_remote_companion_ws_ticket(
        "https://relay.example.test",
        install_id="11111111-1111-4111-8111-111111111111",
        activation_token="lfr_long_lived_receiver_secret",
    )
    url = remote_companion_agent._relay_ws_url(
        "https://relay.example.test",
        install_id="11111111-1111-4111-8111-111111111111",
        websocket_path=result["websocket_path"],
    )

    assert captured["headers"]["Authorization"] == "Bearer lfr_long_lived_receiver_secret"
    assert captured["json"] == {"install_id": "11111111-1111-4111-8111-111111111111"}
    assert "activation_token" not in url
    assert "lfr_long_lived_receiver_secret" not in url
    assert "ticket=" not in url
    assert "lfrws_one_time_ticket" not in url


def test_remote_pairing_payload_adds_invite_fields(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.companion_pairing import remote_pairing_gateway_payload
    from localflight.storage.remote_companion import create_remote_invite

    invite = create_remote_invite(relay_url="https://relay.example.test")
    payload = remote_pairing_gateway_payload(invite=invite, base_url="http://192.168.1.42:8000")

    assert payload["preferred_url"] == "http://192.168.1.42:8000"
    assert "remote=1" in str(payload["deep_link"])
    assert f"invite_id={invite['invite_id']}" in str(payload["deep_link"])
    assert payload["remote_invite"]["install_ref"] == invite["install_ref"]


def test_remote_grant_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.storage.remote_companion import (
        consume_remote_invite,
        create_remote_grant_from_invite,
        create_remote_invite,
        get_remote_grant,
        list_remote_grants,
        revoke_remote_grant,
    )

    invite = create_remote_invite(relay_url="https://relay.example.test")
    consumed = consume_remote_invite(invite["invite_id"])
    assert consumed is not None

    grant = create_remote_grant_from_invite(
        consumed,
        companion_id="lfc_test_phone",
        client_name="Test phone",
        mobile_os="ios",
        device_type="phone",
        app_version="0.5.1",
    )

    assert grant["grant_ref"].startswith("rcg_")
    assert get_remote_grant(grant["grant_ref"])["companion_id"] == "lfc_test_phone"
    assert len(list_remote_grants(include_revoked=False)) == 1

    revoked = revoke_remote_grant(grant["grant_ref"])
    assert revoked and revoked["revoked_at"]
    assert list_remote_grants(include_revoked=False) == []


def test_remote_envelope_round_trip() -> None:
    from localflight.remote_companion_crypto import decrypt_envelope, encrypt_envelope, remote_aad
    from localflight.storage.remote_companion import validate_remote_key
    import os

    remote_key = validate_remote_key(base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("="))
    aad = remote_aad(
        install_ref="abc123def456",
        grant_ref="rcg_test",
        request_id="rcr_test",
        direction="request",
    )
    envelope = encrypt_envelope({"method": "GET", "path": "/api/mobile/summary"}, remote_key=remote_key, aad=aad)

    assert decrypt_envelope(envelope, remote_key=remote_key, aad=aad)["path"] == "/api/mobile/summary"
    with pytest.raises(Exception):
        decrypt_envelope(
            envelope,
            remote_key=remote_key,
            aad=remote_aad(
                install_ref="abc123def456",
                grant_ref="rcg_test",
                request_id="rcr_test",
                direction="response",
            ),
        )


def test_python_envelope_matches_mobile_aes_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from localflight.remote_companion_crypto import encrypt_envelope, remote_aad

    aad = remote_aad(
        install_ref=REMOTE_TEST_INSTALL_REF,
        grant_ref=REMOTE_TEST_GRANT_REF,
        request_id=REMOTE_TEST_REQUEST_ID,
        direction="request",
    )
    monkeypatch.setattr("localflight.remote_companion_crypto.secrets.token_bytes", lambda size: REMOTE_TEST_NONCE)

    envelope = encrypt_envelope(
        {"method": "GET", "path": "/api/mobile/summary"},
        remote_key=REMOTE_TEST_KEY,
        aad=aad,
    )

    assert envelope["alg"] == "A256GCM"
    assert base64.b64decode(envelope["nonce"]) == REMOTE_TEST_NONCE
    plaintext = AESGCM(REMOTE_TEST_KEY_BYTES).decrypt(
        REMOTE_TEST_NONCE,
        base64.b64decode(envelope["ciphertext"]) + base64.b64decode(envelope["tag"]),
        aad,
    )
    assert json.loads(plaintext.decode("utf-8")) == {
        "method": "GET",
        "path": "/api/mobile/summary",
    }


def test_mobile_shaped_envelope_decrypts_in_python() -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from localflight.remote_companion_crypto import decrypt_envelope, remote_aad

    aad = remote_aad(
        install_ref=REMOTE_TEST_INSTALL_REF,
        grant_ref=REMOTE_TEST_GRANT_REF,
        request_id=REMOTE_TEST_REQUEST_ID,
        direction="request",
    )
    mobile_plaintext = b'{"method":"POST","path":"/api/config","body":{"airport_iata":"ZRH"}}'
    sealed = AESGCM(REMOTE_TEST_KEY_BYTES).encrypt(REMOTE_TEST_NONCE, mobile_plaintext, aad)
    envelope = {
        "alg": "A256GCM",
        "nonce": _b64(REMOTE_TEST_NONCE),
        "ciphertext": _b64(sealed[:-16]),
        "tag": _b64(sealed[-16:]),
    }

    assert decrypt_envelope(envelope, remote_key=REMOTE_TEST_KEY, aad=aad) == {
        "method": "POST",
        "path": "/api/config",
        "body": {"airport_iata": "ZRH"},
    }


@pytest.mark.parametrize(
    "aad_kwargs",
    [
        {"install_ref": "wrong-install", "grant_ref": REMOTE_TEST_GRANT_REF, "request_id": REMOTE_TEST_REQUEST_ID},
        {"install_ref": REMOTE_TEST_INSTALL_REF, "grant_ref": "wrong-grant", "request_id": REMOTE_TEST_REQUEST_ID},
        {"install_ref": REMOTE_TEST_INSTALL_REF, "grant_ref": REMOTE_TEST_GRANT_REF, "request_id": "wrong-request"},
    ],
)
def test_remote_envelope_rejects_wrong_aad_or_grant(aad_kwargs: dict[str, str]) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from localflight.remote_companion_crypto import decrypt_envelope, remote_aad

    aad = remote_aad(
        install_ref=REMOTE_TEST_INSTALL_REF,
        grant_ref=REMOTE_TEST_GRANT_REF,
        request_id=REMOTE_TEST_REQUEST_ID,
        direction="request",
    )
    sealed = AESGCM(REMOTE_TEST_KEY_BYTES).encrypt(REMOTE_TEST_NONCE, b'{"ok":true}', aad)
    envelope = {
        "alg": "A256GCM",
        "nonce": _b64(REMOTE_TEST_NONCE),
        "ciphertext": _b64(sealed[:-16]),
        "tag": _b64(sealed[-16:]),
    }

    with pytest.raises(Exception):
        decrypt_envelope(
            envelope,
            remote_key=REMOTE_TEST_KEY,
            aad=remote_aad(direction="request", **aad_kwargs),
        )


def test_remote_envelope_rejects_invalid_tag_and_wrong_key() -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from localflight.remote_companion_crypto import decrypt_envelope, remote_aad

    aad = remote_aad(
        install_ref=REMOTE_TEST_INSTALL_REF,
        grant_ref=REMOTE_TEST_GRANT_REF,
        request_id=REMOTE_TEST_REQUEST_ID,
        direction="request",
    )
    sealed = AESGCM(REMOTE_TEST_KEY_BYTES).encrypt(REMOTE_TEST_NONCE, b'{"ok":true}', aad)
    envelope = {
        "alg": "A256GCM",
        "nonce": _b64(REMOTE_TEST_NONCE),
        "ciphertext": _b64(sealed[:-16]),
        "tag": _b64(sealed[-16:]),
    }
    bad_tag = {**envelope, "tag": _b64(b"\x00" * 16)}

    with pytest.raises(Exception):
        decrypt_envelope(bad_tag, remote_key=REMOTE_TEST_KEY, aad=aad)
    with pytest.raises(Exception):
        decrypt_envelope(envelope, remote_key=base64.urlsafe_b64encode(b"x" * 32).decode("ascii").rstrip("="), aad=aad)


def test_remote_replay_cache_rejects_repeated_request_or_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.sources.web import remote_companion_agent

    monkeypatch.setattr(remote_companion_agent, "_REPLAY_CACHE", {})
    remote_companion_agent._remember_message(
        grant_ref=REMOTE_TEST_GRANT_REF,
        request_id=REMOTE_TEST_REQUEST_ID,
        nonce="same-nonce",
    )
    with pytest.raises(ValueError):
        remote_companion_agent._remember_message(
            grant_ref=REMOTE_TEST_GRANT_REF,
            request_id=REMOTE_TEST_REQUEST_ID,
            nonce="new-nonce",
        )
    with pytest.raises(ValueError):
        remote_companion_agent._remember_message(
            grant_ref=REMOTE_TEST_GRANT_REF,
            request_id="new-request",
            nonce="same-nonce",
        )


def test_remote_dispatcher_allows_companion_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.sources.web import remote_companion_agent

    calls: list[dict[str, object]] = []

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"board": "ready"}

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(remote_companion_agent.requests, "request", fake_request)

    result = asyncio.run(
        remote_companion_agent._dispatch_remote_payload(
            {"method": "GET", "path": "/api/mobile/summary"},
            grant={
                "companion_id": "lfc_test_phone",
                "client_name": "Test phone",
                "mobile_os": "ios",
                "device_type": "phone",
                "app_version": "0.5.1",
            },
        )
    )

    assert result == {"ok": True, "status": 200, "body": {"board": "ready"}}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://127.0.0.1:8000/api/mobile/summary"
    assert calls[0]["headers"]["X-LocalFlight-Companion-Id"] == "lfc_test_phone"


def test_remote_probe_round_trips_through_encrypted_host_handler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.remote_companion_crypto import decrypt_envelope, encrypt_envelope, remote_aad
    from localflight.sources.web import remote_companion_agent
    from localflight.storage.remote_companion import (
        consume_remote_invite,
        create_remote_grant_from_invite,
        create_remote_invite,
    )

    invite = create_remote_invite(relay_url="https://relay.example.test")
    consumed = consume_remote_invite(invite["invite_id"])
    assert consumed is not None
    grant = create_remote_grant_from_invite(
        consumed,
        companion_id="lfc_test_phone",
        client_name="Test phone",
        mobile_os="ios",
        device_type="phone",
        app_version="0.5.1",
    )

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "probe": "remote_companion",
                "client_probe": "rcp_test",
                "host_time": "2026-01-01T00:00:00+00:00",
            }

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        assert method == "GET"
        assert url == "http://127.0.0.1:8000/api/mobile/remote/probe?client_probe=rcp_test"
        return FakeResponse()

    monkeypatch.setattr(remote_companion_agent.requests, "request", fake_request)
    monkeypatch.setattr(remote_companion_agent, "_REPLAY_CACHE", {})

    request_id = "rcr_probe_001"
    request_aad = remote_aad(
        install_ref=str(grant["install_ref"]),
        grant_ref=str(grant["grant_ref"]),
        request_id=request_id,
        direction="request",
    )
    envelope = encrypt_envelope(
        {"method": "GET", "path": "/api/mobile/remote/probe?client_probe=rcp_test"},
        remote_key=str(grant["remote_key"]),
        aad=request_aad,
    )

    response = asyncio.run(
        remote_companion_agent._handle_remote_request(
            {
                "type": "request",
                "install_ref": str(grant["install_ref"]),
                "grant_ref": str(grant["grant_ref"]),
                "request_id": request_id,
                "envelope": envelope,
            }
        )
    )

    assert response["ok"] is True
    assert "remote_key" not in json.dumps(response)
    assert "client_probe" not in json.dumps(response)
    decrypted = decrypt_envelope(
        response["envelope"],
        remote_key=str(grant["remote_key"]),
        aad=remote_aad(
            install_ref=str(grant["install_ref"]),
            grant_ref=str(grant["grant_ref"]),
            request_id=request_id,
            direction="response",
        ),
    )
    assert decrypted == {
        "ok": True,
        "status": 200,
        "body": {
            "ok": True,
            "probe": "remote_companion",
            "client_probe": "rcp_test",
            "host_time": "2026-01-01T00:00:00+00:00",
        },
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/health"),
        ("GET", "/api/config"),
        ("GET", "/api/mobile/summary"),
        ("GET", "/api/mobile/remote/probe?client_probe=rcp_test"),
        ("GET", "/api/admin/system"),
        ("GET", "/api/admin/connections"),
        ("GET", "/api/admin/updates"),
        ("GET", "/api/admin/budget"),
        ("GET", "/api/admin/scheduler"),
        ("GET", "/api/metar"),
        ("GET", "/api/fids?view=departures"),
        ("GET", "/api/fids/detail?callsign=SWR10"),
        ("GET", "/api/history?direction=departures&hours=24"),
        ("GET", "/api/history/summary?hours=24"),
        ("GET", "/api/history/stats?hours=24"),
        ("GET", "/api/history/flight?callsign=SWR10"),
        ("GET", "/api/radar?radius_nm=5"),
        ("GET", "/api/radar/map?radius_nm=5"),
        ("GET", "/api/radar/surface?radius_nm=5"),
        ("GET", "/api/matrix/config"),
        ("GET", "/api/airports/search?q=ZRH"),
        ("GET", "/api/airports/resolve?q=ZRH"),
        ("GET", "/api/docs/privacy"),
        ("POST", "/api/admin/scheduler/restart"),
        ("POST", "/api/admin/companion/checkin"),
        ("POST", "/api/feedback"),
        ("POST", "/api/feedback/crash"),
        ("POST", "/api/matrix/config"),
        ("PATCH", "/api/config"),
    ],
)
def test_remote_dispatcher_allowlist_matches_mobile_companion_routes(method: str, path: str) -> None:
    from localflight.sources.web.remote_companion_agent import _allowed_remote_path

    assert _allowed_remote_path(method, path) == path


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/requests"),
        ("GET", "/api/admin/requests"),
        ("GET", "/api/logs"),
        ("GET", "/api/admin/logs"),
        ("GET", "/api/admin/provider-keys"),
        ("POST", "/api/admin/provider-keys/test"),
        ("GET", "/api/mobile/remote/status"),
        ("POST", "/api/mobile/remote/invite"),
        ("POST", "/api/mobile/remote/revoke"),
        ("POST", "/api/setup/complete"),
        ("POST", "/api/setup/reset"),
        ("GET", "https://example.test/api/mobile/summary"),
        ("DELETE", "/api/config"),
    ],
)
def test_remote_dispatcher_blocks_non_companion_routes(method: str, path: str) -> None:
    from localflight.sources.web.remote_companion_agent import _allowed_remote_path

    with pytest.raises(ValueError):
        _allowed_remote_path(method, path)


def test_mobile_remote_probe_returns_only_coarse_encrypted_test_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.storage.install import get_install_fingerprint
    from localflight.ui import api as ui_api

    response = TestClient(ui_api.app).get("/api/mobile/remote/probe?client_probe=rcp_test")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["probe"] == "remote_companion"
    assert data["client_probe"] == "rcp_test"
    assert data["install_ref"] == get_install_fingerprint()
    assert "host_time" in data
    assert "remote_key" not in data
    assert "activation_token" not in data
    assert "install_id" not in data


def test_remote_invite_requires_host_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.storage.config import AppConfig, save_config
    from localflight.ui import api as ui_api

    save_config(AppConfig(remote_companion_enabled=False))

    response = TestClient(ui_api.app).post("/api/mobile/remote/invite")

    assert response.status_code == 403
    assert response.json()["detail"] == "Remote Companion is disabled on this host"


def test_remote_invite_requires_relay_linked_host(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.storage.config import AppConfig, save_config
    from localflight.ui import api as ui_api

    save_config(AppConfig(remote_companion_enabled=True))
    monkeypatch.setattr(
        "localflight.sources.web.relay_activation.ensure_relay_link",
        lambda **kwargs: {
            "ok": False,
            "linked": False,
            "status": "relay_link_required",
            "error": "This install still needs a verified relay link.",
        },
    )

    response = TestClient(ui_api.app).post("/api/mobile/remote/invite")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "relay_link_required"
    assert "verified relay link" in response.json()["detail"]["message"]


def test_pairing_same_phone_replaces_previous_remote_grant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    from localflight.storage.config import AppConfig, save_config
    from localflight.storage.remote_companion import create_remote_invite, list_remote_grants
    from localflight.ui import api as ui_api

    save_config(AppConfig(remote_companion_enabled=True))
    relay_actions: list[tuple[str, str]] = []

    def fake_register(grant: dict[str, object], *, revoke: bool = False) -> dict[str, object]:
        relay_actions.append(("revoke" if revoke else "register", str(grant.get("grant_ref") or "")))
        return {"ok": True}

    monkeypatch.setattr(ui_api, "_register_remote_grant_or_raise", fake_register)
    client = TestClient(ui_api.app)

    def pair(invite: dict[str, object]) -> str:
        response = client.post(
            "/api/mobile/remote/pair",
            json={
                "companion_id": "lfc_same_phone_0001",
                "client_name": "Test phone",
                "app_version": "0.5.1",
                "mobile_os": "iOS test",
                "device_type": "phone",
                "invite_id": invite["invite_id"],
                "install_ref": invite["install_ref"],
                "relay_url": invite["relay_url"],
                "remote_key": invite["remote_key"],
            },
        )
        assert response.status_code == 200
        return str(response.json()["remote_companion"]["grant_ref"])

    first_ref = pair(create_remote_invite(relay_url="https://relay.example.test"))
    second_ref = pair(create_remote_invite(relay_url="https://relay.example.test"))

    grants = list_remote_grants(include_revoked=True)
    active = [grant for grant in grants if not grant.get("revoked_at")]
    assert [grant["grant_ref"] for grant in active] == [second_ref]
    assert any(grant["grant_ref"] == first_ref and grant.get("revoked_at") for grant in grants)
    assert relay_actions == [
        ("register", first_ref),
        ("register", second_ref),
        ("revoke", first_ref),
    ]
