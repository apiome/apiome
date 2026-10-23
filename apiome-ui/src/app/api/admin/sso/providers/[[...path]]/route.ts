/**
 * Admin SSO providers proxy (EID-1.1, #5011).
 *
 * `/api/admin/sso/providers[/…]` relays the admin console's SSO section to apiome-rest
 * (`/v1/admin/sso/providers`): list and register IdPs, update / enable / remove one, add, verify
 * and remove its domains. Each method verifies the signed `admin_session` cookie (OLO-8.1) first;
 * the same token is presented upstream, where apiome-rest verifies it again. Only the path shapes
 * the REST surface defines are forwarded (`lib/auth/admin-sso-proxy.ts`). Bodies may carry a
 * write-only secret (OIDC client secret, SAML SP key) and are never logged; no response carries one.
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';
import { proxySsoAdmin } from '@lib/auth/admin-sso-proxy';

type RouteContext = { params: Promise<{ path?: string[] }> };

/**
 * The verified admin token, or the 401/403 response to return instead.
 */
async function adminToken(): Promise<{ token: string } | { response: NextResponse }> {
  const token = (await cookies()).get('admin_session')?.value;
  if (!token) {
    return {
      response: NextResponse.json(
        { error: 'unauthorized', message: 'Super-admin authentication required.' },
        { status: 401 }
      ),
    };
  }
  if (!verifyAdminSessionToken(token)) {
    return {
      response: NextResponse.json(
        { error: 'forbidden', message: 'Invalid or expired super-admin session.' },
        { status: 403 }
      ),
    };
  }
  return { token };
}

/**
 * Verify the session, read the body when the method carries one, and forward.
 */
async function handle(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await adminToken();
  if ('response' in auth) return auth.response;

  let body: unknown;
  if (request.method === 'POST' || request.method === 'PATCH') {
    const text = await request.text();
    if (text.trim() !== '') {
      try {
        body = JSON.parse(text);
      } catch {
        return NextResponse.json(
          { error: 'invalid_body', message: 'Request body must be a JSON object.' },
          { status: 400 }
        );
      }
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        return NextResponse.json(
          { error: 'invalid_body', message: 'Request body must be a JSON object.' },
          { status: 400 }
        );
      }
    }
  }

  const { path = [] } = await context.params;
  const result = await proxySsoAdmin(auth.token, request.method, path, body);
  return NextResponse.json(result.body, { status: result.status });
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
