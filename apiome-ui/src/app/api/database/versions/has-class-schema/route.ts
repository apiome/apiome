import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getVersionHasClassSchemaMap } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

/**
 * GET /api/database/versions/has-class-schema?versionIds=id1,id2,id3
 * Returns { success: true, map: { [versionId]: boolean } } for each version (true if has class_schema rows).
 */
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
    const versionIdsParam = searchParams.get('versionIds');
    const versionIds = versionIdsParam ? versionIdsParam.split(',').map((s) => s.trim()).filter(Boolean) : [];
    const map = await getVersionHasClassSchemaMap(versionIds, tenantId);
    return NextResponse.json({ success: true, map });
  } catch (error) {
    console.error('Error fetching has-class-schema:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
