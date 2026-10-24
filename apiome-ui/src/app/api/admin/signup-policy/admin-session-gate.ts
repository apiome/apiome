/**
 * The super-admin session gate shared by the sign-up policy proxy routes (SGN-1.4 #5653,
 * SGN-1.5 #5654): `/api/admin/signup-policy` and `/api/admin/signup-policy/blocked-attempts`.
 */
import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { verifyAdminSessionToken } from '@lib/auth/admin-session';

/**
 * Read and verify the super-admin session cookie.
 *
 * @returns The verified token, or the 401/403 response to send instead.
 */
export async function requireAdminSession(): Promise<{ token: string } | { response: NextResponse }> {
  const cookieStore = await cookies();
  const token = cookieStore.get('admin_session')?.value;

  if (!token) {
    return {
      response: NextResponse.json(
        {
          error: 'unauthorized',
          message: 'Super-admin authentication required.',
        },
        { status: 401 },
      ),
    };
  }
  if (!verifyAdminSessionToken(token)) {
    return {
      response: NextResponse.json(
        {
          error: 'forbidden',
          message: 'Invalid or expired super-admin session.',
        },
        { status: 403 },
      ),
    };
  }
  return { token };
}
