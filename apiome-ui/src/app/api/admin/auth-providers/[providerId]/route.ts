/**
 * Admin auth-provider config proxy — update (OLO-8.7, #4973).
 *
 * `PUT /api/admin/auth-providers/{providerId}` relays a partial provider-config update to
 * apiome-rest (OLO-8.4, `PUT /v1/admin/auth-providers/{provider_id}`). The route verifies the
 * signed `admin_session` cookie (OLO-8.1) before forwarding; the body is relayed verbatim so the
 * REST surface's own validation applies (unknown provider ⇒ 404, incomplete/coming-soon enable ⇒
 * structured 422, secret without encryption configured ⇒ 503). The `client_secret` field is
 * write-only end to end — no response ever echoes it, and this route never logs the body.
 *
 * A successful write invalidates the in-process resolved provider-config cache (OLO-8.5) via the
 * proxy helper, so the change reaches the very next login (OLO-8.6).
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';
import { proxyUpdateAuthProvider } from '@lib/auth/admin-provider-config-proxy';

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ providerId: string }> }
) {
  const cookieStore = await cookies();
  const token = cookieStore.get('admin_session')?.value;

  if (!token) {
    return NextResponse.json(
      { error: 'unauthorized', message: 'Super-admin authentication required.' },
      { status: 401 }
    );
  }
  if (!verifyAdminSessionToken(token)) {
    return NextResponse.json(
      { error: 'forbidden', message: 'Invalid or expired super-admin session.' },
      { status: 403 }
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'invalid_body', message: 'Request body must be a JSON object.' },
      { status: 400 }
    );
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return NextResponse.json(
      { error: 'invalid_body', message: 'Request body must be a JSON object.' },
      { status: 400 }
    );
  }

  const { providerId } = await params;
  const result = await proxyUpdateAuthProvider(token, providerId, payload);
  return NextResponse.json(result.body, { status: result.status });
}
