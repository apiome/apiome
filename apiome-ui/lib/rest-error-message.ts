/**
 * Render a FastAPI error body as one human-readable message.
 *
 * Three detail shapes reach the proxy layer: a plain string (most routes), a structured object
 * (the intake / delivery taxonomy errors, which carry `message` + `remediation` + `code`), and
 * FastAPI's own validation list. Only the first used to survive, so a taxonomy error — the one
 * case that already contains the actionable guidance — surfaced to the user as a bare
 * "Request failed" (MFI-29.3, where git-intake failures are all taxonomy-coded).
 *
 * Kept in its own module so it can be unit-tested without pulling in the database-backed proxy.
 */

/**
 * @param body The parsed JSON error body from a REST call.
 * @returns The message to show the user; a stable fallback when nothing usable is present.
 */
export function restErrorMessage(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === 'string' && msg.trim().length > 0);
    if (messages.length > 0) return messages.join('; ');
  }
  if (detail && typeof detail === 'object') {
    const { message, remediation } = detail as { message?: unknown; remediation?: unknown };
    const parts = [message, remediation].filter(
      (part): part is string => typeof part === 'string' && part.trim().length > 0,
    );
    if (parts.length > 0) return parts.join(' ');
  }
  return 'Request failed';
}

/**
 * The machine-readable `code` of a typed REST refusal (`detail: {code, …}`), or null.
 *
 * E1-6 (#6221): an export source with nothing captured answers `source-not-captured` /
 * `source-withheld`; a proxy passes the code on so the screen can say why and offer Re-import.
 *
 * @param detail The FastAPI `detail` of the error body.
 * @returns The code, or null when the refusal is untyped.
 */
export function restErrorCode(detail: unknown): string | null {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const code = (detail as { code?: unknown }).code;
  return typeof code === 'string' && code.trim() ? code : null;
}
