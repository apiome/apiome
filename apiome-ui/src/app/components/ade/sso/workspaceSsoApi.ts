/**
 * Client transport for Workspace → Single sign-on (EID-1.2, #5012).
 *
 * The page talks to the `/api/workspace-sso` proxy, which forwards to the REST layer's
 * `/v1/tenants/{slug}/sso/providers`. The tenant slug is resolved server-side from the session, so
 * the browser never names a workspace. A refusal arrives as `{ success: false, error, code? }`
 * with REST's status; it is thrown as a {@link WorkspaceSsoError} that keeps the stable `sso-*`
 * code beside the message.
 */

import type { SsoDomainVerifyResult, WorkspaceSsoProvider } from '@lib/workspace-sso';

/** The proxy the page reads from and writes to. */
export const WORKSPACE_SSO_URL = '/api/workspace-sso';

/** A refused request: REST's message, its stable `sso-*` code when it has one, and the status. */
export class WorkspaceSsoError extends Error {
  readonly code: string | undefined;
  readonly status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'WorkspaceSsoError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Call the proxy.
 *
 * @param path Sub-path under `/api/workspace-sso`, already encoded ('' for the collection).
 * @param init The method and an optional JSON body. The body may carry a write-only secret; it is
 *   never logged.
 * @returns The parsed response.
 * @throws WorkspaceSsoError When the request was refused or the proxy could not be reached.
 */
export async function workspaceSsoApi<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${WORKSPACE_SSO_URL}${path}`, {
      method: init.method ?? 'GET',
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: 'no-store',
    });
  } catch {
    throw new WorkspaceSsoError('Single sign-on settings could not be reached. Try again.', 0);
  }
  const json = (await response.json().catch(() => null)) as
    | { success?: boolean; error?: unknown; code?: unknown }
    | null;
  if (!response.ok || json?.success === false) {
    const message = typeof json?.error === 'string' && json.error ? json.error : 'The request failed.';
    throw new WorkspaceSsoError(message, response.status, typeof json?.code === 'string' ? json.code : undefined);
  }
  return json as T;
}

/** @returns The workspace's providers, newest first. */
export async function fetchSsoProviders(): Promise<WorkspaceSsoProvider[]> {
  const body = await workspaceSsoApi<{ providers?: WorkspaceSsoProvider[] }>('');
  return Array.isArray(body.providers) ? body.providers : [];
}

/**
 * Register a provider.
 *
 * @param payload The create body (`buildWorkspaceSsoCreatePayload`).
 * @returns The provider, disabled.
 */
export function createSsoProvider(payload: Record<string, unknown>): Promise<WorkspaceSsoProvider> {
  return workspaceSsoApi<WorkspaceSsoProvider>('', { method: 'POST', body: payload });
}

/**
 * Change a provider — settings, or `{ enabled }`.
 *
 * @param id The provider's id.
 * @param payload The fields to change.
 * @returns The provider as it now stands.
 */
export function updateSsoProvider(id: string, payload: Record<string, unknown>): Promise<WorkspaceSsoProvider> {
  return workspaceSsoApi<WorkspaceSsoProvider>(`/${encodeURIComponent(id)}`, { method: 'PATCH', body: payload });
}

/**
 * Remove a provider, its domains and its secrets.
 *
 * @param id The provider's id.
 * @returns The provider as it was.
 */
export function removeSsoProvider(id: string): Promise<WorkspaceSsoProvider> {
  return workspaceSsoApi<WorkspaceSsoProvider>(`/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/**
 * Add an email domain, unverified.
 *
 * @param id The provider's id.
 * @param domain The domain (an address is accepted).
 * @returns The provider with the new domain and its DNS challenge.
 */
export function addSsoDomain(id: string, domain: string): Promise<WorkspaceSsoProvider> {
  return workspaceSsoApi<WorkspaceSsoProvider>(`/${encodeURIComponent(id)}/domains`, {
    method: 'POST',
    body: { domain },
  });
}

/**
 * Remove an email domain.
 *
 * @param id The provider's id.
 * @param domain The domain.
 * @returns The provider without it.
 */
export function removeSsoDomain(id: string, domain: string): Promise<WorkspaceSsoProvider> {
  return workspaceSsoApi<WorkspaceSsoProvider>(
    `/${encodeURIComponent(id)}/domains/${encodeURIComponent(domain)}`,
    { method: 'DELETE' },
  );
}

/**
 * Check a domain's DNS challenge.
 *
 * @param id The provider's id.
 * @param domain The domain.
 * @returns The provider as it now stands and what the lookup found.
 */
export function verifySsoDomain(id: string, domain: string): Promise<SsoDomainVerifyResult> {
  return workspaceSsoApi<SsoDomainVerifyResult>(
    `/${encodeURIComponent(id)}/domains/${encodeURIComponent(domain)}/verify`,
    { method: 'POST' },
  );
}
