/**
 * Verification results and operations — PFX-5.5 (#6949).
 *
 * The model of a provider's **Verification** page and of one result's page: the shapes REST
 * answers with (`/v1/tenants/{t}/pact-verifier/pacts/provider/{p}/…`), the paths the `/api/pact/*`
 * proxies forward to, the checks those proxies run on what the browser sends, and the wording the
 * pages show — trigger labels, durations, the KPI strip, each interaction's expected and actual
 * values, and the plain-text log a reader copies or downloads.
 *
 * Everything here is pure, so the proxies, the pages and the tests share it.
 */

import { formatValue, shortSha } from '@lib/pact-detail';
import { MAX_FILTER_LENGTH, isPacticipantHandle, pacticipantRoute, safeHttpUrl } from '@lib/pact-pacticipants';

// --- shapes REST answers with -----------------------------------------------------------------------

/** How a result's interactions went. */
export interface ResultCounts {
  total: number;
  passed: number;
  failed: number;
}

/** How a result came to be. `null` for a result recorded before triggers were recorded. */
export type VerificationTrigger = 'published' | 'hosted' | 'manual' | 'stale-recheck' | 'bidirectional';

/** One verification result, as the history and the status list carry it. */
export interface ResultSummary {
  id: string;
  number: number;
  consumer: string;
  consumer_name: string;
  consumer_version: string | null;
  pact_version_sha: string;
  provider_version: string;
  provider_branch: string | null;
  success: boolean;
  kind: string;
  pending: boolean | null;
  wip: boolean;
  build_url: string | null;
  verified_by: string | null;
  trigger: VerificationTrigger | string | null;
  duration_ms: number | null;
  evidence_run_id: string | null;
  created_at: string | null;
  counts: ResultCounts;
}

/** One page of a provider's history, newest first. */
export interface ResultHistoryPage {
  provider: string;
  provider_name: string;
  consumer: string | null;
  results: ResultSummary[];
  next_cursor: string | null;
}

/** One assertion of an evidence run's request. */
export interface EvidenceAssertion {
  kind: string;
  outcome: string;
  subject?: string | null;
  expected?: string | null;
  actual?: string | null;
  code?: string | null;
  message?: string | null;
}

/** One request of an evidence run. */
export interface EvidenceOperation {
  sequence: number;
  operation_key: string;
  operation_name?: string | null;
  http_method: string;
  http_path: string;
  outcome: string;
  failure_code?: string | null;
  failure_message?: string | null;
  expected_status?: string | null;
  actual_status?: number | null;
  duration_ms?: number;
  attempts?: number;
  assertions?: EvidenceAssertion[];
}

/** The evidence run (ECA-1.3) a hosted result was recorded with. */
export interface EvidenceRun {
  id: string;
  target_slug: string;
  target_base_url: string;
  runner_name: string;
  runner_version?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number;
  outcome: string;
  counts?: Record<string, number>;
  operations?: EvidenceOperation[];
}

/** Why a result's evidence run is or is not shown. */
export type EvidenceStatus = 'attached' | 'not-recorded' | 'not-found' | 'forbidden';

/** One result in full. */
export interface ResultDetail {
  result: ResultSummary;
  provider: string;
  provider_name: string;
  test_results: unknown[];
  comparison: Record<string, unknown> | null;
  evidence_status: EvidenceStatus | string;
  evidence: EvidenceRun | null;
}

/** One consumer's newest pact, and how it stands. */
export interface VerificationStatusEntry {
  consumer: string;
  consumer_name: string;
  consumer_version: string;
  pact_version_sha: string;
  published_at: string | null;
  stale: boolean;
  latest_result: ResultSummary | null;
}

/** The KPI strip. */
export interface StatusCounts {
  pacts: number;
  verified: number;
  failing: number;
  stale: number;
  interactions: number;
  passing_interactions: number;
  last_verified_at: string | null;
}

/** Where a provider's verification stands. */
export interface VerificationStatus {
  provider: string;
  provider_name: string;
  counts: StatusCounts;
  pacts: VerificationStatusEntry[];
  truncated: boolean;
}

