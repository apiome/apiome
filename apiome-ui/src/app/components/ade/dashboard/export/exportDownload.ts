/**
 * Browser download helpers shared by the ExportDialog (MFX-6.1) and the Export Studio (MFX-41.1).
 *
 * Both surfaces emit a document via `POST /api/export/document` and then hand it to the browser
 * as a file (or a client-built `.zip`). These two pure-ish helpers — parsing the served filename
 * and triggering the anchor download — live here so the dialog and the Studio behave identically.
 */

/**
 * Parse the filename out of a `Content-Disposition` header.
 *
 * Prefers the RFC 6266 `filename*=UTF-8''…` form, which carries a non-ASCII name (`注文 API.json`),
 * and falls back to the ASCII `filename="…"` REST always sends beside it (X6, #6227).
 *
 * @param disposition The header value, or `null`.
 * @returns The file name, or `null` when the header names none.
 */
export function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  if (extended) {
    try {
      const decoded = decodeURIComponent(extended[1].trim());
      if (decoded) return decoded;
    } catch {
      // A malformed escape: use the ASCII name instead.
    }
  }
  const match = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  return match ? match[1] : null;
}

/** Hand a fetched document to the browser as a file download. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
