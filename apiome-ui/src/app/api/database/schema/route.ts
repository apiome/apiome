import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getClassSchemaById } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const session = await getAuthSession();
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const { searchParams } = new URL(request.url);
    const classSchemaId = searchParams.get('classSchemaId');
    if (!classSchemaId) {
      return NextResponse.json({ success: false, error: 'classSchemaId required' }, { status: 400 });
    }
    const row = await getClassSchemaById(classSchemaId, tenantId);
    if (!row) {
      return NextResponse.json({ success: false, error: 'Class schema not found' }, { status: 404 });
    }
    return NextResponse.json({
      success: true,
      schema: row.schema,
      class_name: row.class_name,
    });
  } catch (error) {
    console.error('Error fetching class schema:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
