"""Contact acceptance must survive SMTP teardown without inviting duplicate sends."""
from __future__ import annotations

import smtplib

import pytest
from fastapi.testclient import TestClient

import relay.main as relay


@pytest.mark.parametrize('outcome', ['accepted_then_disconnect', 'recipient_refused'])
def test_contact_reports_transport_acceptance_and_deduplicates(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'relay.db'))
    monkeypatch.setenv('RELAY_CONTACT_SMTP_HOST', 'smtp.example.test')
    monkeypatch.setenv('RELAY_CONTACT_FROM', 'sender@example.test')
    monkeypatch.setenv('RELAY_CONTACT_TO_GENERAL', 'support@example.test')
    monkeypatch.setenv('RELAY_CONTACT_SMTP_SECURITY', 'starttls')
    relay._ensure_schema()
    sent = []

    class Transport:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            sent.append(message)
            return {'support@example.test': (550, b'fake rejection')} if outcome == 'recipient_refused' else {}

        def __exit__(self, *args):
            if outcome == 'accepted_then_disconnect':
                raise smtplib.SMTPServerDisconnected('fake disconnect after acceptance')

    monkeypatch.setattr(relay.smtplib, 'SMTP', Transport)
    client = TestClient(relay.app)
    body = {'category': 'general', 'subject': 'Delivery evidence test', 'message': 'Fake test message'}
    headers = {'origin': 'https://beacontools.cc', 'fly-client-ip': '198.51.100.75'}
    first = client.post('/v1/site/contact', json=body, headers=headers)
    second = client.post('/v1/site/contact', json=body, headers=headers)
    if outcome == 'accepted_then_disconnect':
        assert first.status_code == 200
        assert second.status_code == 200 and second.json()['deduped']
        assert len(sent) == 1
    else:
        assert first.status_code == second.status_code == 502
        assert len(sent) == 2
        assert 'fake rejection' not in first.text


def test_completed_email_change_does_not_tell_recipient_to_ignore_it(monkeypatch):
    from relay.access.adapters import SmtpLicenseMailer

    messages = []
    monkeypatch.setattr(SmtpLicenseMailer, '_send', lambda self, **message: messages.append(message))
    mailer = SmtpLicenseMailer(host='smtp.example.test', port=587, sender='sender@example.test')
    mailer.send_operator_message(email='recipient@example.test', purpose='operator:email_changed')
    message = messages[0]
    for content in (message['text'], message['html_text']):
        assert 'Contact support if this was unexpected.' in content
        assert 'Ignore this message' not in content


def test_invitation_distinguishes_link_expiry_from_access_expiry(monkeypatch):
    from relay.access.adapters import SmtpLicenseMailer

    messages = []
    monkeypatch.setattr(SmtpLicenseMailer, '_send', lambda self, **message: messages.append(message))
    mailer = SmtpLicenseMailer(host='smtp.example.test', port=587, sender='sender@example.test')
    mailer.send_operator_message(email='recipient@example.test', purpose='operator:invitation', action_url='https://example.test/#fake')
    for content in (messages[0]['text'], messages[0]['html_text']):
        assert 'link expires within 24 hours' in content
        assert 'Access has no scheduled expiry.' in content
