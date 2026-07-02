/**
 * Parse POST /api/versions error body after optimistic push (#2567).
 * REST returns 409 with code STALE_HEAD via the Next.js proxy.
 */

export type VersionsPostStaleHeadPayload = {
  code: 'STALE_HEAD';
  /** Server-supplied error string; undefined when no specific detail was returned. */
  message?: string;
  currentHeadRevisionId?: string;
  currentHead?: Record<string, unknown> | null;
};

export function parseStaleHeadFromVersionsPostJson(
  json: unknown,
  httpStatus: number
): VersionsPostStaleHeadPayload | null {
  if (httpStatus !== 409 || !json || typeof json !== 'object') return null;
  const o = json as Record<string, unknown>;
  if (o.code !== 'STALE_HEAD') return null;
  const message: string | undefined =
    typeof o.error === 'string' && o.error.trim()
      ? o.error
      : typeof o.message === 'string' && o.message.trim()
        ? o.message
        : undefined;
  const currentHeadRevisionId =
    typeof o.currentHeadRevisionId === 'string' ? o.currentHeadRevisionId : undefined;
  const ch = o.currentHead;
  const currentHead =
    ch && typeof ch === 'object' ? (ch as Record<string, unknown>) : null;
  return {
    code: 'STALE_HEAD',
    message,
    currentHeadRevisionId,
    currentHead,
  };
}
