/**
 * Admin auth-provider config proxy — list (OLO-8.7, #4973).
 *
 * `GET /api/admin/auth-providers` relays the super-admin provider-config list from apiome-rest
 * (OLO-8.4, `GET /v1/admin/auth-providers`) to the settings screen. The route verifies the
 * signed `admin_session` cookie (OLO-8.1) before forwarding — the same token is then presented
 * upstream, where apiome-rest verifies it again against the shared HMAC key; the proxy adds no
 * authority of its own. Responses are relayed verbatim and never contain a secret (the REST
 * surface reports only `secret_set`).
 */
import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';
import { proxyListAuthProviders } from '@lib/auth/admin-provider-config-proxy';

export async function GET() {
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

  const result = await proxyListAuthProviders(token);
  return NextResponse.json(result.body, { status: result.status });
}
