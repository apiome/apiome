'use client';

/**
 * The **Uploaded file** card on a catalog item's Provenance tab — RAR-6.2 (#3539).
 *
 * Shown when the item's newest version came from a file upload. A status pill says whether it is
 * recent or may be stale (past the workspace's threshold), then the file, when it was uploaded, the
 * threshold, and the import settings a re-upload replays. With `projects:edit` it offers
 * **Re-upload…**. The last re-upload's outcome ("Added version …" / "nothing changed") shows under
 * the facts. The state is loaded by the page ({@link useCatalogItemUpload}) and shared with the
 * stale banner.
 */

import * as React from 'react';
import { FileUp } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardBody, CardHeader, CardTitle } from '@/app/components/ui/Card';

import { formatRefreshTime } from './catalogRefreshModel';
import { replayedSettings, uploadAgeText, uploadStatusView, type CatalogUpload } from './catalogUploadModel';

export interface CatalogItemUploadCardProps {
  /** The item's upload state; null while it loads. */
  upload: CatalogUpload | null;
  /** Why the state could not be read, or null. */
  error: string | null;
  /** True when the caller may re-upload (`projects:edit` on a live item). */
  canReupload: boolean;
  /** Open the re-upload dialog. */
  onReupload: () => void;
  /** What the last re-upload did, to show under the facts; null for none. */
  lastResult: string | null;
}

/**
 * Render the card. See {@link CatalogItemUploadCardProps}.
 *
 * @returns The card, or `null` when the item is not an upload (or failed to load quietly).
 */
export function CatalogItemUploadCard({ upload, error, canReupload, onReupload, lastResult }: CatalogItemUploadCardProps) {
  if (error) {
    return (
      <Card data-testid="catalog-detail-upload">
        <CardHeader>
          <CardTitle>
            <FileUp aria-hidden />
            Uploaded file
          </CardTitle>
        </CardHeader>
        <CardBody>
          <p className="cid-refresh__error" role="alert">
            {error}
          </p>
        </CardBody>
      </Card>
    );
  }
  if (!upload?.eligible) return null;

  const status = uploadStatusView(upload);
  const settings = replayedSettings(upload.spec);

  return (
    <Card data-testid="catalog-detail-upload">
      <CardHeader className="cid-refresh__head">
        <div>
          <CardTitle>
            <FileUp aria-hidden />
            Uploaded file
          </CardTitle>
          <p className="cid-note">Apiome can&apos;t check an uploaded file for changes; re-upload it when it changes</p>
        </div>
        {canReupload ? (
          <div className="cid-refresh__actions">
            <Button variant="outline" size="sm" onClick={onReupload} data-testid="catalog-detail-upload-reupload">
              Re-upload…
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardBody>
        <dl className="cid-kv" data-testid="catalog-detail-upload-facts">
          <dt>Status</dt>
          <dd>
            <Badge variant={status.tone} data-testid="catalog-detail-upload-status">
              {status.label}
            </Badge>
          </dd>
          <dt>File</dt>
          <dd className="mono cid-refresh__endpoint">{upload.sourceLabel || 'Unnamed file'}</dd>
          <dt>Uploaded</dt>
          <dd>
            {formatRefreshTime(upload.uploadedAt)}
            <span className="cid-quiet"> ({uploadAgeText(upload.ageDays)})</span>
          </dd>
          <dt>May be stale after</dt>
          <dd data-testid="catalog-detail-upload-threshold">
            {upload.staleAfterDays === 1 ? '1 day' : `${upload.staleAfterDays} days`}
          </dd>
          <dt>Re-upload uses</dt>
          <dd data-testid="catalog-detail-upload-settings">
            {!upload.spec ? (
              <span className="cid-quiet">Default settings (uploaded before Apiome kept import settings)</span>
            ) : settings.length ? (
              <ul className="cid-upload__settings">
                {settings.map((row) => (
                  <li key={row.label}>
                    {row.label}: <span className="mono">{row.value}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="cid-quiet">The default settings, as the first upload did</span>
            )}
          </dd>
        </dl>
        {lastResult ? (
          <p className="cid-note cid-upload__result" role="status" data-testid="catalog-detail-upload-result">
            {lastResult}
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
