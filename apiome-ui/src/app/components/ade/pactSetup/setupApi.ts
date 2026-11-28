/**
 * Browser calls for **Set up contracts** (PFX-8.20, #7317), through the `/api/pact/*` proxies. The
 * page's own three proxies (`/api/pact/setup*`) are here; the sections' writes use the routes that
 * already exist (pacticipants, environments, provider-contract sources). Each call throws REST's
 * message on a failure, so the section can show it.
 */

import {
  readSetupState,
  type PullRequestResult,
  type PullRequestsBody,
  type SecretsResult,
  type SetupSaveBody,
  type SetupState,
} from '@lib/pact-setup';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/** JSON request options for a write. */
function send(method: 'PUT' | 'POST', body: unknown): RequestInit {
  return { method, cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

/** REST's answer as the page's state, or a thrown message when it is not one. */
function asState(raw: unknown): SetupState {
  const state = readSetupState(raw);
  if (!state) throw new Error('The set-up answered in a shape this page does not know. Reload the page.');
  return state;
}

/** The six sections and everything they are drawn from. */
export async function fetchSetup(): Promise<SetupState> {
  return asState(await readJson<unknown>(await fetch('/api/pact/setup', { cache: 'no-store' }), 'Could not load the set-up'));
}

/**
 * Save progress: a mark, the first-pact path, or the CI key just created.
 *
 * @param body - Only what changes.
 * @returns The set-up after the change.
 */
export async function saveSetup(body: SetupSaveBody): Promise<SetupState> {
  return asState(await readJson<unknown>(await fetch('/api/pact/setup', send('PUT', body)), 'Could not save the set-up'));
}

/**
 * Write the two secrets into repositories.
 *
 * @param repositoryIds - The repositories.
 * @param token - The API key, as created a moment ago or pasted.
 * @returns One result per repository.
 */
export async function writeSecrets(repositoryIds: string[], token: string): Promise<SecretsResult[]> {
  const body = await readJson<{ results?: SecretsResult[] }>(
    await fetch('/api/pact/setup/github/secrets', send('POST', { repository_ids: repositoryIds, token })),
    'Could not write the secrets',
  );
  return Array.isArray(body.results) ? body.results : [];
}

/**
 * Open the pull requests, or with `preview` only read the workflow each would add.
 *
 * @param body - The repositories with their pacticipants, the environment and the steps.
 * @returns One result per repository, each with the workflow's text.
 */
export async function openPullRequests(body: PullRequestsBody): Promise<PullRequestResult[]> {
  const answer = await readJson<{ results?: PullRequestResult[] }>(
    await fetch('/api/pact/setup/github/pull-requests', send('POST', body)),
    body.preview ? 'Could not read the workflow' : 'Could not open the pull requests',
  );
  return Array.isArray(answer.results) ? answer.results : [];
}

/**
 * Create one environment through the existing route.
 *
 * @param body - What `POST /api/pact/environments` takes.
 */
export async function createEnvironment(body: unknown): Promise<void> {
  await readJson<unknown>(await fetch('/api/pact/environments', send('POST', body)), 'Could not create the environment');
}

/**
 * Turn on "each published version of the project is the provider contract" for a provider, through
 * the existing route (the rest of its sources is kept).
 *
 * @param provider - The provider's name.
 */
export async function turnOnSpecAsContract(provider: string): Promise<void> {
  await readJson<unknown>(
    await fetch('/api/pact/provider-contracts/sources', send('PUT', { provider, onProjectPublish: true })),
    'Could not turn on the provider contract',
  );
}
