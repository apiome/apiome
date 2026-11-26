/**
 * Browser calls for the **Health** pages and the Verification page's health badges (PFX-6.3,
 * #6955), through the `/api/pact/health*` proxies.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 404 names the missing pacticipant or pair).
 */

import type { HealthOverview, HealthWindow, PairHealthDetail } from '@lib/pact-health';
import { readJson } from '../pactPacticipants/pacticipantsApi';

const HEALTH = '/api/pact/health';

/**
 * The workspace's (or one provider's) contract health.
 *
 * @param filters - The window, and optionally a state and a provider.
 * @returns The overview.
 */
export async function fetchHealth(
  filters: { window?: HealthWindow; state?: string | null; provider?: string | null } = {},
): Promise<HealthOverview> {
  const query = new URLSearchParams();
  if (filters.window) query.set('window', filters.window);
  if (filters.state) query.set('state', filters.state);
  if (filters.provider) query.set('provider', filters.provider);
  const rendered = query.toString();
  return readJson<HealthOverview>(
    await fetch(rendered ? `${HEALTH}?${rendered}` : HEALTH, { cache: 'no-store' }),
    'Could not load the contract health',
  );
}

/**
 * One pair's health and trend.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @param window - The window.
 * @returns The detail.
 */
export async function fetchPairHealth(
  provider: string,
  consumer: string,
  window: HealthWindow,
): Promise<PairHealthDetail> {
  const path = `${HEALTH}/${encodeURIComponent(provider)}/${encodeURIComponent(consumer)}?window=${window}`;
  return readJson<PairHealthDetail>(
    await fetch(path, { cache: 'no-store' }),
    "Could not load the pair's health",
  );
}
