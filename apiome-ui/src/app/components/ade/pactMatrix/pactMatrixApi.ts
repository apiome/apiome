/**
 * Browser calls for the **Matrix** and **Can I deploy** pages (PFX-5.4, #6948), through
 * `/api/pact/*`.
 *
 * Every call throws REST's message on a failure (a 400 names the parameter, a 403 reads
 * "Permission denied"), so the page can show it.
 */

import {
  canIDeployParams,
  matrixQueryParams,
  parseMatrixAnswer,
  type CanIDeployForm,
  type MatrixAnswer,
  type MatrixQuery,
} from '@lib/pact-matrix';
import { readJson } from '../pactPacticipants/pacticipantsApi';

/** Where the proxies live. */
const BASE = '/api/pact';

/**
 * Ask the matrix.
 *
 * @param query - The builder's query (already checked with `matrixQueryProblem`).
 * @returns The answer.
 */
export async function fetchMatrix(query: MatrixQuery): Promise<MatrixAnswer> {
  const body = await readJson<unknown>(
    await fetch(`${BASE}/matrix?${matrixQueryParams(query).toString()}`, { cache: 'no-store' }),
    'Could not read the matrix',
  );
  return parseMatrixAnswer(body);
}

/**
 * Ask whether a version can be deployed.
 *
 * @param form - The form (complete).
 * @returns The answer.
 */
export async function fetchCanIDeploy(form: CanIDeployForm): Promise<MatrixAnswer> {
  const body = await readJson<unknown>(
    await fetch(`${BASE}/can-i-deploy?${canIDeployParams(form).toString()}`, { cache: 'no-store' }),
    'Could not ask can-i-deploy',
  );
  return parseMatrixAnswer(body);
}

/**
 * The names of the workspace's broker environments, by name.
 *
 * @returns The names.
 */
export async function fetchEnvironmentNames(): Promise<string[]> {
  const body = await readJson<Record<string, unknown>>(
    await fetch(`${BASE}/environments`, { cache: 'no-store' }),
    'Could not load the environments',
  );
  const embedded = body?._embedded as Record<string, unknown> | undefined;
  const list = Array.isArray(embedded?.environments) ? (embedded.environments as unknown[]) : [];
  return list
    .map((entry) =>
      entry && typeof entry === 'object' ? (entry as Record<string, unknown>).name : null,
    )
    .filter((name): name is string => typeof name === 'string' && name.length > 0);
}
