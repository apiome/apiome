'use client';

/**
 * Load a catalog item's upload state once — RAR-6.2 (#3539).
 *
 * The item page reads it on mount (the stale banner sits above the panes) and shares it with the
 * **Uploaded file** card on the Provenance tab, so one request serves both. A failed read is kept
 * as `error` for the card; the banner just draws nothing.
 */

import * as React from 'react';

import { requestUploadJson, type CatalogUpload } from './catalogUploadModel';

export interface CatalogItemUploadState {
  /** The upload state, or null while it loads (or after an error). */
  upload: CatalogUpload | null;
  /** Why it could not be read, or null. */
  error: string | null;
  /** Replace the state, e.g. with the answer a re-upload returns. */
  setUpload: (upload: CatalogUpload) => void;
}

/**
 * Read `GET /api/catalog/{itemId}/upload` once per item.
 *
 * @param itemId The catalog item.
 * @param enabled False to skip the read (a deleted item cannot be re-uploaded).
 * @returns The state, its error and a setter.
 */
export function useCatalogItemUpload(itemId: string, enabled: boolean): CatalogItemUploadState {
  const [upload, setUpload] = React.useState<CatalogUpload | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    requestUploadJson<CatalogUpload>(
      `/api/catalog/${encodeURIComponent(itemId)}/upload`,
      'The upload details could not be loaded.',
    )
      .then((answer) => {
        if (live) setUpload(answer);
      })
      .catch((caught: unknown) => {
        if (live) setError(caught instanceof Error ? caught.message : String(caught));
      });
    return () => {
      live = false;
    };
  }, [itemId, enabled]);

  return { upload, error, setUpload };
}
