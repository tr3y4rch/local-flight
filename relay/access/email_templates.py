"""Shared, image-independent Beacon Tools email copy and rendering."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import getaddresses
from urllib.parse import urlsplit

from .models import AccessConfigurationError

SUPPORT_URL = "https://beacontools.cc/support"
MANAGEMENT_URL = "https://beacontools.cc/local-flight/relay-access/manage/"
CONTACT_CATEGORIES = {
    "general": "General enquiry",
    "mobile_testing": "Mobile testing",
    "relay": "Relay Access support",
    "privacy": "Privacy request",
}


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


def valid_mailbox(value: str, *, multiple: bool = False) -> bool:
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        addresses = getaddresses([value])
    except ValueError:
        return False
    return bool(addresses) and (multiple or len(addresses) == 1) and all(
        address.count("@") == 1 and all(address.split("@")) and not any(char.isspace() for char in address)
        for _name, address in addresses
    )


def safe_action_url(value: str) -> str:
    """Links supplied by our routes must remain HTTPS, never executable markup."""
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid or any(ord(char) < 33 for char in value):
        raise AccessConfigurationError("Email action URL is invalid")
    return value


def readable_expiry(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc).strftime("%d %B %Y at %H:%M UTC")
    except (ValueError, TypeError):
        raise AccessConfigurationError("Email expiry is invalid") from None


def render_email(
    *, subject: str, heading: str, paragraphs: list[str],
    action_url: str = "", action_label: str = "", license_key: str = "",
    section: str = "Local Flight · Relay Access", customer: bool = True,
) -> EmailContent:
    action_url = safe_action_url(action_url)
    # Both alternatives are built from the same content; callers never supply HTML.
    paragraphs = [value for value in paragraphs if value]
    blocks = ["Beacon Tools", section, heading, *paragraphs]
    if license_key:
        blocks.insert(4, "License key: " + license_key)
    if action_url:
        blocks.extend([action_label, action_url])
    footer = "Need help? Contact Beacon Tools support: " + SUPPORT_URL if customer else "Beacon Tools · Website contact notification"
    blocks.append(footer)
    body_parts = [
        '<p style="margin:0 0 18px;color:#263746;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere">'
        + html.escape(value) + "</p>" for value in paragraphs
    ]
    if license_key:
        body_parts.insert(1, '<p style="margin:0 0 8px;color:#263746">License key:</p><div style="padding:16px;margin:0 0 22px;background:#edf3f7;border:1px solid #cbd8e2;border-radius:8px;font-family:monospace;font-size:17px;color:#102638;word-break:break-all">' + html.escape(license_key) + '</div>')
    body = ''.join(body_parts)
    if action_url:
        body += '<p style="margin:24px 0"><a href="' + html.escape(action_url, quote=True) + '" style="display:inline-block;background:#155e85;color:#ffffff;padding:14px 20px;border-radius:8px;text-decoration:none;font-weight:600;line-height:1.4">' + html.escape(action_label) + '</a></p>'
    footer_html = 'Need help? <a href="' + SUPPORT_URL + '" style="color:#155e85">Contact Beacon Tools support</a>.' if customer else html.escape(footer)
    markup = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body style="margin:0;padding:20px 12px;background:#f1f4f6;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border:1px solid #d4dfe6;border-radius:12px"><tr><td style="padding:28px 24px">'
        '<p style="margin:0 0 6px;font-size:21px;font-weight:700;color:#102638">Beacon Tools</p>'
        '<p style="margin:0 0 28px;color:#526676;font-size:13px">' + html.escape(section) + '</p>'
        '<h1 style="margin:0 0 22px;font-size:26px;line-height:1.25;color:#102638">' + html.escape(heading) + '</h1>'
        + body + '<div style="border-top:1px solid #d4dfe6;margin-top:26px;padding-top:18px;color:#526676;font-size:13px;line-height:1.6">'
        + footer_html + '</div></td></tr></table></td></tr></table></body></html>'
    )
    return EmailContent(subject=subject, text="\n\n".join(blocks) + "\n", html=markup)


def license_email(*, license_key: str, recovery_url: str, purpose: str = "delivery") -> EmailContent:
    # Retain the adapter argument for compatibility; general help stays with support
    # until the customer self-service journey has separate product approval.
    replacement = purpose in {"holder_key_rotation", "admin_key_rotation", "operator_key_rotation", "protected_email_changed"}
    resend = purpose in {"holder_resend", "operator_resend"}
    if replacement:
        heading = "Your replacement license key"
        intro = "Your Relay Access license key for Local Flight has been replaced. The previous key no longer works, and the previous main device has been disconnected."
    elif resend:
        heading = "Your requested license key"
        intro = "Here is your current Relay Access license key for Local Flight. Sending this email has not changed your key or disconnected your main device."
    else:
        heading = "Your Relay Access license is ready"
        intro = "Your Relay Access license for Local Flight is ready to use."
    paragraphs = [intro, "Enter this key in Local Flight's Beacon Relay setup. It controls one main device at a time: one desktop or one phone in Standalone mode. Keep it private.",
                  "For another copy of your key or help replacing a lost or exposed key, contact Beacon Tools support. Resending keeps your access unchanged; replacing the key disconnects the previous main device."]
    if replacement:
        paragraphs.append("If you did not expect this change, contact Beacon Tools support.")
    if not replacement and not resend:
        paragraphs.append("This email delivers access, not a payment receipt. If you paid through Stripe, Apple, or Google, your receipt comes separately from that provider. Local Flight never receives payment-card details.")
    return render_email(subject="Local Flight — " + heading[0].lower() + heading[1:], heading=heading, paragraphs=paragraphs,
                        license_key=license_key, action_url=SUPPORT_URL, action_label="Get support")


def magic_email(*, magic_url: str, purpose: str) -> EmailContent:
    variants = {
        "recovery": ("Your Relay Access recovery link", "Open private recovery link", "Use this one-time link for your Relay Access recovery request. Opening it does not replace your key or disconnect your device. Contact Beacon Tools support if you need help recovering access."),
        "protect_and_deliver": ("Verify your email for Relay Access", "Verify email and receive key", "Verify this email address to protect your Relay Access license for Local Flight and receive its portable key. Email verification does not move access away from your current device."),
        "protect_and_transfer": ("Verify your email before transferring Relay Access", "Verify email for transfer", "Verify this email address before moving Relay Access to another main device. Verification alone does not disconnect your current device; you must confirm the move separately."),
    }
    heading, label, intro = variants.get(purpose.strip().lower(), ("Your private Relay Access link", "Open private link", "Use this one-time link for your Relay Access request. Contact Beacon Tools support if you need help."))
    return render_email(subject="Local Flight — " + heading[0].lower() + heading[1:], heading=heading,
                        paragraphs=[intro, "This link expires in 15 minutes and can be used once. Keep it private.", "If you did not request this link, you can ignore this message."],
                        action_url=magic_url, action_label=label)


def moved_email(*, device_name: str) -> EmailContent:
    return render_email(subject="Local Flight — your main device changed", heading="Your main device changed",
                        paragraphs=["Relay Access is now active on a new main device.", "New main device: " + device_name,
                                    "The previous main device can no longer use Beacon Relay directly. If this was not you, contact Beacon Tools support for help recovering your access."],
                        action_url=SUPPORT_URL, action_label="Get support")


def operator_email(*, purpose: str, action_url: str = "", expires_at: str = "") -> EmailContent:
    if purpose == "operator:invitation":
        heading, label = "Your Relay Access invitation", "Review invitation"
        paragraphs = ["Beacon Tools has invited you to use Relay Access for Local Flight on one main device. Confirm your email address to accept.",
                      "This invitation link expires within 24 hours, or sooner if the access expires. It can be used once.",
                      "Access expires on " + readable_expiry(expires_at) + "." if expires_at else "Access has no scheduled expiry.",
                      "This invitation is not a purchase or payment receipt. If you were not expecting it, you can ignore this message."]
    elif purpose == "operator:email_change":
        heading, label = "Confirm your Relay Access email change", "Confirm this email address"
        paragraphs = ["A change to the protected email address for your Local Flight Relay Access license has been requested.",
                      "Both the old and new email addresses must approve within 30 minutes. Confirming only one address leaves your access unchanged.",
                      "Once both addresses confirm, your key will be replaced and the current main device disconnected. The replacement key will be emailed to the new address.",
                      "Confirm only if you requested this change. Otherwise, ignore this message; do not share the link."]
    elif purpose == "operator:email_changed":
        heading, label = "Your Relay Access email has changed", "Get support"
        paragraphs = ["Both email addresses confirmed the change to your Local Flight Relay Access license.",
                      "The old key no longer works, and the previous main device has been disconnected. Your replacement key is being sent to the new verified address. Use it to reconnect your main device.",
                      "This notice was sent to the previous email address. Contact support if this was unexpected."]
        action_url = SUPPORT_URL
    elif purpose == "operator:smtp_test":
        heading, label = "Email delivery check", ""
        paragraphs = ["This is a Beacon Tools email delivery check for Local Flight. It creates no license and contains no access credentials.",
                      "SMTP acceptance confirms that the mail server accepted the message. Check the destination mailbox to confirm whether it arrived in Inbox or Junk."]
        action_url = ""
    else:
        raise AccessConfigurationError("Operator email type is not supported")
    return render_email(subject="Local Flight — " + heading[0].lower() + heading[1:], heading=heading,
                        paragraphs=paragraphs, action_url=action_url, action_label=label)


def contact_email(*, category: str, subject: str, name: str, reply_email: str, context: str, message: str, network_tag: str) -> EmailContent:
    label = CONTACT_CATEGORIES[category]
    return render_email(subject=f"[Beacon Tools] {label}: {subject}", heading=label,
                        section="Website contact form", customer=False,
                        paragraphs=["A message was submitted through the Beacon Tools website.",
                                    "Name: " + (name or "Not provided"), "Reply email: " + (reply_email or "Not provided"),
                                    "Page/context: " + (context or "Not provided"), "Message:\n" + message,
                                    "Reply directly to this email to contact the sender." if reply_email else "No reply email was provided.",
                                    "Routing reference: " + network_tag])
