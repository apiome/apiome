/**
 * The **Run a verification** page's calls (PFX-8.8, #7305). Each goes through an `/api/*` proxy as
 * the signed-in user; tenancy and permissions are REST's. None throws: every answer is shown beside
 * what it is about.
 */

import type { Cadence } from '@lib/pact-remediation';
import {
  VERIFY_PREVIEW_PROXY,
  readPreview,
  readTargets,
  type VerifyPreview,
  type VerifyTarget,
} from '@lib/pact-verify-run';
import { LIVE_RUNS_PROXY, readInteraction, readLiveRun, type LiveInteraction, type LiveRun } from '@lib/pact-verify-live';
import { UPLOAD_PROXY, readUploadAnswer, type UploadAnswer } from '@lib/pact-verify-upload';

/** A refusal: the message and the status. */
export interface CallFailure {
  error: string;
  status: number;
}

/** A provider, as the Provider select lists it. */
export interface ProviderChoice {
  slug: string;
  name: string;
  mainBranch: string | null;
  /** The project it is linked to (its hosted mock is reproduced on), PFX-8.9. */
  projectId: string | null;
}

/** The status and body of an answer, or `null` offline. */
type Answer = { status: number; body: Record<string, unknown> } | null;

/**
 * Send one request and read its JSON.
 *
 * @param url - The proxy URL.
 * @param init - Fetch options.
 * @returns The answer, or `null` when the proxy could not be reached.
 */
async function send(url: string, init?: RequestInit): Promise<Answer> {
  try {
    const response = await fetch(url, { cache: 'no-store', ...init });
    const body = (await response.json().catch(() => ({}))) as unknown;
    return { status: response.status, body: body && typeof body === 'object' ? (body as Record<string, unknown>) : {} };
  } catch {
    return null;
  }
}

/** A JSON request. */
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

/**
 * The failure of an answer.
 *
 * @param answer - The answer (`null` offline).
 * @param fallback - What to say when the proxy gave no message.
 * @returns The failure.
 */
function failure(answer: Answer, fallback: string): CallFailure {
  if (!answer) return { error: 'The Pact Broker could not be reached. Try again shortly.', status: 503 };
  const error = typeof answer.body.error === 'string' && answer.body.error ? answer.body.error : `${fallback} (${answer.status}).`;
  return { error, status: answer.status };
}

/**
 * The workspace's providers (the first page of pacticipants).
 *
 * @returns The providers, or the failure.
 */
export async function fetchProviders(): Promise<ProviderChoice[] | CallFailure> {
  const answer = await send('/api/pact/pacticipants');
  if (!answer || answer.status >= 400 || !Array.isArray(answer.body.pacticipants)) return failure(answer, 'Could not read the pacticipants');
  return (answer.body.pacticipants as Record<string, unknown>[])
    .filter((row) => typeof row.slug === 'string')
    .map((row) => ({
      slug: String(row.slug),
      name: typeof row.name === 'string' && row.name ? row.name : String(row.slug),
      mainBranch: typeof row.main_branch === 'string' && row.main_branch ? row.main_branch : null,
      projectId: typeof row.project_id === 'string' && row.project_id ? row.project_id : null,
    }));
}

/**
 * The workspace's verification targets.
 *
 * @returns The targets, or the failure.
 */
export async function fetchTargets(): Promise<VerifyTarget[] | CallFailure> {
  const answer = await send('/api/verification-targets');
  if (!answer || answer.status >= 400) return failure(answer, 'Could not read the verification targets');
  return readTargets(answer.body);
}

/**
 * Add a verification target (**Add a target**).
 *
 * @param body - `newTargetBody(form)`.
 * @returns The new target, or the refusal (a 403 without `verification_targets:create`).
 */
export async function createTarget(body: Record<string, unknown>): Promise<VerifyTarget | CallFailure> {
  const answer = await send('/api/verification-targets', json('POST', body));
  if (!answer || answer.status >= 400) return failure(answer, 'The target could not be added');
  const [target] = readTargets({ targets: [answer.body] });
  return target ?? failure(answer, 'The target could not be read');
}

/**
 * Preview the run: nothing is sent to any target, nothing is stored.
 *
 * @param provider - The provider's handle.
 * @param body - `previewBody(form)`.
 * @returns The preview, or the failure.
 */
export async function previewVerification(provider: string, body: Record<string, unknown>): Promise<VerifyPreview | CallFailure> {
  const answer = await send(VERIFY_PREVIEW_PROXY, json('POST', { provider, body }));
  if (!answer || answer.status >= 400) return failure(answer, 'The run could not be previewed');
  return readPreview(answer.body);
}

/**
 * Save the run as the provider's schedule: a provider-wide override of PFX-6.2's cadence and target.
 *
 * @param provider - The provider's handle.
 * @param cadence - How often scheduled runs verify it.
 * @param target - The target they run against.
 * @returns `null` when saved, or the refusal.
 */
