/**
 * Shared proxy plumbing for the lint workspace API routes (CLX-4.1, #4859).
 *
 * Every /api/lint/workspace/* route authenticates the session, resolves the current tenant's
 * slug, mints the REST bearer token via the shared lib/rest-auth helper, forwards to
 * apiome-rest with the required `tenant_slug` query parameter (the /v1/lint/* routers take
 * the tenant slug as a query param, not a path segment), and wraps the response in the
 * { success, ... } envelope.
 */
import { NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL, SessionUserForRest } from '@lib/rest-auth';

/** Authenticated caller context every workspace proxy call needs. */
export interface WorkspaceProxyAuth {
  user: SessionUserForRest;
  tenantSlug: string;
}

/** Resolve the session user + tenant slug, or the 401/400/404 error response to return. */
export async function requireSessionUser(): Promise<
  WorkspaceProxyAuth | { error: NextResponse }
> {
  const session = await getAuthSession();
  if (!session?.user) {
    return { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
  }
  const user = session.user as SessionUserForRest;
  if (!user.current_tenant_id) {
    return {
      error: NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 }),
    };
  }
  const tenant = await getTenantById(user.current_tenant_id);
  if (!tenant?.slug) {
    return {
      error: NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 }),
    };
  }
  return { user, tenantSlug: tenant.slug };
}

/**
 * Forward a request to apiome-rest and wrap the JSON reply in the success envelope.
 *
 * @param auth - Authenticated session user + tenant slug (from requireSessionUser).
 * @param path - REST path under the API base, e.g. `/lint/workspace/findings?...`.
 * @param init - Optional method/body overrides (defaults to GET).
 * @returns The enveloped NextResponse mirroring the upstream status on failure.
 */
export async function proxyToRest(
  auth: WorkspaceProxyAuth,
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<NextResponse> {
  try {
    // The lint routers take the tenant slug as a query parameter (see the REST OpenAPI spec).
    const separator = path.includes('?') ? '&' : '?';
    const url = `${REST_API_BASE_URL}${path}${separator}tenant_slug=${encodeURIComponent(auth.tenantSlug)}`;
    const response = await fetch(url, {
      method: init?.method ?? 'GET',
      headers: createRestAuthHeaders(auth.user),
      ...(init?.body !== undefined ? { body: JSON.stringify(init.body) } : {}),
    });
    const data = await response.json().catch(() => null);
    const payload = typeof data === 'object' && data ? data : {};
    if (!response.ok) {
      const error =
        (payload as { detail?: string; error?: string }).detail ??
        (payload as { error?: string }).error ??
        `HTTP ${response.status}`;
      return NextResponse.json({ success: false, error, ...payload }, { status: response.status });
    }
    return NextResponse.json({ success: true, ...payload });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}

/** Query params the findings proxy forwards verbatim (whitelist). */
export const FINDINGS_PARAM_WHITELIST = [
  'severity',
  'state',
  'axis',
  'grade',
  'coverage',
  'profile',
  'scanner',
  'subjectType',
  'projectId',
  'ownerUserId',
  'ruleId',
  'category',
  'new',
  'q',
  'sort',
  'limit',
  'offset',
] as const;

/** Build a REST query string from whitelisted request params. */
export function whitelistedQuery(searchParams: URLSearchParams): string {
  const out = new URLSearchParams();
  for (const key of FINDINGS_PARAM_WHITELIST) {
    const value = searchParams.get(key);
    if (value !== null && value !== '') out.set(key, value);
  }
  const text = out.toString();
  return text ? `?${text}` : '';
}
