/**
 * Browser calls for the provider-state registry (PFX-3.3, #6933), through `/api/pact-provider-states`.
 */

import type { ProviderOption, ProviderState, StateCheckResponse } from '@lib/pact-provider-states';

/**
 * Read a proxy response, or throw REST's message.
 *
 * @param response - The proxy's answer.
 * @param fallback - What to say when the failure carried no message.
 * @returns The parsed body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as unknown;
  if (!response.ok) {
    const error = body && typeof body === 'object' ? (body as Record<string, unknown>).error : undefined;
    throw new Error(typeof error === 'string' && error ? error : fallback);
  }
  return body as T;
}

/**
 * The workspace's pacticipants, by handle — the providers the page can pick.
 *
 * @returns The providers; always an array.
 */
export async function fetchProviders(): Promise<ProviderOption[]> {
  const body = await readJson<{ pacticipants?: ProviderOption[] }>(
    await fetch('/api/pact-provider-states', { cache: 'no-store' }),
    'Could not load the providers',
  );
  return Array.isArray(body.pacticipants) ? body.pacticipants.map(({ slug, name }) => ({ slug, name })) : [];
}

/**
 * A provider's registered states.
 *
 * @param provider - The provider's handle.
 * @returns The states; always an array.
 */
export async function fetchProviderStates(provider: string): Promise<ProviderState[]> {
  const body = await readJson<ProviderState[]>(
    await fetch(`/api/pact-provider-states/${encodeURIComponent(provider)}`, { cache: 'no-store' }),
    'Could not load the provider states',
  );
  return Array.isArray(body) ? body : [];
}

/**
 * Check the provider's default pact selection against its states.
 *
 * @param provider - The provider's handle.
 * @returns The check; `states` and `unused` are always arrays.
 */
export async function checkProviderStates(provider: string): Promise<StateCheckResponse> {
  const body = await readJson<StateCheckResponse>(
    await fetch(`/api/pact-provider-states/${encodeURIComponent(provider)}/check`, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }),
    'Could not check the provider states',
  );
  return {
    ...body,
    states: Array.isArray(body.states) ? body.states : [],
    unused: Array.isArray(body.unused) ? body.unused : [],
  };
}
