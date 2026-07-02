import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getDataSnapshotCounts } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

/**
 * GET /api/database/snapshot/counts?classSchemaIds=id1,id2,id3
 * Returns { success: true, counts: { [classSchemaId]: number } } for each id (0 if no rows).
 */
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
    const { searchParams } = new URL(request.url);
    const classSchemaIdsParam = searchParams.get('classSchemaIds');
    const classSchemaIds = classSchemaIdsParam
      ? classSchemaIdsParam.split(',').map((s) => s.trim()).filter(Boolean)
      : [];
    const counts = await getDataSnapshotCounts(classSchemaIds, tenantId);
    return NextResponse.json({ success: true, counts });
  } catch (error) {
    console.error('Error fetching snapshot counts:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
