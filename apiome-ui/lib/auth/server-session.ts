'use server';

import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';

/**
 * Returns the current server session, or null when called outside an
 * authenticated request context (e.g. in unit tests with no mock).
 */
export async function getAuthSession() {
  return getServerSession(authOptions);
}
