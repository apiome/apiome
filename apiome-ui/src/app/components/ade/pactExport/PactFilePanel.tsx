'use client';

/**
 * **A pact file** — the Export page's third kind (PFX-8.18, #7315).
 *
 * Download any published pact exactly as stored (the broker's links taken off), chosen by consumer,
 * provider and which pact — or **Every pact for this provider** as a zip, with a README naming every
 * consumer left out and why. A pair without such a pact shows the mockup's **No pact for the pair**
 * state. No `apiome pact` command downloads a pact, so the block shows the REST request only.
 */

import * as React from 'react';
import { Archive, Download } from 'lucide-react';
import { Button, CommandBlock, Input, Label } from '@/app/components/ui';
import { pactCommandSurfaces } from '@lib/pact-commands';
import {
  noPactMessage,
  PACT_CHOICE_LABELS,
  PACT_CHOICES,
  pactFileAction,
  PROVIDER_PACT_CHOICES,
  validatePactFile,
  validateProviderPacts,
  type PactChoice,
  type PactFileDraft,
} from '@lib/pact-export';
import { fetchPactFile, fetchProviderPacts, isFailure, saveFile } from './exportApi';
import { PacticipantField } from './PacticipantField';

/** Props of {@link PactFilePanel}. */
export interface PactFilePanelProps {
  draft: PactFileDraft;
  onDraft: (draft: PactFileDraft) => void;
  pacticipants: string[];
  onStatus: (status: { tone: 'warn' | 'danger'; text: string } | null) => void;
}

export function PactFilePanel({ draft, onDraft, pacticipants, onStatus }: PactFilePanelProps) {
  const [busy, setBusy] = React.useState<'one' | 'every' | null>(null);
  const [saved, setSaved] = React.useState<string | null>(null);
  const field = PACT_CHOICE_LABELS[draft.choice].field;
  const edit = (patch: Partial<PactFileDraft>) => {
    onDraft({ ...draft, ...patch });
    setSaved(null);
  };

  const downloadOne = async () => {
    const problem = validatePactFile(draft);
    if (problem) return onStatus({ tone: 'danger', text: problem });
    onStatus(null);
    setBusy('one');
    const answer = await fetchPactFile(draft);
    setBusy(null);
    if (isFailure(answer)) {
      return onStatus({ tone: 'danger', text: answer.status === 404 ? `${noPactMessage(draft.consumer, draft.provider)} (${answer.error})` : answer.error });
    }
    saveFile(answer.fileName, `${JSON.stringify(answer.pact, null, 2)}\n`);
    setSaved(answer.fileName);
  };

  const downloadEvery = async () => {
    const problem = validateProviderPacts(draft);
    if (problem) return onStatus({ tone: 'danger', text: problem });
    onStatus(null);
    setBusy('every');
    const answer = await fetchProviderPacts(draft);
    setBusy(null);
    if (isFailure(answer)) return onStatus({ tone: 'danger', text: answer.error });
    saveFile(answer.fileName, answer.blob);
    setSaved(answer.fileName);
  };

  return (
    <div className="ppub__split" data-testid="pexp-file">
      <section className="ppub-card" aria-labelledby="pexp-file-title">
        <h2 className="ppub-card__title" id="pexp-file-title">
          Download a published pact
        </h2>
        <div className="ppub-grid">
          <PacticipantField id="pexp-file-consumer" label="Consumer" value={draft.consumer} options={pacticipants} onChange={(consumer) => edit({ consumer })} />
          <PacticipantField id="pexp-file-provider" label="Provider" value={draft.provider} options={pacticipants} onChange={(provider) => edit({ provider })} />
          <div className="ppub-field">
            <Label htmlFor="pexp-file-choice">Which pact</Label>
            <select id="pexp-file-choice" className="ppub-select" value={draft.choice} onChange={(event) => edit({ choice: event.target.value as PactChoice, choiceValue: '' })}>
              {PACT_CHOICES.map((choice) => (
                <option key={choice} value={choice}>
                  {PACT_CHOICE_LABELS[choice].label}
                </option>
              ))}
            </select>
          </div>
          {field ? (
            <div className="ppub-field">
              <Label htmlFor="pexp-file-value">{field}</Label>
              <Input id="pexp-file-value" value={draft.choiceValue} onChange={(event) => edit({ choiceValue: event.target.value })} />
            </div>
          ) : null}
        </div>
        <div className="ppub-row-actions">
          <Button onClick={() => void downloadOne()} disabled={busy !== null} title={busy ? 'A download is in progress' : undefined} data-testid="pexp-file-download">
            <Download aria-hidden />
            {busy === 'one' ? 'Downloading…' : 'Download pact.json'}
          </Button>
          <Button
            variant="outline"
            onClick={() => void downloadEvery()}
            disabled={busy !== null || !PROVIDER_PACT_CHOICES.includes(draft.choice)}
            title={PROVIDER_PACT_CHOICES.includes(draft.choice) ? 'Each consumer’s pact, and a README of any left out' : 'A version or a SHA names one consumer’s pact'}
            data-testid="pexp-file-every"
          >
            <Archive aria-hidden />
            {busy === 'every' ? 'Collecting…' : 'Every pact for this provider (.zip)'}
          </Button>
        </div>
        {saved ? (
          <p className="ppub-hint" role="status" data-testid="pexp-file-saved">
            Saved {saved}.
          </p>
        ) : null}
      </section>
      <aside className="ppub__aside">
        <CommandBlock surfaces={pactCommandSurfaces(pactFileAction(draft, ''))} footnote="Replace {tenant} with your workspace’s handle in the path." data-testid="pexp-file-command" />
      </aside>
    </div>
  );
}
