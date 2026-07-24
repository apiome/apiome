import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getDataSnapshotPage } from '@lib/db/helper-database';

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
    const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
    const pageSize = Math.min(100, Math.max(1, parseInt(searchParams.get('pageSize') || '20', 10)));
    const orderBy = searchParams.get('orderBy') ?? undefined;
    const orderDir = searchParams.get('orderDir') ?? undefined;
    const includeDeleted = searchParams.get('includeDeleted') === 'true';
    const { rows, total } = await getDataSnapshotPage(classSchemaId, tenantId, page, pageSize, orderBy, orderDir, { includeDeleted });
    return NextResponse.json({ success: true, rows, total, page, pageSize });
  } catch (error) {
    console.error('Error fetching snapshot list:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
