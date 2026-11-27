'use client';

/**
 * The live run drawer of **Run a verification** (PFX-8.9, #7306), built to the run drawer of
 * `docs/mockups/contracts/verify.html`:
 *
 * - the header names the provider build and says *Against staging · started 14:02:11 · 38 of 61
 *   interactions*; a striped progress bar follows the run;
 * - one table row per pact (Queued, Running, Passed, Failed, Incomplete, Stopped) with interactions;
 * - the newest failing interaction: its request, what failed, **Expected** beside **Provider
 *   returned**, then **Show the request**, **Re-run this interaction** (once the run is over;
 *   nothing is published) and **Reproduce on the mock** (the provider's project, when it has one);
 * - the run log, read on from a cursor;
 * - the footer says closing keeps the run going; **Stop run** stops it before its next interaction.
 *
 * The drawer only shows the run; the page follows it ({@link useLiveRun}), so closing it changes
 * nothing about the run.
 */

import * as React from 'react';
import Link from 'next/link';
import { RotateCw, Send, Square } from 'lucide-react';
import {
  Alert,
  Badge,
  Button,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  MethodChip,
} from '@/app/components/ui';
import { OUTCOME_LABELS, verificationRoute } from '@lib/pact-verification';
import {
  expectedActual,
  failureBadge,
  footerNote,
  operationMethod,
  operationPath,
  pactCount,
  pactStatusBadge,
  progressPercent,
  reproduceOnMockHref,
  requestText,
  runIsOver,
  runSubtitle,
  type LiveLogLine,
  type LiveRun,
} from '@lib/pact-verify-live';
import { runHeadline } from '@lib/pact-verify-run';
import type { RerunState } from './useLiveRun';

/** Props for {@link RunDrawer}. */
export interface RunDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  run: LiveRun | null;
  log: LiveLogLine[];
  /** Why the newest poll, stop or re-run failed. */
  problem: string | null;
  rerun: RerunState;
  stopping: boolean;
  /** Whether the viewer may stop and re-run (`pacts:create`). */
  canAct: boolean;
  /** The provider's project, for **Reproduce on the mock**. */
  projectId: string | null;
  onStop: () => void;
  onRerun: (sha: string, caseId: string) => void;
}

/**
 * The drawer.
 *
 * @param props - The run and what the drawer can do.
 * @returns The drawer.
 */
