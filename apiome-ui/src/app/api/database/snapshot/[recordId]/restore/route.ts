import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getClassSchemaById } from '@lib/db/helper-database';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ recordId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    const { recordId } = await params;
    if (!recordId) {
      return NextResponse.json({ success: false, error: 'recordId required' }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const classSchemaId = searchParams.get('classSchemaId');
    if (!classSchemaId) {
      return NextResponse.json({ success: false, error: 'classSchemaId query parameter required' }, { status: 400 });
    }

    const row = await getClassSchemaById(classSchemaId, tenantId);
    if (!row) {
      return NextResponse.json({ success: false, error: 'Class schema not found' }, { status: 404 });
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant?.slug) {
      return NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 });
    }

    const headers = createRestAuthHeaders(session.user as { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string });
    const url = new URL(
      `${REST_API_BASE_URL}/data/${encodeURIComponent(tenant.slug)}/records/${encodeURIComponent(recordId)}/restore`
    );
    url.searchParams.set('class_schema_id', classSchemaId);
    const res = await fetch(url.toString(), { method: 'POST', headers });

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof json.detail === 'string' ? json.detail : json.error ?? 'Restore failed';
      return NextResponse.json({ success: false, error: message }, { status: res.status });
    }

    return NextResponse.json({ success: true, record_id: recordId });
  } catch (error) {
    console.error('Error restoring record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
