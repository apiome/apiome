import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getClassSchemaById, getDataSnapshotByRecordId } from '@lib/db/helper-database';
import { getTenantById } from '@lib/db/helper';
import { validatePayloadAgainstSchema } from '@lib/database/validateSchema';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

export async function GET(
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

    const snapshot = await getDataSnapshotByRecordId(recordId, classSchemaId, tenantId);
    if (!snapshot) {
      return NextResponse.json({ success: false, error: 'Record not found' }, { status: 404 });
    }

    return NextResponse.json({ success: true, record_id: recordId, data: snapshot.data });
  } catch (error) {
    console.error('Error fetching snapshot:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

export async function PATCH(
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

    let body: { classSchemaId?: string; data?: Record<string, unknown> };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
    }
    const { classSchemaId, data } = body;
    if (!classSchemaId || typeof classSchemaId !== 'string') {
      return NextResponse.json({ success: false, error: 'classSchemaId required' }, { status: 400 });
    }
    if (data === undefined || typeof data !== 'object' || data === null) {
      return NextResponse.json({ success: false, error: 'data must be an object' }, { status: 400 });
    }

    const row = await getClassSchemaById(classSchemaId, tenantId);
    if (!row) {
      return NextResponse.json({ success: false, error: 'Class schema not found' }, { status: 404 });
    }

    const validation = validatePayloadAgainstSchema(data, row.schema);
    if (!validation.valid) {
      return NextResponse.json(
        { success: false, error: 'Validation failed', errors: validation.errors },
        { status: 400 }
      );
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant?.slug) {
      return NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 });
    }

    const headers = createRestAuthHeaders(session.user as { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string });
    const res = await fetch(
      `${REST_API_BASE_URL}/data/${encodeURIComponent(tenant.slug)}/records/${encodeURIComponent(recordId)}`,
      {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ class_schema_id: classSchemaId, data }),
      }
    );

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof json.detail === 'string' ? json.detail : json.error ?? 'Update failed';
      return NextResponse.json({ success: false, error: message }, { status: res.status });
    }

    return NextResponse.json({ success: true, record_id: recordId });
  } catch (error) {
    console.error('Error updating record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

export async function DELETE(
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
      `${REST_API_BASE_URL}/data/${encodeURIComponent(tenant.slug)}/records/${encodeURIComponent(recordId)}`
    );
    url.searchParams.set('class_schema_id', classSchemaId);
    const res = await fetch(url.toString(), { method: 'DELETE', headers });

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof json.detail === 'string' ? json.detail : json.error ?? 'Delete failed';
      return NextResponse.json({ success: false, error: message }, { status: res.status });
    }

    return NextResponse.json({ success: true, record_id: recordId });
  } catch (error) {
    console.error('Error deleting record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
