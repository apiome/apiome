/**
 * The **comparison fidelity report** of one bi-directional result — PFX-2.5 (#6929).
 *
 * What the comparison of a consumer's pact with the provider's OpenAPI document actually compared,
 * and what it could not, so a green verdict is never read as stronger than it is (the same honesty
 * rule as CTG-4.3 coverage):
 *
 * * the verdict beside its **strength** — only *Compared in full* is green;
 * * one sentence to read the verdict by, and the counts behind it;
 * * per interaction: every check with its status as an icon **and** a word (a check that did not
 *   run says why), the matching rules the comparison could not prove, and the items it could not
 *   compare, each with its JSON Pointer into the pact.
 *
 * Presentational: the data comes from `fetchComparisonFidelity`.
 */

import * as React from 'react';
import { CircleCheck, CircleDashed, CircleMinus, CircleX } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import {
  CHECK_STATUS_LABELS,
  STRENGTH_TONES,
  VERDICT_TONES,
  interactionName,
  operationLine,
  verdictLabel,
  type ComparisonFidelityReport as Report,
  type FidelityCheckStatus,
  type FidelityInteraction,
  type FidelityNote,
} from '@lib/pact-comparisons';

/** Props for {@link ComparisonFidelityReport}. */
export interface ComparisonFidelityReportProps {
  /** The report, as `GET …/pact-comparisons/{id}/fidelity` returns it. */
  report: Report;
}

/** The icon each check status leads with. */
const CHECK_ICONS: Readonly<Record<FidelityCheckStatus, typeof CircleCheck>> = {
  compared: CircleCheck,
  partial: CircleDashed,
  failed: CircleX,
  'not-run': CircleMinus,
};

/** The counters under the statement, in reading order. */
const COUNTERS: ReadonlyArray<{ key: keyof Report['summary']; label: string }> = [
  { key: 'interactions', label: 'Interactions' },
  { key: 'fullyCompared', label: 'Compared in full' },
  { key: 'failed', label: 'Failed' },
  { key: 'unsupportedMatchingRules', label: 'Unsupported rules' },
  { key: 'couldNotCompare', label: 'Not compared' },
  { key: 'checksNotRun', label: 'Checks not run' },
];

/**
 * A list of fidelity notes under a heading, or nothing when it is empty.
 *
 * @param props - The heading, its id, and the notes.
 * @returns The section, or `null`.
 */
function NoteList({ id, title, notes }: { id: string; title: string; notes: FidelityNote[] }) {
  if (notes.length === 0) return null;
  return (
    <section className="pcf__notes" aria-labelledby={id}>
      <h4 id={id} className="pcf__notes-title">
        {title} <span className="pcf__count">({notes.length})</span>
      </h4>
      <ul className="pcf__note-list">
        {notes.map((note) => (
          <li key={`${note.code}:${note.pactPointer}:${note.message}`} className="pcf__note" data-code={note.code}>
            <span className="pcf__note-message">{note.message}</span>
            <span className="pcf__note-meta">
              <code className="pcf__code">{note.code}</code>
              {note.matcher ? <span>matcher {note.matcher}</span> : null}
              <code className="pcf__pointer">{note.pactPointer}</code>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * One interaction's checks and notes.
 *
 * @param props - The interaction and the report's id prefix.
 * @returns The section.
 */
function InteractionReport({ interaction, prefix }: { interaction: FidelityInteraction; prefix: string }) {
  const id = `${prefix}-i${interaction.index}`;
  const operation = operationLine(interaction);
  return (
    <section className="pcf__interaction" aria-labelledby={id} data-testid={`pcf-interaction-${interaction.index}`}>
      <div className="pcf__interaction-head">
        <h3 id={id} className="pcf__interaction-title">
          {interactionName(interaction)}
        </h3>
        <Badge variant={VERDICT_TONES[interaction.verdict] ?? 'neutral'}>
          {interaction.verdict === 'pass' ? 'Pass' : interaction.verdict === 'partial' ? 'Partial' : 'Fail'}
        </Badge>
        {operation ? <code className="pcf__operation">{operation}</code> : null}
      </div>
      <ul className="pcf__checks" aria-label={`Checks of ${interactionName(interaction)}`}>
        {interaction.checks.map((check) => {
          const Icon = CHECK_ICONS[check.status] ?? CircleMinus;
          return (
            <li key={check.check} className="pcf__check" data-status={check.status} data-testid={`pcf-check-${interaction.index}-${check.check}`}>
              <Icon className="pcf__icon" aria-hidden />
              <span className="pcf__check-label">{check.label}</span>
              <span className="pcf__check-status">{CHECK_STATUS_LABELS[check.status] ?? check.status}</span>
              {check.reason ? <span className="pcf__check-reason">{check.reason}</span> : null}
            </li>
          );
        })}
      </ul>
      <NoteList id={`${id}-rules`} title="Unsupported matching rules" notes={interaction.unsupportedMatchingRules} />
      <NoteList id={`${id}-gaps`} title="Could not compare" notes={interaction.couldNotCompare} />
    </section>
  );
}

/**
 * The fidelity report.
 *
 * @param props - See {@link ComparisonFidelityReportProps}.
 * @returns The section.
 */
export function ComparisonFidelityReport({ report }: ComparisonFidelityReportProps) {
  const prefix = `pcf-${report.result.id}`;
  const { consumer, provider } = report.result;
  return (
    <section className="pcf" aria-labelledby={`${prefix}-title`} data-testid="pact-comparison-fidelity" data-strength={report.strength}>
      <div className="pcf__head">
        <h2 id={`${prefix}-title`} className="pcf__title">
          Comparison fidelity
        </h2>
        <Badge variant={report.strength === 'full' ? VERDICT_TONES[report.verdict] : STRENGTH_TONES[report.strength]} data-testid="pcf-verdict">
          {verdictLabel(report.verdict, report.strength)}
        </Badge>
      </div>
      <p className="pcf__pair">
        {consumer.name}
        {consumer.version ? ` ${consumer.version}` : ''} against the provider contract of {provider.name} {provider.version}
        {report.selfVerification ? ` · self-verification ${report.selfVerification}` : ''}
      </p>
      <p className="pcf__statement" data-testid="pcf-statement">
        {report.statement}
      </p>
      <dl className="pcf__counters">
        {COUNTERS.map((counter) => (
          <div key={counter.key} className="pcf__counter" data-zero={report.summary[counter.key] === 0 || undefined}>
            <dt className="pcf__counter-label">{counter.label}</dt>
            <dd className="pcf__counter-value">{report.summary[counter.key] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {report.error ? (
        <p className="pcf__error" role="note">
          <code className="pcf__code">{report.error.code}</code> {report.error.message}
        </p>
      ) : null}
      {report.interactions.map((interaction) => (
        <InteractionReport key={interaction.index} interaction={interaction} prefix={prefix} />
      ))}
    </section>
  );
}
