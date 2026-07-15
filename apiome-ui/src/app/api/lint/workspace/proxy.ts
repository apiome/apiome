/**
 * Shared proxy plumbing for the lint workspace API routes (CLX-4.1, #4859).
 *
 * Every /api/lint/workspace/* route authenticates the session, mints the REST bearer token
 * via the shared lib/rest-auth helper, forwards to apiome-rest (tenant scope travels in the
 * token — no tenant slug in the path), and wraps the response in the { success, ... } envelope.
 */
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { createRestAuthHeaders, REST_API_BASE_URL, SessionUserForRest } from '@lib/rest-auth';

/** Resolve the session user or the 401/400 error response to return instead. */
export async function requireSessionUser(): Promise<
  { user: SessionUserForRest } | { error: NextResponse }
> {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
  }
  const user = session.user as SessionUserForRest;
  if (!user.current_tenant_id) {
    return {
      error: NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 }),
    };
  }
  return { user };
}

/**
 * Forward a request to apiome-rest and wrap the JSON reply in the success envelope.
 *
 * @param user - Authenticated session user (from requireSessionUser).
 * @param path - REST path under the API base, e.g. `/lint/workspace/findings?...`.
 * @param init - Optional method/body overrides (defaults to GET).
 * @returns The enveloped NextResponse mirroring the upstream status on failure.
 */
export async function proxyToRest(
  user: SessionUserForRest,
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<NextResponse> {
  try {
    const response = await fetch(`${REST_API_BASE_URL}${path}`, {
      method: init?.method ?? 'GET',
      headers: createRestAuthHeaders(user),
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
