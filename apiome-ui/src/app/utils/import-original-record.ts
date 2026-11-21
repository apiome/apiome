/**
 * Record the original document of an import (COA-5.3, #7079).
 *
 * The import wizard and the repository file import write a revision themselves, so REST never
 * sees the file they read. After such an import succeeds, the dialog sends the text here
 * (`POST /api/import-originals`) and REST keeps it — after the workspace's secret scrub — as the
 * revision's original in the document store. A dry run writes no revision, so it records nothing.
 */

/** The `POST /api/import-originals` body. */
export interface ImportOriginalRecordBody {
  /** The revision the import produced (`versions.id`). */
  versionId: string;
  /** The document text, exactly as the dialog read it. */
  content: string;
  /** The file name, path or URL the document came from. */
  filename?: string;
}

/**
 * Build the record body for a finished import, or `null` when there is nothing to record.
 *
 * @param result The finished import's result; `versionId` is the revision's record id.
 * @param content The document text the import read.
 * @param filename The file name, path or URL the document came from.
 * @returns The body, or `null` without a revision or without text.
 */
export function buildImportOriginalRecord(
  result: { versionId?: string | null } | null | undefined,
  content: string | null | undefined,
  filename?: string | null,
): ImportOriginalRecordBody | null {
  const versionId = result?.versionId?.trim();
  if (!versionId || typeof content !== 'string' || !content.trim()) return null;
  const name = filename?.trim();
  return { versionId, content, ...(name ? { filename: name } : {}) };
}

/**
 * Send the record. Best-effort: a failure is logged and reported, never thrown, because the import
 * itself already succeeded.
 *
 * @param body From {@link buildImportOriginalRecord}.
 * @param fetchImpl The fetch to use (tests pass one).
 * @returns `true` when REST answered without an error (also when the revision already had an original).
 */
export async function recordImportOriginal(
  body: ImportOriginalRecordBody,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const response = await fetchImpl('/api/import-originals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) console.warn('[import-original] could not record the original document', response.status);
    return response.ok;
  } catch (error) {
    console.warn(
      '[import-original] could not record the original document',
      error instanceof Error ? error.name : 'unknown',
    );
    return false;
  }
}
