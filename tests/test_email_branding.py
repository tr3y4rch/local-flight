"""Behavioral checks for mail identities, content parity, and safe rendering."""
from __future__ import annotations

from html.parser import HTMLParser

import pytest
from fastapi import HTTPException

import relay.main as relay
from relay.access.adapters import SmtpLicenseMailer
from relay.access.email_templates import (
    MANAGEMENT_URL, SUPPORT_URL, CONTACT_CATEGORIES, contact_email,
    license_email, magic_email, moved_email, operator_email, readable_expiry,
)
from relay.access.models import AccessConfigurationError


class ReadableHTML(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.text = []
        self.links = []
        self.feed(content)

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs)["href"])


def variants():
    cases = []
    for purpose in ("delivery", "holder_resend", "operator_resend", "holder_key_rotation", "admin_key_rotation", "operator_key_rotation", "protected_email_changed"):
        cases.append(license_email(license_key="FAKE-NOT-A-LICENSE", recovery_url=MANAGEMENT_URL, purpose=purpose))
    for purpose in ("recovery", "protect_and_deliver", "protect_and_transfer", "unknown"):
        cases.append(magic_email(magic_url=MANAGEMENT_URL + "#token=fake-token", purpose=purpose))
    cases.append(moved_email(device_name="Fake device <script>alert(1)</script>"))
    for purpose in ("operator:invitation", "operator:email_change", "operator:email_changed", "operator:smtp_test"):
        cases.append(operator_email(purpose=purpose, action_url=MANAGEMENT_URL + "#fake-token"))
    cases.append(operator_email(purpose="operator:invitation", expires_at="2026-09-10T14:30:00+02:00", action_url=MANAGEMENT_URL))
    for category in CONTACT_CATEGORIES:
        cases.append(contact_email(category=category, subject="Fake subject", name="Fake <sender>", reply_email="person@example.test", context="/support/", message="First line\n<script>fake</script>", network_tag="fake-reference"))
    return cases


@pytest.mark.parametrize("content", variants(), ids=lambda c: c.subject)
def test_plaintext_and_html_have_equivalent_information(content):
    parsed = ReadableHTML(content.html)
    visible = " ".join(" ".join(parsed.text).split())
    for block in content.text.strip().split("\n\n"):
        if block.startswith("https://"):
            assert block in parsed.links
        elif block.startswith("Need help?"):
            assert SUPPORT_URL in parsed.links and "Contact Beacon Tools support" in visible
        else:
            assert " ".join(block.split()) in visible
    assert "<script>" not in content.html
    assert "<img" not in content.html
    assert all(link.startswith("https://") for link in parsed.links)
    assert "Beacon Tools" in visible


@pytest.mark.parametrize("purpose,expected", [("delivery", "license is ready"), ("operator_issue", "license is ready"), ("holder_resend", "requested license key"), ("operator_resend", "requested license key"), ("holder_key_rotation", "replacement license key"), ("admin_key_rotation", "replacement license key"), ("operator_key_rotation", "replacement license key"), ("protected_email_changed", "replacement license key")])
def test_license_subject_matches_delivery_event(purpose, expected):
    content = license_email(license_key="FAKE-KEY", recovery_url=MANAGEMENT_URL, purpose=purpose)
    assert expected in content.subject
    if "resend" in purpose:
        assert "has not changed your key or disconnected" in content.text
    if "rotation" in purpose or purpose == "protected_email_changed":
        assert "previous key no longer works" in content.text
        assert "previous main device has been disconnected" in content.text


