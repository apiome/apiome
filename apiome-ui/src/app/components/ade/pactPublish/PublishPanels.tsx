'use client';

/**
 * The Publish page's panels (PFX-8.3, #7300): the file table, the result dialog and the read-only
 * note. Pure presentation — the page holds the state and the model (`lib/pact-publish-page.ts`)
 * decides every sentence.
 */

import * as React from 'react';
import Link from 'next/link';
import { Download, FileJson, X } from 'lucide-react';
import { Badge, Button } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { CAN_I_DEPLOY_ROUTE } from '@lib/pact-matrix';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { WEBHOOKS_ROUTE } from '@lib/pact-webhooks';
import {
  checkSentence,
  conflictMessage,
  publishedSentence,
  specLabel,
  type CheckVerdict,
  type DeriveOutcome,
  type PactFileRow,
  type PublishOutcome,
} from '@lib/pact-publish-page';

/** The badge tone and label of a check verdict. */
const VERDICT_BADGE: Record<CheckVerdict['kind'], { tone: 'ok' | 'accent' | 'danger' | 'warn'; label: string }> = {
  new: { tone: 'accent', label: 'New' },
  unchanged: { tone: 'ok', label: 'Unchanged' },
  conflict: { tone: 'danger', label: 'Conflict' },
  error: { tone: 'warn', label: 'Not checked' },
};

/** Props for {@link FileTable}. */
export interface FileTableProps {
  rows: PactFileRow[];
  /** The check verdict of each row, by id (after **Check only**). */
  verdicts: Record<string, CheckVerdict>;
  /** The version the verdicts were read for. */
  checkedVersion: string;
  /** Remove a row; without it the rows have no remove button (the written pact, PFX-8.5). */
  onRemove?: (id: string) => void;
}

/**
 * One row per file: its pair, specification, interaction count, and why it will not be published
 * or what a check found.
 *
 * @param props - See {@link FileTableProps}.
 * @returns The table.
 */
