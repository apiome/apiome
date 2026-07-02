import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const tenant = await getTenantById(tenantId);
    if (!tenant?.slug) {
      return NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 });
    }
    const { searchParams } = new URL(request.url);
    const projectId = searchParams.get('projectId');
    const fromVersionId = searchParams.get('fromVersionId');
    const toVersionId = searchParams.get('toVersionId');
    if (!projectId || !fromVersionId || !toVersionId) {
      return NextResponse.json(
        { success: false, error: 'projectId, fromVersionId, and toVersionId are required' },
        { status: 400 }
      );
    }
    const params = new URLSearchParams({
      projectId,
      fromVersionId,
      toVersionId,
    });
    const response = await fetch(
      `${REST_API_BASE_URL}/migration-plans/${encodeURIComponent(tenant.slug)}/counts?${params.toString()}`,
      {
        method: 'GET',
        headers: createRestAuthHeaders(session.user as { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string }),
      }
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = typeof data.detail === 'string' ? data.detail : data.error ?? 'Failed to fetch rule counts';
      return NextResponse.json({ success: false, error: message }, { status: response.status });
    }
    return NextResponse.json({ success: true, counts: data.counts ?? {} });
  } catch (error) {
    console.error('Error fetching migration plan rule counts:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
