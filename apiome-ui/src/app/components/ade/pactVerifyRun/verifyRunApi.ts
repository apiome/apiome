/**
 * The **Run a verification** page's calls (PFX-8.8, #7305). Each goes through an `/api/*` proxy as
 * the signed-in user; tenancy and permissions are REST's. None throws: every answer is shown beside
 * what it is about.
 */

import type { Cadence } from '@lib/pact-remediation';
import {
  VERIFY_PREVIEW_PROXY,
  VERIFY_RUN_PROXY,
  readPreview,
  readRun,
  readTargets,
  type VerifyPreview,
  type VerifyRunAnswer,
  type VerifyTarget,
} from '@lib/pact-verify-run';

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
 * Run the hosted verifier.
 *
 * @param provider - The provider's handle.
 * @param body - `verifyBody(form)`.
 * @returns The run, or the refusal (with REST's reason, e.g. a production target and mutating requests).
 */
export async function runVerification(provider: string, body: Record<string, unknown>): Promise<VerifyRunAnswer | CallFailure> {
  const answer = await send(VERIFY_RUN_PROXY, json('POST', { provider, body }));
  if (!answer || answer.status >= 400) return failure(answer, 'The verification could not start');
  return readRun(answer.body);
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
