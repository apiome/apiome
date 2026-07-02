/** Shared filename/download utilities. */

/** Safe filename segment for downloads — strips non-word characters and caps at 96 chars. */
export function sanitizeFilenameSegment(raw: string): string {
  const s = raw.replace(/[^\w\-+.]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return s.slice(0, 96) || 'report';
}
