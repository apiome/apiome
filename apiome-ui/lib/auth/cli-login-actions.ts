'use server';

/**
 * Server actions behind the `apiome login` approve page (#5501).
 *
 * Each action reads the caller's session on the server, signs a short-lived Bearer JWT for
 * apiome-rest (`createRestAuthHeaders`) and calls `/v1/cli/login/requests/{code}…`. Nothing the
 * client sends identifies the user: only the code (and, to approve, a workspace slug) crosses the
 * wire, and apiome-rest checks membership and `api_keys:create` itself.
 */

import { getAuthSession } from './server-session';
import { normalizeCliUserCode, type CliLoginRequest } from './cli-login';
import { createRestAuthHeaders, REST_API_BASE_URL } from '../rest-auth';
import { restErrorMessage } from '../rest-error-message';

/** The outcome of an action: data, or why not (`signed-out`, `not-found`, `forbidden`, `failed`). */
export type CliLoginActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; reason: 'signed-out' | 'not-found' | 'forbidden' | 'failed'; message: string };

/** What approve and deny return. */
export interface CliLoginDecision {
  user_code: string;
  status: string;
  tenant_slug?: string | null;
}

const NOT_FOUND_MESSAGE =
  'This code is not waiting for approval. It may have expired (codes last 10 minutes), been used, or been typed wrong. Run `apiome login` again for a new one.';

/**
 * Call apiome-rest as the signed-in user.
 *
 * @param method HTTP method.
 * @param code The code from the page (normalized here).
 * @param suffix Path after the code (`''`, `/approve`, `/deny`).
 * @param body JSON body, if any.
 * @returns The parsed response, or a reason.
 */
async function callCliLogin<T>(
  method: 'GET' | 'POST',
  code: unknown,
  suffix: '' | '/approve' | '/deny',
  body?: unknown
): Promise<CliLoginActionResult<T>> {
  const session = await getAuthSession();
  const user = session?.user as { user_id?: string; email?: string | null; name?: string | null } | undefined;
  if (!user?.user_id) {
    return { ok: false, reason: 'signed-out', message: 'Sign in to approve this login.' };
  }
  const canonical = normalizeCliUserCode(code);
  if (!canonical) return { ok: false, reason: 'not-found', message: NOT_FOUND_MESSAGE };

  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/cli/login/requests/${encodeURIComponent(canonical)}${suffix}`,
      {
        method,
        headers: createRestAuthHeaders({ user_id: user.user_id, email: user.email, name: user.name }),
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
      }
    );
    const payload = await response.json().catch(() => null);
    if (response.ok) return { ok: true, data: payload as T };
    if (response.status === 404) return { ok: false, reason: 'not-found', message: NOT_FOUND_MESSAGE };
    if (response.status === 401) {
      return { ok: false, reason: 'signed-out', message: 'Your session ended. Sign in again.' };
    }
    if (response.status === 403) {
      return { ok: false, reason: 'forbidden', message: restErrorMessage(payload) };
    }
    return { ok: false, reason: 'failed', message: restErrorMessage(payload) };
  } catch {
    return { ok: false, reason: 'failed', message: 'Apiome could not be reached. Try again.' };
  }
}

/**
 * Read a pending login and the caller's workspaces.
 *
 * @param code The code shown in the terminal.
 * @returns The login, or a reason.
 */
export async function getCliLoginRequest(code: unknown): Promise<CliLoginActionResult<CliLoginRequest>> {
  return callCliLogin<CliLoginRequest>('GET', code, '');
}

/**
 * Approve a pending login for one workspace.
 *
 * @param code The code shown in the terminal.
 * @param tenantSlug The workspace the CLI's key will belong to.
 * @returns The decision, or a reason (`forbidden` without `api_keys:create` there).
 */
export async function approveCliLogin(
  code: unknown,
  tenantSlug: unknown
): Promise<CliLoginActionResult<CliLoginDecision>> {
  if (typeof tenantSlug !== 'string' || !tenantSlug.trim()) {
    return { ok: false, reason: 'failed', message: 'Choose a workspace.' };
  }
  return callCliLogin<CliLoginDecision>('POST', code, '/approve', { tenant_slug: tenantSlug.trim() });
}

/**
 * Deny a pending login.
 *
 * @param code The code shown in the terminal.
 * @returns The decision, or a reason.
 */
export async function denyCliLogin(code: unknown): Promise<CliLoginActionResult<CliLoginDecision>> {
  return callCliLogin<CliLoginDecision>('POST', code, '/deny');
}
