/**
 * Admin proxy for the sign-up attempts an abuse guard refused (SGN-1.5, #5654).
 *
 * `GET /api/admin/signup-policy/blocked-attempts?limit=N` relays
 * `GET /v1/admin/signup-policy/blocked-attempts` to the **Recent blocked sign-ups** list on the
 * System settings Sign-up card. Like the policy proxy beside it, it verifies the signed
 * `admin_session` cookie (OLO-8.1) and presents the same token upstream, where apiome-rest
 * verifies it again.
 */
import { NextRequest, NextResponse } from 'next/server';
import { proxyListBlockedSignupAttempts } from '@lib/auth/admin-signup-policy-proxy';
import { requireAdminSession } from '../admin-session-gate';

/** How many attempts the card asks for when the query names none. */
const DEFAULT_LIMIT = 50;

export async function GET(request: NextRequest) {
  const session = await requireAdminSession();
  if ('response' in session) return session.response;

  const raw = request.nextUrl.searchParams.get('limit');
  const limit = raw === null ? DEFAULT_LIMIT : Number(raw);
  const result = await proxyListBlockedSignupAttempts(session.token, limit);
  return NextResponse.json(result.body, { status: result.status });
}
