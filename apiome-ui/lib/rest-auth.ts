/**
 * Build Authorization header for server-side calls to apiome-rest.
 * Uses NEXTAUTH_SECRET to sign a JWT with user/tenant from session.
 */

import jwt from 'jsonwebtoken';

export interface SessionUserForRest {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

/**
 * Create headers for REST API calls, including Bearer JWT.
 * Returns only Content-Type if user_id or secret is missing.
 */
export function createRestAuthHeaders(user: SessionUserForRest): Record<string, string> {
  if (!user?.user_id) {
    return { 'Content-Type': 'application/json' };
  }
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    return { 'Content-Type': 'application/json' };
  }
  const token = jwt.sign(
    {
      user_id: user.user_id,
      sub: user.user_id,
      email: user.email,
      name: user.name,
      current_tenant_id: user.current_tenant_id,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' }
  );
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

export const REST_API_BASE_URL =
  process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
