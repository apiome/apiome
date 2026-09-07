'use client';

import * as React from 'react';
import { Upload } from 'lucide-react';

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
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';

import { groupUnresolved, type UnresolvedInteraction } from './consumersModel';

/**
 * Import a Pact file — CTG-4.1 (#4479).
 *
 * The first of the two ingestion paths. A Pact file is what a consumer-driven contract test
 * already produces, so importing one asks nothing new of the consumer's team.
 *
 * ### The dialog stays open on success
 *
 * Every other write dialog on this screen closes when it succeeds. This one does not, because
 * its result is not "saved" — it is *what resolved and what did not*. An import that placed
 * eleven interactions and could not place three has told you something about the API, and
 * closing over that report would make the failure look like success. The dialog shows the
 * unresolved list grouped by reason, and closes when the reader is done with it.
 *
 * ### The file never leaves the browser as a file
 *
 * A picked file is read to text and posted as JSON, so the proxy stays one shape and no
 * multipart path has to be maintained for a document that is JSON anyway.
 */

/** What an import produced, as the caller reports it back. */
export interface PactImportOutcome {
  /** How many operations the stored revision declares. */
  operationCount: number;
  /** How many fields it declares. */
  fieldCount: number;
  /** The revision number written. */
  revision: number;
  /** Everything that could not be placed. */
  unresolved: UnresolvedInteraction[];
}

/** Props for {@link PactImportDialog}. */
export interface PactImportDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The consumer's display name, when importing for an existing one. */
  consumerName?: string | null;
  /** The consumer's handle, when importing for an existing one. */
  consumerSlug?: string | null;
  /**
   * Import the document.
   *
   * @param pact The Pact document as text.
   * @param consumerSlug The handle to file it under, or an empty string to use the document's
   *   own consumer name.
   * @returns The outcome, or an error message.
   */
  onImport: (
    pact: string,
    consumerSlug: string,
  ) => Promise<{ outcome: PactImportOutcome } | { error: string }>;
}

/**
 * The Pact import dialog.
 *
 * @param props See {@link PactImportDialogProps}.
 * @returns The dialog.
 */
export default function PactImportDialog({
  open,
  onOpenChange,
  consumerName,
  consumerSlug,
  onImport,
}: PactImportDialogProps) {
  const [pact, setPact] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [outcome, setOutcome] = React.useState<PactImportOutcome | null>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setPact('');
    setSlug(consumerSlug ?? '');
    setError('');
    setBusy(false);
    setOutcome(null);
  }, [open, consumerSlug]);

  const readFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setError('');
    setPact(await file.text());
    // Clear the input so picking the same file twice still fires a change event.
    event.target.value = '';
  };

  const handleImport = async () => {
    if (!pact.trim() || busy) return;
    setBusy(true);
    setError('');
    setOutcome(null);
    const result = await onImport(pact, slug.trim());
    setBusy(false);
    if ('error' in result) {
      setError(result.error);
      return;
    }
    setOutcome(result.outcome);
  };

  const groups = outcome ? groupUnresolved(outcome.unresolved) : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="cns-dialog cns-dialog--wide">
        <DialogHeader>
          <DialogTitle>Import a Pact file</DialogTitle>
          <DialogDescription>
            {consumerName
              ? `Resolve ${consumerName}'s Pact interactions against this project's latest version.`
              : "Resolve a Pact file's interactions against this project's latest version. The consumer is registered if it does not exist yet."}
          </DialogDescription>
        </DialogHeader>

        <div className="cns-form">
          {!consumerSlug && (
            <div className="cns-form__field">
              <Label htmlFor="pact-consumer-slug">Consumer handle</Label>
              <Input
                id="pact-consumer-slug"
                className="mono"
                value={slug}
                maxLength={128}
                placeholder="billing-service"
                onChange={(event) => setSlug(event.target.value)}
              />
              <p className="cns-form__hint">
                Leave empty to use the name the Pact document declares.
              </p>
            </div>
          )}

          <div className="cns-form__field">
            <div className="cns-form__row">
              <Label htmlFor="pact-document">Pact document</Label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => fileInput.current?.click()}
              >
                <Upload aria-hidden="true" />
                Choose a file
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept="application/json,.json"
                className="cns-file"
                onChange={readFile}
                data-testid="pact-file-input"
              />
            </div>
            <Textarea
              id="pact-document"
              className="mono cns-pact"
              value={pact}
              rows={10}
              spellCheck={false}
              placeholder='{"consumer": {"name": "billing-service"}, "interactions": [ … ]}'
              onChange={(event) => setPact(event.target.value)}
            />
            <p className="cns-form__hint">
              Pact specification 1.x–4.x. Matching rules and provider states are not read — they
              say how a value is compared, not which fields are used.
            </p>
          </div>

          {error && <Alert variant="danger">{error}</Alert>}

          {outcome && (
            <div className="cns-outcome" data-testid="pact-import-outcome">
              <Alert variant={outcome.unresolved.length > 0 ? 'warn' : 'ok'}>
                Revision {outcome.revision} stored: {outcome.operationCount} operations,{' '}
                {outcome.fieldCount} fields
                {outcome.unresolved.length > 0
                  ? `, ${outcome.unresolved.length} interactions unresolved.`
                  : '.'}
              </Alert>

              {groups.map((group) => (
                <section className="cns-outcome__group" key={group.reason}>
                  <h3 className="cns-outcome__heading">
                    {group.label}
                    <span className="cns-outcome__count">{group.entries.length}</span>
                  </h3>
                  <ul className="cns-outcome__list">
                    {group.entries.slice(0, 12).map((entry, index) => (
                      <li className="cns-outcome__item" key={`${group.reason}-${index}`}>
                        <code className="mono">{entry.message}</code>
                        {entry.description && (
                          <span className="cns-outcome__where">{entry.description}</span>
                        )}
                      </li>
                    ))}
                    {group.entries.length > 12 && (
                      <li className="cns-outcome__item cns-outcome__item--more">
                        +{group.entries.length - 12} more
                      </li>
                    )}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {outcome ? 'Done' : 'Cancel'}
          </Button>
          <Button type="button" onClick={handleImport} disabled={!pact.trim() || busy}>
            {busy && <Spinner className="size-4" />}
            {outcome ? 'Import again' : 'Import'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
