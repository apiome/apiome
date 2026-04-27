import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

type SessionUser = {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
};

async function resolveAuthContext() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
  }
  const user = session.user as SessionUser;
  if (!user.current_tenant_id) {
    return { error: NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 }) };
  }
  const tenant = await getTenantById(user.current_tenant_id);
  if (!tenant?.slug) {
    return { error: NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 }) };
  }
  return { sessionUser: user, tenantSlug: tenant.slug };
}

export async function GET(request: NextRequest) {
  try {
    const auth = await resolveAuthContext();
    if ('error' in auth) return auth.error;

    const { searchParams } = new URL(request.url);
    const q = new URLSearchParams();
    for (const key of ['provider', 'status', 'q', 'page', 'pageSize'] as const) {
      const v = searchParams.get(key);
      if (v != null && v.length > 0) q.set(key, v);
    }
    const qs = q.toString();
    const url = `${REST_API_BASE_URL}/repositories/${auth.tenantSlug}/scan-reports${qs ? `?${qs}` : ''}`;

    const response = await fetch(url, { method: 'GET', headers: createRestAuthHeaders(auth.sessionUser) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const raw = data as { detail?: unknown; message?: string };
      const asObj = raw.detail;
      const detailMessage =
        typeof asObj === 'string'
          ? asObj
          : asObj && typeof asObj === 'object' && asObj && 'message' in (asObj as object)
            ? String((asObj as { message?: string }).message ?? 'Request failed')
            : typeof data.detail === 'string'
              ? data.detail
              : 'Failed to load scan reports';
      return NextResponse.json(
        { success: false, error: detailMessage },
        { status: response.status },
      );
    }
    return NextResponse.json({ success: true, data });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
