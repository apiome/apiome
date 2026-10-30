'use client';

/**
 * CatalogStaleUploadBanner — RAR-6.2 (#3539): the item page's hint that an uploaded file may have
 * drifted from the copy its owner keeps elsewhere.
 *
 * An item imported from an uploaded file has no live source Apiome could re-check, so when its
 * newest version is at least the workspace's threshold old (90 days by default) this banner sits
 * above the panes. **Re-upload…** opens the re-upload dialog (offered to callers who may edit the
 * item); **Upload details** opens the Provenance tab, where the **Uploaded file** card lists the
 * import settings a re-upload replays. It draws nothing for a recent upload or a non-upload.
 */

import * as React from 'react';

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';

import { staleUploadTitle, type CatalogUpload } from './catalogUploadModel';

export interface CatalogStaleUploadBannerProps {
  /** The item's upload state; `null` (loading) or a non-stale state draws nothing. */
  upload: CatalogUpload | null;
  /** Whether the caller may re-upload (`projects:edit` on a live item). */
  canReupload: boolean;
  /** Open the re-upload dialog. */
  onReupload: () => void;
  /** Open the Provenance tab. */
  onOpenDetails: () => void;
}

/**
 * Render the banner. See {@link CatalogStaleUploadBannerProps}.
 *
 * @returns The banner, or `null` unless the upload may be stale.
 */
export function CatalogStaleUploadBanner({ upload, canReupload, onReupload, onOpenDetails }: CatalogStaleUploadBannerProps) {
  if (!upload?.stale) return null;
  return (
    <Alert
      variant="warn"
      role="status"
      className="cid-stale-upload"
      data-testid="catalog-stale-upload-banner"
      actions={
        <>
          {canReupload ? (
            <Button size="sm" variant="outline" onClick={onReupload} data-testid="catalog-stale-upload-reupload">
              Re-upload…
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onOpenDetails} data-testid="catalog-stale-upload-details">
            Upload details
          </Button>
        </>
      }
    >
      <AlertTitle>{staleUploadTitle(upload)}</AlertTitle>
      <AlertDescription>
        It may be stale. Apiome can&apos;t check an uploaded file for changes, so re-upload the current copy to bring
        this item up to date. The re-upload uses the same import settings.
      </AlertDescription>
    </Alert>
  );
}
