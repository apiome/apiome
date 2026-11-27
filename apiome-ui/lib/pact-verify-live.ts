/**
 * The live verification run (PFX-8.9, #7306): what the run drawer on **Run a verification** reads.
 *
 * **Run verification** starts a live run (`POST …/verify/runs`, the same body as `…/verify`) and
 * the drawer polls `GET …/pact-verifier/runs/{id}` every {@link LIVE_POLL_MS} — one row per pact
 * with interactions done of the total, the newest failing interaction with expected beside actual,
 * and the log since the drawer's cursor. Closing the drawer stops nothing; **Stop run** does, before
 * the next interaction. One interaction of a finished run can be re-run (nothing is published).
 *
 * Everything here is pure: readers that tolerate a partial answer, and the sentences the drawer and
 * the completion toast show. The BFF pickers ({@link pickRunId}, {@link pickRerunBody}) refuse
 * anything the drawer would not send, naming it.
 */

import { VERIFY_RUN_PROXY, readRun, type VerifyRunAnswer } from './pact-verify-run';

/** How often the drawer reads the run (the run is reflected within two seconds). */
export const LIVE_POLL_MS = 1000;

/** The most log lines the drawer keeps (REST keeps the same). */
export const MAX_LOG_LINES = 2000;

/** The proxy that starts a run. */
export const LIVE_RUNS_PROXY = VERIFY_RUN_PROXY;

/** A pact's place in the run. */
export type LivePactStatus = 'queued' | 'running' | 'passed' | 'failed' | 'incomplete' | 'stopped';

/** One pact of the run. */
export interface LiveRunPact {
  consumer: string;
  consumerName: string;
  consumerVersion: string;
  sha: string;
  status: LivePactStatus | string;
  pending: boolean;
  interactions: number;
  done: number;
  passed: number;
  failed: number;
  skipped: number;
  errored: number;
  published: boolean | null;
  notPublishedReason: string | null;
}

/** One expected-versus-actual difference. */
export interface LiveMismatch {
  attribute: string;
  field: string;
  rule: string;
  expected: string | null;
  actual: string | null;
  description: string;
}

/** One interaction's result. */
export interface LiveInteraction {
  caseId: string;
  description: string;
  operation: string;
  outcome: string;
  code: string | null;
  message: string | null;
  expectedStatus: string | null;
  actualStatus: number | null;
  durationMs: number;
  providerStates: string[];
  mismatches: LiveMismatch[];
}

/** The newest interaction that did not pass, and its pact. */
export interface LiveFailure {
  consumer: string;
  consumerName: string;
  consumerVersion: string;
  sha: string;
  interaction: LiveInteraction;
}

/** One log line. */
export interface LiveLogLine {
  seq: number;
  kind: string;
  outcome: string | null;
  text: string;
}

/** The run as it stands. */
export interface LiveRun {
  runId: string;
  provider: string;
  providerName: string;
  providerVersion: string;
  providerBranch: string | null;
  target: string;
  targetBaseUrl: string;
  environment: string;
  status: 'running' | 'finished' | 'errored' | string;
  stopRequested: boolean;
  startedAt: string;
  finishedAt: string | null;
  interactions: number;
  done: number;
  pacts: LiveRunPact[];
  skipped: { consumerName: string; consumerVersion: string; code: string; reason: string }[];
  failure: LiveFailure | null;
  log: LiveLogLine[];
  logNext: number;
  logDropped: number;
  result: VerifyRunAnswer | null;
  /** Why the run broke on Apiome's side (status `errored`). Not `error`: callers tell answers from failures by that key. */
  fault: string | null;
}

// --- reading -----------------------------------------------------------------------------------

type Json = Record<string, unknown>;

function rec(value: unknown): Json {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {};
}

