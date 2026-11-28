'use client';

/**
 * Step 3 of the **Migration wizard** — **Copy** (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`.
 *
 * - a striped progress bar and a table with one row per kind: copied, skipped, failed;
 * - every record that failed, with its reason — nothing is dropped silently;
 * - the live log, read on from a cursor;
 * - **Stop** while it runs (it stops before its next batch and resumes where it stopped);
 * - once it is over: **Resume** for a stopped or failed copy; **Retry the N that failed** in place
 *   of **Continue** until every record is copied or the failures are set aside.
 *
 * The copy is the server's: leaving the page changes nothing about it. Resuming needs the source's
 * credentials again — they were never stored — so the step asks for them when the wizard has none.
 */

import * as React from 'react';
import Link from 'next/link';
import { RotateCw, Square } from 'lucide-react';
import { Badge, Button } from '@/app/components/ui';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  KIND_LABELS,
  copiedCell,
  failedCount,
  formatCount,
  hasCredentials,
  runBadge,
  runIsOver,
  skippedCell,
  type MigrationLogLine,
  type MigrationRun,
  type SourceForm,
} from '@lib/pact-migration';
import { CredentialFields } from './ConnectStep';

/** Props for {@link CopyStep}. */
export interface CopyStepProps {
  run: MigrationRun;
  log: MigrationLogLine[];
  /** Why the newest read or stop failed. */
  problem: string | null;
  stopping: boolean;
  canMigrate: boolean;
  /** The **Connect** step's fields, for the credentials a resume needs. */
  form: SourceForm;
  onForm: (form: SourceForm) => void;
  /** Whether the viewer chose to go on without the records that failed. */
  failuresDismissed: boolean;
  onDismissFailures: () => void;
  busy: boolean;
  /** Why a resume failed, if it did. */
  error: string | null;
  onStop: () => void;
  onResume: () => void;
  onBack: () => void;
  onContinue: () => void;
}

/**
 * The **Copy** step.
 *
 * @param props - See {@link CopyStepProps}.
 * @returns The step's body and footer.
 */
