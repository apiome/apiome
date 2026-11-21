/**
 * Download a revision's stored original (COA-5.7, #7083).
 *
 * Proxies `GET /api/versions/[versionId]/original?projectId=…[&part=…]` to
 * `GET /v1/versions/{tenant}/{projectId}/{versionId}/original[/{part}]`. The body is streamed
 * through untouched, with the headers a download needs (`Content-Type`, `Content-Disposition`,
 * `Content-Length`, `ETag`, `Accept-Ranges`, `Content-Range`, `X-Apiome-Content-Sha256`), and
 * `Range`, `If-Range` and `If-None-Match` are forwarded, so `206` / `304` / `416` reach the browser.
 *
 * Auth and forwarding only: the `versions:view` permission and the withheld rule are REST's. A
 * refusal keeps REST's status and comes back as `{ success: false, error, code }` (`code` is
 * `original-not-stored` or `original-withheld` for the two expected cases).
 */

import { NextRequest, NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/** Request headers forwarded to REST. */
const FORWARDED_REQUEST_HEADERS = ['range', 'if-range', 'if-none-match'] as const;
/** Response headers passed back to the browser. */
const PASSED_RESPONSE_HEADERS = [
  'content-type',
  'content-disposition',
  'content-length',
  'content-range',
  'accept-ranges',
  'etag',
  'cache-control',
  'x-apiome-content-sha256',
  'x-content-type-options',
] as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Build the REST path of an original.
 *
 * @param slug Tenant slug.
 * @param projectId Project UUID.
 * @param versionId Revision UUID.
 * @param part A file of a stored set, by its path inside the set; omitted for the original itself.
 * @returns The absolute REST URL.
 */
function restOriginalUrl(slug: string, projectId: string, versionId: string, part?: string | null): string {
  const base = `${REST_API_BASE_URL}/versions/${encodeURIComponent(slug)}/${projectId}/${versionId}/original`;
  const trimmed = (part ?? '').replace(/^\/+|\/+$/g, '');
  if (!trimmed) return base;
  return `${base}/${trimmed.split('/').map(encodeURIComponent).join('/')}`;
}

/** `GET /api/versions/[versionId]/original` — stream the original (or one file of a set). */
export async function GET(request: NextRequest, { params }: { params: Promise<{ versionId: string }> }) {
  const { versionId } = await params;
  const projectId = request.nextUrl.searchParams.get('projectId') ?? '';
  if (!UUID.test(versionId) || !UUID.test(projectId)) {
    return NextResponse.json({ success: false, error: 'A project and version id are required.' }, { status: 400 });
  }
  const context = await getAuthenticatedTenantContext();
  if (!context.ok) {
    return NextResponse.json({ success: false, error: context.error }, { status: context.status });
  }

  const headers: Record<string, string> = { ...createRestAuthHeaders(context.user) };
  delete headers['Content-Type'];
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }

  let rest: Response;
  try {
    rest = await fetch(restOriginalUrl(context.tenantSlug, projectId, versionId, request.nextUrl.searchParams.get('part')), {
      method: 'GET',
      headers,
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ success: false, error: 'apiome-rest could not be reached.' }, { status: 502 });
  }

  if (!rest.ok && rest.status !== 304 && rest.status !== 206) {
    const contentType = rest.headers.get('content-type') ?? '';
    const data = contentType.includes('application/json') ? await rest.json().catch(() => null) : null;
    const detail = data?.detail;
    const error =
      typeof detail === 'string'
        ? detail
        : typeof detail?.message === 'string'
          ? detail.message
          : `The original could not be downloaded (HTTP ${rest.status}).`;
    return NextResponse.json(
      { success: false, error, code: typeof detail?.code === 'string' ? detail.code : undefined },
      { status: rest.status },
    );
  }

  const passed = new Headers();
  for (const name of PASSED_RESPONSE_HEADERS) {
    const value = rest.headers.get(name);
    if (value) passed.set(name, value);
  }
  return new NextResponse(rest.status === 304 ? null : rest.body, { status: rest.status, headers: passed });
}
