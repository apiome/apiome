import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { mergeVersionBranchesServer } from '@lib/db/helper';

/**
 * POST /api/projects/[projectId]/version-branches/merge
 * Body: { sourceBranchName, targetBranchName, baseRevisionId } — baseRevisionId must match current target tip.
 */
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
    const sourceBranchName = typeof body.sourceBranchName === 'string' ? body.sourceBranchName : '';
    const targetBranchName = typeof body.targetBranchName === 'string' ? body.targetBranchName : '';
    const baseRevisionId = typeof body.baseRevisionId === 'string' ? body.baseRevisionId : '';
    if (!sourceBranchName.trim() || !targetBranchName.trim() || !baseRevisionId.trim()) {
      return NextResponse.json(
        { success: false, error: 'sourceBranchName, targetBranchName, and baseRevisionId are required' },
        { status: 400 }
      );
    }
    const raw = await mergeVersionBranchesServer({
      projectId,
      tenantId,
      userId,
      sourceBranchName,
      targetBranchName,
      baseRevisionId,
    });
    const data = JSON.parse(raw) as {
      success: boolean;
      status?: number;
      error?: string;
      code?: string;
      conflictPaths?: string[];
      version?: unknown;
      [k: string]: unknown;
    };
    const st = typeof data.status === 'number' ? data.status : data.success ? 200 : 500;
    const { status: _s, ...rest } = data;
    return NextResponse.json(rest, { status: st });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
