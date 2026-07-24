import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getClassSchemaById } from '@lib/db/helper-database';
import { getTenantById } from '@lib/db/helper';
import { validatePayloadAgainstSchema } from '@lib/database/validateSchema';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  try {
    const session = await getAuthSession();
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
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
    const res = await fetch(`${REST_API_BASE_URL}/data/${encodeURIComponent(tenant.slug)}/records`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ class_schema_id: classSchemaId, data }),
    });

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof json.detail === 'string' ? json.detail : json.error ?? 'Insert failed';
      return NextResponse.json({ success: false, error: message }, { status: res.status });
    }

    return NextResponse.json({ success: true, record_id: json.record_id });
  } catch (error) {
    console.error('Error inserting record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
