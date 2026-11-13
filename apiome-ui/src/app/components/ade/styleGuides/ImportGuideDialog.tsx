'use client';

import * as React from 'react';
import { FileUp, Link2, Upload } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Spinner } from '@/app/components/ui/Spinner';

import {
  EMPTY_STYLE_GUIDE_IMPORT_DRAFT,
  MAX_STYLE_GUIDE_DOCUMENT_BYTES,
  buildStyleGuideImportRequest,
  styleGuideImportSummary,
  type StyleGuideImportDraft,
  type StyleGuideImportRequest,
  type StyleGuideImportResult,
  type StyleGuideImportSource,
} from './styleGuideTransfer';

/**
 * The import dialog — Rule Set Import/Export (#1747).
 *
 * Creates a new custom guide from an `apiome.style-guide` JSON document, read from an
 * uploaded file or fetched from a URL. The dialog has two faces: the form, and — once the
 * write worked — what was imported, including any built-in rule this instance does not know
 * (an export from a newer or older release). Those are reported rather than silently dropped,
 * so the result stays on screen until the reader presses **Done**.
 */

/** Props for {@link ImportGuideDialog}. */
export interface ImportGuideDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /**
   * Run the import.
   *
   * @param request The POST body.
   * @returns `{result}` on success, or `{error}` — the sentence to show inline.
   */
  onSubmit: (
    request: StyleGuideImportRequest
  ) => Promise<{ result: StyleGuideImportResult } | { error: string }>;
}

/** Prefix for the dialog's field ids. */
const FIELD_ID = 'style-guide-import';

/**
 * The import dialog.
 *
 * @param props See {@link ImportGuideDialogProps}.
 * @returns The dialog.
 */
export default function ImportGuideDialog({ open, onOpenChange, onSubmit }: ImportGuideDialogProps) {
  const [draft, setDraft] = React.useState<StyleGuideImportDraft>(EMPTY_STYLE_GUIDE_IMPORT_DRAFT);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<StyleGuideImportResult | null>(null);

  // Opening is what resets the dialog, so a failed import keeps what the reader chose.
  React.useEffect(() => {
    if (!open) return;
    setDraft(EMPTY_STYLE_GUIDE_IMPORT_DRAFT);
    setError('');
    setBusy(false);
    setResult(null);
  }, [open]);

  /** Read the chosen file into the draft, refusing one the server would refuse anyway. */
  const pickFile = React.useCallback(async (file: File | undefined) => {
    setError('');
    if (!file) {
      setDraft((d) => ({ ...d, fileContent: '', fileName: '' }));
      return;
    }
    if (file.size > MAX_STYLE_GUIDE_DOCUMENT_BYTES) {
      setDraft((d) => ({ ...d, fileContent: '', fileName: '' }));
      setError('That file is larger than the 1 MiB limit.');
      return;
    }
    const text = await file.text();
    setDraft((d) => ({ ...d, fileContent: text, fileName: file.name }));
  }, []);

  const submit = React.useCallback(async () => {
    const built = buildStyleGuideImportRequest(draft);
    if ('error' in built) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError('');
    const outcome = await onSubmit(built.request);
    setBusy(false);
    if ('error' in outcome) {
      setError(outcome.error);
      return;
    }
    setResult(outcome.result);
  }, [draft, onSubmit]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="style-guide-import-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="accent">
              <Upload aria-hidden />
            </span>
            Import style guide
          </DialogTitle>
          <DialogDescription>
            Create a custom guide from a style-guide JSON file exported from Apiome.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="sg-form" data-testid="style-guide-import-result">
            <Alert variant="ok">
              <span>
                <strong>Created “{result.guide.name}”.</strong> {styleGuideImportSummary(result)}
              </span>
            </Alert>
            {result.skipped.length > 0 && (
              <div className="sg-field" data-testid="style-guide-import-skipped">
                <p className="sg-section-title">
                  Skipped {result.skipped.length} {result.skipped.length === 1 ? 'rule' : 'rules'}
                </p>
                <p className="sg-field__hint">
                  These built-in rules are not on this instance, so the guide does not include
                  them.
                </p>
                <ul className="sg-import-skipped">
                  {result.skipped.map((rule) => (
                    <li key={rule.ruleId}>
                      <code>{rule.ruleId}</code>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <form
            className="sg-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            {error && (
              <Alert variant="error" data-testid="style-guide-import-error">
                {error}
              </Alert>
            )}

            <div className="sg-field">
              <Label id={`${FIELD_ID}-source-label`}>Import from</Label>
              <Segmented
                size="sm"
                className="sg-import-source"
                value={draft.source}
                aria-labelledby={`${FIELD_ID}-source-label`}
                data-testid="style-guide-import-source"
                onValueChange={(next) => {
                  setError('');
                  setDraft((d) => ({ ...d, source: next as StyleGuideImportSource }));
                }}
              >
                <SegmentedItem value="file" disabled={busy}>
                  <FileUp aria-hidden />
                  File
                </SegmentedItem>
                <SegmentedItem value="url" disabled={busy}>
                  <Link2 aria-hidden />
                  URL
                </SegmentedItem>
              </Segmented>
            </div>

            {draft.source === 'file' ? (
              <div className="sg-field">
                <Label htmlFor={`${FIELD_ID}-file`}>
                  File <span aria-hidden="true">*</span>
                </Label>
                <Input
                  id={`${FIELD_ID}-file`}
                  type="file"
                  className="sg-import-file"
                  accept=".json,application/json"
                  disabled={busy}
                  data-testid="style-guide-import-file"
                  onChange={(event) => void pickFile(event.target.files?.[0])}
                />
                <p className="sg-field__hint">
                  A <code>.style-guide.json</code> file from a guide’s <strong>Export</strong>{' '}
                  action. Up to 1 MiB.
                </p>
              </div>
            ) : (
              <div className="sg-field">
                <Label htmlFor={`${FIELD_ID}-url`}>
                  URL <span aria-hidden="true">*</span>
                </Label>
                <Input
                  id={`${FIELD_ID}-url`}
                  type="url"
                  value={draft.url}
                  placeholder="https://example.com/payments.style-guide.json"
                  disabled={busy}
                  data-testid="style-guide-import-url"
                  onChange={(event) => setDraft((d) => ({ ...d, url: event.target.value }))}
                />
                <p className="sg-field__hint">
                  Fetched by the server. Private and internal addresses are refused.
                </p>
              </div>
            )}

            <div className="sg-field">
              <Label htmlFor={`${FIELD_ID}-name`}>
                Name <span className="sg-field__optional">(optional)</span>
              </Label>
              <Input
                id={`${FIELD_ID}-name`}
                value={draft.name}
                placeholder="Keep the name in the file"
                disabled={busy}
                data-testid="style-guide-import-name"
                onChange={(event) => setDraft((d) => ({ ...d, name: event.target.value }))}
              />
              <p className="sg-field__hint">
                Set one when a guide with the file’s name already exists.
              </p>
            </div>
          </form>
        )}

        <DialogFooter>
          {result ? (
            <Button data-testid="style-guide-import-done" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          ) : (
            <>
              <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                disabled={busy}
                data-testid="style-guide-import-submit"
                onClick={() => void submit()}
              >
                {busy ? <Spinner size="sm" aria-hidden /> : null}
                {busy ? 'Importing…' : 'Import guide'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
