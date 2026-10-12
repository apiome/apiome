/**
 * Super-admin reset of a user's two-factor (TFA-1.2, #5656).
 *
 * `POST /api/admin/users/{userId}/two-factor/reset` → apiome-rest
 * `POST /v1/admin/users/{userId}/two-factor/reset`.
 *
 * The admin console cannot call apiome-rest directly (different origin; the signed `admin_session`
 * cookie lives on the UI domain), so this route verifies that cookie, forwards the reason and the
 * typed confirmation with the session presented upstream — apiome-rest verifies it again, performs
 * the reset and writes the audit rows — and then emails the user. The answer says whether the
 * email went out, so an administrator on an installation without a sender knows to tell the user
 * themselves.
 *
 * Same-origin only: this changes another person's account on the strength of a cookie.
 */

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';
import { forwardToAdminRest } from '@lib/auth/admin-provider-config-proxy';
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

  const token = (await cookies()).get('admin_session')?.value;
  if (!token) {
    return NextResponse.json(
      { success: false, error: 'Super-admin authentication required.' },
      { status: 401 }
    );
  }
  if (!verifyAdminSessionToken(token)) {
    return NextResponse.json(
      { success: false, error: 'Invalid or expired super-admin session.' },
      { status: 403 }
    );
  }

  const payload = parseResetRequest(await request.json().catch(() => null));
  if (!payload) {
    return NextResponse.json(
      { success: false, error: 'Give a reason and type the user’s email address to confirm.' },
      { status: 400 }
    );
  }

  const { userId } = await params;
  const upstream = await forwardToAdminRest(
    `/users/${encodeURIComponent(userId)}/two-factor/reset`,
    { method: 'POST', body: JSON.stringify(payload) },
    token
  );
  const answer = await finishTwoFactorReset(upstream.status, upstream.body, sendTwoFactorResetEmail);
  return NextResponse.json(answer.body, { status: answer.status });
}