def test_security_and_diagnostic_emails_do_not_include_receipt_footer():
    messages = [magic_email(magic_url=MANAGEMENT_URL, purpose="recovery"), moved_email(device_name="Fake device")]
    messages += [operator_email(purpose=p) for p in ("operator:email_change", "operator:email_changed", "operator:smtp_test")]
    for content in messages:
        assert "payment" not in content.text.lower()
        assert "payment" not in content.html.lower()
    changed = messages[-2]
    assert "ignore" not in changed.text.lower()
    assert SUPPORT_URL in ReadableHTML(changed.html).links
    diagnostic = messages[-1]
    assert "LFRA-" not in diagnostic.text and "#token=" not in diagnostic.html


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "http://example.test", "https://user:password@example.test", "https://example.test/\nBcc:foo", "https://[broken"])
def test_unsafe_email_action_links_are_rejected(bad):
    with pytest.raises(AccessConfigurationError):
        magic_email(magic_url=bad, purpose="recovery")


def test_dates_are_readable_and_timezone_explicit():
    assert readable_expiry("2026-09-10T14:30:00+02:00") == "10 September 2026 at 12:30 UTC"
    for value in ("not-a-date", "2026-09-10T12:30:00"):
        with pytest.raises(AccessConfigurationError):
            readable_expiry(value)


@pytest.fixture
def transport(monkeypatch):
    messages = []
    class Capture:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, message): messages.append(message); return {}
    monkeypatch.setattr(relay.smtplib, "SMTP", Capture)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_SECURITY", "starttls")
    monkeypatch.setenv("MAIL_FROM", "legacy@example.test")
    monkeypatch.setenv("MAIL_TO", "legacy-inbox@example.test")
    return messages


def test_explicit_license_identity_overrides_legacy_fallback(transport, monkeypatch):
    monkeypatch.setenv("RELAY_LICENSE_FROM", "Beacon Tools <home@example.test>")
    monkeypatch.setenv("RELAY_LICENSE_REPLY_TO", "home@example.test")
    monkeypatch.setenv("RELAY_CONTACT_FROM", "Beacon Tools Forms <feedback@example.test>")
    mailer = relay._license_mailer()
    mailer.send_license(email="protected@example.test", license_key="FAKE-KEY", recovery_url=MANAGEMENT_URL)
    message = transport[0]
    assert message["From"] == "Beacon Tools <home@example.test>"
    assert message["To"] == "protected@example.test"
    assert message["Reply-To"] == "home@example.test"
    assert message["Date"]


@pytest.mark.parametrize("category", list(CONTACT_CATEGORIES))
def test_form_destination_and_submitter_reply_route(category, transport, monkeypatch):
    monkeypatch.setenv("RELAY_CONTACT_FROM", "Beacon Tools Forms <feedback@example.test>")
    monkeypatch.setenv("RELAY_CONTACT_TO_GENERAL", "home@example.test")
    monkeypatch.setenv("RELAY_CONTACT_TO_PRIVACY", "privacy@example.test")
    relay._send_contact_email(relay.SiteContactIn(category=category, subject="Fake question", message="Fake message", reply_email="submitter@example.test"), network_tag="fake-tag")
    message = transport[0]
    assert message["From"] == "Beacon Tools Forms <feedback@example.test>"
    assert message["To"] == ("privacy@example.test" if category == "privacy" else "home@example.test")
    assert message["Reply-To"] == "submitter@example.test"
    assert message.get_body(preferencelist=("html",)) is not None


@pytest.mark.parametrize("field", ["sender", "reply_to", "recipient"])
def test_customer_header_injection_never_opens_smtp(field, transport):
    settings = {"sender": "Beacon Tools <home@example.test>", "reply_to": "home@example.test"}
    recipient = "customer@example.test"
    attack = "person@example.test\r\nBcc: attacker@example.test"
    if field == "recipient": recipient = attack
    else: settings[field] = attack
    mailer = SmtpLicenseMailer(host="smtp.example.test", port=587, **settings)
    with pytest.raises(AccessConfigurationError):
        mailer.send_license(email=recipient, license_key="FAKE-KEY", recovery_url=MANAGEMENT_URL)
    assert not transport


