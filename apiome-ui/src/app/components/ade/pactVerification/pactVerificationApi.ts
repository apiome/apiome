/**
 * Browser calls for the **Verification** pages (PFX-5.5, #6949), through `/api/pact/*` and the
 * verification-target proxy.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 409 says the pair is already running).
 */

import {
  targetOptions,
  type ConsoleRunResponse,
  type ResultDetail,
  type ResultHistoryPage,
  type RunBody,
  type TargetOption,
  type VerificationStatus,
} from '@lib/pact-verification';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/** A provider's verification proxies below `/api/pact`. */
function base(provider: string): string {
  return `/api/pact/pacticipants/${encodeURIComponent(provider)}/verification`;
}

/**
 * Where the provider's verification stands.
 *
 * @param provider - The provider's handle.
 * @returns The status.
 */
export async function fetchVerificationStatus(provider: string): Promise<VerificationStatus> {
  return readJson<VerificationStatus>(
    await fetch(`${base(provider)}/status`, { cache: 'no-store' }),
    'Could not load the verification status',
  );
}

/**
 * One page of the provider's history.
 *
 * @param provider - The provider's handle.
 * @param options - `consumer` narrows; `cursor` is the previous page's `next_cursor`.
 * @returns The page.
 */
export async function fetchVerificationHistory(
  provider: string,
  options: { consumer?: string | null; cursor?: string | null } = {},
): Promise<ResultHistoryPage> {
  const query = new URLSearchParams();
  if (options.consumer) query.set('consumer', options.consumer);
  if (options.cursor) query.set('cursor', options.cursor);
  const rendered = query.toString();
  return readJson<ResultHistoryPage>(
    await fetch(`${base(provider)}/results${rendered ? `?${rendered}` : ''}`, { cache: 'no-store' }),
    'Could not load the verification history',
  );
}

/**
 * One result in full.
 *
 * @param provider - The provider's handle.
 * @param resultId - The result's id.
 * @returns The result.
 */
export async function fetchVerificationResult(provider: string, resultId: string): Promise<ResultDetail> {
  return readJson<ResultDetail>(
    await fetch(`${base(provider)}/results/${encodeURIComponent(resultId)}`, { cache: 'no-store' }),
    'Could not load the verification result',
  );
}

/**
 * Re-run one pact's verification.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @param sha - The pact version.
 * @param body - The target and, optionally, the provider version and branch.
 * @returns The run.
 */
export async function rerunVerification(
  provider: string,
  consumer: string,
  sha: string,
  body: RunBody,
): Promise<ConsoleRunResponse> {
  const query = new URLSearchParams({ consumer, sha });
  return readJson<ConsoleRunResponse>(
    await fetch(`${base(provider)}/reverify?${query.toString()}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'The verification could not be run',
  );
}

/**
 * Verify every stale pact of the provider.
 *
 * @param provider - The provider's handle.
 * @param body - The target and the provider version.
 * @returns The run.
 */
export async function verifyStale(provider: string, body: RunBody): Promise<ConsoleRunResponse> {
  return readJson<ConsoleRunResponse>(
    await fetch(`${base(provider)}/verify-stale`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'The stale pacts could not be verified',
  );
}

/**
 * The workspace's verification targets, for the run form.
 *
 * @returns The targets, enabled first.
 */
export async function fetchTargetOptions(): Promise<TargetOption[]> {
  const body = await readJson<unknown>(
    await fetch('/api/verification-targets', { cache: 'no-store' }),
    'Could not load the verification targets',
  );
  return targetOptions(body);
}
