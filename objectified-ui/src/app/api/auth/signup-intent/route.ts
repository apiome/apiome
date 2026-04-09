import { NextRequest, NextResponse } from 'next/server';

/**
 * Sets a short-lived cookie so the next GitHub/GitLab OAuth callback is treated as self-signup (new account).
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

  const body = await request.json().catch(() => ({}));
  const provider = body?.provider;
  if (provider !== 'github' && provider !== 'gitlab') {
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