@pytest.mark.parametrize("field", ["RELAY_CONTACT_FROM", "RELAY_CONTACT_TO_GENERAL", "reply_email"])
def test_contact_header_injection_never_opens_smtp(field, transport, monkeypatch):
    attack = "person@example.test\r\nBcc: attacker@example.test"
    body = relay.SiteContactIn(subject="Fake question", message="Fake message", reply_email=attack if field == "reply_email" else "person@example.test")
    if field != "reply_email": monkeypatch.setenv(field, attack)
    with pytest.raises(HTTPException):
        relay._send_contact_email(body, network_tag="fake-reference")
    assert not transport


@pytest.mark.parametrize("family", ["recovery", "protect_and_deliver", "protect_and_transfer", "move", "operator:invitation", "operator:email_change", "operator:email_changed", "operator:smtp_test"])
def test_customer_notice_families_use_the_same_explicit_identity(family, transport, monkeypatch):
    monkeypatch.setenv("RELAY_LICENSE_FROM", "Beacon Tools <home@example.test>")
    monkeypatch.setenv("RELAY_LICENSE_REPLY_TO", "home@example.test")
    mailer = relay._license_mailer()
    if family.startswith("operator:"):
        mailer.send_operator_message(email="protected@example.test", purpose=family, action_url=MANAGEMENT_URL)
    elif family == "move":
        mailer.send_receiver_moved(email="protected@example.test", device_name="Fake device")
    else:
        mailer.send_magic_link(email="protected@example.test", magic_url=MANAGEMENT_URL, purpose=family)
    message = transport[0]
    assert message["From"] == "Beacon Tools <home@example.test>"
    assert message["To"] == "protected@example.test"
    assert message["Reply-To"] == "home@example.test"


# These fixtures exercise the real durable queue and operator routes.
from test_operator_toolbox_api import stack, issue_and_claim, post


def test_queue_passes_license_purpose_and_diagnostic_uses_reply_destination(stack):
    client, service, mailer = stack
    _, license_id, _ = issue_and_claim(stack)
    original = next(message for message in mailer.messages if message["kind"] == "license")
    assert original["purpose"] == "operator_issue"
    response = post(client, f"licenses/{license_id}/action", action="rotate_key", confirmed=True)
    assert response.status_code == 200
    relay._deliver_pending_license_emails()
    latest = [message for message in mailer.messages if message["kind"] == "license"][-1]
    assert latest["purpose"] == "operator_key_rotation"
    mailer.reply_to = "home@example.test"
    mailer.sender = "Beacon Tools <home@example.test>"
    response = post(client, "toolbox/action", action="smtp_test", email="ignored@example.test")
    assert response.status_code == 200
    assert mailer.messages[-1]["kind"] == "operator:smtp_test"
    assert mailer.messages[-1]["email"] == "home@example.test"


def test_diagnostic_fallback_extracts_address_from_display_name(stack):
    client, _, mailer = stack
    mailer.reply_to = ""
    mailer.sender = "Beacon Tools <home@example.test>"
    response = post(client, "toolbox/action", action="smtp_test")
    assert response.status_code == 200
    assert mailer.messages[-1]["email"] == "home@example.test"


def test_email_copy_does_not_promote_unapproved_customer_self_service():
    general = [license_email(license_key="FAKE-KEY", recovery_url=MANAGEMENT_URL, purpose=purpose)
               for purpose in ("delivery", "holder_resend", "holder_key_rotation")]
    general.append(moved_email(device_name="Fake device"))
    for content in general:
        assert MANAGEMENT_URL not in content.text
        assert set(ReadableHTML(content.html).links) == {SUPPORT_URL}
    for content in variants():
        assert "license management" not in content.text.lower()
        assert "manage relay access" not in content.text.lower()
    private_link = MANAGEMENT_URL + "#token=fake-existing-verification"
    assert private_link in ReadableHTML(magic_email(magic_url=private_link, purpose="recovery").html).links
