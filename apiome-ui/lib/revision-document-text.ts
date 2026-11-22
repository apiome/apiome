/**
 * The text form of a revision's OpenAPI document as the UI shows it (COA-5.13, #7089).
 *
 * apiome-rest stores and serves the document as compact JSON. The spec viewer and every text diff
 * work on lines, so the UI re-prints it with two-space indentation. Kept in one place so the
 * browser reader (`src/app/utils/revision-document.ts`) and the server routes
 * (`lib/revision-document-server.ts`) print it the same way and their diffs line up.
 */

/**
 * Re-print a JSON document with two-space indentation.
 *
 * @param compact The document as apiome-rest sent it.
 * @returns The same document, one value per line.
 * @throws SyntaxError when `compact` is not JSON.
 */
export function prettyDocumentText(compact: string): string {
  return JSON.stringify(JSON.parse(compact), null, 2);
}

/**
 * Whether two reads returned the same document, judged by digest alone.
 *
 * Two revisions with equal digests have byte-identical documents, so a diff of them is empty and
 * need not be computed. A missing digest never matches: without one the texts must be compared.
 *
 * @param a The digest of one side, if REST sent one.
 * @param b The digest of the other side.
 * @returns True only when both digests are present and equal.
 */
export function sameDocumentDigest(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  return Boolean(a) && Boolean(b) && String(a).toLowerCase() === String(b).toLowerCase();
}