export function RunDrawer({
  open,
  onOpenChange,
  run,
  log,
  problem,
  rerun,
  stopping,
  canAct,
  projectId,
  onStop,
  onRerun,
}: RunDrawerProps) {
  const [showRequest, setShowRequest] = React.useState(false);
  const logRef = React.useRef<HTMLPreElement | null>(null);
  React.useEffect(() => {
    const pane = logRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [log.length]);
  if (!run) return null;
  const over = runIsOver(run);
  const percent = progressPercent(run);
  const failure = run.failure;
  const pair = failure ? expectedActual(failure.interaction) : null;
  const mock = reproduceOnMockHref(projectId);
  const rerunHere =
    failure && rerun.kind !== 'idle' && rerun.caseId === failure.interaction.caseId ? rerun : null;
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent size="lg" data-testid="pvl-drawer">
        <DrawerHeader>
          <DrawerTitle>
            Verifying {run.providerName} {run.providerVersion}
          </DrawerTitle>
          <DrawerDescription data-testid="pvl-subtitle">{runSubtitle(run)}</DrawerDescription>
        </DrawerHeader>
        <DrawerBody className="pvl">
          <progress
            className={`pvl-progress${over ? '' : ' pvl-progress--striped'}`}
            max={100}
            value={percent}
            aria-label="Run progress"
            data-testid="pvl-progress"
          >
            {percent}%
          </progress>
          {over && run.result ? (
            <div className="pvl-verdict" data-testid="pvl-verdict">
              <Badge
                status={
                  run.result.success
                    ? 'passed'
                    : run.result.outcome === 'failed' || run.result.connection_error
                      ? 'failed'
                      : 'warning'
                }
                dot
              >
                {OUTCOME_LABELS[run.result.outcome] ?? run.result.outcome}
              </Badge>
              <span>{runHeadline(run.result)}</span>
            </div>
          ) : null}
          {run.status === 'errored' ? (
            <Alert variant="danger" data-testid="pvl-errored">
              {run.fault ?? 'The run stopped on Apiome’s side.'}
            </Alert>
          ) : null}
          {problem ? (
            <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pvl-problem">
              {problem}
            </p>
          ) : null}

          <table className="pvl-table" data-testid="pvl-pacts">
            <thead>
              <tr>
                <th scope="col">Consumer</th>
                <th scope="col">Pact</th>
                <th scope="col">Result</th>
                <th scope="col" className="pvl-table__num">
                  Interactions
                </th>
              </tr>
            </thead>
            <tbody>
              {run.pacts.map((row) => {
                const badge = pactStatusBadge(row);
                return (
                  <tr key={`${row.consumer}:${row.sha}`} data-testid="pvl-pact-row">
                    <td className="pvl-table__primary">
                      {row.consumerName}{' '}
                      <span className="pvl-mono pvl-subtle">{row.consumerVersion}</span>
                    </td>
                    <td className="pvl-mono">{row.sha.slice(0, 6)}</td>
                    <td>
                      <Badge status={badge.status} dot>
                        {badge.label}
                      </Badge>
                    </td>
                    <td className="pvl-table__num">{pactCount(row)}</td>
                  </tr>
                );
              })}
              {run.pacts.length === 0 ? (
                <tr>
                  <td colSpan={4} className="pvl-subtle">
                    No pact to replay.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          {run.skipped.length ? (
            <ul className="pvl-skipped" data-testid="pvl-skipped">
              {run.skipped.map((item) => (
                <li key={`${item.consumerName}:${item.consumerVersion}:${item.code}`}>
                  <span className="pvl-table__primary">
                    {item.consumerName} {item.consumerVersion}
                  </span>{' '}
                  — {item.reason}
                </li>
              ))}
            </ul>
          ) : null}

          {failure && pair ? (
            <section
              className="pvl-failure"
              aria-label="The failing interaction"
              data-testid="pvl-failure"
            >
              <div className="pvl-failure__head">
                <MethodChip method={operationMethod(failure.interaction.operation)} />
                <span className="pvl-mono">{operationPath(failure.interaction.operation)}</span>
                <Badge status="failed">{failureBadge(failure.interaction)}</Badge>
                <span className="pvl-subtle">
                  {failure.consumerName} {failure.consumerVersion}
                  {failure.interaction.providerStates.length
                    ? ` · state ${failure.interaction.providerStates.map((s) => `“${s}”`).join(', ')}`
                    : ''}
                </span>
              </div>
              <div className="pvl-failure__pair">
                <div>
                  <div className="pvl-caps">Expected</div>
                  <pre className="pvl-code" data-testid="pvl-expected">
                    {pair.expected.map((line) => (
                      <span key={line} className="pvl-code__del">
                        {line}
                        {'\n'}
                      </span>
                    ))}
                  </pre>
                </div>
                <div>
                  <div className="pvl-caps">Provider returned</div>
                  <pre className="pvl-code" data-testid="pvl-actual">
                    {pair.actual.map((line) => (
                      <span key={line} className="pvl-code__add">
                        {line}
                        {'\n'}
                      </span>
                    ))}
                  </pre>
                </div>
              </div>
              {showRequest ? (
                <pre className="pvl-code" data-testid="pvl-request">
                  {requestText(run, failure.interaction)}
                </pre>
              ) : null}
              <div className="pvl-failure__actions">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowRequest((shown) => !shown)}
                  aria-expanded={showRequest}
                  data-testid="pvl-show-request"
                >
                  <Send aria-hidden />
                  {showRequest ? 'Hide the request' : 'Show the request'}
                </Button>
                {canAct ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onRerun(failure.sha, failure.interaction.caseId)}
                    disabled={!over || rerunHere?.kind === 'running'}
                    title={
                      over
                        ? 'Replays this interaction only; nothing is published'
                        : 'Available once the run is over'
                    }
                    data-testid="pvl-rerun"
                  >
                    <RotateCw aria-hidden />
                    {rerunHere?.kind === 'running' ? 'Re-running…' : 'Re-run this interaction'}
                  </Button>
                ) : null}
                {mock ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link href={mock} data-testid="pvl-mock">
                      Reproduce on the mock
                    </Link>
                  </Button>
                ) : (
                  <span className="pvl-subtle" data-testid="pvl-mock-missing">
                    Bind {run.providerName} to a project to reproduce this on its mock.
                  </span>
                )}
              </div>
              {rerunHere?.kind === 'done' ? (
                <div className="pvl-rerun" role="status" data-testid="pvl-rerun-result">
                  <Badge
                    status={rerunHere.interaction.outcome === 'passed' ? 'passed' : 'failed'}
                    dot
                  >
                    {rerunHere.interaction.outcome === 'passed' ? 'Passed' : 'Still failing'}
                  </Badge>
                  <span>
                    Re-run of this interaction only — nothing was published. Start a run to record a
                    result.
                  </span>
                </div>
              ) : null}
              {rerunHere?.kind === 'failed' ? (
                <p
                  className="ppub-hint ppub-hint--danger"
                  role="alert"
                  data-testid="pvl-rerun-error"
                >
                  {rerunHere.error}
                </p>
              ) : null}
            </section>
          ) : null}

          <pre
            className="pvl-log"
            aria-label="Run log"
            tabIndex={0}
            ref={logRef}
            data-testid="pvl-log"
          >
            {run.logDropped ? `… ${run.logDropped} earlier lines are not kept\n` : ''}
            {log.map((line) => (
              <span
                key={line.seq}
                className={
                  line.outcome === 'failed' || line.outcome === 'errored'
                    ? 'pvl-log__bad'
                    : undefined
                }
              >
                {line.text}
                {'\n'}
              </span>
            ))}
          </pre>
        </DrawerBody>
        <DrawerFooter className="pvl-footer">
          <span className="pvl-subtle pvl-footer__note" data-testid="pvl-footer-note">
            {footerNote(stopping ? { ...run, stopRequested: true } : run)}
          </span>
          {over ? (
            <Button size="sm" variant="outline" asChild>
              <Link href={verificationRoute(run.provider)}>Open the Verification page</Link>
            </Button>
          ) : canAct ? (
            <Button
              size="sm"
              variant="danger-soft"
              onClick={onStop}
              disabled={stopping || run.stopRequested}
              data-testid="pvl-stop"
            >
              <Square aria-hidden />
              {stopping || run.stopRequested ? 'Stopping…' : 'Stop run'}
            </Button>
          ) : null}
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

export default RunDrawer;
