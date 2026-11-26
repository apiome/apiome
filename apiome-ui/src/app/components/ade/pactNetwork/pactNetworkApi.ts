/**
 * Browser call for the **Network** page (PFX-5.3, #6947), through `/api/pact/*`.
 *
 * Throws REST's message on a failure, so the page can show it (a 403 reads "Permission denied").
 */

import type { PactNetwork } from '@lib/pact-network';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/**
 * The network of pacticipants connected to one.
 *
 * @param slug - The pacticipant's handle.
 * @returns The network.
 */
export async function fetchPactNetwork(slug: string): Promise<PactNetwork> {
  return readJson<PactNetwork>(
    await fetch(`/api/pact/pacticipants/${encodeURIComponent(slug)}/network`, {
      cache: 'no-store',
    }),
    'Could not load the network',
  );
}