/** One pact a console run verified. */
export interface RunPact {
  consumer: string;
  consumer_name: string;
  consumer_version: string;
  pact_version_sha: string;
  outcome: string;
  pending: boolean;
  published: boolean;
  not_published_reason: string | null;
  result: { number: number; success: boolean; url: string } | null;
  counts?: Record<string, number>;
}

/** A pact a console run chose but did not verify. */
export interface SkippedPact {
  consumer: string;
  consumer_name: string;
  consumer_version: string;
  pact_version_sha: string;
  code: string;
  reason: string;
}

/** What a re-run or verify-all-stale answered. */
export interface ConsoleRunResponse {
  provider: string;
  provider_version: string;
  provider_branch: string | null;
  target: { slug: string; base_url: string; environment: string };
  success: boolean;
  outcome: string;
  pacts: RunPact[];
  trigger: string;
  skipped: SkippedPact[];
}

/** A verification target, as the picker lists it. */
export interface TargetOption {
  slug: string;
  name: string;
  environment: string;
  protocol: string;
  enabled: boolean;
}

// --- routes and proxy paths -----------------------------------------------------------------------

/**
 * The provider's **Verification** page.
 *
 * @param provider - The provider's handle.
 * @param consumer - Narrow the history to one consumer.
 * @returns The route.
 */
export function verificationRoute(provider: string, consumer?: string | null): string {
  const base = `${pacticipantRoute(provider)}/verification`;
  return consumer ? `${base}?consumer=${encodeURIComponent(consumer)}` : base;
}

/**
 * One result's page.
 *
 * @param provider - The provider's handle.
 * @param resultId - The result's id.
 * @returns The route.
 */
export function verificationResultRoute(provider: string, resultId: string): string {
  return `${pacticipantRoute(provider)}/verification/results/${encodeURIComponent(resultId)}`;
}

