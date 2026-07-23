'use server';

import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';

/**
 * Whether the current request carries a valid super-admin session.
 *
 * The `admin_session` cookie is an HMAC-signed token (see
 * lib/auth/admin-session.ts). A cookie that was not minted by this server, or
 * one whose expiry has passed, fails verification — a hand-forged value is
 * rejected here.
 *
 * @returns `true` only when a present cookie verifies by signature and expiry.
 */
export async function isAdminAuthenticated(): Promise<boolean> {
  try {
    const cookieStore = await cookies();
    const adminSession = cookieStore.get('admin_session');

    return verifyAdminSessionToken(adminSession?.value);
  } catch {
    return false;
  }
}
