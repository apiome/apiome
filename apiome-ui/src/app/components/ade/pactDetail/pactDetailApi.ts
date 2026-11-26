/**
 * Browser calls for the **Pact** page and a pacticipant's **Pacts** section (PFX-5.2, #6946),
 * through `/api/pact/*`.
 *
 * Every call throws REST's message on a failure, so the page can show it (a 404 reads "No pact
 * found", a 403 "Permission denied"). Matrix bodies are parsed into the page's shapes here.
 */

import {
  parsePacticipantPacts,
  parsePact,
  parsePairHistory,
  type PacticipantPacts,
  type PactHistory,
  type PactView,
  type PreviousPactResponse,
} from '@lib/pact-detail';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/** Where the proxies live. */
const BASE = '/api/pact';

/** An integration's path below `/api/pact`. */
function pairBase(provider: string, consumer: string): string {
  return `${BASE}/pacts/${encodeURIComponent(provider)}/${encodeURIComponent(consumer)}`;
}

/** `?version=…`, or nothing for the latest pact. */
function versionQuery(version: string | null | undefined): string {
  return version ? `?version=${encodeURIComponent(version)}` : '';
}

/** A pact as read: the page's view of it, and the document as published. */
export interface LoadedPact {
  view: PactView;
  document: unknown;
}

/**
 * One pact of an integration.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @param version - A consumer version; the latest pact when absent.
 * @returns The pact, or `null` when there is none (REST's 404: no such pact or pacticipant).
 */
export async function fetchPact(
  provider: string,
  consumer: string,
  version?: string | null,
): Promise<LoadedPact | null> {
  const response = await fetch(`${pairBase(provider, consumer)}${versionQuery(version)}`, {
    cache: 'no-store',
  });
  if (response.status === 404) return null;
  const document = await readJson<unknown>(response, 'Could not load the pact');
  return { view: parsePact(document), document };
}

/**
 * An integration's consumer versions, newest first, with their verification results.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @returns The history.
 */
export async function fetchPactHistory(provider: string, consumer: string): Promise<PactHistory> {
  const body = await readJson<unknown>(
    await fetch(`${pairBase(provider, consumer)}/history`, { cache: 'no-store' }),
    'Could not load the history',
  );
  return parsePairHistory(body, consumer, provider);
}

/**
 * The previous different pact of a consumer version.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @param version - The consumer version; the latest pact when absent.
 * @returns The outcome, and the previous pact when found.
 */
export async function fetchPreviousPact(
  provider: string,
  consumer: string,
  version?: string | null,
): Promise<PreviousPactResponse> {
  return readJson<PreviousPactResponse>(
    await fetch(`${pairBase(provider, consumer)}/previous${versionQuery(version)}`, {
      cache: 'no-store',
    }),
    'Could not load the previous pact',
  );
}

/**
 * The integrations a pacticipant is in, with each one's newest pact.
 *
 * @param slug - The pacticipant's handle.
 * @returns The integrations.
 */
export async function fetchPacticipantPacts(slug: string): Promise<PacticipantPacts> {
  const body = await readJson<unknown>(
    await fetch(`${BASE}/pacticipants/${encodeURIComponent(slug)}/pacts`, { cache: 'no-store' }),
    'Could not load the pacts',
  );
  return parsePacticipantPacts(body);
}
