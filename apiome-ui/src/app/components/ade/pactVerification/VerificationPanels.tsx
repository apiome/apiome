'use client';

/**
 * The pieces of the **Verification** pages (PFX-5.5, #6949). Presentation and the run form —
 * the pages own the reads.
 *
 * Tables are real `<table>`s with captions and column headers; each interaction is a native
 * `<details>` disclosure (failed ones open), so the pages are read and driven from the keyboard
 * like the other Contracts pages.
 */

import * as React from 'react';
import Link from 'next/link';
import { Play } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { formatWhen, safeHttpUrl, shortVersion } from '@lib/pact-pacticipants';
import { pactRoute, shortSha } from '@lib/pact-detail';
import {
  SETTINGS_ROUTE,
  SOURCE_TEXT,
  cadenceLabel,
  formatHours,
  requestRoute,
  stateText,
  type EffectiveSettings,
} from '@lib/pact-remediation';
import {
  OUTCOME_LABELS,
  formatDuration,
  passRate,
  resultVerdict,
  runSummary,
  triggerLabel,
  verificationResultRoute,
  type ConsoleRunResponse,
  type EvidenceRun,
  type InteractionOutcome,
  type ResultSummary,
  type RunBody,
  type StatusCounts,
  type TargetOption,
  type VerificationStatusEntry,
} from '@lib/pact-verification';

/**
 * A result's verdict as a badge.
 *
 * @param props - The result.
 * @returns The badge.
 */
export function ResultBadge({ result }: { result: Pick<ResultSummary, 'success' | 'pending'> }) {
  const verdict = resultVerdict(result);
  return (
    <Badge variant={verdict.variant} data-testid="pvx-verdict">
      {verdict.label}
    </Badge>
  );
}

/**
 * The KPI strip: pacts, verified, failing, stale, pass rate, last verified.
 *
 * @param props - The counts.
 * @returns The strip.
 */
