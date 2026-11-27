/**
 * The **Publish a provider contract** page's calls (PFX-8.6, #7303). Each goes through an `/api/*`
 * proxy as the signed-in user; tenancy and permissions are REST's. None throws: every answer is shown
 * beside what it is about.
 */

import {
  readCheckAnswer,
  readPublishAnswer,
  type CheckAnswer,
  type ContractRequestBody,
  type PublishAnswer,
} from '@lib/pact-provider-contract';

/** A refusal: the message, REST's code when it sent one, and the status. */
export interface CallFailure {
  error: string;
  status: number;
  code?: string;
}

/** A version of a project, as the Version select lists it. */
export interface VersionChoice {
  label: string;
  published: boolean;
}

/** A verification target, as **Run it now** lists it. */
export interface TargetChoice {
  slug: string;
  name: string;
  baseUrl: string;
  environment: string;
}

/** A recorded contract-test run, as **Reuse** lists it. */
export interface ReportChoice {
  id: string;
  createdAt: string | null;
  outcome: string;
  cases: number;
  failed: number;
  target: string;
}

const UNREACHABLE = 'The Pact Broker could not be reached. Try again shortly.';

/**
 * Send one request and read its JSON.
 *
 * @param url - The proxy URL.
 * @param init - Fetch options.
 * @returns The status and body, or `null` offline.
 */
async function send(url: string, init?: RequestInit): Promise<{ status: number; body: Record<string, unknown> } | null> {
  try {
    const response = await fetch(url, init);
    const body = (await response.json().catch(() => ({}))) as unknown;
    return { status: response.status, body: body && typeof body === 'object' ? (body as Record<string, unknown>) : {} };
  } catch {
    return null;
  }
}

/** The failure of an answer. */
function failure(answer: { status: number; body: Record<string, unknown> }, fallback: string): CallFailure {
  const error = typeof answer.body.error === 'string' && answer.body.error ? answer.body.error : `${fallback} (${answer.status}).`;
  return { error, status: answer.status, ...(typeof answer.body.code === 'string' ? { code: answer.body.code } : {}) };
}

/** POST a JSON body. */
function post(url: string, body: unknown): Promise<{ status: number; body: Record<string, unknown> } | null> {
  return send(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/**
 * Check the contract (**Compare only** and the live aside): nothing is stored.
 *
 * @param body - `checkRequest(form)`.
 * @returns What a publish would record, or the refusal.
 */
export async function checkProviderContract(body: ContractRequestBody): Promise<CheckAnswer | CallFailure> {
  const answer = await post('/api/pact/provider-contracts/check', body);
  if (!answer) return { error: UNREACHABLE, status: 503 };
  if (answer.status >= 400) return failure(answer, 'The check was refused');
  return readCheckAnswer(answer.body);
}

/**
 * Publish the contract (after **Run it now**, only when the run passed).
 *
 * @param body - `publishRequest(form, fetched)`.
 * @returns What was published (or why nothing was), or the refusal.
 */
export async function publishProviderContract(body: ContractRequestBody): Promise<PublishAnswer | CallFailure> {
  const answer = await post('/api/pact/provider-contracts', body);
  if (!answer) return { error: UNREACHABLE, status: 503 };
  if (answer.status >= 400) return failure(answer, 'The Pact Broker refused it');
  return readPublishAnswer(answer.body);
}

/**
 * A project's versions, newest first.
 *
 * @param projectId - The project's id.
 * @returns The versions, or the failure.
 */
export async function fetchVersions(projectId: string): Promise<VersionChoice[] | CallFailure> {
  const answer = await send(`/api/versions?projectId=${encodeURIComponent(projectId)}`);
  if (!answer) return { error: 'The versions could not be read. Try again shortly.', status: 503 };
  if (answer.status >= 400 || !Array.isArray(answer.body.versions)) return failure(answer, 'Could not read the versions');
  return (answer.body.versions as Record<string, unknown>[])
    .filter((row) => typeof row.version_id === 'string' && row.version_id && !row.deleted_at)
    .map((row) => ({ label: String(row.version_id), published: row.published === true }));
}

/**
 * The workspace's verification targets.
 *
 * @returns The targets, or the failure.
 */
export async function fetchTargets(): Promise<TargetChoice[] | CallFailure> {
  const answer = await send('/api/verification-targets');
  if (!answer) return { error: 'The verification targets could not be read. Try again shortly.', status: 503 };
  if (answer.status >= 400 || !Array.isArray(answer.body.targets)) return failure(answer, 'Could not read the verification targets');
  return (answer.body.targets as Record<string, unknown>[])
    .filter((row) => typeof row.slug === 'string')
    .map((row) => ({
      slug: String(row.slug),
      name: typeof row.name === 'string' && row.name ? row.name : String(row.slug),
      baseUrl: typeof row.base_url === 'string' ? row.base_url : '',
      environment: typeof row.environment === 'string' ? row.environment : '',
    }));
}

/**
 * A version's recorded contract-test runs, newest first.
 *
 * @param project - The project's handle.
 * @param version - The version label.
 * @returns The runs, or the failure.
 */
export async function fetchReports(project: string, version: string): Promise<ReportChoice[] | CallFailure> {
  const answer = await send(`/api/pact/provider-contracts/reports?${new URLSearchParams({ project, version }).toString()}`);
  if (!answer) return { error: 'The contract-test runs could not be read. Try again shortly.', status: 503 };
  // REST answers this list as a bare array.
  const rows: unknown = answer.body;
  if (answer.status >= 400 || !Array.isArray(rows)) return failure(answer, 'Could not read the contract-test runs');
  return (rows as Record<string, unknown>[])
    .filter((row) => typeof row.id === 'string')
    .map((row) => ({
      id: String(row.id),
      createdAt: typeof row.created_at === 'string' ? row.created_at : null,
      outcome: typeof row.outcome === 'string' ? row.outcome : 'errored',
      cases: typeof row.cases_total === 'number' ? row.cases_total : 0,
      failed: typeof row.cases_failed === 'number' ? row.cases_failed : 0,
      target: typeof row.target_slug === 'string' ? row.target_slug : '',
    }));
}

/**
 * How a recorded run reads in the Run select, e.g. `2026-11-26 16:40 · staging · 412 checks · 0 failed · passed`.
 *
 * @param report - The run.
 * @returns The label.
 */
export function reportLabel(report: ReportChoice): string {
  const when = report.createdAt ? report.createdAt.replace('T', ' ').slice(0, 16) : 'Unknown time';
  return `${when} · ${report.target || 'a target'} · ${report.cases} checks · ${report.failed} failed · ${report.outcome}`;
}
