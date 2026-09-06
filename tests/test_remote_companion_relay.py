from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import relay.main as relay_main

INSTALL_ID = "11111111-1111-4111-8111-111111111111"
ACTIVATION_TOKEN = "lfm_test_remote_companion_token"
GRANT_REF = "rcg_test_phone"


def _use_temp_relay_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay.db"))
    relay_main._REMOTE_COMPANION_HOSTS.clear()
    relay_main._ensure_schema()


def _issue_managed_activation() -> None:
    conn = relay_main._connect()
    relay_main._store_activation_token(
        conn,
        token=ACTIVATION_TOKEN,
        label="Remote Companion Test",
        schedule_limit=1000,
        radar_limit=1000,
        created_by="pytest",
    )
    conn.commit()
    conn.close()


def _install_ref() -> str:
    return relay_main._install_fingerprint(INSTALL_ID)


def _grant_payload(action: str = "register") -> dict[str, object]:
    return {
        "install_id": INSTALL_ID,
        "activation_token": ACTIVATION_TOKEN,
        "install_ref": _install_ref(),
        "grant_ref": GRANT_REF,
        "companion_ref": "lfc_test_phone",
        "action": action,
        "client_name": "Test phone",
        "device_type": "phone",
        "app_version": "0.5.1",
    }


def _request_payload(request_id: str = "rcr_test_0001", envelope: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "install_ref": _install_ref(),
        "grant_ref": GRANT_REF,
        "request_id": request_id,
        "envelope": envelope or {
            "alg": "A256GCM",
            "nonce": "request-nonce",
            "ciphertext": "encrypted-request",
            "tag": "request-tag",
        },
    }


def _register_grant(client: TestClient) -> None:
    response = client.post("/v1/remote-companion/grants", json=_grant_payload())
    assert response.status_code == 200


def test_remote_companion_grant_register_and_revoke(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)

    register = client.post("/v1/remote-companion/grants", json=_grant_payload())
    assert register.status_code == 200
    assert register.json()["action"] == "register"

    conn = relay_main._connect()
    row = conn.execute(
        "SELECT install_ref, grant_ref, revoked_at FROM remote_companion_grants WHERE grant_ref=?",
        (GRANT_REF,),
    ).fetchone()
    conn.close()
    assert row["install_ref"] == _install_ref()
    assert row["revoked_at"] is None

    revoke = client.post("/v1/remote-companion/grants", json=_grant_payload("revoke"))
    assert revoke.status_code == 200
    assert revoke.json()["action"] == "revoke"

    conn = relay_main._connect()
    row = conn.execute(
        "SELECT revoked_at FROM remote_companion_grants WHERE grant_ref=?",
        (GRANT_REF,),
    ).fetchone()
    conn.close()
    assert row["revoked_at"]


