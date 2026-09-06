const SECRET_REPLACEMENTS: ReadonlyArray<readonly [RegExp, string]> = [
  [
    /(AVIATIONSTACK_API_KEY|AERODATABOX_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY|LINEAR_REPORTER_API_KEY)=\S+/gi,
    "$1=[redacted]"
  ],
  [
    /(LOCALFLIGHT_ACTIVATION_TOKEN|RELAY_ACCESS_HASH_SECRET|RELAY_ACCESS_KEY_SECRET|STRIPE_SECRET_KEY|STRIPE_WEBHOOK_SECRET|RELAY_LICENSE_SMTP_PASSWORD|RELAY_CONTACT_SMTP_PASSWORD|SMTP_PASSWORD)=\S+/gi,
    "$1=[redacted]"
  ],
  [/(access_key=)[^&\s]+/gi, "$1[redacted]"],
  [/(X-RapidAPI-Key['":\s]+)[A-Za-z0-9._-]+/gi, "$1[redacted]"],
  [/(x-magicapi-key['":\s]+)[A-Za-z0-9._-]+/gi, "$1[redacted]"],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]"],
  [/lin_api_[A-Za-z0-9_]+/gi, "[redacted-linear-token]"],
  [/lfm_[A-Za-z0-9._~-]+/gi, "[redacted-activation-token]"],
  [/lfr[a-z0-9]*_[A-Za-z0-9._~-]+/gi, "[redacted-relay-token]"],
  [/\bLFRA(?:[ -]?[0-9A-HJKMNP-TV-Z]){27}\b/gi, "[redacted-relay-license-key]"],
  [/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "[redacted-uuid]"],
  [/\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/g, "10.$1.$2.x"],
  [/\b192\.168\.(\d{1,3})\.(\d{1,3})\b/g, "192.168.$1.x"],
  [/\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b/g, "172.$1.$2.x"]
];

export function redactSensitiveReportText(value: string | null | undefined): string {
  let redacted = value || "";
  for (const [pattern, replacement] of SECRET_REPLACEMENTS) {
    redacted = redacted.replace(pattern, replacement);
  }
  return redacted;
}
