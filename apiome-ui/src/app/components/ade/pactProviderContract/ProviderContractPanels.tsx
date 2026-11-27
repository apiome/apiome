'use client';

/**
 * The **Publish a provider contract** page's panels (PFX-8.6, #7303): the evidence option cards,
 * the aside (*If you publish now* and *Nobody uses*), the failed-run card and the result dialog.
 * Pure presentation — the page holds the state and `lib/pact-provider-contract.ts` decides every
 * sentence.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleAlert, CircleCheck, CircleX, Webhook } from 'lucide-react';
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
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  EVIDENCE_CHOICES,
  NOTIFICATIONS_LINE,
  asideHeadline,
  canIDeployHref,
  evidenceSentence,
  nobodyUsesSentence,
  publishedLines,
  verdictSentence,
  type CheckAnswer,
  type EvidenceKind,
  type EvidenceStrength,
  type PublishAnswer,
} from '@lib/pact-provider-contract';

/** The badge tone of each strength. */
const STRENGTH_TONE: Record<EvidenceStrength, 'ok' | 'warn' | 'neutral'> = { Strong: 'ok', Weak: 'warn', None: 'neutral' };

/** Props for {@link EvidenceOptions}. */
export interface EvidenceOptionsProps {
  value: EvidenceKind;
  onChange: (kind: EvidenceKind) => void;
  /** The inputs of the chosen option, shown under it. */
  children: React.ReactNode;
}

/**
 * The five evidence choices as option cards — a radio group, each labelled with its strength — and
 * the chosen one's inputs.
 *
 * @param props - See {@link EvidenceOptionsProps}.
 * @returns The group.
 */
