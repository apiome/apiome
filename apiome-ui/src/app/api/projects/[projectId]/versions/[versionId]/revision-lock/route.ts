import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { resolveTenantAdminForSession, setVersionRevisionLock } from '@lib/db/helper';

/**
 * POST /api/projects/[projectId]/versions/[versionId]/revision-lock
 * Body: { revisionLocked: boolean } — tenant administrators only
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string; versionId: string }> }
) {
  try {
    const session = await getAuthSession();
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    const userId = (session.user as { user_id?: string }).user_id;
    if (!tenantId || !userId) {
      return NextResponse.json({ success: false, error: 'No tenant or user' }, { status: 400 });
    }
    const isTenantAdmin = await resolveTenantAdminForSession(
      userId,
      tenantId,
      (session.user as { is_tenant_admin?: boolean }).is_tenant_admin
    );
    const { projectId, versionId } = await params;
    const body = await request.json();
    if (typeof body.revisionLocked !== 'boolean') {
      return NextResponse.json({ success: false, error: 'revisionLocked boolean is required' }, { status: 400 });
    }
    const raw = await setVersionRevisionLock(
      versionId,
      projectId,
      tenantId,
      userId,
      isTenantAdmin,
      body.revisionLocked
    );
    const data = JSON.parse(raw) as { success: boolean; version?: unknown; error?: string; code?: string };
    if (!data.success) {
      const st =
        data.code === 'FORBIDDEN'
          ? 403
          : data.error?.toLowerCase().includes('not found')
            ? 404
            : 400;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true, version: data.version });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
