/**
 * Shared auth helpers for identity API proxies (MFI-6.4, #4410).
 */
import { getServerSession } from 'next-auth';
import jwt from 'jsonwebtoken';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';

const REST_API_BASE_URL = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

export async function resolveIdentityProxyContext(): Promise<
  | { error: string; status: number }
  | { tenantSlug: string; headers: Record<string, string> }
> {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return { error: 'Unauthorized', status: 401 };
  }
  const user = session.user as SessionUser;
  const tenantId = user.current_tenant_id;
  if (!tenantId) {
    return { error: 'No tenant selected', status: 400 };
  }
  const tenant = await getTenantById(tenantId);
  if (!tenant?.slug) {
    return { error: 'Tenant not found', status: 404 };
  }
  const secret = process.env.NEXTAUTH_SECRET;
  if (!user.user_id || !secret) {
    return { error: 'Unauthorized', status: 401 };
  }
  const token = jwt.sign(
    {
      user_id: user.user_id,
      sub: user.user_id,
      email: user.email,
      name: user.name,
      current_tenant_id: tenantId,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' },
  );
  return {
    tenantSlug: tenant.slug,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
  };
}

export async function handleIdentityRestResponse(
  response: Response,
  defaultError: string,
): Promise<{ data: unknown; error: string | null; status: number }> {
  const contentType = response.headers.get('content-type');
  if (!contentType?.includes('application/json')) {
    const text = await response.text();
    return { data: null, error: text || defaultError, status: response.status || 500 };
  }
  const data = await response.json();
  if (!response.ok) {
    return { data: null, error: data.detail || defaultError, status: response.status };
  }
  return { data, error: null, status: response.status };
}

export { REST_API_BASE_URL };
