/**
 * User-facing error messages for the public export dialog — MFX-7.3 (#3862).
 *
 * Maps the REST guard responses (429 rate limit, 413 size cap, 404 unpublished) to stable
 * copy the dialog can show without parsing raw JSON error envelopes. The envelope parsing
 * itself lives in `lib/http/problemDetail`, shared with the Get SDK panel (SDK-3.3).
 */

import { detailFromBody } from '../http/problemDetail';

/**
 * A stable, user-facing message for a failed public export HTTP response.
 *
 * @param status - The HTTP status code from fetch.
 * @param bodyText - Optional raw response body for server detail extraction.
 * @returns A short sentence suitable for the dialog error banner.
 */
export function publicExportErrorMessage(status: number, bodyText?: string | null): string {
  const detail = bodyText ? detailFromBody(bodyText) : null;

  if (status === 429) {
    return (
      detail ??
      'Too many export requests from this browser. Please wait a moment and try again.'
    );
  }
  if (status === 413) {
    return (
      detail ??
      'This export is too large to download publicly. Try another target or contact the publisher.'
    );
  }
  if (status === 404) {
    return detail ?? 'This version is not available for public export.';
  }
  if (detail) {
    return detail;
  }
  return `Export failed (${status}).`;
}

/**
 * Read response text once and build the public export error message.
 *
 * @param response - A non-OK fetch Response from the public export surface.
 */
export async function publicExportErrorFromResponse(response: Response): Promise<string> {
  let bodyText = '';
  try {
    bodyText = await response.text();
  } catch {
    bodyText = '';
  }
  return publicExportErrorMessage(response.status, bodyText);
}
