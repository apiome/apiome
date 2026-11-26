/**
 * Browser calls for the **Environments** pages (PFX-5.7, #6951), through `/api/pact/*`.
 *
 * Each throws REST's message on a failure, so the page can show it (a 403 reads "Permission
 * denied", a 404 names the unknown environment, pacticipant or version, a 400 the parameter).
 */

import {
  simulationParams,
  type HistoryPage,
  type Simulation,
  type SimulationForm,
  type Topology,
} from '@lib/pact-environments';
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
