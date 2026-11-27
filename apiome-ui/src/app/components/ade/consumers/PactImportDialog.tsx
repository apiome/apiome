'use client';

import * as React from 'react';
import Link from 'next/link';
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
import { Checkbox } from '@/app/components/ui/Checkbox';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';

import {
  pactConsumerName,
  parseTags,
  validatePublishDraft,
  type PublishDraft,
} from '@lib/pact-publish';
import { PUBLISH_HANDOFF_KEY, publishRoute } from '@lib/pact-publish-page';
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
  /**
   * What publishing to the Pact Broker did (PFX-5.8): its notices, or the reason it failed. Absent
   * when the broker was not asked. A failed publish never undoes the registry import.
   */
  broker?: { notices: string[] } | { error: string };
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
  /** The provider the broker section starts with (this project's handle). */
  defaultProvider?: string | null;
  /**
   * Import the document.
   *
   * @param pact The Pact document as text.
   * @param consumerSlug The handle to file it under, or an empty string to use the document's
   *   own consumer name.
   * @param publish When set, also publish the pact to the Pact Broker with these details.
   * @param consumerName The consumer the pact is for (resolved by the dialog), for the broker.
   * @returns The outcome, or an error message.
   */
  onImport: (
    pact: string,
    consumerSlug: string,
    publish?: { consumerName: string; draft: PublishDraft },
  ) => Promise<{ outcome: PactImportOutcome } | { error: string }>;
}

/** The broker section before anything is typed. */
const EMPTY_DRAFT: PublishDraft = { providerName: '', version: '', branch: '', tags: '', buildUrl: '' };

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
  defaultProvider,
  onImport,
}: PactImportDialogProps) {
  const [pact, setPact] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [publish, setPublish] = React.useState(false);
  const [draft, setDraft] = React.useState<PublishDraft>(EMPTY_DRAFT);
  const [outcome, setOutcome] = React.useState<PactImportOutcome | null>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setPact('');
    setSlug(consumerSlug ?? '');
    setError('');
    setBusy(false);
    setOutcome(null);
    setPublish(false);
    setDraft({ ...EMPTY_DRAFT, providerName: defaultProvider ?? '' });
  }, [open, consumerSlug, defaultProvider]);

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
    // The consumer the broker files the pact under: the dialog's, else the handle, else the document's.
    const brokerConsumer = consumerName || slug.trim() || consumerSlug || pactConsumerName(pact);
    if (publish) {
      const problem = validatePublishDraft(draft, brokerConsumer);
      if (problem) {
        setError(problem);
        return;
      }
    }
    setBusy(true);
    setError('');
    setOutcome(null);
    const result = await onImport(
      pact,
      slug.trim(),
      publish ? { consumerName: brokerConsumer, draft } : undefined,
    );
    setBusy(false);
    if ('error' in result) {
      setError(result.error);
      return;
    }
    setOutcome(result.outcome);
  };

  const groups = outcome ? groupUnresolved(outcome.unresolved) : [];

  /**
   * The shortcut to the Publish page (PFX-8.3): the fields travel in the address, the pact itself
   * through sessionStorage (it can be megabytes). A refused storage only means the page opens
   * without it.
   */
  const handOff = () => {
    try {
      if (pact.trim()) window.sessionStorage.setItem(PUBLISH_HANDOFF_KEY, JSON.stringify({ pact }));
    } catch {
      // The page opens with the fields only.
    }
  };

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

          <div className="cns-form__field cns-publish">
            <div className="cns-form__row">
              <Checkbox
                id="pact-publish"
                checked={publish}
                onCheckedChange={(value) => setPublish(value === true)}
              />
              <Label htmlFor="pact-publish">Also publish to the Pact Broker</Label>
            </div>
            <p className="cns-form__hint">
              Files the pact under a consumer version so the provider can verify it and can-i-deploy
              can see it. Without this the pact is stored as a consumer contract only. Several
              files, a check before publishing, or tag-with-branch:{' '}
              <Link
                href={publishRoute({
                  source: 'paste',
                  version: draft.version,
                  branch: draft.branch,
                  buildUrl: draft.buildUrl,
                  tags: parseTags(draft.tags),
                })}
                onClick={handOff}
                data-testid="pact-publish-page-link"
              >
                open the Publish page
              </Link>
              .
            </p>
            {publish && (
              <div className="cns-publish__fields" data-testid="pact-publish-fields">
                <div className="cns-form__field">
                  <Label htmlFor="pact-publish-provider">Provider</Label>
                  <Input
                    id="pact-publish-provider"
                    className="mono"
                    value={draft.providerName}
                    maxLength={255}
                    placeholder="orders-api"
                    onChange={(event) => setDraft({ ...draft, providerName: event.target.value })}
                  />
                </div>
                <div className="cns-form__field">
                  <Label htmlFor="pact-publish-version">Consumer version</Label>
                  <Input
                    id="pact-publish-version"
                    className="mono"
                    value={draft.version}
                    maxLength={255}
                    placeholder="9f3c2a1"
                    onChange={(event) => setDraft({ ...draft, version: event.target.value })}
                  />
                </div>
                <div className="cns-form__field">
                  <Label htmlFor="pact-publish-branch">Branch (optional)</Label>
                  <Input
                    id="pact-publish-branch"
                    className="mono"
                    value={draft.branch}
                    maxLength={255}
                    placeholder="main"
                    onChange={(event) => setDraft({ ...draft, branch: event.target.value })}
                  />
                </div>
                <div className="cns-form__field">
                  <Label htmlFor="pact-publish-tags">Tags (optional)</Label>
                  <Input
                    id="pact-publish-tags"
                    className="mono"
                    value={draft.tags}
                    placeholder="prod, release-2"
                    onChange={(event) => setDraft({ ...draft, tags: event.target.value })}
                  />
                </div>
                <div className="cns-form__field">
                  <Label htmlFor="pact-publish-build">Build URL (optional)</Label>
                  <Input
                    id="pact-publish-build"
                    className="mono"
                    value={draft.buildUrl}
                    maxLength={2048}
                    placeholder="https://ci.example.com/builds/42"
                    onChange={(event) => setDraft({ ...draft, buildUrl: event.target.value })}
                  />
                </div>
              </div>
            )}
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

              {outcome.broker && (
                <div data-testid="pact-publish-outcome">
                  {'error' in outcome.broker ? (
                    <Alert variant="danger">
                      Stored in the registry, but not published to the Pact Broker:{' '}
                      {outcome.broker.error}
                    </Alert>
                  ) : (
                    <Alert variant="ok">
                      Published to the Pact Broker.
                      {outcome.broker.notices.length > 0 && (
                        <ul className="cns-outcome__list">
                          {outcome.broker.notices.map((line, index) => (
                            <li className="cns-outcome__item" key={index}>
                              {line}
                            </li>
                          ))}
                        </ul>
                      )}
                    </Alert>
                  )}
                </div>
              )}

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
