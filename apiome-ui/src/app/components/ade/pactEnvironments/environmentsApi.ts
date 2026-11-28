/**
 * Browser calls for the **Environments** pages (PFX-5.7, #6951), through `/api/pact/*`.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 404 names the unknown environment, pacticipant or version, a 400 the parameter).
 *
 * The writes of PFX-8.12 (#7309) — create, edit and delete an environment, record a deployment or a
 * release — answer the result or a {@link EnvironmentWriteFailure} with the proxy's status and, for
 * a "no" from can-i-deploy, its reasons, so the dialog can say what happened where it happened.
 *
 * PFX-8.13 (#7310) adds the board and the history reads, and the two endings: record an
 * undeployment and end support for a release.
 */

import {
  simulationParams,
  type HistoryPage,
  type Simulation,
  type SimulationForm,
  type Topology,
} from '@lib/pact-environments';
import {
  parseBrokerEnvironments,
  type BrokerEnvironment,
  type DeploymentBody,
  type EnvironmentBody,
  type ReleaseBody,
} from '@lib/pact-environment-writes';
import type { Board, EventsPage } from '@lib/pact-environment-board';
import type { SupportEndedBody, UndeploymentBody } from '@lib/pact-environment-endings';
import { readJson } from '../pactPacticipants/pacticipantsApi';

const BASE = '/api/pact';

/**
 * Every environment and what is deployed and released to it now.
 *
 * @returns The topology.
 */
export async function fetchTopology(): Promise<Topology> {
  const body = await readJson<Topology>(
    await fetch(`${BASE}/environment-topology`, { cache: 'no-store' }),
    'Could not load the environments',
  );
  return { environments: Array.isArray(body.environments) ? body.environments : [], truncated: Boolean(body.truncated) };
}

/**
 * The what-is-where board.
 *
 * @returns The board.
 */
export async function fetchBoard(): Promise<Board> {
  const body = await readJson<Board>(await fetch(`${BASE}/environment-board`, { cache: 'no-store' }), 'Could not load the board');
  return {
    ...body,
    environments: Array.isArray(body.environments) ? body.environments : [],
    rows: Array.isArray(body.rows) ? body.rows : [],
    truncated: Boolean(body.truncated),
  };
}

/**
 * One page of the environments' history (every environment, newest first).
 *
 * @param cursor - The previous page's `nextCursor`, or nothing for the first page.
 * @returns The page.
 */
export async function fetchEvents(cursor?: string | null): Promise<EventsPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  const body = await readJson<EventsPage>(
    await fetch(`${BASE}/environment-history${query}`, { cache: 'no-store' }),
    'Could not load the history',
  );
  return { events: Array.isArray(body.events) ? body.events : [], nextCursor: body.nextCursor ?? null };
}

/**
 * One page of an environment's deployment history.
 *
 * @param environment - The environment's name.
 * @param options - `pacticipant` narrows; `cursor` is the previous page's `nextCursor`.
 * @returns The page.
 */
export async function fetchHistory(
  environment: string,
  options: { pacticipant?: string | null; cursor?: string | null } = {},
): Promise<HistoryPage> {
  const query = new URLSearchParams();
  if (options.pacticipant) query.set('pacticipant', options.pacticipant);
  if (options.cursor) query.set('cursor', options.cursor);
  const rendered = query.toString();
  const body = await readJson<HistoryPage>(
    await fetch(`${BASE}/environments/${encodeURIComponent(environment)}/deployments${rendered ? `?${rendered}` : ''}`, {
      cache: 'no-store',
    }),
    'Could not load the deployment history',
  );
  return { ...body, deployments: Array.isArray(body.deployments) ? body.deployments : [] };
}

/**
 * Simulate deploying one version to an environment (nothing is recorded).
 *
 * @param environment - The environment's name.
 * @param form - The question (already checked with `simulationFormProblem`).
 * @returns The simulation.
 */
export async function fetchSimulation(environment: string, form: SimulationForm): Promise<Simulation> {
  const body = await readJson<Simulation>(
    await fetch(`${BASE}/environments/${encodeURIComponent(environment)}/simulate?${simulationParams(form).toString()}`, {
      cache: 'no-store',
    }),
    'Could not simulate the deployment',
  );
  return {
    ...body,
    impacts: Array.isArray(body.impacts) ? body.impacts : [],
    notChecked: Array.isArray(body.notChecked) ? body.notChecked : [],
    summary: body.summary ?? {},
  };
}

/** A refused write: the message, the status and — for a "no" from can-i-deploy — its reasons. */
export interface EnvironmentWriteFailure {
  error: string;
  status: number;
  reasons?: string[];
}

