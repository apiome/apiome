import { NextRequest, NextResponse } from 'next/server';

/**
 * Sets a short-lived cookie so the next GitHub/GitLab OAuth callback is treated as self-signup (new account).
 */
export async function GET(request: NextRequest) {
  const provider = request.nextUrl.searchParams.get('provider');
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