export function KpiStrip({ counts }: { counts: StatusCounts }) {
  const items: Array<[string, string, string]> = [
    ['pacts', 'Pacts', String(counts.pacts)],
    ['verified', 'Verified', String(counts.verified)],
    ['failing', 'Failing', String(counts.failing)],
    ['stale', 'Stale', String(counts.stale)],
    ...(counts.overdue === undefined ? [] : [['overdue', 'Overdue', String(counts.overdue)] as [string, string, string]]),
    ['pass-rate', 'Interactions passing', passRate(counts)],
    ['last', 'Last verified', counts.last_verified_at ? formatWhen(counts.last_verified_at) : 'Never'],
  ];
  return (
    <dl className="pvx-kpis" data-testid="pvx-kpis">
      {items.map(([key, label, value]) => (
        <div key={key} className={`pvx-kpi pvx-kpi--${key}`} data-testid={`pvx-kpi-${key}`}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * What PFX-6.2 adds to a pact's row: overdue past its stale threshold, its open re-publish request,
 * and why a scheduled verification did not run.
 *
 * @param props - The row.
 * @returns The notes, or nothing.
 */
export function RemediationNotes({ entry }: { entry: VerificationStatusEntry }) {
  const request = entry.republish_request;
  const attempt = entry.scheduled;
  const blocked = attempt && (attempt.status === 'skipped' || attempt.status === 'errored') ? attempt : null;
  if (!entry.overdue && !request && !blocked) return null;
  return (
    <span className="pvx-remediation" data-testid={`pvx-remediation-${entry.consumer}`}>
      {entry.overdue ? (
        <Badge
          variant="danger"
          data-testid="pvx-overdue"
          title={entry.stale_since ? `Past its stale threshold since ${formatWhen(entry.stale_since)}` : undefined}
        >
          Overdue
        </Badge>
      ) : null}
      {request ? (
        <Link className="ppx__link" href={requestRoute(request.id)} data-testid="pvx-republish-link">
          Re-publish {stateText(request.state).label.toLowerCase()}
        </Link>
      ) : null}
      {blocked ? (
        <span className="ppx__muted" data-testid="pvx-schedule-note">
          Scheduled run {blocked.status}: {blocked.reason ?? blocked.code}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The cadence and stale threshold that apply to the provider, with where to change them.
 *
 * @param props - The provider's effective settings, when known.
 * @returns The line, or nothing.
 */
export function CadenceLine({ settings }: { settings: EffectiveSettings | null | undefined }) {
  if (!settings) return null;
  return (
    <p className="ppx__muted pvx-cadence" data-testid="pvx-cadence">
      Verification cadence: {cadenceLabel(settings.cadence)} ({SOURCE_TEXT[settings.cadence_source]}) · stale after{' '}
      {formatHours(settings.stale_threshold_hours)}
      {settings.target ? ` · scheduled runs replay against ${settings.target}` : ''} ·{' '}
      <Link className="ppx__link" href={SETTINGS_ROUTE}>
        Verification settings
      </Link>
    </p>
  );
}

/**
 * Each consumer's newest pact with its newest result, stale ones marked, each with **Re-run**.
 *
 * @param props - The entries, the provider, and what **Re-run** does.
 * @returns The table.
 */
export function StatusTable({
  entries,
  provider,
  onRerun,
}: {
  entries: VerificationStatusEntry[];
  provider: string;
  onRerun: (entry: VerificationStatusEntry) => void;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pvx-status-table">
        <caption className="sr-only">Each consumer&apos;s newest pact and its newest verification result</caption>
        <thead>
          <tr>
            <th scope="col">Consumer</th>
            <th scope="col">Pact</th>
            <th scope="col">Newest result</th>
            <th scope="col">Provider version</th>
            <th scope="col">Verified</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const result = entry.latest_result;
            return (
              <tr key={entry.consumer} data-testid={`pvx-status-${entry.consumer}`}>
                <th scope="row">
                  <Link className="ppx__link ppx__name" href={pactRoute(entry.consumer, provider)}>
                    {entry.consumer_name}
                  </Link>
                </th>
                <td>
                  <span className="ppx__mono" title={entry.consumer_version}>
                    {shortVersion(entry.consumer_version)}
                  </span>{' '}
                  <span className="ppx__muted ppx__mono" title={entry.pact_version_sha}>
                    {shortSha(entry.pact_version_sha)}
                  </span>
                </td>
                <td>
                  {result ? (
                    <span className="ppx__chips">
                      <ResultBadge result={result} />
                      <Link className="ppx__link" href={verificationResultRoute(provider, result.id)}>
                        Result {result.number}
                      </Link>
                    </span>
                  ) : (
                    <Badge variant="warn" data-testid="pvx-stale">
                      Stale — not verified
                    </Badge>
                  )}
                  <RemediationNotes entry={entry} />
                </td>
                <td className="ppx__mono" title={result?.provider_version}>
                  {result ? shortVersion(result.provider_version) : <span className="ppx__muted">—</span>}
                </td>
                <td className="ppx__when">{result ? formatWhen(result.created_at) : '—'}</td>
                <td>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onRerun(entry)}
                    data-testid={`pvx-rerun-${entry.consumer}`}
                    aria-label={`Re-run the verification of ${entry.consumer_name}'s pact`}
                  >
                    <Play aria-hidden />
                    Re-run
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The provider's verification results, newest first.
 *
 * @param props - The results and the provider.
 * @returns The table.
 */
export function HistoryTable({ results, provider }: { results: ResultSummary[]; provider: string }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pvx-history-table">
        <caption className="sr-only">Verification results, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Result</th>
            <th scope="col">Consumer</th>
            <th scope="col">Provider version</th>
            <th scope="col">Verdict</th>
            <th scope="col">Interactions</th>
            <th scope="col">Trigger</th>
            <th scope="col">Duration</th>
            <th scope="col">Build</th>
            <th scope="col">Verified</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => {
            const build = safeHttpUrl(result.build_url);
            return (
              <tr key={result.id} data-testid={`pvx-history-${result.id}`}>
                <th scope="row">
                  <Link className="ppx__link" href={verificationResultRoute(provider, result.id)}>
                    #{result.number} · {shortSha(result.pact_version_sha)}
                  </Link>
                </th>
                <td>{result.consumer_name}</td>
                <td>
                  <span className="ppx__mono" title={result.provider_version}>
                    {shortVersion(result.provider_version)}
                  </span>
                  {result.provider_branch ? (
                    <span className="ppx__muted ppx__mono"> · {result.provider_branch}</span>
                  ) : null}
                </td>
                <td>
                  <span className="ppx__chips">
                    <ResultBadge result={result} />
                    {result.wip ? <Badge variant="neutral">Work in progress</Badge> : null}
                  </span>
                </td>
                <td>
                  {result.counts.passed} / {result.counts.total} passed
                </td>
                <td>{triggerLabel(result.trigger)}</td>
                <td className="ppx__when">{formatDuration(result.duration_ms)}</td>
                <td>
                  {build ? (
                    <a className="ppx__link" href={build} target="_blank" rel="noreferrer noopener">
                      Build
                    </a>
                  ) : (
                    <span className="ppx__muted">—</span>
                  )}
                </td>
                <td className="ppx__when">{formatWhen(result.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Each interaction of a result: failed ones open, each mismatch with expected and actual side by side.
 *
 * @param props - The interactions.
 * @returns The list.
 */
export function InteractionResults({ outcomes }: { outcomes: InteractionOutcome[] }) {
  if (outcomes.length === 0) {
    return <p className="ppx__muted">The verifier sent no per-interaction results.</p>;
  }
  return (
    <ul className="pvx-interactions" data-testid="pvx-interactions">
      {outcomes.map((outcome, index) => (
        <li key={`${index}-${outcome.description}`}>
          <details className="pvx-interaction" open={!outcome.success}>
            <summary className="pvx-interaction__summary">
              <Badge variant={outcome.success ? 'success' : outcome.pending ? 'warn' : 'danger'}>
                {outcome.success ? 'Passed' : outcome.outcome && outcome.outcome !== 'failed' ? outcome.outcome : 'Failed'}
              </Badge>
              <span className="pvx-interaction__name">{outcome.description}</span>
            </summary>
            <div className="pvx-interaction__body">
              {outcome.providerState ? (
                <p className="ppx__muted">Provider state: {outcome.providerState}</p>
              ) : null}
              {outcome.code ? <p className="ppx__muted ppx__mono">{outcome.code}</p> : null}
              {outcome.unreadable ? (
                <>
                  <p className="ppx__muted">This entry is not one the page can read; it is shown as sent.</p>
                  <pre className="ppx__snippet">{outcome.unreadable}</pre>
                </>
              ) : null}
              {outcome.mismatches.map((mismatch, at) => (
                <div key={at} className="pvx-mismatch" data-testid="pvx-mismatch">
                  <p className="pvx-mismatch__where">
                    {[mismatch.attribute, mismatch.field].filter(Boolean).join(' ') || 'Mismatch'}
                    {mismatch.rule ? <span className="ppx__muted"> · rule {mismatch.rule}</span> : null}
                  </p>
                  {mismatch.description ? <p className="ppx__statement">{mismatch.description}</p> : null}
                  {mismatch.expected !== null || mismatch.actual !== null ? (
                    <div className="pvx-diff">
                      <div className="pvx-diff__side pvx-diff__side--expected">
                        <span className="ppx__meta">Expected</span>
                        <pre>{mismatch.expected ?? '(not sent)'}</pre>
                      </div>
                      <div className="pvx-diff__side pvx-diff__side--actual">
                        <span className="ppx__meta">Actual</span>
                        <pre>{mismatch.actual ?? '(not sent)'}</pre>
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
              {outcome.messages.map((message, at) => (
                <p key={at} className="ppx__statement">
                  {message}
                </p>
              ))}
              {outcome.success && outcome.mismatches.length === 0 ? (
                <p className="ppx__muted">Every check of this interaction passed.</p>
              ) : null}
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}

/**
 * The evidence run's requests: what was sent, what came back, how it was judged.
 *
 * @param props - The evidence run.
 * @returns The table.
 */
export function EvidenceRequests({ run }: { run: EvidenceRun }) {
  const operations = run.operations ?? [];
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pvx-evidence-table">
        <caption className="sr-only">Requests the run sent to {run.target_slug}</caption>
        <thead>
          <tr>
            <th scope="col">Request</th>
            <th scope="col">Status</th>
            <th scope="col">Outcome</th>
            <th scope="col">Assertions</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {operations.map((op) => {
            const assertions = op.assertions ?? [];
            const failed = assertions.filter((assertion) => assertion.outcome === 'failed').length;
            return (
              <tr key={op.sequence}>
                <th scope="row" className="ppx__mono">
                  {op.http_method} {op.http_path}
                </th>
                <td className="ppx__mono">
                  {op.actual_status ?? '—'}
                  {op.expected_status ? <span className="ppx__muted"> (expected {op.expected_status})</span> : null}
                </td>
                <td>
                  <Badge variant={op.outcome === 'passed' ? 'success' : op.outcome === 'skipped' ? 'neutral' : 'danger'}>
                    {op.outcome}
                  </Badge>
                  {op.failure_message ? <p className="ppx__muted">{op.failure_message}</p> : null}
                </td>
                <td>
                  {assertions.length - failed} / {assertions.length} passed
                </td>
                <td className="ppx__when">{formatDuration(op.duration_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * What a console run did: the sentence, each pact's outcome and every pact it did not run.
 *
 * @param props - The run.
 * @returns The outcome.
 */
export function RunOutcome({ run }: { run: ConsoleRunResponse }) {
  return (
    <div className="pvx-run-outcome" data-testid="pvx-run-outcome" role="status">
      <p className="ppx__statement">{runSummary(run)}</p>
      {run.pacts.length > 0 ? (
        <ul className="ppx__plain-list">
          {run.pacts.map((pact) => (
            <li key={pact.pact_version_sha} className="ppx__chips">
              <Badge variant={pact.outcome === 'passed' ? 'success' : pact.outcome === 'failed' ? 'danger' : 'warn'}>
                {OUTCOME_LABELS[pact.outcome] ?? pact.outcome}
              </Badge>
              <span>
                {pact.consumer_name} · {shortSha(pact.pact_version_sha)}
                {pact.result ? ` · result ${pact.result.number}` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {run.skipped.length > 0 ? (
        <ul className="ppx__plain-list" data-testid="pvx-run-skipped">
          {run.skipped.map((pact) => (
            <li key={pact.pact_version_sha}>
              <Badge variant="neutral">Not run</Badge> {pact.consumer_name}: {pact.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** What the run dialog is for. */
export interface RunRequest {
  /** `rerun` (one pact) or `stale` (every stale pact). */
  mode: 'rerun' | 'stale';
  title: string;
  description: string;
  /** Prefilled provider version and branch (a re-run's newest result). */
  providerVersion?: string | null;
  providerBranch?: string | null;
}

/**
 * The run dialog: target, provider version and branch, the mutating opt-in, then the outcome.
 *
 * @param props - What is run, the targets (or why they could not be read), how to run and how to close.
 * @returns The dialog.
 */
export function RunDialog({
  request,
  targets,
  targetsError,
  onRun,
  onClose,
}: {
  request: RunRequest;
  targets: TargetOption[] | null;
  targetsError: string | null;
  onRun: (body: RunBody) => Promise<ConsoleRunResponse>;
  onClose: () => void;
}) {
  const [target, setTarget] = React.useState('');
  const [version, setVersion] = React.useState(request.providerVersion ?? '');
  const [branch, setBranch] = React.useState(request.providerBranch ?? '');
  const [allowMutating, setAllowMutating] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [run, setRun] = React.useState<ConsoleRunResponse | null>(null);

  React.useEffect(() => {
    if (!target && targets && targets.length > 0) {
      setTarget((targets.find((option) => option.enabled) ?? targets[0]).slug);
    }
  }, [target, targets]);

  const needsVersion = request.mode === 'stale' || !request.providerVersion;
  const ready = Boolean(target) && (!needsVersion || version.trim().length > 0) && !busy;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const body: RunBody = { target_ref: target };
      if (version.trim()) body.provider_version = version.trim();
      if (branch.trim()) body.provider_branch = branch.trim();
      if (allowMutating) body.verification = { allow_mutating: true };
      setRun(await onRun(body));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The verification could not be run.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent data-testid="pvx-run-dialog" data-mode={request.mode}>
        <DialogHeader>
          <DialogTitle>{request.title}</DialogTitle>
          <DialogDescription>{request.description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <DialogBody>
            <div className="pvx-run-form">
              <label className="pmx-field" htmlFor="pvx-target">
                <span className="ppx__field-label">Verification target</span>
                {targets === null && !targetsError ? (
                  <span className="ppx__muted">Reading the targets…</span>
                ) : targets && targets.length > 0 ? (
                  <select
                    id="pvx-target"
                    className="pmx-input"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    disabled={busy || run !== null}
                  >
                    {targets.map((option) => (
                      <option key={option.slug} value={option.slug} disabled={!option.enabled}>
                        {option.name} ({option.environment}, {option.protocol}){option.enabled ? '' : ' — disabled'}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="ppx__error" data-testid="pvx-no-targets">
                    {targetsError ?? 'No verification target is registered yet. Create one with the verification-targets REST API (POST …/verification-targets) first.'}
                  </span>
                )}
              </label>
              <label className="pmx-field" htmlFor="pvx-version">
                <span className="ppx__field-label">
                  Provider version{needsVersion ? '' : ' (the newest result’s, unless you change it)'}
                </span>
                <input
                  id="pvx-version"
                  className="pmx-input"
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  placeholder="4f1e2d0"
                  maxLength={255}
                  required={needsVersion}
                  disabled={busy || run !== null}
                />
              </label>
              <label className="pmx-field" htmlFor="pvx-branch">
                <span className="ppx__field-label">Provider branch (optional)</span>
                <input
                  id="pvx-branch"
                  className="pmx-input"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  placeholder="main"
                  maxLength={255}
                  disabled={busy || run !== null}
                />
              </label>
              <label className="pmx-check">
                <input
                  type="checkbox"
                  checked={allowMutating}
                  onChange={(event) => setAllowMutating(event.target.checked)}
                  disabled={busy || run !== null}
                />
                Send mutating requests (POST, PUT, PATCH, DELETE) when the target allows them
              </label>
            </div>
            {error ? (
              <p className="ppx__error" role="alert" data-testid="pvx-run-error">
                {error}
              </p>
            ) : null}
            {run ? <RunOutcome run={run} /> : null}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy} data-testid="pvx-run-close">
              {run ? 'Done' : 'Cancel'}
            </Button>
            {run ? null : (
              <Button type="submit" disabled={!ready} data-testid="pvx-run-submit">
                <Play aria-hidden />
                {busy ? 'Verifying…' : request.mode === 'stale' ? 'Verify stale pacts' : 'Re-run verification'}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
