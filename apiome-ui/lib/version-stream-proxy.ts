/**
 * Stream a revision's stored bytes from apiome-rest to the browser.
 *
 * Shared by the two version routes that pass a stored object through untouched:
 * `/api/versions/[versionId]/original` (the file a version was imported from, COA-5.7) and
 * `/api/versions/[versionId]/document` (the rendered OpenAPI document, COA-5.13). Both check the ids,
 * resolve the signed-in user's workspace, forward the conditional request headers and hand REST's
 * body back as a stream, so a large document is never buffered in the Next.js server.
 *
 * Auth and forwarding only: the permission check is REST's. A refusal keeps REST's status and comes
 * back as `{ success: false, error, code }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What one streaming route forwards and passes back. */
export interface VersionStreamOptions {
  /**
   * The REST path below `/versions/{tenant}/{projectId}/{versionId}`, with its leading slash
   * (for example `/document`).
   */
  suffix: string;
  /** Request headers forwarded to REST (lower case). */
  forwardedRequestHeaders: readonly string[];
  /** Response headers passed back to the browser (lower case). */
  passedResponseHeaders: readonly string[];
  /** Says what could not be read, given REST's status, when REST sent no message of its own. */
  failureMessage: (status: number) => string;
}

/**
 * Proxy one GET of a revision's stored bytes.
 *
 * @param request The browser's request; `projectId` is read from its query string.
 * @param versionId The revision UUID from the route.
 * @param options What to forward; see {@link VersionStreamOptions}.
 * @returns REST's response streamed through (`200`, `206`, `304`), or a failure envelope: `400` for
 *   a malformed id, the session's status when nobody is signed in, `502` when REST is unreachable,
 *   otherwise REST's own status.
 */
export async function proxyVersionStream(
  request: NextRequest,
  versionId: string,
  options: VersionStreamOptions,
): Promise<NextResponse> {
  const projectId = request.nextUrl.searchParams.get('projectId') ?? '';
  if (!UUID.test(versionId) || !UUID.test(projectId)) {
    return NextResponse.json(
      { success: false, error: 'A project and version id are required.' },
      { status: 400 },
    );
  }
  const context = await getAuthenticatedTenantContext();
  if (!context.ok) {
    return NextResponse.json({ success: false, error: context.error }, { status: context.status });
  }

  const headers: Record<string, string> = { ...createRestAuthHeaders(context.user) };
  delete headers['Content-Type'];
  for (const name of options.forwardedRequestHeaders) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }

  const url = `${REST_API_BASE_URL}/versions/${encodeURIComponent(context.tenantSlug)}/${projectId}/${versionId}${options.suffix}`;
  let rest: Response;
  try {
    rest = await fetch(url, { method: 'GET', headers, cache: 'no-store' });
  } catch {
    return NextResponse.json(
      { success: false, error: 'apiome-rest could not be reached.' },
      { status: 502 },
    );
  }

  if (!rest.ok && rest.status !== 304 && rest.status !== 206) {
    const contentType = rest.headers.get('content-type') ?? '';
    const data = contentType.includes('application/json')
      ? await rest.json().catch(() => null)
      : null;
    const detail = data?.detail;
    const error =
      typeof detail === 'string'
        ? detail
        : typeof detail?.message === 'string'
          ? detail.message
          : options.failureMessage(rest.status);
    return NextResponse.json(
      { success: false, error, code: typeof detail?.code === 'string' ? detail.code : undefined },
      { status: rest.status },
    );
  }

  const passed = new Headers();
  for (const name of options.passedResponseHeaders) {
    const value = rest.headers.get(name);
    if (value) passed.set(name, value);
  }
  return new NextResponse(rest.status === 304 ? null : rest.body, {
    status: rest.status,
    headers: passed,
  });
}

/**
 * Encode a path inside a stored set of files as REST path segments.
 *
 * @param part The path inside the set, or nothing.
 * @returns `''` for no part, else `/a/b` with each segment percent-encoded.
 */
export function encodePartPath(part?: string | null): string {
  const trimmed = (part ?? '').replace(/^\/+|\/+$/g, '');
  return trimmed ? `/${trimmed.split('/').map(encodeURIComponent).join('/')}` : '';
}
