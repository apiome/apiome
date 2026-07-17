import { NextRequest, NextResponse } from 'next/server';
import { isProviderEnabled } from '../../../../../lib/auth/provider-registry';

/**
 * Sets a short-lived cookie so the next OAuth callback is treated as self-signup (new account).
 * The provider must be enabled in this deployment's provider registry (OLO-2.3) — the same
 * gate that decides which sign-up buttons the login page renders.
 * Uses POST to prevent CSRF-style flow manipulation via cross-site GET requests.
 */
export async function POST(request: NextRequest) {
  // Validate Origin to prevent cross-site requests
  const origin = request.headers.get('origin');
  const host = request.headers.get('host');
  if (!origin || !host) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }
  try {
    const originHost = new URL(origin).host;
    if (originHost !== host) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }
  } catch {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON in request body' }, { status: 400 });
  }
  const provider = body?.provider;
  if (typeof provider !== 'string' || !isProviderEnabled(provider)) {
    return NextResponse.json({ error: 'Invalid provider' }, { status: 400 });
  }

  const response = NextResponse.json({ success: true, provider });
  response.cookies.set(
    'oauth_signup_intent',
    JSON.stringify({
      provider,
      timestamp: Date.now(),
    }),
    {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      maxAge: 600,
      path: '/',
      sameSite: 'lax',
    }
  );
  return response;
}
