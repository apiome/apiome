import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import {
  checkLoginRateLimit,
  recordLoginFailure,
  recordLoginSuccess,
} from '@lib/auth/login-rate-limit';

/** Resolve a best-effort client IP for rate-limiting the super-admin password form. */
function clientRateLimitKey(request: NextRequest): string {
  const forwarded = request.headers.get('x-forwarded-for');
  const ip = forwarded?.split(',')[0]?.trim() || request.headers.get('x-real-ip') || 'unknown';
  return `admin:${ip}`;
}

export async function POST(request: NextRequest) {
  try {
    const { password } = await request.json();

    const adminPassword = process.env.ADMIN_PASSWORD;

    if (!adminPassword) {
      return NextResponse.json(
        { error: 'Admin password not configured' },
        { status: 500 }
      );
    }

    // Brute-force protection: throttle repeated failures from the same client IP.
    const rateLimitKey = clientRateLimitKey(request);
    const limit = checkLoginRateLimit(rateLimitKey);
    if (limit.blocked) {
      const retryAfter = Math.ceil(limit.retryAfterMs / 1000);
      return NextResponse.json(
        { error: 'Too many failed attempts. Try again later.' },
        { status: 429, headers: { 'Retry-After': String(retryAfter) } }
      );
    }

    if (password === adminPassword) {
      recordLoginSuccess(rateLimitKey);

      // Create a cookie to store admin authentication
      const cookieStore = await cookies();

      // Create a simple token (in production, use JWT or more secure method)
      const token = Buffer.from(`admin:${Date.now()}`).toString('base64');

      cookieStore.set('admin_session', token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 60 * 60 * 8, // 8 hours
        path: '/',
      });

      return NextResponse.json({ success: true });
    } else {
      recordLoginFailure(rateLimitKey);
      return NextResponse.json(
        { error: 'Invalid password' },
        { status: 401 }
      );
    }
  } catch (error) {
    console.error('Admin auth error:', error);
    return NextResponse.json(
      { error: 'Authentication failed' },
      { status: 500 }
    );
  }
}

export async function DELETE() {
  // Logout endpoint
  const cookieStore = await cookies();
  cookieStore.delete('admin_session');

  return NextResponse.json({ success: true });
}

