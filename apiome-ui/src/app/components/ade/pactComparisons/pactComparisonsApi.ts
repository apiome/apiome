/**
 * Browser calls for bi-directional comparisons (PFX-2.5, #6929), through `/api/pact-comparisons`.
 */

import type { ComparisonFidelityReport, ComparisonListResponse } from '@lib/pact-comparisons';

/**
 * Read a proxy response, or throw REST's message.
 *
 * @param response - The proxy's answer.
 * @param fallback - What to say when the failure carried no message.
 * @returns The parsed body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as unknown as T;
}

/**
 * The workspace's most recent bi-directional comparisons, newest first.
 *
 * @returns The list; `comparisons` is always an array.
 */
export async function fetchPactComparisons(): Promise<ComparisonListResponse> {
  const body = await readJson<ComparisonListResponse>(
    await fetch('/api/pact-comparisons', { cache: 'no-store' }),
    'Could not load the comparisons'
  );
  return { ...body, comparisons: Array.isArray(body.comparisons) ? body.comparisons : [] };
}

/**
 * One result's fidelity report.
 *
 * @param id - The verification result id.
 * @returns The report; `interactions` is always an array.
 */
export async function fetchComparisonFidelity(id: string): Promise<ComparisonFidelityReport> {
  const body = await readJson<ComparisonFidelityReport>(
    await fetch(`/api/pact-comparisons/${encodeURIComponent(id)}/fidelity`, { cache: 'no-store' }),
    'Could not load the fidelity report'
  );
  return { ...body, interactions: Array.isArray(body.interactions) ? body.interactions : [] };
}
