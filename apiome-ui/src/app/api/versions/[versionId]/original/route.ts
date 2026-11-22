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

import { NextRequest } from 'next/server';
import { encodePartPath, proxyVersionStream } from '@lib/version-stream-proxy';

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

/** `GET /api/versions/[versionId]/original` — stream the original (or one file of a set). */
export async function GET(request: NextRequest, { params }: { params: Promise<{ versionId: string }> }) {
  const { versionId } = await params;
  return proxyVersionStream(request, versionId, {
    suffix: `/original${encodePartPath(request.nextUrl.searchParams.get('part'))}`,
    forwardedRequestHeaders: FORWARDED_REQUEST_HEADERS,
    passedResponseHeaders: PASSED_RESPONSE_HEADERS,
    failureMessage: (status) => `The original could not be downloaded (HTTP ${status}).`,
  });
}