/**
 * Send one write through a proxy and read its answer.
 *
 * @param url - The proxy URL.
 * @param method - The method.
 * @param fallback - What to say when the failure carried no message.
 * @param body - The JSON body.
 * @returns The parsed body, or the failure.
 */
async function send<T>(url: string, method: string, fallback: string, body?: unknown): Promise<T | EnvironmentWriteFailure> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
  } catch {
    return { error: 'The Pact Broker could not be reached. Try again shortly.', status: 503 };
  }
  const parsed = ((await response.json().catch(() => ({}))) ?? {}) as Record<string, unknown>;
  if (!response.ok) {
    const error = typeof parsed.error === 'string' && parsed.error ? parsed.error : fallback;
    const reasons = Array.isArray(parsed.reasons) ? parsed.reasons.filter((line): line is string => typeof line === 'string') : undefined;
    return { error, status: response.status, ...(reasons ? { reasons } : {}) };
  }
  return parsed as T;
}

/**
 * What a successful environment, deployment or release write answers (the fields the page reads).
 * No index signature and no `error` key, so `'error' in answer` tells a failure apart.
 */
export interface WriteAnswer {
  uuid?: string;
  name?: string;
}

/** An environment's path below `/api/pact`. */
function environmentBase(name: string): string {
  return `${BASE}/environments/${encodeURIComponent(name)}`;
}

/**
 * Every environment with its contacts (for the Edit dialog), by name.
 *
 * @returns The environments.
 */
export async function fetchBrokerEnvironments(): Promise<BrokerEnvironment[]> {
  const body = await readJson<unknown>(await fetch(`${BASE}/environments`, { cache: 'no-store' }), 'Could not load the environments');
  return parseBrokerEnvironments(body);
}

/**
 * Create an environment.
 *
 * @param body - The checked body.
 * @returns REST's environment, or the failure (409 for a taken name).
 */
export function createEnvironment(body: EnvironmentBody) {
  return send<WriteAnswer>(`${BASE}/environments`, 'POST', 'Could not create the environment', body);
}

/**
 * Replace an environment's fields.
 *
 * @param name - Its current name.
 * @param body - The checked body.
 * @returns REST's environment, or the failure.
 */
export function updateEnvironment(name: string, body: EnvironmentBody) {
  return send<WriteAnswer>(environmentBase(name), 'PUT', 'Could not save the environment', body);
}

/**
 * Delete an environment (refused while versions run there).
 *
 * @param name - Its name.
 * @returns `{ deleted: true }`, or the failure.
 */
export function deleteEnvironment(name: string) {
  return send<{ deleted: boolean }>(environmentBase(name), 'DELETE', 'Could not delete the environment');
}

/** What recording a deployment answers: REST's deployment and the verdict it was recorded over. */
export interface RecordedDeployment extends WriteAnswer {
  verdict?: 'yes' | 'no';
}

/**
 * Record a deployment; the proxy asks can-i-deploy first.
 *
 * @param environment - The environment's name.
 * @param body - The checked body.
 * @returns The deployment, or the failure (409 with `reasons` for a "no" without the tick).
 */
export function recordDeployment(environment: string, body: DeploymentBody) {
  return send<RecordedDeployment>(`${environmentBase(environment)}/deployments`, 'POST', 'Could not record the deployment', body);
}

/**
 * Record a release.
 *
 * @param environment - The environment's name.
 * @param body - The checked body.
 * @returns REST's release, or the failure.
 */
export function recordRelease(environment: string, body: ReleaseBody) {
  return send<WriteAnswer>(`${environmentBase(environment)}/releases`, 'POST', 'Could not record the release', body);
}

/** What recording an undeployment answers: the deployments it ended. */
export interface RecordedUndeployment {
  undeployed: { uuid: string; version: string; applicationInstance: string | null }[];
}

/**
 * Record an undeployment (the deployment in that instance, or the unnamed one).
 *
 * @param environment - The environment's name.
 * @param body - The checked body.
 * @returns The deployments ended, or the failure (404 saying what is deployed when nothing matches).
 */
export function recordUndeployment(environment: string, body: UndeploymentBody) {
  return send<RecordedUndeployment>(`${environmentBase(environment)}/undeployments`, 'POST', 'Could not record the undeployment', body);
}

/**
 * End support for a released version.
 *
 * @param environment - The environment's name.
 * @param body - The checked body.
 * @returns How many releases were ended, or the failure.
 */
export function endSupport(environment: string, body: SupportEndedBody) {
  return send<{ ended: number }>(`${environmentBase(environment)}/support-ended`, 'POST', 'Could not end support', body);
}
