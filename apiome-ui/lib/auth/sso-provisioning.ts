/**
 * Just-in-time provisioning after an enterprise SSO sign-in (EID-1.3, #5013).
 *
 * A workspace's identity provider belongs to that workspace. Once a sign-in through it has been
 * admitted (`sso-resolution.ts`), apiome-ui asks apiome-rest to make that person a member of the
 * provider's workspace: the service-token-gated
 * `POST /v1/tenants/{tenant}/sso/providers/{id}/provision`. apiome-rest owns every rule — the
 * default role, the seat limit, never demoting a member, never reaching into another workspace —
 * and the call is idempotent, so it is made on every SSO sign-in, not only the first.
 *
 * Never throws and never logs a response body: an unreachable REST API, a missing token, a refusal
 * or a malformed answer are all `null`, and the caller decides what a sign-in without an answer
 * means.
 *
 * Server-only.
 */

import { getRestApiBaseUrl } from '../rest-auth';
import type { ResolvedSsoProvider } from './sso-provider-resolver';

/** What apiome-rest decided for one sign-in. Mirrors `app.sso_provisioning.OUTCOMES`. */
export const SSO_PROVISION_OUTCOMES = [
  /** The membership was created by this sign-in, with the provider's default role. */
  'provisioned',
  /** A pending invitation was accepted by signing in. */
  'activated',
  /** Already an active member; nothing changed. */
  'existing',
  /** The membership is suspended; nothing changed. */
  'suspended',
  /** Every licensed member seat is in use; no membership was created. */
  'seat-cap-blocked',
] as const;

export type SsoProvisionOutcome = (typeof SSO_PROVISION_OUTCOMES)[number];

/** The answer of one provisioning call. */
export interface SsoProvisionResult {
  outcome: SsoProvisionOutcome;
  tenantId: string;
  tenantName: string;
  /** The member's role after the call; null when they hold none, and when blocked. */
  roleSlug: string | null;
}

/** Where a person lands when their workspace has no seat left for them. */
export const SSO_OUT_OF_SEATS_PATH = '/login/out-of-seats';

/** Longest workspace name carried in the out-of-seats link. */
const MAX_WORKSPACE_NAME_LENGTH = 120;

const PROVISION_TIMEOUT_MS = 5_000;

/**
 * The out-of-seats page for a workspace.
 *
 * @param workspaceName The workspace's display name, when known.
 * @returns A same-origin path, with the name as the `workspace` query value.
 */
export function ssoOutOfSeatsPath(workspaceName: string | null | undefined): string {
  const name = (workspaceName ?? '').trim().slice(0, MAX_WORKSPACE_NAME_LENGTH);
  return name ? `${SSO_OUT_OF_SEATS_PATH}?workspace=${encodeURIComponent(name)}` : SSO_OUT_OF_SEATS_PATH;
}

/**
 * Read one provisioning answer off the wire.
 *
 * @param body The parsed JSON response.
 * @returns The result, or null when the outcome is not one this build knows or the workspace is
 *   missing.
 */
export function parseSsoProvisionResult(body: unknown): SsoProvisionResult | null {
  if (!body || typeof body !== 'object') return null;
  const row = body as Record<string, unknown>;
  const outcome = SSO_PROVISION_OUTCOMES.find((known) => known === row.outcome);
  if (!outcome || typeof row.tenant_id !== 'string' || !row.tenant_id) return null;
  return {
    outcome,
    tenantId: row.tenant_id,
    tenantName: typeof row.tenant_name === 'string' ? row.tenant_name : '',
    roleSlug: typeof row.role_slug === 'string' && row.role_slug ? row.role_slug : null,
  };
}

/**
 * Ask apiome-rest to provision the person who just signed in through `provider`.
 *
 * @param provider The provider the sign-in came through; its `tenantId` is the workspace.
 * @param userId The signed-in account.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The answer, or null when there is none (no workspace on the provider, no service token,
 *   REST unreachable, a refusal, or a malformed body).
 */
export async function provisionSsoMember(
  provider: Pick<ResolvedSsoProvider, 'id' | 'tenantId'>,
  userId: string,
  fetchImpl: typeof fetch = fetch
): Promise<SsoProvisionResult | null> {
  const token = process.env.INTERNAL_SERVICE_TOKEN?.trim();
  if (!token || !provider.tenantId || !userId) return null;
  const url =
    `${getRestApiBaseUrl()}/tenants/${encodeURIComponent(provider.tenantId)}` +
    `/sso/providers/${encodeURIComponent(provider.id)}/provision`;
  try {
    const response = await fetchImpl(url, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Service-Token': token },
      body: JSON.stringify({ user_id: userId }),
      signal: AbortSignal.timeout(PROVISION_TIMEOUT_MS),
    });
    if (!response.ok) {
      console.warn(`[sso-provisioning] provision endpoint returned ${response.status}`);
      return null;
    }
    return parseSsoProvisionResult(await response.json());
  } catch (error) {
    console.warn(`[sso-provisioning] provision endpoint unreachable (${error instanceof Error ? error.name : 'unknown'})`);
    return null;
  }
}
