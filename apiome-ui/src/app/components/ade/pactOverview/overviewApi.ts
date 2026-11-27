/**
 * Browser calls for the **Contracts** landing (PFX-8.1, #7298), through `/api/pact/integrations`.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied").
 */

import { integrationsQuery, type OverviewQuery, type PactIntegrationsPage } from '@lib/pact-overview';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/**
 * One page of the workspace's integrations, with the strip's counts.
 *
 * @param state - The search, filter chip and page.
 * @returns The page.
 */
export async function fetchIntegrations(
  state: Pick<OverviewQuery, 'q' | 'filter' | 'page'>,
): Promise<PactIntegrationsPage> {
  return readJson<PactIntegrationsPage>(
    await fetch(`/api/pact/integrations?${integrationsQuery(state)}`, { cache: 'no-store' }),
    'Could not load the integrations',
  );
}
