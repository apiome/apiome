import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { deleteVersionTag, resolveTenantAdminForSession, updateVersionTag } from '@lib/db/helper';

/**
 * PATCH /api/projects/[projectId]/version-tags/[tagId] — body: { versionId?, immutable?, protected? }
 * DELETE /api/projects/[projectId]/version-tags/[tagId]
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string; tagId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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
    const { projectId, tagId } = await params;
    const body = await request.json();
    const versionId = typeof body.versionId === 'string' ? body.versionId : undefined;
    const immutable = body.immutable === true ? true : undefined;
    const protectedFlag = typeof body.protected === 'boolean' ? body.protected : undefined;
    const raw = await updateVersionTag(tagId, projectId, tenantId, userId, isTenantAdmin, {
      versionId,
      immutable,
      protected: protectedFlag,
    });
    const data = JSON.parse(raw) as {
      success: boolean;
      tag?: unknown;
      error?: string;
      code?: string;
    };
    if (!data.success) {
      const st =
        data.code === 'TAG_IMMUTABLE'
          ? 409
          : data.code === 'TAG_PROTECTED' || data.code === 'TAG_PROTECT_POLICY_ADMIN_ONLY'
            ? 403
            : data.error?.toLowerCase().includes('not found')
              ? 404
              : 400;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true, tag: data.tag });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string; tagId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
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
    const { projectId, tagId } = await params;
    const raw = await deleteVersionTag(tagId, projectId, tenantId, userId, isTenantAdmin);
    const data = JSON.parse(raw) as { success: boolean; error?: string; code?: string };
    if (!data.success) {
      const st =
        data.code === 'TAG_IMMUTABLE'
          ? 409
          : data.code === 'TAG_PROTECTED'
            ? 403
            : data.error?.toLowerCase().includes('not found')
              ? 404
              : 400;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
