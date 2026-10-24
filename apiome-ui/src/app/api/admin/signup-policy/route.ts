/**
 * Admin sign-up policy proxy (SGN-1.4, #5653).
 *
 * `GET /api/admin/signup-policy` relays the installation sign-up policy from apiome-rest
 * (`GET /v1/admin/signup-policy`) to the Sign-up card on System settings;
 * `PUT /api/admin/signup-policy` relays a save (or, with `mode: null`, a clear) to
 * `PUT /v1/admin/signup-policy`. Both verify the signed `admin_session` cookie (OLO-8.1) before
 * forwarding — the same token is then presented upstream, where apiome-rest verifies it again; the
 * proxy adds no authority of its own. The body is relayed verbatim so the REST surface's own
 * validation applies (unknown mode or invalid domain ⇒ structured 422).
 *
 * A successful save drops the in-process sign-up policy cache via the proxy helper, so the change
 * applies to the very next sign-up.
 */
import { NextRequest, NextResponse } from 'next/server';
import { requireAdminSession } from './admin-session-gate';
import { proxyGetSignupPolicy, proxyUpdateSignupPolicy } from '@lib/auth/admin-signup-policy-proxy';
import type { AdminSignupPolicyUpdatePayload } from '@lib/auth/admin-signup-policy';

export async function GET() {
  const session = await requireAdminSession();
  if ('response' in session) return session.response;

  const result = await proxyGetSignupPolicy(session.token);
  return NextResponse.json(result.body, { status: result.status });
}

export async function PUT(request: NextRequest) {
  const session = await requireAdminSession();
  if ('response' in session) return session.response;

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    payload = null;
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return NextResponse.json(
      { error: 'invalid_body', message: 'Request body must be a JSON object.' },
      { status: 400 },
    );
  }

  const result = await proxyUpdateSignupPolicy(
    session.token,
    payload as AdminSignupPolicyUpdatePayload,
  );
  return NextResponse.json(result.body, { status: result.status });
}
