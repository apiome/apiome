import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { mergeVersionBranchesPreviewServer } from '@lib/db/helper';

/**
 * POST /api/projects/[projectId]/version-branches/merge-preview
 * Body: { sourceBranchName, targetBranchName }
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
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const { projectId } = await params;
    const body = await request.json();
    const sourceBranchName = typeof body.sourceBranchName === 'string' ? body.sourceBranchName : '';
    const targetBranchName = typeof body.targetBranchName === 'string' ? body.targetBranchName : '';
    if (!sourceBranchName.trim() || !targetBranchName.trim()) {
      return NextResponse.json(
        { success: false, error: 'sourceBranchName and targetBranchName are required' },
        { status: 400 }
      );
    }
    const raw = await mergeVersionBranchesPreviewServer({
      projectId,
      tenantId,
      sourceBranchName,
      targetBranchName,
    });
    const data = JSON.parse(raw) as { success: boolean; status?: number; error?: string; [k: string]: unknown };
    const st = typeof data.status === 'number' ? data.status : data.success ? 200 : 500;
    const { status: _s, ...rest } = data;
    return NextResponse.json(rest, { status: st });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
