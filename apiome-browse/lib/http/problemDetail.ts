/**
 * Reading a FastAPI error body — shared by every public REST surface browse talks to.
 *
 * The REST layer answers a refusal with `{"detail": "..."}`. Two surfaces need to lift that
 * sentence out and fall back to their own copy when it is absent — the public export dialog
 * (MFX-7.3) and the Get SDK panel (SDK-3.3) — so the parsing lives here rather than once per
 * surface, where the two copies would agree until one of them was fixed.
 *
 * Framework-free, so it is unit-testable under the browse Vitest setup (which runs `lib/**`
 * only, in a node environment).
 */

/**
 * Parse a FastAPI-style error body, when the response carried one.
 *
 * @param body - The raw response body text.
 * @returns The trimmed `detail` sentence, or null when the body is not JSON, is not an object,
 *   or names no usable `detail`.
 */
export function detailFromBody(body: string): string | null {
  const trimmed = body.trim();
  if (!trimmed.startsWith('{')) return null;
  try {
    const parsed = JSON.parse(trimmed) as { detail?: unknown };
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Read a non-OK response's body once and return its `detail`, if any.
 *
 * Never throws: a body that cannot be read is the same answer as one that names no detail, and a
 * caller in an error path should not have to handle a second error.
 *
 * @param response - A non-OK fetch Response.
 * @returns The server's `detail` sentence, or null.
 */
export async function readProblemDetail(response: Response): Promise<string | null> {
  let bodyText = '';
  try {
    bodyText = await response.text();
  } catch {
    return null;
  }
  return detailFromBody(bodyText);
}
