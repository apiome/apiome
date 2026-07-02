import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import {
  listVersionBranches,
  createVersionBranch,
} from '@lib/db/helper';

/**
 * GET /api/projects/[projectId]/version-branches
 * POST /api/projects/[projectId]/version-branches — body: { name, fromVersionId }
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const { projectId } = await params;
    const raw = await listVersionBranches(projectId, tenantId);
    const data = JSON.parse(raw) as { success: boolean; branches?: unknown; error?: string; status?: number };
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
    return NextResponse.json({ success: true, branches: data.branches });
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
    const session = await getServerSession(authOptions);
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
    const fromVersionId = typeof body.fromVersionId === 'string' ? body.fromVersionId : '';
    if (!name.trim() || !fromVersionId.trim()) {
      return NextResponse.json(
        { success: false, error: 'name and fromVersionId are required' },
        { status: 400 }
      );
    }
    const raw = await createVersionBranch(projectId, tenantId, name, fromVersionId, userId);
    const data = JSON.parse(raw) as { success: boolean; branch?: unknown; error?: string };
    if (!data.success) {
      return NextResponse.json(data, { status: data.error?.includes('already exists') ? 409 : 400 });
    }
    return NextResponse.json({ success: true, branch: data.branch });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
