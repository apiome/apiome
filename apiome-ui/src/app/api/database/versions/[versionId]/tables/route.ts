import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getClassSchemasForVersion } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  try {
    const session = await getAuthSession();
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const { versionId } = await params;
    if (!versionId) {
      return NextResponse.json({ success: false, error: 'Version ID required' }, { status: 400 });
    }
    const tables = await getClassSchemasForVersion(versionId, tenantId);
    return NextResponse.json({ success: true, tables });
  } catch (error) {
    console.error('Error fetching database tables:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
