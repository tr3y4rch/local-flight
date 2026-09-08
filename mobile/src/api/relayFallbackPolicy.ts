export function shouldRetryOfficialPublicRelay(input: {
  status: number;
  contentType: string;
  hasJsonPayload: boolean;
}): boolean {
  if (input.status === 429) return false;
  if (input.status === 404 || input.status === 405 || input.status === 408 || input.status >= 500) return true;
  // A non-JSON response from an edge proxy is not a Local Flight policy
  // decision. Structured JSON authentication, activation, validation, quota
  // and rate-limit responses remain authoritative and are never replayed.
  return !input.hasJsonPayload
    && !input.contentType.toLowerCase().includes("application/json");
}
