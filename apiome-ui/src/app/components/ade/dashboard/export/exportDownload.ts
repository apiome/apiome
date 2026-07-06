/**
 * Browser download helpers shared by the ExportDialog (MFX-6.1) and the Export Studio (MFX-41.1).
 *
 * Both surfaces emit a document via `POST /api/export/document` and then hand it to the browser
 * as a file (or a client-built `.zip`). These two pure-ish helpers — parsing the served filename
 * and triggering the anchor download — live here so the dialog and the Studio behave identically.
 */

/** Parse the filename out of a `Content-Disposition: attachment; filename="…"` header. */
export function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename="?([^";]+)"?/i.exec(disposition);
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
