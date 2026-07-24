import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { createVersionTag, listVersionTags, resolveTenantAdminForSession } from '@lib/db/helper';

/**
 * GET /api/projects/[projectId]/version-tags
 * POST /api/projects/[projectId]/version-tags — body: { name, versionId, message?, channel?, immutable? }
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
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
    const { projectId } = await params;
    const raw = await listVersionTags(projectId, tenantId);
    const data = JSON.parse(raw) as { success: boolean; tags?: unknown; error?: string; status?: number };
    if (!data.success) {
      const error = data.error?.toLowerCase() ?? '';
      const st =
        typeof data.status === 'number'
          ? data.status
          : error.includes('not found')
            ? 404
            : 500;
      return NextResponse.json(data, { status: st });
    }
    return NextResponse.json({ success: true, tags: data.tags });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
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
    const { projectId } = await params;
    const body = await request.json();
    const name = typeof body.name === 'string' ? body.name : '';
    const versionId = typeof body.versionId === 'string' ? body.versionId : '';
    if (!name.trim() || !versionId.trim()) {
      return NextResponse.json(
        { success: false, error: 'name and versionId are required' },
        { status: 400 }
      );
    }
    const isTenantAdmin = await resolveTenantAdminForSession(
      userId,
      tenantId,
      (session.user as { is_tenant_admin?: boolean }).is_tenant_admin
    );
    const raw = await createVersionTag(
      projectId,
      tenantId,
      name,
      versionId,
      userId,
      {
        message: typeof body.message === 'string' ? body.message : null,
        channel: typeof body.channel === 'string' ? body.channel : null,
        immutable: body.immutable === true,
        protected: body.protected === true,
      },
      isTenantAdmin
    );
    const data = JSON.parse(raw) as {
      success: boolean;
      tag?: unknown;
      error?: string;
      code?: string;
      status?: number;
    };
    if (!data.success) {
      let status = 400;
      if (typeof data.status === 'number') {
        status = data.status;
      } else {
        const error = data.error?.toLowerCase() ?? '';
        if (data.code === 'TAG_NAME_CONFLICT' || error.includes('already exists')) {
          status = 409;
        } else if (data.code === 'PROTECTED_TAG_ADMIN_ONLY') {
          status = 403;
        } else if (error.includes('not found')) {
          status = 404;
        }
      }
      return NextResponse.json(data, { status });
    }
    return NextResponse.json({ success: true, tag: data.tag });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