export function EvidenceOptions({ value, onChange, children }: EvidenceOptionsProps) {
  return (
    <div className="ppc-evidence">
      <div className="ppc-options" role="radiogroup" aria-label="Evidence" data-testid="ppc-evidence">
        {EVIDENCE_CHOICES.map((choice) => {
          const id = `ppc-evidence-${choice.kind}`;
          return (
            <label key={choice.kind} htmlFor={id} className={value === choice.kind ? 'ppc-option is-active' : 'ppc-option'} data-testid={id}>
              <input
                id={id}
                type="radio"
                name="ppc-evidence"
                className="ppc-option__radio"
                checked={value === choice.kind}
                onChange={() => onChange(choice.kind)}
                aria-describedby={`${id}-desc`}
              />
              <span className="ppc-option__body">
                <span className="ppc-option__head">
                  <span className="ppc-option__title">{choice.title}</span>
                  <Badge variant={STRENGTH_TONE[choice.strength]}>{choice.strength}</Badge>
                </span>
                <span className="ppc-option__desc" id={`${id}-desc`}>
                  {choice.description}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      <div className="ppc-option-panel" data-testid="ppc-evidence-panel">
        {children}
      </div>
    </div>
  );
}

/** What the aside shows. */
export type AsideState =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'failed'; error: string }
  | { kind: 'ready'; answer: CheckAnswer };

/**
 * *If you publish now* and *Nobody uses*: the verdict per consumer before anything is saved.
 *
 * @param props - The check's state, the provider version, and a note that replaces the evidence line
 *   (**Run it now**: the evidence is read from the run when the contract is published).
 * @returns The cards.
 */
export function PublishNowAside({
  state,
  version,
  evidenceNote,
  idleNote,
}: {
  state: AsideState;
  version: string;
  evidenceNote?: string | null;
  /** What the idle aside says instead of the default (the Repository tab has no preview, PFX-8.7). */
  idleNote?: string | null;
}) {
  if (state.kind === 'idle') {
    return (
      <section className="ppub-card" data-testid="ppc-aside">
        <p className="ppub-caps">If you publish now</p>
        <p className="ppub-hint">
          {idleNote ?? 'Fill in the contract, the provider and its version: the verdict per consumer appears here before anything is saved.'}
        </p>
      </section>
    );
  }
  if (state.kind === 'checking') {
    return (
      <section className="ppub-card" data-testid="ppc-aside" aria-busy="true">
        <p className="ppub-caps">If you publish now</p>
        <p className="ppub-hint">Comparing with every consumer’s pact…</p>
      </section>
    );
  }
  if (state.kind === 'failed') {
    return (
      <section className="ppub-card" data-testid="ppc-aside">
        <p className="ppub-caps">If you publish now</p>
        <p className="ppub-hint ppub-hint--danger" data-testid="ppc-aside-error">
          {state.error}
        </p>
      </section>
    );
  }
  const { answer } = state;
  const headline = asideHeadline(answer);
  const nobody = nobodyUsesSentence(answer);
  const usedPercent = answer.coverage && answer.coverage.operations ? Math.round((answer.coverage.used / answer.coverage.operations) * 100) : 0;
  const blocks = answer.results.some((row) => row.success === false) || (!evidenceNote && !answer.evidence.verified);
  return (
    <>
      <section className="ppub-card" data-testid="ppc-aside">
        <div className="ppc-aside__head">
          <p className="ppub-caps">If you publish now</p>
          <span className="ppub-hint">live · nothing saved</span>
        </div>
        <div className="ppc-headline">
          {headline.ring ? (
            <span className={`ppc-ring ppc-ring--${headline.tone}`} data-percent={headline.percent} aria-hidden>
              {headline.ring}
            </span>
          ) : null}
          <div>
            <p className="ppc-headline__title" data-testid="ppc-headline">
              {headline.title}
            </p>
            <p className="ppub-hint">{headline.detail}</p>
          </div>
        </div>
        {answer.results.length ? (
          <ul className="ppub-ix__list" data-testid="ppc-consumers">
            {answer.results.map((row) => (
              <li key={`${row.consumer}-${row.sha}`} className="ppub-ix" data-testid="ppc-consumer">
                {row.success === null ? (
                  <CircleAlert aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" />
                ) : row.success ? (
                  <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
                ) : (
                  <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
                )}
                <div className="ppub-ix__main">
                  <span className="ppub-ix__name">
                    <b>{row.consumer}</b> <span className="ppx__mono ppub-hint">{row.sha.slice(0, 6)}</span>
                  </span>
                  <span className="ppub-ix__sub">{verdictSentence(row)}</span>
                </div>
                <Badge variant={row.success === null ? 'warn' : row.success ? (row.verdict === 'unverified' ? 'warn' : 'ok') : 'danger'}>
                  {row.success === null ? 'Not compared' : row.success ? (row.verdict === 'unverified' ? 'Unverified' : 'Fine') : 'Breaks'}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="ppub-hint" data-testid="ppc-aside-evidence">
          Evidence: {evidenceNote ?? evidenceSentence(answer.evidence)}
        </p>
        {blocks ? (
          <p className="ppc-callout" data-testid="ppc-aside-callout">
            <b>You can still publish.</b> Publishing records the truth;{' '}
            <Link href={canIDeployHref(answer.provider.name || '', version)}>can-i-deploy</Link> is what stops{' '}
            {version || 'this version'} reaching an environment while a consumer depends on what changed — and an unverified contract never
            unblocks a deploy.
          </p>
        ) : null}
      </section>
      {nobody ? (
        <section className="ppub-card" data-testid="ppc-nobody-uses">
          <p className="ppub-caps">Nobody uses</p>
          {answer.coverage && answer.coverage.operations ? (
            <progress
              className="ppc-bar"
              max={100}
              value={usedPercent}
              aria-label={`${answer.coverage.used} of ${answer.coverage.operations} operations are used by a consumer`}
            />
          ) : null}
          <p className="ppub-hint">{nobody}</p>
        </section>
      ) : null}
    </>
  );
}

/** A **Run it now** that did not pass: nothing was published, and why. */
export function FailedRunCard({ answer }: { answer: Extract<PublishAnswer, { published: false }> }) {
  return (
    <section className="ppub-card ppc-failed" aria-labelledby="ppc-failed-title" data-testid="ppc-failed-run">
      <h2 className="ppub-card__title" id="ppc-failed-title">
        <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
        Nothing was published
      </h2>
      <p className="ppub-card__lead">{answer.message}</p>
      {answer.failing.length ? (
        <ul className="ppub-ix__list" data-testid="ppc-failing-operations">
          {answer.failing.map((op, index) => (
            <li key={`${op.operation}-${index}`} className="ppub-ix">
              <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
              <div className="ppub-ix__main">
                <span className="ppub-ix__name ppx__mono">{op.operation}</span>
                <span className="ppub-ix__sub">{op.detail ?? op.outcome}</span>
              </div>
              <Badge variant="danger">{op.outcome}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {answer.reportId ? (
        <p className="ppub-hint" data-testid="ppc-failed-report">
          The run is recorded as provider-verification report <span className="ppx__mono">{answer.reportId}</span>
          {answer.runId ? (
            <>
              {' '}
              (evidence run <span className="ppx__mono">{answer.runId}</span>)
            </>
          ) : null}
          . Fix the provider and run again — or reuse a later passing run.
        </p>
      ) : null}
    </section>
  );
}

/**
 * The result dialog: what was recorded, the evidence, notifications and the can-i-deploy link.
 *
 * @param props - The published answer (or `null` when closed), and the two actions.
 * @returns The dialog.
 */
export function ContractResultDialog({
  answer,
  onClose,
  onAgain,
  followLine,
}: {
  answer: Extract<PublishAnswer, { published: true }> | null;
  onClose: () => void;
  onAgain: () => void;
  /** **Do this on every publish** (PFX-8.7): whether the project is now followed, or why not. */
  followLine?: { tone: 'ok' | 'warn'; text: string } | null;
}) {
  return (
    <Dialog open={answer !== null} onOpenChange={(open) => !open && onClose()}>
      {answer ? (
        <DialogContent data-testid="ppc-result">
          <DialogHeader>
            <DialogTitle>{answer.created ? 'Provider contract published' : 'Already published — nothing changed'}</DialogTitle>
            <DialogDescription>
              {answer.provider} {answer.providerVersion} · evidence: {evidenceSentence(answer.evidence)}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <ul className="ppub-result__list" data-testid="ppc-result-lines">
              {publishedLines(answer).map((line) => (
                <li key={line.text} className={`ppc-result__line ppc-result__line--${line.tone}`}>
                  {line.tone === 'ok' ? (
                    <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
                  ) : line.tone === 'danger' ? (
                    <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
                  ) : (
                    <CircleAlert aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" />
                  )}
                  <span>{line.text}</span>
                </li>
              ))}
              <li className="ppc-result__line ppc-result__line--neutral" data-testid="ppc-result-notifications">
                <Webhook aria-hidden className="ppub-ix__glyph" />
                <span>{NOTIFICATIONS_LINE}</span>
              </li>
              {followLine ? (
                <li className={`ppc-result__line ppc-result__line--${followLine.tone}`} data-testid="ppc-result-follow">
                  {followLine.tone === 'ok' ? (
                    <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
                  ) : (
                    <CircleAlert aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" />
                  )}
                  <span>{followLine.text}</span>
                </li>
              ) : null}
            </ul>
            {!answer.evidence.verified ? (
              <p className="ppc-callout" data-testid="ppc-result-unverified">
                <b>Unverified.</b> Its verdicts read “unverified” and never unblock a deploy. Publish evidence for {answer.providerVersion} to
                change that.
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" asChild>
              <Link href={CONTRACTS_ROUTE}>Back to Contracts</Link>
            </Button>
            <Button variant="outline" onClick={onAgain}>
              Publish another
            </Button>
            <Button asChild>
              <Link href={canIDeployHref(answer.provider, answer.providerVersion)}>Can I deploy {answer.providerVersion}?</Link>
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
