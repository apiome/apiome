/**
 * Response headers the export BFF passes through from a REST download (X6, #6227).
 *
 * `POST /api/export/document` and `GET /api/export/jobs/{jobId}/download` hand an emitted file to
 * the browser verbatim. They keep REST's `Content-Type` and `Content-Disposition` (whose
 * `filename*` carries a non-ASCII name), and always send `X-Content-Type-Options: nosniff` so the
 * browser trusts the declared media type of a document built from imported content instead of
 * guessing one from its bytes.
 */

/**
 * The headers to send with a passed-through export download.
 *
 * @param upstream The REST response's headers.
 * @param options `contentLength` also copies `Content-Length` (a streamed job download).
 * @returns The headers for the BFF response.
 */
export function exportDownloadHeaders(upstream: Headers, options: { contentLength?: boolean } = {}): Headers {
  const headers = new Headers();
  const contentType = upstream.get('content-type');
  if (contentType) headers.set('Content-Type', contentType);
  const disposition = upstream.get('content-disposition');
  if (disposition) headers.set('Content-Disposition', disposition);
  if (options.contentLength) {
    const length = upstream.get('content-length');
    if (length) headers.set('Content-Length', length);
  }
  headers.set('X-Content-Type-Options', 'nosniff');
  return headers;
}
