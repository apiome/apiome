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

export async function GET(request: Request) {
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

  const { searchParams } = new URL(request.url);
  const limitRaw = searchParams.get('limit') ?? '5';
  const limit = Math.min(50, Math.max(1, Number.parseInt(limitRaw, 10) || 5));

  const url = `${REST_API_BASE_URL}/dashboard/${encodeURIComponent(tenant.slug)}/recent_imports_attention?limit=${encodeURIComponent(String(limit))}`;
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
            : 'Failed to load recent imports';
    return NextResponse.json({ success: false, error: detailMessage }, { status: response.status });
  }
  return NextResponse.json({ success: true, data });
}

export async function POST(request: Request) {
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

  let body: { importJobId?: string };
  try {
    body = (await request.json()) as { importJobId?: string };
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }
  const importJobId = typeof body.importJobId === 'string' ? body.importJobId.trim() : '';
  if (!importJobId) {
    return NextResponse.json({ success: false, error: 'importJobId required' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/dashboard/${encodeURIComponent(tenant.slug)}/recent_imports_attention/dismiss`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      ...createRestAuthHeaders(user),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ importJobId }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const raw = data as { detail?: unknown };
    const detailMessage =
      typeof raw.detail === 'string'
        ? raw.detail
        : 'Failed to dismiss';
    return NextResponse.json({ success: false, error: detailMessage }, { status: response.status });
  }
  return NextResponse.json({ success: true, data });
}