/** A result id: a UUID. */
const RESULT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** A pact version: 64 hex characters (a SHA-256 of the pact's content). */
const PACT_SHA = /^[0-9a-f]{64}$/i;
/** A history cursor: the position REST handed out. */
const CURSOR = /^[0-9]{1,19}$/;

/** Whether a route segment is a result id. */
export function isResultId(value: string): boolean {
  return RESULT_ID.test(value);
}

/** Whether a route segment is a pact version SHA. */
export function isPactSha(value: string): boolean {
  return PACT_SHA.test(value);
}

/** The REST path of a provider's console routes (the handle already checked). */
function providerPath(provider: string): string {
  return `pact-verifier/pacts/provider/${encodeURIComponent(provider)}`;
}

/** The REST path of the status read. */
export function statusProxyPath(provider: string): string {
  return `${providerPath(provider)}/verification-status`;
}

/** The REST path of the history list (its query is added by the proxy). */
export function resultsProxyPath(provider: string): string {
  return `${providerPath(provider)}/results`;
}

/** The REST path of one result. */
export function resultProxyPath(provider: string, resultId: string): string {
  return `${providerPath(provider)}/results/${encodeURIComponent(resultId)}`;
}

/** The REST path of a re-run. */
export function reverifyProxyPath(provider: string, consumer: string, sha: string): string {
  return `${providerPath(provider)}/consumer/${encodeURIComponent(consumer)}/pact-version/${sha.toLowerCase()}/reverify`;
}

/** The REST path of verify-all-stale. */
export function verifyStaleProxyPath(provider: string): string {
  return `${providerPath(provider)}/verify-stale`;
}

/** The history's page size. */
export const HISTORY_PAGE = 25;

/** The filters the history accepts besides `cursor`. */
export const HISTORY_FILTERS = ['consumer'] as const;

/**
 * Whether the history's query can be forwarded: `consumer` a handle, `cursor` a position.
 * (`forwardPactList` then refuses anything else, repeats and empties.)
 *
 * @param params - The browser's query string.
 * @returns `null`, or why it is a 400.
 */
export function historyQueryProblem(params: URLSearchParams): string | null {
  const consumer = params.get('consumer');
  if (consumer !== null && consumer.trim() && !isPacticipantHandle(consumer.trim())) {
    return 'The consumer filter is not a pacticipant handle.';
  }
  const cursor = params.get('cursor');
  if (cursor !== null && cursor.trim() && !CURSOR.test(cursor.trim())) return 'The cursor is not valid.';
  return null;
}

// --- the run body the proxies forward ---------------------------------------------------------------

/** What a console run may be sent; anything else is refused by the proxy. */
export interface RunBody {
  target_ref: string;
  provider_version?: string;
  provider_branch?: string;
  build_url?: string;
  verification?: { allow_mutating?: boolean; replay_without_state_setup?: boolean };
}

/** The body fields a run accepts, in the order the error names them. */
export const RUN_FIELDS = ['target_ref', 'provider_version', 'provider_branch', 'build_url', 'verification'] as const;

/** The `verification` options a run accepts. */
export const RUN_OPTIONS = ['allow_mutating', 'replay_without_state_setup'] as const;

/** The checked body, or why it is a 400. */
export type PickedRunBody = { ok: true; body: RunBody } | { ok: false; error: string };

/** A trimmed string field, `undefined` when absent or empty, or the error. */
function textField(raw: Record<string, unknown>, key: string, max: number): string | undefined | Error {
  const value = raw[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') return new Error(`${key} must be text.`);
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (trimmed.length > max) return new Error(`${key} is longer than ${max} characters.`);
  return trimmed;
}

/**
 * Check a run body before it is forwarded: only the known fields, each the right type and size.
 *
 * @param raw - The parsed JSON body.
 * @param requireVersion - Whether `provider_version` is required (verify-all-stale).
 * @returns The body to forward, or the reason for a 400.
 */
export function pickRunBody(raw: unknown, requireVersion: boolean): PickedRunBody {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, error: 'The body must be a JSON object.' };
  const input = raw as Record<string, unknown>;
  for (const key of Object.keys(input)) {
    if (!(RUN_FIELDS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported field ${key}: a run accepts ${RUN_FIELDS.join(', ')}.` };
    }
  }
  const body: Partial<RunBody> = {};
  const limits: Record<string, number> = { target_ref: 200, provider_version: 255, provider_branch: 255, build_url: 2000 };
  for (const key of ['target_ref', 'provider_version', 'provider_branch', 'build_url'] as const) {
    const value = textField(input, key, limits[key]);
    if (value instanceof Error) return { ok: false, error: value.message };
    if (value !== undefined) body[key] = value;
  }
  if (!body.target_ref) return { ok: false, error: 'Choose a verification target (target_ref).' };
  if (requireVersion && !body.provider_version) {
    return { ok: false, error: 'Give the provider version the pacts are verified as (provider_version).' };
  }
  if (body.build_url && safeHttpUrl(body.build_url) === null) {
    return { ok: false, error: 'build_url must be an http(s) URL.' };
  }
  if (input.verification !== undefined) {
    const options = input.verification;
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      return { ok: false, error: 'verification must be an object.' };
    }
    const picked: RunBody['verification'] = {};
    for (const [key, value] of Object.entries(options as Record<string, unknown>)) {
      if (!(RUN_OPTIONS as readonly string[]).includes(key)) {
        return { ok: false, error: `Unsupported option verification.${key}: a run accepts ${RUN_OPTIONS.join(', ')}.` };
      }
      if (typeof value !== 'boolean') return { ok: false, error: `verification.${key} must be true or false.` };
      picked[key as (typeof RUN_OPTIONS)[number]] = value;
    }
    body.verification = picked;
  }
  return { ok: true, body: body as RunBody };
}

// --- wording ------------------------------------------------------------------------------------------

/** What each trigger is called on the page. */
export const TRIGGER_LABELS: Record<VerificationTrigger, string> = {
  published: 'Pact verifier',
  hosted: 'Hosted verifier',
  manual: 'Re-run',
  'stale-recheck': 'Stale re-check',
  bidirectional: 'Bi-directional',
};

/**
 * A result's trigger as the page names it.
 *
 * @param trigger - The stored trigger, or `null`.
 * @returns E.g. `Re-run`; `Not recorded` for a result recorded before triggers were.
 */
export function triggerLabel(trigger: string | null | undefined): string {
  if (!trigger) return 'Not recorded';
  return TRIGGER_LABELS[trigger as VerificationTrigger] ?? trigger;
}

/**
 * A run's duration.
 *
 * @param ms - Milliseconds, or `null` when Apiome did not run it.
 * @returns `420 ms`, `1.8 s`, `2 min 5 s`, or `—`.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`;
}

/**
 * The pass rate of the newest results' interactions.
 *
 * @param counts - The KPI counts.
 * @returns E.g. `92%`, or `—` with no interactions.
 */
export function passRate(counts: StatusCounts): string {
  if (counts.interactions <= 0) return '—';
  return `${Math.round((counts.passing_interactions / counts.interactions) * 100)}%`;
}

/** What the page says when a result's evidence run is not shown. */
export const EVIDENCE_TEXT: Record<Exclude<EvidenceStatus, 'attached'>, string> = {
  'not-recorded':
    'A Pact verifier published this result, so Apiome holds no request log for it: the log is in the build that ran it.',
  'not-found': 'The request log of this run was removed by evidence retention.',
  forbidden: 'Your role cannot read verification evidence, so the request log is not shown.',
};

/**
 * The verdict of one result, as a label and a badge variant.
 *
 * @param result - The result.
 * @returns The label and the variant.
 */
export function resultVerdict(result: Pick<ResultSummary, 'success' | 'pending'>): {
  label: string;
  variant: 'success' | 'danger' | 'warn';
} {
  if (result.success) return { label: 'Passed', variant: 'success' };
  return result.pending ? { label: 'Failed (pending)', variant: 'warn' } : { label: 'Failed', variant: 'danger' };
}

/** How a run's pact came out, on the page. */
export const OUTCOME_LABELS: Record<string, string> = {
  passed: 'Passed',
  failed: 'Failed',
  incomplete: 'Incomplete — nothing published',
  'no-pacts': 'Nothing to verify',
};

/**
 * One sentence on a console run's answer.
 *
 * @param run - The run.
 * @returns E.g. `2 pacts verified as 4f1e2d0: 1 passed, 1 failed. 1 not run.`
 */
export function runSummary(run: ConsoleRunResponse): string {
  if (run.pacts.length === 0 && run.skipped.length === 0) return 'No stale pact: nothing to verify.';
  const counts = new Map<string, number>();
  for (const pact of run.pacts) counts.set(pact.outcome, (counts.get(pact.outcome) ?? 0) + 1);
  const parts = ['passed', 'failed', 'incomplete']
    .filter((outcome) => counts.get(outcome))
    .map((outcome) => `${counts.get(outcome)} ${outcome}`);
  const verified = `${run.pacts.length} ${run.pacts.length === 1 ? 'pact' : 'pacts'} verified as ${run.provider_version}`;
  const head = run.pacts.length ? `${verified}: ${parts.join(', ')}.` : 'No pact was verified.';
  return run.skipped.length ? `${head} ${run.skipped.length} not run.` : head;
}

// --- expected vs actual ---------------------------------------------------------------------------

/** One mismatch of an interaction. */
export interface MismatchRow {
  attribute: string | null;
  field: string | null;
  rule: string | null;
  description: string | null;
  /** `null` when the verifier did not send the value. */
  expected: string | null;
  actual: string | null;
}

/** One entry of a result's `testResults`, read for the page. */
export interface InteractionOutcome {
  description: string;
  success: boolean;
  /** The hosted verifier's outcome (`passed`, `failed`, `skipped`, `unsupported` …), when sent. */
  outcome: string | null;
  code: string | null;
  providerState: string | null;
  pending: boolean;
  mismatches: MismatchRow[];
  /** Exception messages (an interaction that failed without a mismatch, or was skipped). */
  messages: string[];
  /** Set when the entry was not an object the page can read; it is shown as JSON. */
  unreadable: string | null;
}

/** A string field of a JSON object, or `null`. */
function str(raw: Record<string, unknown>, key: string): string | null {
  const value = raw[key];
  return typeof value === 'string' && value ? value : null;
}

/**
 * A value a verifier sent as expected or actual, as JSON text — a string keeps its quotes, so a type
 * mismatch (`2026` against `"2026"`) is visible; `null` when it sent none.
 */
function shown(raw: Record<string, unknown>, key: string): string | null {
  if (!(key in raw)) return null;
  const value = raw[key];
  return value === undefined ? 'undefined' : (JSON.stringify(value, null, 2) ?? String(value));
}

/**
 * Read a result's `testResults` for the page: every entry kept, in order — one the page cannot
 * read is kept as JSON with the reason, never dropped.
 *
 * @param testResults - The stored entries.
 * @returns One outcome per entry.
 */
export function interactionOutcomes(testResults: unknown[]): InteractionOutcome[] {
  return testResults.map((entry, index) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      return {
        description: `Entry ${index + 1}`,
        success: false,
        outcome: null,
        code: null,
        providerState: null,
        pending: false,
        mismatches: [],
        messages: [],
        unreadable: JSON.stringify(entry) ?? String(entry),
      };
    }
    const raw = entry as Record<string, unknown>;
    const mismatches = (Array.isArray(raw.mismatches) ? raw.mismatches : []).map((item): MismatchRow => {
      const mismatch = item && typeof item === 'object' && !Array.isArray(item) ? (item as Record<string, unknown>) : {};
      return {
        attribute: str(mismatch, 'attribute'),
        field: str(mismatch, 'identifier') ?? str(mismatch, 'path'),
        rule: str(mismatch, 'rule'),
        description: str(mismatch, 'description') ?? (Object.keys(mismatch).length ? null : formatValue(item)),
        expected: shown(mismatch, 'expected'),
        actual: shown(mismatch, 'actual'),
      };
    });
    const messages = (Array.isArray(raw.exceptions) ? raw.exceptions : [])
      .map((item) =>
        item && typeof item === 'object' ? str(item as Record<string, unknown>, 'message') : typeof item === 'string' ? item : null,
      )
      .filter((message): message is string => message !== null);
    return {
      description: str(raw, 'interactionDescription') ?? str(raw, 'description') ?? `Interaction ${index + 1}`,
      success: raw.success === true,
      outcome: str(raw, 'outcome'),
      code: str(raw, 'code'),
      providerState: str(raw, 'interactionProviderState'),
      pending: raw.pending === true,
      mismatches,
      messages,
      unreadable: null,
    };
  });
}

// --- the log ---------------------------------------------------------------------------------------

/**
 * A result as plain text — what **Copy** and **Download** hand out. The same detail always gives
 * the same text: the result, each interaction with its mismatches (expected and actual), and the
 * evidence run's requests with their assertions when it is attached.
 *
 * @param detail - The result in full.
 * @returns The log.
 */
export function renderVerificationLog(detail: ResultDetail): string {
  const r = detail.result;
  const lines: string[] = [
    `Verification result ${r.number} — ${r.consumer_name} → ${detail.provider_name}`,
    `Result id:        ${r.id}`,
    `Verdict:          ${resultVerdict(r).label}`,
    `Pact version:     ${r.pact_version_sha}`,
    `Consumer version: ${r.consumer_version ?? '—'}`,
    `Provider version: ${r.provider_version}${r.provider_branch ? ` (branch ${r.provider_branch})` : ''}`,
    `Trigger:          ${triggerLabel(r.trigger)}`,
    `Verifier:         ${r.verified_by ?? '—'}`,
    `Duration:         ${formatDuration(r.duration_ms)}`,
    `Published:        ${r.created_at ?? '—'}`,
  ];
  if (r.build_url) lines.push(`Build:            ${r.build_url}`);
  lines.push('', `Interactions: ${r.counts.passed} passed, ${r.counts.failed} not passed, ${r.counts.total} in all`);
  for (const outcome of interactionOutcomes(detail.test_results)) {
    const mark = outcome.success ? 'PASS' : (outcome.outcome ?? 'FAIL').toUpperCase();
    lines.push('', `[${mark}] ${outcome.description}`);
    if (outcome.providerState) lines.push(`  Provider state: ${outcome.providerState}`);
    if (outcome.code) lines.push(`  Code: ${outcome.code}`);
    if (outcome.unreadable) lines.push(`  Unreadable entry: ${outcome.unreadable}`);
    for (const mismatch of outcome.mismatches) {
      const where = [mismatch.attribute, mismatch.field].filter(Boolean).join(' ');
      lines.push(`  Mismatch${where ? ` at ${where}` : ''}${mismatch.rule ? ` (rule ${mismatch.rule})` : ''}`);
      if (mismatch.description) lines.push(`    ${mismatch.description}`);
      if (mismatch.expected !== null) lines.push(`    Expected: ${mismatch.expected.replace(/\n/g, '\n              ')}`);
      if (mismatch.actual !== null) lines.push(`    Actual:   ${mismatch.actual.replace(/\n/g, '\n              ')}`);
    }
    for (const message of outcome.messages) lines.push(`  ${message}`);
  }
  if (detail.evidence) {
    const run = detail.evidence;
    lines.push(
      '',
      `Evidence run ${run.id}`,
      `Target: ${run.target_slug} (${run.target_base_url}) · ${run.runner_name}${run.runner_version ? ` ${run.runner_version}` : ''} · ${run.outcome} · ${formatDuration(run.duration_ms)}`,
    );
    for (const op of run.operations ?? []) {
      const status = op.actual_status === null || op.actual_status === undefined ? 'no response' : String(op.actual_status);
      lines.push(
        '',
        `${op.http_method} ${op.http_path} → ${status}${op.expected_status ? ` (expected ${op.expected_status})` : ''} · ${op.outcome} · ${formatDuration(op.duration_ms)}${op.attempts && op.attempts > 1 ? ` · ${op.attempts} attempts` : ''}`,
      );
      if (op.failure_message) lines.push(`  ${op.failure_code ? `${op.failure_code}: ` : ''}${op.failure_message}`);
      for (const assertion of op.assertions ?? []) {
        lines.push(`  - ${assertion.outcome} ${assertion.kind}${assertion.subject ? ` ${assertion.subject}` : ''}`);
        if (assertion.outcome !== 'passed') {
          if (assertion.expected) lines.push(`      Expected: ${assertion.expected}`);
          if (assertion.actual) lines.push(`      Actual:   ${assertion.actual}`);
          if (assertion.message) lines.push(`      ${assertion.message}`);
        }
      }
    }
  } else if (detail.evidence_status !== 'attached') {
    const text = EVIDENCE_TEXT[detail.evidence_status as Exclude<EvidenceStatus, 'attached'>];
    if (text) lines.push('', text);
  }
  return `${lines.join('\n')}\n`;
}

/**
 * The file name a downloaded log gets.
 *
 * @param detail - The result.
 * @returns E.g. `verification-ledger-api-billing-service-3fa1c2d4e5f6-2.log`.
 */
export function logFileName(detail: ResultDetail): string {
  const r = detail.result;
  return `verification-${detail.provider}-${r.consumer}-${shortSha(r.pact_version_sha)}-${r.number}.log`;
}

/** Longest a version shown in a form may be. */
export const MAX_RUN_VERSION_LENGTH = MAX_FILTER_LENGTH;

/**
 * The targets a run can use, read from `/api/verification-targets`: enabled first, by name.
 *
 * @param body - The target list.
 * @returns The options.
 */
export function targetOptions(body: unknown): TargetOption[] {
  const targets = body && typeof body === 'object' ? (body as Record<string, unknown>).targets : null;
  if (!Array.isArray(targets)) return [];
  return targets
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      slug: String(item.slug ?? ''),
      name: String(item.name ?? item.slug ?? ''),
      environment: String(item.environment ?? ''),
      protocol: String(item.protocol ?? 'http'),
      enabled: item.enabled !== false,
    }))
    .filter((target) => target.slug)
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
}
