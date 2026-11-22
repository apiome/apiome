/**
 * catalog-revision-diff (MFI-28.1, #4117) — the "compare read" behind the inline version diff in the
 * catalog detail Versions tab.
 *
 * The catalog reads each revision's OpenAPI document exactly as the versions dashboard does: the
 * document apiome-rest renders once per change of a revision and keeps in the document store
 * (COA-5.13, #7089), fetched through {@link loadRevisionDocument}. The two documents are shown
 * side by side / unified in the shared Monaco diff viewer. Nothing is generated in the browser or
 * in the Next.js server.
 *
 * Isolating the read here keeps `CatalogVersionsPanel` a thin view and gives its jest tests a single
 * module to mock.
 */

import { loadRevisionDocument, type RevisionDocument } from '@/app/utils/revision-document';
import type { CatalogVersionRevision } from '@/app/utils/catalog-versions-timeline';

/**
 * Read one catalog revision's OpenAPI document.
 *
 * @param revision The revision to read.
 * @param itemId The catalog item's (project's) id.
 * @param signal Aborts the read.
 * @returns The pretty-printed (2-space) document and its digest; two revisions with the same digest
 *   have the same document.
 * @throws RevisionDocumentError when the document cannot be read.
 */
export async function loadCatalogRevisionSpec(
  revision: CatalogVersionRevision,
  itemId: string,
  signal?: AbortSignal,
): Promise<RevisionDocument> {
  return loadRevisionDocument(itemId, revision.id, signal);
}
