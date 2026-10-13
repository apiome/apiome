/**
 * Workspace-owner reset of a member's two-factor (TFA-1.2, #5656).
 *
 * `POST /api/access/members/{userId}/two-factor/reset` → apiome-rest
 * `POST /v1/access/{tenantSlug}/members/{userId}/two-factor/reset`.
 *
 * More specific than the `/api/access/[...path]` catch-all, which would forward this call too but
 * could not do the two things it needs: refuse a cross-site request, and email the member once the
 * reset has succeeded. The workspace comes from the session, never from the browser. apiome-rest
 * decides whether the caller may do this — an owner, of an active member who belongs to no other
 * workspace — and its refusal is passed on with its stable code.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL, type SessionUserForRest } from '@lib/rest-auth';
import { isSameOriginRequest } from '@lib/auth/same-origin';
import { sendTwoFactorResetEmail } from '@lib/auth/send-two-factor-reset-email';
import { finishTwoFactorReset, parseResetRequest } from '@lib/auth/two-factor-reset';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ userId: string }> }
) {
  if (!isSameOriginRequest(request.headers)) {
    return NextResponse.json({ success: false, error: 'Forbidden' }, { status: 403 });
  }

  const session = await getAuthSession();
  const user = session?.user as SessionUserForRest | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }
  const tenant = await getTenantById(user.current_tenant_id);
  if (!tenant?.slug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
  }

  const payload = parseResetRequest(await request.json().catch(() => null));
  if (!payload) {
    return NextResponse.json(
      { success: false, error: 'Give a reason and type the member’s email address to confirm.' },
      { status: 400 }
    );
  }

  const { userId } = await params;
  let status = 502;
  let body: unknown = null;
  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/access/${encodeURIComponent(tenant.slug)}/members/${encodeURIComponent(userId)}/two-factor/reset`,
      { method: 'POST', headers: createRestAuthHeaders(user), body: JSON.stringify(payload), cache: 'no-store' }
    );
    status = response.status;
    body = await response.json().catch(() => null);
  } catch {
    body = { message: 'Could not reach the Apiome API. Check that it is running and try again.' };
  }

  const answer = await finishTwoFactorReset(status, body, sendTwoFactorResetEmail);
  return NextResponse.json(answer.body, { status: answer.status });
}