export function FileTable({ rows, verdicts, checkedVersion, onRemove }: FileTableProps) {
  return (
    <div className="ppub-table-wrap">
      <table className="ppub-table" data-testid="ppub-files">
        <thead>
          <tr>
            <th scope="col">File</th>
            <th scope="col">Consumer → provider</th>
            <th scope="col">Spec</th>
            <th scope="col" className="ppub-table__num">
              Interactions
            </th>
            <th scope="col">
              <span className="sr-only">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const verdict = verdicts[row.id];
            return (
              <tr key={row.id} className={row.problem ? 'ppub-row ppub-row--invalid' : 'ppub-row'} data-testid={`ppub-file-${row.id}`}>
                <td className="ppub-table__file">
                  <div className="ppub-table__name">
                    <FileJson aria-hidden className="ppub-table__glyph" />
                    <span className="ppx__mono">{row.fileName}</span>
                  </div>
                  {row.problem ? (
                    <div className="ppub-row__problem" data-testid="ppub-row-problem">
                      {row.problem}
                    </div>
                  ) : verdict ? (
                    <div className={`ppub-row__verdict ppub-row__verdict--${verdict.kind}`} data-testid="ppub-row-verdict">
                      <Badge variant={VERDICT_BADGE[verdict.kind].tone}>{VERDICT_BADGE[verdict.kind].label}</Badge>
                      <span>{checkSentence(verdict, checkedVersion)}</span>
                    </div>
                  ) : null}
                </td>
                <td>{row.consumer && row.provider ? `${row.consumer} → ${row.provider}` : '—'}</td>
                <td>
                  <div className="ppub-chips">
                    <Badge variant="neutral">{specLabel(row.specVersion)}</Badge>
                    {row.kinds.map((kind) => (
                      <Badge key={kind} variant="neutral">
                        {kind}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="ppub-table__num">{row.problem ? '—' : row.interactions}</td>
                <td className="ppub-table__remove">
                  {onRemove ? (
                    <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${row.fileName}`} onClick={() => onRemove(row.id)}>
                      <X aria-hidden />
                    </Button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** One batch that REST refused. */
export interface PublishFailure {
  consumer: string;
  error: string;
  status: number;
}

/** What the result dialog shows. */
export interface PublishResult {
  version: string;
  branch: string;
  outcomes: PublishOutcome[];
  failures: PublishFailure[];
  /** Rows that were not sent, with their reason. */
  skipped: PactFileRow[];
  /** A derived publish's findings and pact, when the Derive tab published. */
  derived: DeriveOutcome | null;
}

/**
 * Save a JSON document as a file.
 *
 * @param document - The document.
 * @param fileName - The file's name.
 */
function download(document: Record<string, unknown>, fileName: string) {
  const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = window.document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * The result: which pacts are new and pending, which were unchanged, what was refused or not sent,
 * whether comparisons ran and webhooks were notified — and where to go next.
 *
 * @param props - The result (`null` closes the dialog), what closing does, and what starting over does.
 * @returns The dialog.
 */
export function ResultDialog({
  result,
  onClose,
  onAgain,
}: {
  result: PublishResult | null;
  onClose: () => void;
  /** **Publish another**: close and start over. */
  onAgain: () => void;
}) {
  const published = result ? result.outcomes.flatMap((outcome) => outcome.pacts) : [];
  const changed = published.filter((pact) => pact.state !== 'unchanged').length;
  const compared = result ? result.outcomes.reduce((sum, outcome) => sum + outcome.compared, 0) : 0;
  const notices = result ? result.outcomes.flatMap((outcome) => outcome.notices) : [];
  const consumers = result ? [...new Set(result.outcomes.map((outcome) => outcome.consumer))] : [];
  const title = !result
    ? ''
    : published.length === 0
      ? 'Nothing was published'
      : `${published.length} ${published.length === 1 ? 'pact' : 'pacts'} published`;
  return (
    <Dialog open={result !== null} onOpenChange={(open) => !open && onClose()}>
      {result ? (
        <DialogContent data-testid="ppub-result">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {consumers.length ? `${consumers.join(', ')} ` : ''}
              {result.version}
              {result.branch ? ` on ${result.branch}` : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {published.length ? (
              <ul className="ppub-result__list" data-testid="ppub-result-pacts">
                {published.map((pact, index) => (
                  <li key={`${pact.provider}-${index}`} className={`ppub-result__item ppub-result__item--${pact.state}`}>
                    <b>{pact.provider}</b> — {publishedSentence(pact)}
                  </li>
                ))}
              </ul>
            ) : null}
            {result.failures.length ? (
              <ul className="ppub-result__list" data-testid="ppub-result-failures">
                {result.failures.map((failure) => (
                  <li key={failure.consumer} className="ppub-result__item ppub-result__item--refused">
                    <b>{failure.consumer}</b> — not published:{' '}
                    {failure.status === 409 ? `${conflictMessage(result.version)} (${failure.error})` : failure.error}
                  </li>
                ))}
              </ul>
            ) : null}
            {result.skipped.length ? (
              <ul className="ppub-result__list" data-testid="ppub-result-skipped">
                {result.skipped.map((row) => (
                  <li key={row.id} className="ppub-result__item ppub-result__item--refused">
                    <b className="ppx__mono">{row.fileName}</b> — not sent: {row.problem}
                  </li>
                ))}
              </ul>
            ) : null}
            {result.derived ? (
              <div className="ppub-result__derived" data-testid="ppub-result-derived">
                <p>
                  Generated from contract revision {result.derived.revision ?? '—'}:{' '}
                  {result.derived.findings.length
                    ? `${result.derived.findings.length} ${result.derived.findings.length === 1 ? 'finding' : 'findings'} — values invented or left out.`
                    : 'no findings.'}
                </p>
                {result.derived.findings.length ? (
                  <ul className="ppub-result__list">
                    {result.derived.findings.map((finding, index) => (
                      <li key={index} className="ppub-result__item">
                        {finding.method && finding.path ? <span className="ppx__mono">{`${finding.method} ${finding.path} `}</span> : null}
                        {finding.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {result.derived.pact ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => download(result.derived!.pact!, 'pact.json')}>
                    <Download aria-hidden />
                    Download the published pact
                  </Button>
                ) : null}
              </div>
            ) : null}
            <p className="ppub-result__line" data-testid="ppub-result-follow-up">
              {changed > 0 ? (
                <>
                  {changed === 1 ? 'The new pact notified' : `The ${changed} new or changed pacts notified`} the contract webhooks that listen for
                  them — see <Link href={WEBHOOKS_ROUTE}>Webhooks</Link> for the deliveries.
                </>
              ) : published.length ? (
                'No content changed, so no webhook fired.'
              ) : null}
              {compared > 0 ? ` ${compared} bi-directional ${compared === 1 ? 'comparison' : 'comparisons'} ran against the provider’s contract.` : ''}
            </p>
            {notices.length ? (
              <details className="ppub-result__notices">
                <summary>What the broker said</summary>
                <ul className="ppub-result__list">
                  {notices.map((line, index) => (
                    <li key={index} className="ppub-result__item ppx__mono">
                      {line}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" asChild>
              <Link href={CONTRACTS_ROUTE}>Back to Contracts</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href={CAN_I_DEPLOY_ROUTE}>Can I deploy?</Link>
            </Button>
            <Button onClick={onAgain}>Publish another</Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

/**
 * What a role without `pacts:create` sees instead of the form.
 *
 * @param props - Whether the role could not be read at all.
 * @returns The note.
 */
export function ReadOnlyNote({ unknown }: { unknown: boolean }) {
  return (
    <section className="ppub-card ppub-readonly" aria-labelledby="ppub-readonly-title" data-testid="ppub-readonly">
      <h2 className="ppub-card__title" id="ppub-readonly-title">
        {unknown ? 'Your permissions could not be read' : 'Your role cannot publish pacts'}
      </h2>
      <p className="ppub-card__lead">
        Publishing needs the <b>Pacts</b> create permission, which the <b>Editor</b>, <b>Admin</b> and <b>Owner</b> roles hold. Ask a workspace owner
        for it, or publish from your build with the command below — a build’s API key carries its own permissions.
      </p>
    </section>
  );
}
