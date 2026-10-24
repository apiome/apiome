/**
 * Browser calls for the tenant two-factor policy (TFA-1.3, #5657), through `/api/two-factor-policy`.
 */

import type { TwoFactorPolicy, TwoFactorPolicyChange } from '@lib/two-factor-policy';

/**
 * Parse a proxy answer, throwing REST's message (or `fallback`) on failure.
 *
 * @param response - The proxy's answer.
 * @param fallback - The message when REST gave none.
 * @returns The JSON body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/**
 * The current tenant's two-factor policy.
 *
 * @returns The policy with its compliance counts.
 */
export async function fetchTwoFactorPolicy(): Promise<TwoFactorPolicy> {
  return readJson<TwoFactorPolicy>(await fetch('/api/two-factor-policy'), 'Could not load the two-factor policy');
}

/**
 * Change the current tenant's two-factor policy.
 *
 * @param change - The requirement and/or the grace period.
 * @returns The policy after the change.
 */
export async function saveTwoFactorPolicy(change: TwoFactorPolicyChange): Promise<TwoFactorPolicy> {
  const response = await fetch('/api/two-factor-policy', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  });
  return readJson<TwoFactorPolicy>(response, 'Could not save the two-factor policy');
}
