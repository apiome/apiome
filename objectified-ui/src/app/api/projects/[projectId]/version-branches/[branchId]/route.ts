import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { deleteVersionBranch, updateVersionBranchProtection } from '@lib/db/helper';

/**
 * PATCH /api/projects/[projectId]/version-branches/[branchId] — body: { protected?: boolean, requireMergePath?: boolean } (tenant admin only; at least one field)
 * DELETE /api/projects/[projectId]/version-branches/[branchId]
 */
export async function PATCH(
  request: NextRequest,
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
    const body = (await request.json()) as { protected?: boolean; requireMergePath?: boolean };
    const hasProtected = typeof body.protected === 'boolean';
    const hasRequireMerge = typeof body.requireMergePath === 'boolean';
    if (!hasProtected && !hasRequireMerge) {
      return NextResponse.json(
        { success: false, error: 'Provide protected and/or requireMergePath', code: 'INVALID_INPUT' },
        { status: 400 }
      );
    }
    const raw = await updateVersionBranchProtection(
      branchId,
      projectId,
      tenantId,
      userId,
      isTenantAdmin,
      hasProtected ? body.protected : undefined,
      hasRequireMerge ? body.requireMergePath : undefined
    );
    const data = JSON.parse(raw) as { success: boolean; branch?: unknown; error?: string; code?: string };
    if (!data.success) {
      const st =
        data.code === 'FORBIDDEN'
          ? 403
          : data.error?.toLowerCase().includes('not found')
            ? 404
            : 400;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true, branch: data.branch });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}

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
    const data = JSON.parse(raw) as { success: boolean; error?: string; status?: number; code?: string };
    if (!data.success) {
      const error = data.error?.toLowerCase() ?? '';
      const st =
        typeof data.status === 'number'
          ? data.status
          : data.code === 'BRANCH_PROTECTED'
            ? 403
            : error.includes('not found')
              ? 404
              : error.includes('unauthorized') || error.includes('forbidden')
                ? 403
                : 500;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
