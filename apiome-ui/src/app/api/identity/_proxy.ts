/**
 * Shared auth helpers for identity API proxies (MFI-6.4, #4410).
 */
import { getAuthSession } from '@lib/auth/server-session';
import jwt from 'jsonwebtoken';
import { getTenantById } from '@lib/db/helper';
import { getJwtSigningSecret } from '@lib/rest-auth';
import { isSameOriginRequest, type OriginCheckHeaders } from '@lib/auth/same-origin';

const REST_API_BASE_URL = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

/** The refusal a proxy returns for a write that did not come from this app's own pages. */
const CROSS_SITE_REFUSAL = { error: 'Forbidden', status: 403 } as const;

/**
 * Refuse a cross-site write to an identity proxy (#4963).
 *
 * The proxies forward the caller's body to apiome-rest under a token minted from the session, so
 * a write is only as intended as the request that carried the session cookie. apiome-rest scopes
 * every id in the body to the token's tenant; this check additionally keeps another site from
 * driving the write at all.
 *
 * @param headers The incoming request's headers.
 * @returns `null` when the request is same-origin, otherwise the `{ error, status }` to answer with.
 */
export function refuseCrossSiteWrite(
  headers: OriginCheckHeaders,
): { error: string; status: number } | null {
  return isSameOriginRequest(headers) ? null : CROSS_SITE_REFUSAL;
}

/**
 * Resolve who an identity proxy call is made for, and the headers to forward it with.
 *
 * The tenant and user come from the server-side session only — never from the request — and are
 * signed into a short-lived token for apiome-rest. Ids in the request **body** (`projectId`,
 * `relatedProjectId`) are forwarded as sent: apiome-rest is what confirms each one belongs to the
 * token's tenant (`identity_routes.py`; pinned by `tests/test_api_identity.py`).
 *
 * @returns The tenant slug and forwarding headers, or the `{ error, status }` to answer with when
 *   there is no session, no active tenant, or no signing secret.
 */
export async function resolveIdentityProxyContext(): Promise<
  | { error: string; status: number }
  | { tenantSlug: string; headers: Record<string, string> }
> {
  const session = await getAuthSession();
  if (!session?.user) {
    return { error: 'Unauthorized', status: 401 };
  }
  const user = session.user as SessionUser;
  const tenantId = user.current_tenant_id;
  if (!tenantId) {
    return { error: 'No tenant selected', status: 400 };
  }
  const tenant = await getTenantById(tenantId);
  if (!tenant?.slug) {
    return { error: 'Tenant not found', status: 404 };
  }
  const secret = getJwtSigningSecret();
  if (!user.user_id || !secret) {
    return { error: 'Unauthorized', status: 401 };
  }
  const token = jwt.sign(
    {
      user_id: user.user_id,
      sub: user.user_id,
      email: user.email,
      name: user.name,
      current_tenant_id: tenantId,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' },
  );
  return {
    tenantSlug: tenant.slug,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
  };
}

export async function handleIdentityRestResponse(
  response: Response,
  defaultError: string,
): Promise<{ data: unknown; error: string | null; status: number }> {
  const contentType = response.headers.get('content-type');
  if (!contentType?.includes('application/json')) {
    const text = await response.text();
    return { data: null, error: text || defaultError, status: response.status || 500 };
  }
  const data = await response.json();
  if (!response.ok) {
    return { data: null, error: data.detail || defaultError, status: response.status };
  }
  return { data, error: null, status: response.status };
}

export { REST_API_BASE_URL };
