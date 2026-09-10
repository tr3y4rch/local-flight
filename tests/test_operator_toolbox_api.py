from __future__ import annotations

import json
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient

import relay.main as b
from relay.access.adapters import (
    RecordingLicenseMailer,
    SmtpLicenseMailer,
    MailTransportError,
)
from relay.access.models import InvalidChallenge, LicenseInactive
from test_relay_access_admin_e2e import (
    _configure_access_admin,
    ADMIN_HOST,
    ADMIN_AUTH,
    PUBLIC_HOST,
)


@pytest.fixture
def stack(tmp_path, monkeypatch):
    _configure_access_admin(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_ACCESS_DEPLOYMENT_ENVIRONMENT", "staging")
    monkeypatch.setenv("RELAY_ACCESS_SITE_URL", "https://staging.beacontools.cc")
    monkeypatch.setenv("RELAY_ACCESS_OPERATOR_ISSUANCE_ENABLED", "1")
    mailer = RecordingLicenseMailer()
    mailer.reply_to = "support@example.test"
    mailer.sender = "sender@example.test"
    monkeypatch.setattr(b, "_license_mailer", lambda: mailer)
    b._maybe_create_access_backup(force=True)
    return TestClient(b.app), b._license_service(), mailer


def post(client, path, **body):
    return client.post(
        "/admin/api/operator/" + path,
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={
            "reason": "Operator workflow test",
            "request_id": uuid.uuid4().hex,
            **body,
        },
    )


def issue_and_claim(stack):
    client, service, mailer = stack
    issued = post(
        client, "grants", kind="test", email="recipient@example.test", confirmed=True
    )
    assert issued.status_code == 202, issued.text
    url = next(m["url"] for m in mailer.messages if m["kind"] == "operator:invitation")
    token = parse_qs(urlparse(url).fragment)["operator_claim"][0]
    assert not urlparse(url).query
    inspect = client.post(
        "/v1/access/operator/inspect",
        headers=PUBLIC_HOST,
        json={"token": token, "kind": "invitation"},
    )
    assert inspect.status_code == 200, inspect.text
    assert service.operator_grants()["items"][0]["license_id"] is None
    claim = client.post(
        "/v1/access/operator/claim", headers=PUBLIC_HOST, json={"token": token}
    )
    assert claim.status_code == 200, claim.text
    key = next(m["license_key"] for m in mailer.messages if m["kind"] == "license")
    return issued.json(), claim.json()["license_id"], key


def test_operator_routes_full_claim_diagnostics_and_privacy(
    stack, monkeypatch, caplog, capsys
):
    client, service, mailer = stack
    grant, license_id, key = issue_and_claim(stack)
    install_id = "88888888-8888-4888-8888-888888888888"
    activation = service.activate(
        install_id=install_id,
        device_kind="desktop",
        device_name="Test receiver",
        license_key=key,
    )
    b._record_install_profile(
        install_id=install_id,
        presence_event="relay_activity",
        client_kind="desktop",
        app_version="0.6.1",
    )
    monkeypatch.setattr(
        b._req,
        "get",
        lambda *a, **k: pytest.fail("Diagnostics must not call providers"),
    )
    monkeypatch.setattr(
        b._req,
        "post",
        lambda *a, **k: pytest.fail("Diagnostics must not call providers"),
    )
    with service._operator_connection() as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM usage")]
    response = client.get(
        f"/admin/api/operator/licenses/{license_id}",
        headers=ADMIN_HOST,
        auth=("invented-name", ADMIN_AUTH[1]),
    )
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["receivers"][0]["support_id"] == b._install_fingerprint(install_id)
    assert d["diagnostics"]["stored_state_only"]
    assert d["email"]["items"][0]["evidence_label"] == "SMTP accepted"
    assert d["email"]["items"][0]["attempts"][0]["stage"] == "accepted"
    assert response.headers["cache-control"] == "no-store"
    with service._operator_connection() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM usage")] == before
    note = post(
        client,
        f"licenses/{license_id}/action",
        action="add_note",
        note=f"Customer supplied {key} recipient@example.test token=abcde",
        reason="Test redaction",
    )
    assert note.status_code == 200, note.text
    history = post(client, "history/search", license_id=license_id).json()
    assert history["items"][0]["actor"] == "owner"
    assert "[redacted" in history["items"][0]["note"]
    assert all(i["actor"] != "invented-name" for i in history["items"])
    search = post(client, "licenses/search", q="recipient@example.test")
    assert search.status_code == 200, search.text
    assert len(search.json()["items"]) == 1
    invalid = post(client, "grants", email="recipient@example.test", kind="INVALID")
    assert invalid.status_code == 422 and "recipient@example.test" not in invalid.text
    rendered = (
        json.dumps(
            [d, history, search.json(), service.operator_license_support(license_id)]
        )
        + caplog.text
        + capsys.readouterr().out
    )
    for secret in (
        key,
        activation.credential.credential,
        install_id,
        "recipient@example.test",
        "token=abcde",
    ):
        assert secret not in rendered
    with service._operator_connection() as conn:
        stored = " ".join(
            str(tuple(r))
            for table in (
                "operator_notes",
                "operator_audit",
                "operator_grants",
                "mail_attempts",
            )
            for r in conn.execute(f"SELECT * FROM {table}")
        )
    assert key not in stored and "recipient@example.test" not in stored


def test_persistence_failure_after_smtp_acceptance_never_auto_resends(
    stack, monkeypatch
):
    client, service, mailer = stack
    _, license_id, _ = issue_and_claim(stack)
    ref = service.queue_license_email(license_id, purpose="fake_persistence_test")

    def unavailable(*args, **kwargs):
        raise RuntimeError("Fake database unavailable")

    monkeypatch.setattr(type(service), "finish_license_email", unavailable)
    before = len(mailer.messages)
    b._deliver_pending_license_emails()
    assert len(mailer.messages) == before + 1
    b._deliver_pending_license_emails()
    assert len(mailer.messages) == before + 1
    with service._operator_connection() as conn:
        assert (
            conn.execute(
                "SELECT status FROM license_deliveries WHERE delivery_id=?", (ref,)
            ).fetchone()[0]
            == "sending"
        )
        conn.execute(
            "UPDATE license_deliveries SET updated_at='2000-01-01T00:00:00+00:00' WHERE delivery_id=?",
            (ref,),
        )
    service.recover_interrupted_mail()
    message = next(
        m
        for m in service.operator_mail(license_id=license_id)["items"]
        if m["message_ref"] == ref
    )
    assert message["status"] == "uncertain"
    assert message["attempts"][0]["outcome"] == "accepted"


def test_auth_origin_readiness_and_no_legacy_bypass(stack, monkeypatch):
    client, service, _ = stack
    _, license_id, _ = issue_and_claim(stack)
    assert (
        client.get("/admin/api/operator/configuration", headers=ADMIN_HOST).status_code
        == 401
    )
    assert (
        client.get(
            "/admin/api/operator/configuration", headers=PUBLIC_HOST, auth=ADMIN_AUTH
        ).status_code
        == 404
    )
    rejected = client.post(
        f"/admin/api/operator/licenses/{license_id}/action",
        headers={
            **ADMIN_HOST,
            "origin": "https://evil.example",
            "sec-fetch-site": "cross-site",
        },
        auth=ADMIN_AUTH,
        json={
            "action": "suspend_license",
            "reason": "fake",
            "request_id": "fake-request-123",
            "confirmed": True,
        },
    )
    assert rejected.status_code == 403
    missing = post(client, f"licenses/{license_id}/action", action="suspend_license")
    assert missing.status_code == 422
    assert service.authority(license_id)["effective_state"] == "active"
    legacy = client.post(
        f"/admin/api/access/{license_id}/action",
        headers=ADMIN_HOST,
        auth=ADMIN_AUTH,
        json={"action": "rotate_key"},
    )
    assert legacy.status_code == 422
    monkeypatch.setenv("RELAY_ACCESS_OPERATOR_ISSUANCE_ENABLED", "0")
    assert (
        post(
            client, "grants", kind="test", email="another@example.test", confirmed=True
        ).status_code
        == 409
    )
    assert service.authority(license_id)["effective_state"] == "active"
    monkeypatch.setenv("RELAY_ACCESS_OPERATOR_ISSUANCE_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_BACKUP_ENABLED", "0")
    assert (
        post(
            client, "grants", kind="test", email="another@example.test", confirmed=True
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "failure,expected,stage",
    [
        ("success", "accepted", "accepted"),
        ("rejected", "failed", "transmit"),
        ("authentication", "failed", "authenticate"),
        ("connect_timeout", "failed", "connect"),
        ("transmit_timeout", "uncertain", "transmit"),
        ("disconnect", "uncertain", "transmit"),
        ("quit_timeout", "accepted", "accepted"),
    ],
)
def test_smtp_evidence_and_uncertain_retry(
    stack, monkeypatch, failure, expected, stage
):
    client, service, _ = stack
    _, license_id, _ = issue_and_claim(stack)

    class Smtp:
        def __init__(self, *a, **kw):
            if failure == "connect_timeout":
                raise TimeoutError("raw sensitive connect payload")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            if failure == "quit_timeout":
                raise TimeoutError("raw sensitive QUIT payload")

        def starttls(self):
            pass

        def login(self, *a):
            if failure == "authentication":
                raise smtplib.SMTPAuthenticationError(
                    535, b"raw sensitive authentication payload"
                )

        def send_message(self, message):
            assert message["Message-ID"]
            if failure == "rejected":
                raise smtplib.SMTPDataError(550, b"raw sensitive SMTP payload")
            if failure == "transmit_timeout":
                raise TimeoutError("raw sensitive transmission payload")
            if failure == "disconnect":
                raise smtplib.SMTPServerDisconnected("raw sensitive disconnect payload")
            return {}

    monkeypatch.setattr("relay.access.adapters.smtplib.SMTP", Smtp)
    mailer = SmtpLicenseMailer(
        host="smtp.example.test",
        port=587,
        sender="support@example.test",
        username="fake",
        password="fake",
        security="starttls",
    )
    monkeypatch.setattr(b, "_license_mailer", lambda: mailer)
    ref = service.queue_license_email(license_id, purpose="evidence_test")
    b._deliver_pending_license_emails(limit=10)
    evidence = next(
        m
        for m in service.operator_mail(license_id=license_id)["items"]
        if m["message_ref"] == ref
    )
    assert evidence["status"] == ("sent" if expected == "accepted" else expected)
    assert evidence["attempts"][0]["outcome"] == expected
    assert evidence["attempts"][0]["stage"] == stage
    assert "raw sensitive" not in json.dumps(evidence)
    if expected == "uncertain":
        assert not evidence["next_attempt_at"]
        assert b._deliver_pending_license_emails(limit=10) == 0
        with pytest.raises(InvalidChallenge):
            service.operator_mail_action(
                kind="license",
                message_ref=ref,
                action="retry",
                reason="Test retry",
                request_id=uuid.uuid4().hex,
            )
        service.operator_mail_action(
            kind="license",
            message_ref=ref,
            action="retry",
            reason="Explicit duplicate risk",
            request_id=uuid.uuid4().hex,
            acknowledge_duplicate=True,
        )
        assert service.operator_mail(license_id=license_id)["items"]


def test_smtp_test_has_no_access_secrets_and_uses_configured_destination(stack):
    client, _, mailer = stack
    response = post(
        client, "toolbox/action", action="smtp_test", email="ignored@example.test"
    )
    assert response.status_code == 200, response.text
    assert response.json()["recipient"] == "s***@example.test"
    message = mailer.messages[-1]
    assert message["email"] == "support@example.test"
    assert not message["url"]
    assert "license_key" not in message


def test_default_test_duration_retry_and_invitation_email_search(stack):
    client, service, _ = stack
    request_id = uuid.uuid4().hex
    body = {
        "kind": "test",
        "email": "pending@example.test",
        "confirmed": True,
        "request_id": request_id,
    }
    first = post(client, "grants", **body)
    second = post(client, "grants", **body)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["expires_at"]
    found = post(client, "email/search", q="pending@example.test")
    assert found.status_code == 200, found.text
    assert len(found.json()["items"]) == 1
    assert "pending@example.test" not in found.text


def test_cancellation_claim_race_legacy_label_and_expired_paths(stack):
    _, service, _ = stack
    grant, license_id, key = issue_and_claim(stack)
    session = service.exchange_magic_link(
        service.request_magic_link("recipient@example.test").token
    )
    activation = service.activate(
        install_id="fake-install",
        device_kind="desktop",
        device_name="Fake",
        license_key=key,
    )
    ref = service.queue_license_email(license_id, purpose="cancel_test")
    service.operator_mail_action(
        kind="license",
        message_ref=ref,
        action="cancel",
        reason="Test cancel",
        request_id=uuid.uuid4().hex,
    )
    assert service.claim_due_license_emails() == []
    ref = service.queue_license_email(license_id, purpose="sending_test")
    service.claim_due_license_emails()
    with pytest.raises(InvalidChallenge):
        service.operator_mail_action(
            kind="license",
            message_ref=ref,
            action="cancel",
            reason="Test sending race",
            request_id=uuid.uuid4().hex,
        )
    with service._operator_connection() as conn:
        conn.execute(
            "UPDATE license_deliveries SET status='sent' WHERE delivery_id=?", (ref,)
        )
    assert (
        next(m for m in service.operator_mail()["items"] if m["message_ref"] == ref)[
            "evidence_label"
        ]
        == "SMTP accepted—legacy record"
    )
    with service._operator_connection() as conn:
        conn.execute(
            "UPDATE operator_grants SET expires_at=? WHERE grant_id=?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                grant["grant_id"],
            ),
        )
    for fn in [
        lambda: service.queue_license_email(license_id),
        lambda: service.resend_license_email(session.token, license_id),
        lambda: service.create_activation_grant(session.token, license_id),
        lambda: service.create_mobile_license_claim(
            license_id=license_id, install_id="fake-install"
        ),
        lambda: service.check_receiver_authority(install_id="fake-install"),
        lambda: service.resolve_credential(activation.credential.credential),
    ]:
        with pytest.raises(LicenseInactive):
            fn()


def test_established_remote_companion_disconnects_on_expiry(stack, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    client, service, _ = stack
    _, license_id, key = issue_and_claim(stack)
    monkeypatch.setenv("RELAY_ACCESS_REMOTE_COMPANION_ENABLED", "1")
    monkeypatch.setenv("RELAY_ACCESS_ALLOW_TEST_LICENSES", "1")
    install_id = "91919191-9191-4191-8191-919191919191"
    active = service.activate(
        install_id=install_id,
        device_kind="desktop",
        device_name="Test",
        license_key=key,
    )
    ticket = client.post(
        "/v1/remote-companion/host/ticket",
        headers={
            **PUBLIC_HOST,
            "Authorization": "Bearer " + active.credential.credential,
        },
        json={"install_id": install_id},
    )
    assert ticket.status_code == 200, ticket.text
    with client.websocket_connect(
        f"/v1/remote-companion/host/ws?install_id={install_id}",
        headers={**PUBLIC_HOST, "Authorization": "Bearer " + ticket.json()["ticket"]},
    ) as ws:
        with service._operator_connection() as conn:
            conn.execute(
                "UPDATE operator_grants SET expires_at=? WHERE license_id=?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    license_id,
                ),
            )
        ws.send_json({"type": "response", "request_id": "expiry-probe"})
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008
    assert b._install_fingerprint(install_id) not in b._REMOTE_COMPANION_HOSTS


def test_switched_off_issuance_names_itself_instead_of_reporting_no_problems(
    stack, monkeypatch
):
    """A disabled switch must appear as an outstanding gate.

    Omitting it produced a console that showed "Outstanding gates: None" beside
    a dead button whose tooltip told the operator to finish server gates that
    were already green, leaving no way to discover the real cause.
    """
    client, _service, _mailer = stack

    ready = client.get(
        "/admin/api/operator/configuration", headers=ADMIN_HOST, auth=ADMIN_AUTH
    ).json()
    assert ready["issuance_enabled"] is True
    assert ready["issuance_ready"] is True
    assert "issuance_switched_off" not in ready["readiness_problems"]

    monkeypatch.setenv("RELAY_ACCESS_OPERATOR_ISSUANCE_ENABLED", "0")
    off = client.get(
        "/admin/api/operator/configuration", headers=ADMIN_HOST, auth=ADMIN_AUTH
    ).json()

    assert off["issuance_enabled"] is False
    assert off["issuance_ready"] is False
    assert "issuance_switched_off" in off["readiness_problems"]
    # Every other gate still passes, so the switch must be the only one named.
    assert off["readiness_problems"] == ["issuance_switched_off"]


def test_founder_summary_reports_counts_without_exposing_any_install(stack):
    """The console needs bridge progress, never per-founder identities."""
    client, _service, _mailer = stack

    summary = client.get(
        "/admin/api/operator/founders", headers=ADMIN_HOST, auth=ADMIN_AUTH
    )
    assert summary.status_code == 200
    body = summary.json()
    for key in (
        "total",
        "claimed",
        "awaiting_upgrade",
        "cutoff_at",
        "bridge_expires_at",
        "migration_active",
    ):
        assert key in body
    assert body["total"] == body["claimed"] + body["awaiting_upgrade"]
    serialized = json.dumps(body)
    for leaked in ("install_id", "install_ref_hash", "legacy_token_hash", "license_id"):
        assert leaked not in serialized

    assert (
        client.get("/admin/api/operator/founders", headers=ADMIN_HOST).status_code == 401
    )