export function CopyStep({
  run,
  log,
  problem,
  stopping,
  canMigrate,
  form,
  onForm,
  failuresDismissed,
  onDismissFailures,
  busy,
  error,
  onStop,
  onResume,
  onBack,
  onContinue,
}: CopyStepProps) {
  const over = runIsOver(run);
  const failed = failedCount(run);
  const badge = runBadge(run);
  const interrupted = over && run.status !== 'completed';
  const retry = over && run.status === 'completed' && failed > 0 && !failuresDismissed;
  const needsResume = canMigrate && run.can_resume && (interrupted || retry);
  const needsCredentials = needsResume && !hasCredentials(form, run.auth_kind);
  const logRef = React.useRef<HTMLPreElement | null>(null);
  React.useEffect(() => {
    const element = logRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [log.length]);

  return (
    <>
      <div className="pmg-body" data-testid="pmg-copy">
        <div className="pmg-row">
          <span className="pmg-strong">
            {over ? 'Copy from' : 'Copying from'} {run.host}
          </span>
          <Badge status={badge.status} dot data-testid="pmg-copy-state">
            {badge.label}
          </Badge>
        </div>
        <div className="pmg-meter">
          <progress
            className={`pvl-progress${over ? '' : ' pvl-progress--striped'}`}
            max={100}
            value={run.percent}
            aria-label="Copy progress"
            data-testid="pmg-progress"
          >
            {run.percent}%
          </progress>
          <span className="pmg-meter__value">{run.percent}%</span>
        </div>

        {run.error ? (
          <p
            className={run.status === 'failed' ? 'ppub-hint ppub-hint--danger' : 'ppub-hint'}
            role={run.status === 'failed' ? 'alert' : 'status'}
            data-testid="pmg-run-error"
          >
            {run.error}
          </p>
        ) : null}
        {problem ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-problem">
            {problem}
          </p>
        ) : null}

        <table className="pvl-table" data-testid="pmg-kinds">
          <thead>
            <tr>
              <th scope="col">Kind</th>
              <th scope="col" className="pvl-table__num">
                Copied
              </th>
              <th scope="col" className="pvl-table__num">
                Skipped
              </th>
              <th scope="col" className="pvl-table__num">
                Failed
              </th>
            </tr>
          </thead>
          <tbody>
            {run.kinds.map((row) => {
              const skipped = skippedCell(row);
              return (
                <tr key={row.kind} data-testid={`pmg-kind-${row.kind}`}>
                  <td className="pvl-table__primary">{KIND_LABELS[row.kind]}</td>
                  <td className="pvl-table__num">{copiedCell(row, !over)}</td>
                  <td className="pvl-table__num">
                    {formatCount(skipped.count)}
                    {skipped.note ? <span className="pmg-subtle"> {skipped.note}</span> : null}
                  </td>
                  <td className="pvl-table__num">
                    {row.failed > 0 ? (
                      <a href="#pmg-failures" className="pmg-failed">
                        {formatCount(row.failed)}
                      </a>
                    ) : (
                      '0'
                    )}
                  </td>
                </tr>
              );
            })}
            {run.kinds.length === 0 ? (
              <tr>
                <td colSpan={4} className="pvl-subtle">
                  {over ? 'Nothing was read from the source.' : 'Reading the source…'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>

        {failed > 0 ? (
          <section id="pmg-failures" className="pmg-card" aria-labelledby="pmg-failures-title" data-testid="pmg-failures">
            <h3 id="pmg-failures-title" className="pmg-heading">
              {formatCount(failed)} {failed === 1 ? 'record' : 'records'} could not be copied
            </h3>
            <ul className="pmg-lines">
              {run.failures.map((failure) => (
                <li key={`${failure.kind}:${failure.key}:${failure.code}`}>
                  <span className="pvl-mono">
                    {failure.kind} {failure.key}
                  </span>{' '}
                  — {failure.message} <span className="pmg-subtle">({failure.code})</span>
                </li>
              ))}
            </ul>
            {run.failures_dropped > 0 ? (
              <p className="pmg-subtle">
                {formatCount(run.failures_dropped)} more failed and are counted above; a retry lists what is still
                failing.
              </p>
            ) : null}
          </section>
        ) : null}

        <pre className="pvl-log" aria-label="Log" tabIndex={0} ref={logRef} data-testid="pmg-log">
          {log.length && log[0].seq > 1 ? `… ${formatCount(log[0].seq - 1)} earlier lines are not kept\n` : ''}
          {log.map((line) => (
            <span key={line.seq} className={/ failed: /.test(line.text) ? 'pvl-log__bad' : undefined}>
              {line.text}
              {'\n'}
            </span>
          ))}
        </pre>

        {needsCredentials ? (
          <section className="pmg-card" aria-labelledby="pmg-again-title" data-testid="pmg-credentials">
            <h3 id="pmg-again-title" className="pmg-heading">
              Sign in to {run.host} again
            </h3>
            <p className="pmg-subtle">The credentials were never stored, so carrying on needs them once more.</p>
            <CredentialFields form={form} onChange={onForm} idPrefix="pmg-again" />
          </section>
        ) : null}
        {error ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-copy-error">
            {error}
          </p>
        ) : null}
        <p className="pmg-subtle" data-testid="pmg-copy-note">
          {over
            ? 'Run it as often as you like — repeats copy only what changed.'
            : 'You can leave this page. The copy continues, and Past migrations brings you back to it; stopping is safe and it resumes where it stopped.'}
        </p>
      </div>
      <div className="pmg-footer">
        {over ? (
          <Button variant="outline" asChild className="pmg-footer__start">
            <Link href={CONTRACTS_ROUTE}>Save &amp; close</Link>
          </Button>
        ) : (
          <Button
            variant="danger-soft"
            className="pmg-footer__start"
            onClick={onStop}
            disabled={!canMigrate || stopping || run.stop_requested}
            data-testid="pmg-stop"
          >
            <Square aria-hidden />
            {stopping || run.stop_requested ? 'Stopping…' : 'Stop'}
          </Button>
        )}
        <Button variant="ghost" onClick={onBack} data-testid="pmg-back">
          Back
        </Button>
        {retry && needsResume ? (
          <Button variant="ghost" onClick={onDismissFailures} data-testid="pmg-dismiss-failures">
            Continue without them
          </Button>
        ) : null}
        {needsResume ? (
          <Button onClick={onResume} disabled={busy || needsCredentials} data-testid="pmg-resume">
            <RotateCw aria-hidden />
            {busy ? 'Starting…' : retry ? `Retry the ${formatCount(failed)} that failed` : 'Resume'}
          </Button>
        ) : (
          <Button onClick={onContinue} disabled={!over || run.status !== 'completed'} data-testid="pmg-continue">
            Continue
          </Button>
        )}
      </div>
    </>
  );
}

export default CopyStep;
