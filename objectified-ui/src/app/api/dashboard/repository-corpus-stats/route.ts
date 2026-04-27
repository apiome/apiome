import { NextResponse } from 'next/server';
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

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  const user = session.user as SessionUser;
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }
  const tenant = await getTenantById(user.current_tenant_id);
  if (!tenant?.slug) {
    return NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/dashboard/${encodeURIComponent(tenant.slug)}/repository_corpus_stats`;
  const response = await fetch(url, { method: 'GET', headers: createRestAuthHeaders(user) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const raw = data as { detail?: unknown; message?: string };
    const asObj = raw.detail;
    const detailMessage =
      typeof asObj === 'string'
        ? asObj
        : asObj && typeof asObj === 'object' && asObj && 'message' in (asObj as object)
          ? String((asObj as { message?: string }).message ?? 'Request failed')
          : typeof (data as { detail?: string }).detail === 'string'
            ? (data as { detail: string }).detail
            : 'Failed to load corpus stats';
    return NextResponse.json({ success: false, error: detailMessage }, { status: response.status });
  }
  return NextResponse.json({ success: true, data });
}
