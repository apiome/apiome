/**
 * Read a revision's OpenAPI document (COA-5.13, #7089).
 *
 * Proxies `GET /api/versions/[versionId]/document?projectId=…` to
 * `GET /v1/versions/{tenant}/{projectId}/{versionId}/document`, the document apiome-rest renders
 * once per change of the revision and then serves from the document store. The version view, the
 * compare view and the catalog's version diff read it here; nothing is generated in this server and
 * Postgres is not queried for classes or properties.
 *
 * The body is streamed through untouched with `Content-Type`, `Content-Length`, `ETag`,
 * `X-Apiome-Content-Sha256` (the document's digest) and `X-Apiome-Document-Cache` (`hit` or `miss`).
 * `If-None-Match` is forwarded, so an unchanged document answers `304` with no body.
 *
 * Auth and forwarding only: the `versions:view` permission is REST's. A refusal keeps REST's status
 * and comes back as `{ success: false, error, code }`.
 */

import { NextRequest } from 'next/server';
import { proxyVersionStream } from '@lib/version-stream-proxy';

export const dynamic = 'force-dynamic';

/** Request headers forwarded to REST. */
const FORWARDED_REQUEST_HEADERS = ['if-none-match'] as const;
/** Response headers passed back to the browser. */
const PASSED_RESPONSE_HEADERS = [
  'content-type',
  'content-length',
  'etag',
  'cache-control',
  'x-apiome-content-sha256',
  'x-apiome-document-cache',
] as const;

/** `GET /api/versions/[versionId]/document` — stream the revision's rendered OpenAPI document. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> },
) {
  const { versionId } = await params;
  return proxyVersionStream(request, versionId, {
    suffix: '/document',
    forwardedRequestHeaders: FORWARDED_REQUEST_HEADERS,
    passedResponseHeaders: PASSED_RESPONSE_HEADERS,
    failureMessage: (status) => `The document could not be read (HTTP ${status}).`,
  });
}
