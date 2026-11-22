/**
 * The settings a document-storage request may carry (COA-5.15, #7092), shared by the save and
 * test proxies so neither forwards a field REST does not define.
 */

const STRING_FIELDS = ['credentialId', 'bucket', 'prefix', 'region', 'endpointUrl', 'kmsKeyId'] as const;
const ADDRESSING = ['auto', 'path', 'virtual'];
const SSE = ['', 's3', 'kms'];

/**
 * Keep only the well-formed settings fields of a browser body.
 *
 * @param raw - The parsed request body.
 * @returns The body to forward, or null when it names no valid `mode`.
 */
export function settingsBody(raw: unknown): Record<string, unknown> | null {
  const input = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  if (input.mode !== 'platform' && input.mode !== 'tenant') return null;
  const body: Record<string, unknown> = { mode: input.mode };
  for (const field of STRING_FIELDS) {
    if (typeof input[field] === 'string') body[field] = input[field];
  }
  if (typeof input.addressingStyle === 'string' && ADDRESSING.includes(input.addressingStyle)) {
    body.addressingStyle = input.addressingStyle;
  }
  if (typeof input.sse === 'string' && SSE.includes(input.sse)) body.sse = input.sse;
  return body;
}
