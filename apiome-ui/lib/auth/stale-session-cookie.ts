import { hkdf } from '@panva/hkdf';
import { jwtDecrypt } from 'jose';
import type { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE_NAMES = [
  'next-auth.session-token',
  '__Secure-next-auth.session-token',
  '__Host-next-auth.session-token',
] as const;

async function getDerivedEncryptionKey(secret: string) {
  return hkdf('sha256', secret, '', 'NextAuth.js Generated Encryption Key', 32);
}

export function findSessionCookieName(request: NextRequest): string | null {
  for (const name of SESSION_COOKIE_NAMES) {
    if (request.cookies.has(name)) {
      return name;
    }
  }
  return null;
}

export async function isNextAuthSessionTokenValid(
  token: string,
  secret: string,
): Promise<boolean> {
  try {
    await jwtDecrypt(token, await getDerivedEncryptionKey(secret));
    return true;
  } catch {
    return false;
  }
}

export function clearSessionCookie(response: NextResponse, cookieName: string): void {
  response.cookies.set(cookieName, '', {
    maxAge: 0,
    path: '/',
  });

  // Session cookies may be scoped to NEXTAUTH_COOKIE_DOMAIN (shared across
  // subdomains); a host-only expiry does not remove those. Appended as a raw
  // header because response.cookies keys by name and would drop the first set.
  const domain = process.env.NEXTAUTH_COOKIE_DOMAIN?.trim();
  if (domain && process.env.NODE_ENV === 'production') {
    response.headers.append(
      'Set-Cookie',
      `${cookieName}=; Max-Age=0; Path=/; Domain=${domain}; Secure; HttpOnly; SameSite=Lax`,
    );
  }
}

/**
 * Clears NextAuth session cookies that cannot be decrypted with the current
 * NEXTAUTH_SECRET (e.g. after setup.sh regenerates the secret). Avoids noisy
 * JWT_SESSION_ERROR logs on every request until the browser cookie expires.
 */
export async function clearStaleSessionCookieIfNeeded(
  request: NextRequest,
  response: NextResponse,
): Promise<void> {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    return;
  }

  const cookieName = findSessionCookieName(request);
  if (!cookieName) {
    return;
  }

  const token = request.cookies.get(cookieName)?.value;
  if (!token) {
    return;
  }

  const valid = await isNextAuthSessionTokenValid(token, secret);
  if (!valid) {
    clearSessionCookie(response, cookieName);
  }
}