export async function saveSchedule(provider: string, cadence: Cadence, target: string): Promise<CallFailure | null> {
  const answer = await send('/api/pact/verification-settings/overrides', json('PUT', { provider, cadence, target_ref: target }));
  if (!answer || answer.status >= 400) return failure(answer, 'The schedule could not be saved');
  return null;
}

// --- the live run and the upload (PFX-8.9, #7306) ---------------------------------------------------

/** A failure that also carries REST's pointer into the report (an upload refusal). */
export interface UploadFailure extends CallFailure {
  pointer: string | null;
}

/**
 * Start a live run (the body of `POST …/verify`), answered at once.
 *
 * @param provider - The provider's handle.
 * @param body - `verifyBody(form)`.
 * @returns The run as it starts, or the refusal (with REST's reason).
 */
export async function startLiveRun(provider: string, body: Record<string, unknown>): Promise<LiveRun | CallFailure> {
  const answer = await send(LIVE_RUNS_PROXY, json('POST', { provider, body }));
  if (!answer || answer.status >= 400) return failure(answer, 'The verification could not start');
  return readLiveRun(answer.body) ?? failure(answer, 'The run could not be read');
}

/**
 * Read a live run from a log cursor.
 *
 * @param runId - The run's id.
 * @param logAfter - The newest log line already shown.
 * @returns The run, or the failure.
 */
export async function pollLiveRun(runId: string, logAfter: number): Promise<LiveRun | CallFailure> {
  const answer = await send(`${LIVE_RUNS_PROXY}/${encodeURIComponent(runId)}?log_after=${logAfter}`);
  if (!answer || answer.status >= 400) return failure(answer, 'The run could not be read');
  return readLiveRun(answer.body) ?? failure(answer, 'The run could not be read');
}

/**
 * Ask a live run to stop.
 *
 * @param runId - The run's id.
 * @returns The run as it stands, or the refusal.
 */
export async function stopLiveRun(runId: string): Promise<LiveRun | CallFailure> {
  const answer = await send(`${LIVE_RUNS_PROXY}/${encodeURIComponent(runId)}/stop`, { method: 'POST' });
  if (!answer || answer.status >= 400) return failure(answer, 'The run could not be stopped');
  return readLiveRun(answer.body) ?? failure(answer, 'The run could not be read');
}

/**
 * Re-run one interaction of a finished run; nothing is published.
 *
 * @param runId - The run's id.
 * @param sha - The pact version.
 * @param caseId - The interaction's case id.
 * @returns What replaying it showed, or the refusal (409 while the run is going).
 */
export async function rerunInteraction(runId: string, sha: string, caseId: string): Promise<LiveInteraction | CallFailure> {
  const answer = await send(`${LIVE_RUNS_PROXY}/${encodeURIComponent(runId)}/rerun`, json('POST', { pact_version_sha: sha, case_id: caseId }));
  if (!answer || answer.status >= 400) return failure(answer, 'The interaction could not be re-run');
  return readInteraction(answer.body.interaction);
}

/** A consumer's newest pact, as the upload dialog offers it. */
export interface ConsumerPact {
  consumer: string;
  consumerName: string;
  consumerVersion: string;
  sha: string;
}

/**
 * The provider's consumers and each one's newest pact (the Verification page's status read).
 *
 * @param provider - The provider's handle.
 * @returns The pacts, or the failure.
 */
export async function fetchConsumerPacts(provider: string): Promise<ConsumerPact[] | CallFailure> {
  const answer = await send(`/api/pact/pacticipants/${encodeURIComponent(provider)}/verification/status`);
  if (!answer || answer.status >= 400) return failure(answer, 'Could not read the provider’s pacts');
  const rows = Array.isArray(answer.body.pacts) ? (answer.body.pacts as Record<string, unknown>[]) : [];
  return rows
    .filter((row) => typeof row.consumer === 'string' && typeof row.pact_version_sha === 'string')
    .map((row) => ({
      consumer: String(row.consumer),
      consumerName: typeof row.consumer_name === 'string' && row.consumer_name ? row.consumer_name : String(row.consumer),
      consumerVersion: typeof row.consumer_version === 'string' ? row.consumer_version : '',
      sha: String(row.pact_version_sha),
    }));
}

/**
 * Upload a verifier's report as a verification result.
 *
 * @param body - `uploadBody(provider, form)`.
 * @returns What the server read, or its refusal with the reason and the pointer into the report.
 */
export async function uploadResults(body: Record<string, unknown>): Promise<UploadAnswer | UploadFailure> {
  const answer = await send(UPLOAD_PROXY, json('POST', body));
  if (!answer || answer.status >= 400) {
    const pointer = answer && typeof answer.body.pointer === 'string' ? answer.body.pointer : null;
    return { ...failure(answer, 'The report could not be uploaded'), pointer };
  }
  return readUploadAnswer(answer.body);
}