def test_remote_companion_grant_requires_managed_activation(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    response = client.post("/v1/remote-companion/grants", json=_grant_payload())

    assert response.status_code == 403
    assert response.json()["detail"] in {
        "Activation token invalid or revoked",
        "Remote Companion requires a managed relay-linked install",
    }


def test_remote_companion_grant_registration_stores_no_aes_secret(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    secret = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"

    response = client.post(
        "/v1/remote-companion/grants",
        json={**_grant_payload(), "remote_key": secret, "provider_key": "should-not-store"},
    )

    assert response.status_code == 200
    conn = relay_main._connect()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(remote_companion_grants)").fetchall()}
    row = conn.execute(
        "SELECT * FROM remote_companion_grants WHERE grant_ref=?",
        (GRANT_REF,),
    ).fetchone()
    conn.close()
    assert "remote_key" not in columns
    assert "provider_key" not in columns
    assert secret not in str(dict(row))
    assert "should-not-store" not in str(dict(row))


def test_remote_companion_request_reports_host_offline(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    _register_grant(client)

    response = client.post("/v1/remote-companion/request", json=_request_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == "remote_host_offline"


def test_remote_companion_host_websocket_rejects_unlinked_install(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    client = TestClient(relay_main.app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/remote-companion/host/ws?install_id={INSTALL_ID}&activation_token=missing&app_version=0.5.1"
        ):
            pass


def test_remote_companion_host_uses_one_time_ticket_without_credential_in_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    issued = client.post(
        "/v1/remote-companion/host/ticket",
        headers={"Authorization": f"Bearer {ACTIVATION_TOKEN}"},
        json={"install_id": INSTALL_ID},
    )
    assert issued.status_code == 200
    ticket = issued.json()["ticket"]
    assert ticket.startswith("lfrws_")
    conn = relay_main._connect()
    try:
        assert ticket not in "\n".join(conn.iterdump())
    finally:
        conn.close()
    ws_url = f"{issued.json()['websocket_path']}?install_id={INSTALL_ID}&app_version=0.5.1"
    assert ACTIVATION_TOKEN not in ws_url
    assert ticket not in ws_url
    headers = {"Authorization": f"Bearer {ticket}"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{ws_url}&ticket={ticket}"):
            pass
    with client.websocket_connect(ws_url, headers=headers):
        assert _install_ref() in relay_main._REMOTE_COMPANION_HOSTS
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(ws_url, headers=headers):
            pass


def test_remote_companion_ticket_is_burned_by_wrong_installation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    issued = client.post(
        "/v1/remote-companion/host/ticket",
        headers={"Authorization": f"Bearer {ACTIVATION_TOKEN}"},
        json={"install_id": INSTALL_ID},
    )
    ticket = issued.json()["ticket"]
    wrong_install = "22222222-2222-4222-8222-222222222222"
    headers = {"Authorization": f"Bearer {ticket}"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/remote-companion/host/ws?install_id={wrong_install}",
            headers=headers,
        ):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/remote-companion/host/ws?install_id={INSTALL_ID}",
            headers=headers,
        ):
            pass


def test_remote_companion_request_rejects_revoked_grant(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    _register_grant(client)
    revoke = client.post("/v1/remote-companion/grants", json=_grant_payload("revoke"))
    assert revoke.status_code == 200

    response = client.post("/v1/remote-companion/request", json=_request_payload())

    assert response.status_code == 403
    assert response.json()["detail"] == "Remote Companion grant is not active"


def test_remote_companion_rejects_oversized_request_envelope(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    monkeypatch.setattr(relay_main, "_remote_companion_max_envelope_bytes", lambda: 96)
    client = TestClient(relay_main.app)
    _register_grant(client)

    response = client.post(
        "/v1/remote-companion/request",
        json=_request_payload(envelope={"nonce": "n", "ciphertext": "x" * 160, "tag": "t"}),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Remote Companion encrypted request envelope is too large"


@pytest.mark.parametrize(
    ("limit_name", "expected_detail"),
    [
        ("_remote_companion_grant_rpm_limit", "Remote Companion grant rate limit reached; try again shortly."),
        ("_remote_companion_install_rpm_limit", "Remote Companion install rate limit reached; try again shortly."),
        ("_remote_companion_network_rpm_limit", "Remote Companion network rate limit reached; try again shortly."),
    ],
)
def test_remote_companion_rate_limits_by_grant_install_and_network(
    tmp_path: Path,
    monkeypatch,
    limit_name: str,
    expected_detail: str,
) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    for name in (
        "_remote_companion_grant_rpm_limit",
        "_remote_companion_install_rpm_limit",
        "_remote_companion_network_rpm_limit",
    ):
        monkeypatch.setattr(relay_main, name, lambda: 100)
    monkeypatch.setattr(relay_main, limit_name, lambda: 1)
    client = TestClient(relay_main.app)
    _register_grant(client)
    headers = {"fly-client-ip": "203.0.113.44"}

    first = client.post("/v1/remote-companion/request", json=_request_payload("rcr_rate_001"), headers=headers)
    second = client.post("/v1/remote-companion/request", json=_request_payload("rcr_rate_002"), headers=headers)

    assert first.status_code == 503
    assert first.json()["detail"] == "remote_host_offline"
    assert second.status_code == 429
    assert second.json()["detail"] == expected_detail
    assert second.headers["retry-after"] == "60"


def test_remote_companion_rejects_when_host_session_has_too_many_pending_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    monkeypatch.setattr(relay_main, "_remote_companion_max_pending", lambda: 1)
    client = TestClient(relay_main.app)
    _register_grant(client)

    class FakeHostWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)

    fake_websocket = FakeHostWebSocket()
    relay_main._REMOTE_COMPANION_HOSTS[_install_ref()] = relay_main.RemoteCompanionHostSession(
        install_ref=_install_ref(),
        install_id=INSTALL_ID,
        websocket=fake_websocket,
        pending={"already_pending": object()},
    )

    response = client.post("/v1/remote-companion/request", json=_request_payload())

    assert response.status_code == 429
    assert response.json()["detail"] == "Remote Companion host has too many pending requests; try again shortly."
    assert response.headers["retry-after"] == "5"
    assert fake_websocket.sent == []


def test_remote_companion_websocket_forwards_request_and_response(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    _register_grant(client)

    class FakeHostWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            future = relay_main._REMOTE_COMPANION_HOSTS[_install_ref()].pending[str(payload["request_id"])]
            future.set_result(
                {
                    "type": "response",
                    "request_id": "rcr_test_0001",
                    "install_ref": _install_ref(),
                    "grant_ref": GRANT_REF,
                    "ok": True,
                    "envelope": {
                        "alg": "A256GCM",
                        "nonce": "response-nonce",
                        "ciphertext": "encrypted-response",
                        "tag": "response-tag",
                    },
                }
            )

    fake_websocket = FakeHostWebSocket()
    relay_main._REMOTE_COMPANION_HOSTS[_install_ref()] = relay_main.RemoteCompanionHostSession(
        install_ref=_install_ref(),
        install_id=INSTALL_ID,
        websocket=fake_websocket,
    )

    response = client.post("/v1/remote-companion/request", json=_request_payload())

    assert response.status_code == 200
    assert fake_websocket.sent == [
        {
            "type": "request",
            "install_ref": _install_ref(),
            "grant_ref": GRANT_REF,
            "request_id": "rcr_test_0001",
            "envelope": {
                "alg": "A256GCM",
                "nonce": "request-nonce",
                "ciphertext": "encrypted-request",
                "tag": "request-tag",
            },
        }
    ]
    data = response.json()
    assert data["envelope"]["ciphertext"] == "encrypted-response"
    assert data["relay"]["request_id"] == "rcr_test_0001"


def test_remote_companion_relay_never_forwards_plaintext_request_fields(
    tmp_path: Path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    client = TestClient(relay_main.app)
    _register_grant(client)
    sensitive_path = "/api/admin/provider-keys"
    sensitive_body = "AERODATABOX_SECRET_SHOULD_NOT_APPEAR"

    class FakeHostWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            future = relay_main._REMOTE_COMPANION_HOSTS[_install_ref()].pending[str(payload["request_id"])]
            future.set_result(
                {
                    "type": "response",
                    "request_id": "rcr_privacy_0001",
                    "install_ref": _install_ref(),
                    "grant_ref": GRANT_REF,
                    "ok": True,
                    "envelope": {
                        "alg": "A256GCM",
                        "nonce": "response-nonce",
                        "ciphertext": "encrypted-response",
                        "tag": "response-tag",
                    },
                }
            )

    fake_websocket = FakeHostWebSocket()
    relay_main._REMOTE_COMPANION_HOSTS[_install_ref()] = relay_main.RemoteCompanionHostSession(
        install_ref=_install_ref(),
        install_id=INSTALL_ID,
        websocket=fake_websocket,
    )
    payload = _request_payload(
        "rcr_privacy_0001",
        envelope={
            "alg": "A256GCM",
            "nonce": "request-nonce",
            "ciphertext": "encrypted-request",
            "tag": "request-tag",
        },
    )

    with caplog.at_level("INFO"):
        response = client.post("/v1/remote-companion/request", json=payload)

    assert response.status_code == 200
    forwarded = fake_websocket.sent[0]
    assert "path" not in forwarded
    assert "body" not in forwarded
    assert "envelope" in forwarded
    assert sensitive_path not in caplog.text
    assert sensitive_body not in caplog.text
    assert "encrypted-request" not in caplog.text


def test_remote_companion_rejects_oversized_response_envelope(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    request_limit = relay_main._remote_companion_envelope_size(_request_payload()["envelope"]) + 20
    monkeypatch.setattr(relay_main, "_remote_companion_max_envelope_bytes", lambda: request_limit)
    client = TestClient(relay_main.app)
    _register_grant(client)

    class FakeHostWebSocket:
        async def send_json(self, payload: dict[str, object]) -> None:
            future = relay_main._REMOTE_COMPANION_HOSTS[_install_ref()].pending[str(payload["request_id"])]
            future.set_result(
                {
                    "type": "response",
                    "request_id": "rcr_test_0001",
                    "install_ref": _install_ref(),
                    "grant_ref": GRANT_REF,
                    "ok": True,
                    "envelope": {
                        "alg": "A256GCM",
                        "nonce": "response-nonce",
                        "ciphertext": "x" * (request_limit + 80),
                        "tag": "response-tag",
                    },
                }
            )

    relay_main._REMOTE_COMPANION_HOSTS[_install_ref()] = relay_main.RemoteCompanionHostSession(
        install_ref=_install_ref(),
        install_id=INSTALL_ID,
        websocket=FakeHostWebSocket(),
    )

    response = client.post("/v1/remote-companion/request", json=_request_payload())

    assert response.status_code == 413
    assert response.json()["detail"] == "Remote Companion encrypted response envelope is too large"


def test_remote_companion_websocket_timeout(tmp_path: Path, monkeypatch) -> None:
    _use_temp_relay_db(tmp_path, monkeypatch)
    _issue_managed_activation()
    monkeypatch.setattr(relay_main, "_REMOTE_COMPANION_TIMEOUT_S", 0.05)
    client = TestClient(relay_main.app)
    _register_grant(client)

    class SilentHostWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)

    fake_websocket = SilentHostWebSocket()
    relay_main._REMOTE_COMPANION_HOSTS[_install_ref()] = relay_main.RemoteCompanionHostSession(
        install_ref=_install_ref(),
        install_id=INSTALL_ID,
        websocket=fake_websocket,
    )

    response = client.post("/v1/remote-companion/request", json=_request_payload("rcr_timeout_001"))

    assert fake_websocket.sent == [
        {
            "type": "request",
            "install_ref": _install_ref(),
            "grant_ref": GRANT_REF,
            "request_id": "rcr_timeout_001",
            "envelope": {
                "alg": "A256GCM",
                "nonce": "request-nonce",
                "ciphertext": "encrypted-request",
                "tag": "request-tag",
            },
        }
    ]
    assert response.status_code == 504
    assert response.json()["detail"] == "remote_host_timeout"
