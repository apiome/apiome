import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { deleteVersionBranch } from '@lib/db/helper';

/**
 * DELETE /api/projects/[projectId]/version-branches/[branchId]
 */
export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string; branchId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    const userId = (session.user as { user_id?: string }).user_id;
    const isTenantAdmin = Boolean((session.user as { is_tenant_admin?: boolean }).is_tenant_admin);
    if (!tenantId || !userId) {
      return NextResponse.json({ success: false, error: 'No tenant or user' }, { status: 400 });
    }
    const { projectId, branchId } = await params;
    const raw = await deleteVersionBranch(branchId, projectId, tenantId, userId, isTenantAdmin);
    const data = JSON.parse(raw) as { success: boolean; error?: string };
    if (!data.success) {
      const st = data.error?.includes('not found') ? 404 : 403;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