function list(value: unknown): Json[] {
  return Array.isArray(value)
    ? value.filter((item): item is Json => Boolean(item) && typeof item === 'object')
    : [];
}

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function opt(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Read one interaction's result.
 *
 * @param body - REST's `InteractionVerification`.
 * @returns The interaction.
 */
export function readInteraction(body: unknown): LiveInteraction {
  const row = rec(body);
  return {
    caseId: str(row.case_id),
    description: str(row.description),
    operation: str(row.operation),
    outcome: str(row.outcome),
    code: opt(row.code),
    message: opt(row.message),
    expectedStatus: opt(row.expected_status),
    actualStatus: typeof row.actual_status === 'number' ? row.actual_status : null,
    durationMs: num(row.duration_ms),
    providerStates: Array.isArray(row.provider_states)
      ? row.provider_states.filter((s): s is string => typeof s === 'string')
      : [],
    mismatches: list(row.mismatches).map((m) => ({
      attribute: str(m.attribute),
      field: str(m.field),
      rule: str(m.rule),
      expected: opt(m.expected),
      actual: opt(m.actual),
      description: str(m.description),
    })),
  };
}

/**
 * Read `GET …/pact-verifier/runs/{id}` (or the start's answer).
 *
 * @param body - REST's JSON.
 * @returns The run, or `null` when the answer is not a run at all.
 */
export function readLiveRun(body: unknown): LiveRun | null {
  const run = rec(body);
  if (typeof run.run_id !== 'string' || !run.run_id) return null;
  const failure = run.failure ? rec(run.failure) : null;
  const error = run.error ? rec(run.error) : null;
  return {
    runId: run.run_id,
    provider: str(run.provider),
    providerName: str(run.provider_name, str(run.provider)),
    providerVersion: str(run.provider_version),
    providerBranch: opt(run.provider_branch),
    target: str(run.target),
    targetBaseUrl: str(run.target_base_url),
    environment: str(run.environment),
    status: str(run.status, 'running'),
    stopRequested: run.stop_requested === true,
    startedAt: str(run.started_at),
    finishedAt: opt(run.finished_at),
    interactions: num(run.interactions),
    done: num(run.done),
    pacts: list(run.pacts).map((row) => ({
      consumer: str(row.consumer),
      consumerName: str(row.consumer_name, str(row.consumer)),
      consumerVersion: str(row.consumer_version),
      sha: str(row.pact_version_sha),
      status: str(row.status, 'queued'),
      pending: row.pending === true,
      interactions: num(row.interactions),
      done: num(row.done),
      passed: num(row.passed),
      failed: num(row.failed),
      skipped: num(row.skipped),
      errored: num(row.errored),
      published: typeof row.published === 'boolean' ? row.published : null,
      notPublishedReason: opt(row.not_published_reason),
    })),
    skipped: list(run.skipped).map((row) => ({
      consumerName: str(row.consumer_name, str(row.consumer)),
      consumerVersion: str(row.consumer_version),
      code: str(row.code),
      reason: str(row.reason),
    })),
    failure: failure
      ? {
          consumer: str(failure.consumer),
          consumerName: str(failure.consumer_name, str(failure.consumer)),
          consumerVersion: str(failure.consumer_version),
          sha: str(failure.pact_version_sha),
          interaction: readInteraction(failure.interaction),
        }
      : null,
    log: list(run.log).map((line) => ({
      seq: num(line.seq),
      kind: str(line.kind),
      outcome: opt(line.outcome),
      text: str(line.text),
    })),
    logNext: num(run.log_next),
    logDropped: num(run.log_dropped),
    result: run.result && typeof run.result === 'object' ? readRun(run.result as Json) : null,
    fault: error ? str(error.message, 'The run stopped on Apiome’s side.') : null,
  };
}

/**
 * Append a poll's new log lines to what the drawer already shows, keeping the newest
 * {@link MAX_LOG_LINES}.
 *
 * @param shown - The lines shown so far.
 * @param fresh - The lines the poll returned (after the drawer's cursor).
 * @returns The lines to show, oldest first, with no line twice.
 */
export function mergeLog(shown: LiveLogLine[], fresh: LiveLogLine[]): LiveLogLine[] {
  const last = shown.length ? shown[shown.length - 1].seq : 0;
  const merged = [...shown, ...fresh.filter((line) => line.seq > last)];
  return merged.length > MAX_LOG_LINES ? merged.slice(merged.length - MAX_LOG_LINES) : merged;
}

// --- what the drawer says ------------------------------------------------------------------------

/** Whether the run is over (finished or broken). */
export function runIsOver(run: LiveRun): boolean {
  return run.status !== 'running';
}

/**
 * How far the run is, for the progress bar.
 *
 * @param run - The run.
 * @returns 0–100; 100 once the run is over.
 */
export function progressPercent(run: LiveRun): number {
  if (runIsOver(run)) return 100;
  if (run.interactions <= 0) return 0;
  return Math.min(99, Math.floor((run.done / run.interactions) * 100));
}

/**
 * `14:02:11` for an ISO time, in the reader's own time zone.
 *
 * @param iso - The time.
 * @returns The clock time, or `''` for a missing or malformed time.
 */
export function clockTime(iso: string | null): string {
  if (!iso) return '';
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return '';
  return moment.toLocaleTimeString('en-GB', { hour12: false });
}

/**
 * The drawer's subtitle.
 *
 * @param run - The run.
 * @returns E.g. `Against staging · started 14:02:11 · 38 of 61 interactions`.
 */
export function runSubtitle(run: LiveRun): string {
  const parts = [`Against ${run.target || 'the target'}`];
  const started = clockTime(run.startedAt);
  if (started) parts.push(`started ${started}`);
  parts.push(
    `${run.done} of ${run.interactions} ${run.interactions === 1 ? 'interaction' : 'interactions'}`,
  );
  return parts.join(' · ');
}

/** The badge of a pact's row: its label and the status vocabulary's tone. */
export function pactStatusBadge(row: LiveRunPact): { label: string; status: string } {
  switch (row.status) {
    case 'queued':
      return { label: 'Queued', status: 'pending' };
    case 'running':
      return { label: 'Running', status: 'running' };
    case 'passed':
      return { label: 'Passed', status: 'passed' };
    case 'failed':
      return { label: row.pending ? 'Failed (pending)' : 'Failed', status: 'failed' };
    case 'incomplete':
      return { label: 'Incomplete', status: 'warning' };
    case 'stopped':
      return { label: 'Stopped', status: 'skipped' };
    default:
      return { label: row.status, status: 'pending' };
  }
}

/** `5 / 6` — interactions that passed of the pact's total (done of total while it runs). */
export function pactCount(row: LiveRunPact): string {
  if (row.status === 'queued' || row.status === 'running')
    return `${row.done} / ${row.interactions}`;
  return `${row.passed} / ${row.interactions}`;
}

/**
 * The failing interaction's headline badge.
 *
 * @param interaction - The interaction.
 * @returns E.g. `Body differs`, `Status differs`, `Could not connect`.
 */
export function failureBadge(interaction: LiveInteraction): string {
  const first = interaction.mismatches[0];
  if (first) {
    const what =
      first.attribute === 'body'
        ? 'Body'
        : first.attribute === 'status'
          ? 'Status'
          : first.attribute === 'header'
            ? 'Header'
            : 'Response';
    return `${what} differs`;
  }
  if (interaction.code === 'timeout' || interaction.code === 'transport-error')
    return 'Could not connect';
  return interaction.outcome === 'errored' ? 'Errored' : 'Not verified';
}

/**
 * What the pact expected and what the provider returned, one line per mismatch.
 *
 * @param interaction - The interaction.
 * @returns `{ expected, actual }` as the two code panes show them.
 */
export function expectedActual(interaction: LiveInteraction): {
  expected: string[];
  actual: string[];
} {
  if (!interaction.mismatches.length) {
    return {
      expected: [
        interaction.expectedStatus
          ? `status ${interaction.expectedStatus}`
          : interaction.description,
      ],
      actual: [interaction.message ?? interaction.code ?? interaction.outcome],
    };
  }
  return {
    expected: interaction.mismatches.map(
      (m) =>
        `${m.field || m.attribute}: ${m.expected ?? '(nothing)'}${m.rule && m.rule !== 'equality' ? `  (${m.rule})` : ''}`,
    ),
    actual: interaction.mismatches.map(
      (m) => `${m.field || m.attribute}: ${m.actual ?? '(missing)'}`,
    ),
  };
}

/** The method of an operation (`POST /invoices` → `POST`), lower-cased for the method chip. */
export function operationMethod(operation: string): string {
  const method = operation.split(' ', 1)[0] ?? '';
  return /^[A-Z]+$/.test(method) ? method : '';
}

/** The path of an operation (`POST /invoices` → `/invoices`). */
export function operationPath(operation: string): string {
  const method = operationMethod(operation);
  return method ? operation.slice(method.length).trim() : operation;
}

/**
 * The request the interaction sends, as **Show the request** prints it.
 *
 * @param run - The run (its target).
 * @param interaction - The interaction.
 * @returns A short, copyable description: the provider states, the request against the target, and
 *   the status the pact expects.
 */
export function requestText(run: LiveRun, interaction: LiveInteraction): string {
  const lines: string[] = [];
  for (const state of interaction.providerStates) lines.push(`# provider state: “${state}”`);
  const method = operationMethod(interaction.operation) || 'GET';
  const base = run.targetBaseUrl.replace(/\/+$/, '');
  lines.push(`curl -X ${method} '${base}${operationPath(interaction.operation)}'`);
  if (interaction.expectedStatus)
    lines.push(`# the pact expects status ${interaction.expectedStatus}`);
  return lines.join('\n');
}

/**
 * The toast when a run ends while the drawer is closed.
 *
 * @param run - The finished run.
 * @returns The title, one sentence, and the tone.
 */
export function finishedToast(run: LiveRun): {
  title: string;
  description: string;
  tone: 'success' | 'error' | 'warning';
} {
  const who = `${run.providerName} ${run.providerVersion}`;
  if (run.status === 'errored')
    return { title: 'The verification run broke', description: run.fault ?? who, tone: 'error' };
  const result = run.result;
  if (!result) return { title: 'Verification finished', description: who, tone: 'warning' };
  if (result.connection_error)
    return { title: 'Could not connect', description: result.connection_error, tone: 'error' };
  if (result.outcome === 'passed')
    return {
      title: 'Verification passed',
      description: `${who}: every pact passed.`,
      tone: 'success',
    };
  if (result.outcome === 'failed')
    return { title: 'Verification failed', description: `${who}: a pact failed.`, tone: 'error' };
  if (result.outcome === 'stopped')
    return {
      title: 'Verification stopped',
      description: `${who} was stopped before it finished.`,
      tone: 'warning',
    };
  return {
    title: 'Verification finished',
    description: `${who}: ${result.outcome}.`,
    tone: 'warning',
  };
}

/**
 * The drawer's footer note.
 *
 * @param run - The run.
 * @returns What closing does, or how the run ended.
 */
export function footerNote(run: LiveRun): string {
  if (!runIsOver(run)) {
    return run.stopRequested
      ? 'Stopping — the run ends before its next interaction.'
      : 'Closing keeps it running; a toast tells you when it ends.';
  }
  if (run.status === 'errored') return run.fault ?? 'The run stopped on Apiome’s side.';
  return 'The run is over. Results are on the provider’s Verification page.';
}

/**
 * Where **Reproduce on the mock** goes: the provider's project on the Versions page, where each
 * version's hosted mock is switched on and its URL copied.
 *
 * @param projectId - The project the provider pacticipant is linked to, if any.
 * @returns The link, or `null` when the provider is not linked to a project.
 */
export function reproduceOnMockHref(projectId: string | null | undefined): string | null {
  if (!projectId) return null;
  return `/ade/dashboard/versions?projectId=${encodeURIComponent(projectId)}`;
}

// --- the BFF ---------------------------------------------------------------------------------------

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether a value is a live run's id (a UUID). */
export function isRunId(value: string): boolean {
  return RUN_ID.test(value);
}

/**
 * The REST path of one run below `/v1/tenants/{slug}`.
 *
 * @param runId - The checked run id.
 * @param action - `stop`, `rerun`, or nothing for the read.
 * @returns E.g. `pact-verifier/runs/{id}/stop`.
 */
export function runRestPath(runId: string, action?: 'stop' | 'rerun'): string {
  const base = `pact-verifier/runs/${encodeURIComponent(runId)}`;
  return action ? `${base}/${action}` : base;
}

/**
 * The browser's query of a run read: only `log_after`, a whole number.
 *
 * @param params - The query string.
 * @returns The cursor, or why the query is refused.
 */
export function pickLogAfter(
  params: URLSearchParams,
): { ok: true; logAfter: number } | { ok: false; error: string } {
  for (const key of params.keys()) {
    if (key !== 'log_after')
      return { ok: false, error: `${key} is not a parameter of a run read.` };
  }
  const raw = params.get('log_after');
  if (raw === null || raw === '') return { ok: true, logAfter: 0 };
  if (!/^\d{1,9}$/.test(raw)) return { ok: false, error: 'log_after must be a whole number.' };
  return { ok: true, logAfter: Number(raw) };
}

/**
 * Read the browser's re-run body: `{ pact_version_sha, case_id }` and nothing else.
 *
 * @param raw - The parsed JSON.
 * @returns The body, or the first reason it is refused.
 */
export function pickRerunBody(
  raw: unknown,
):
  { ok: true; body: { pact_version_sha: string; case_id: string } } | { ok: false; error: string } {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return { ok: false, error: 'The request must be a JSON object.' };
  const body = raw as Json;
  const unknown = Object.keys(body).find((key) => key !== 'pact_version_sha' && key !== 'case_id');
  if (unknown) return { ok: false, error: `${unknown} is not a field of a re-run.` };
  const sha = typeof body.pact_version_sha === 'string' ? body.pact_version_sha.trim() : '';
  const caseId = typeof body.case_id === 'string' ? body.case_id.trim() : '';
  if (!/^[0-9a-f]{6,128}$/i.test(sha))
    return { ok: false, error: 'pact_version_sha must be the pact version.' };
  if (!caseId || caseId.length > 500)
    return { ok: false, error: 'case_id must be the interaction’s case id.' };
  return { ok: true, body: { pact_version_sha: sha, case_id: caseId } };
}
