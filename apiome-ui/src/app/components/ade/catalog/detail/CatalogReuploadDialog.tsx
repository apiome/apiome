'use client';

/**
 * Re-upload a catalog item's file — RAR-6.2 (#3539).
 *
 * Opened from the stale banner or the **Uploaded file** card. The user picks the new copy of the
 * file; the dialog lists the import settings the first upload used, which REST replays, so the new
 * version is imported the same way. **Re-upload** sends `POST /api/catalog/{id}/reupload`: a file
 * that matches the current version adds nothing, a changed one adds a version. Anything REST
 * refuses (the import quality policy, a file the importer cannot read) is shown under the form.
 */

import * as React from 'react';

import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';

import {
  replaySummary,
  replayedSettings,
  requestUploadJson,
  reuploadBodyFrom,
  type CatalogReuploadResult,
  type CatalogUpload,
} from './catalogUploadModel';

export interface CatalogReuploadDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per open so the form resets. */
  open: boolean;
  /** The item's id and name. */
  item: { id: string; name: string };
  /** The item's upload state (what the re-upload replays). */
  upload: CatalogUpload;
  /** Called with the open state. */
  onOpenChange: (open: boolean) => void;
  /** Called with REST's answer after a re-upload ran. */
  onReuploaded: (result: CatalogReuploadResult) => void;
}

const FILE_FIELD = 'catalog-reupload-file';

/**
 * Render the dialog. See {@link CatalogReuploadDialogProps}.
 *
 * @returns The dialog.
 */
export function CatalogReuploadDialog({ open, item, upload, onOpenChange, onReuploaded }: CatalogReuploadDialogProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [sending, setSending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const returnFocus = useReturnFocus(open);
  const settings = replayedSettings(upload.spec);

  const handleReupload = async () => {
    if (!file) {
      setError('Choose the new copy of the file first.');
      return;
    }
    setSending(true);
    setError(null);
    try {
      const body = await reuploadBodyFrom(file);
      const result = await requestUploadJson<CatalogReuploadResult>(
        `/api/catalog/${encodeURIComponent(item.id)}/reupload`,
        'The file could not be re-uploaded.',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      );
      onReuploaded(result);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The file could not be re-uploaded.');
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!sending ? onOpenChange(next) : undefined)}>
      <DialogContent size="sm" onCloseAutoFocus={returnFocus} data-testid="catalog-reupload-dialog">
        <DialogHeader>
          <DialogTitle>Re-upload {item.name}</DialogTitle>
          <DialogDescription>
            Choose the current copy of {upload.sourceLabel || 'the file'}. If it differs from this item&apos;s
            current version, Apiome adds a version with a change report.
          </DialogDescription>
        </DialogHeader>

        <div className="cid-refresh-form">
          <FormField label="File" htmlFor={FILE_FIELD}>
            <Input
              id={FILE_FIELD}
              type="file"
              className="cid-reupload__file"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setError(null);
              }}
              data-testid="catalog-reupload-file"
            />
          </FormField>

          <div className="cid-reupload__replay" data-testid="catalog-reupload-replay">
            <p className="cid-note">{replaySummary(upload)}</p>
            {settings.length ? (
              <dl className="cid-kv">
                {settings.map((row) => (
                  <React.Fragment key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </React.Fragment>
                ))}
              </dl>
            ) : null}
          </div>

          {error ? (
            <div className="cid-refresh__error" role="alert" data-testid="catalog-reupload-error">
              {error}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={sending}
            title={sending ? 'Wait for the re-upload to finish' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={sending || !file}
            title={sending ? 'Importing the file' : !file ? 'Choose a file first' : undefined}
            onClick={() => void handleReupload()}
            data-testid="catalog-reupload-submit"
          >
            {sending ? 'Re-uploading…' : 'Re-upload'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
